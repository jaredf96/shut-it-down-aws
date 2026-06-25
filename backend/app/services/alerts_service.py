"""Rule-based alert engine.

Given the current scan's resources (and, optionally, the previous scan's
resources for change detection), produce a list of Alerts. The engine is
deliberately small and rule-driven so new rules are easy to add and so the
same alerts can later be pushed to email/Slack unchanged.

Each resource produces at most one alert — the most significant applicable
rule wins — to keep the signal clean.
"""

from __future__ import annotations

from app.models import Alert, AlertSeverity

# Strict cost-risk ordering used to detect risk *increases* between scans.
# REVIEW is intentionally absent (0) — it is "needs a human", not a level.
_RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

_SEVERITY_ORDER = {AlertSeverity.CRITICAL: 0, AlertSeverity.WARNING: 1, AlertSeverity.INFO: 2}

_RULE_TITLES = {
    "risk_increased": "Risk increased",
    "new_billable_resource": "New billable resource",
    "new_review_resource": "New resource to review",
    "high_risk_resource": "Ongoing high-risk resource",
}


def _as_dict(resource) -> dict:
    return resource.model_dump(mode="json") if hasattr(resource, "model_dump") else resource


def _identity(resource: dict) -> tuple:
    return (
        resource.get("resource_type"),
        resource.get("region"),
        resource.get("resource_id"),
        resource.get("account_id"),
    )


def _classify(risk: str, is_new: bool, risk_increased: bool):
    """Pick (severity, rule) for one resource, or (None, None) for no alert."""
    if risk_increased:
        return AlertSeverity.CRITICAL, "risk_increased"
    if is_new and risk in ("HIGH", "MEDIUM"):
        return AlertSeverity.CRITICAL, "new_billable_resource"
    if is_new and risk == "REVIEW":
        return AlertSeverity.INFO, "new_review_resource"
    if risk == "HIGH":
        return AlertSeverity.WARNING, "high_risk_resource"
    return None, None


def evaluate(resources, previous_resources=None) -> list[Alert]:
    """Produce alerts for the current scan.

    `previous_resources` enables change-aware rules (new / escalated). When it
    is None (no history yet), only standing rules fire — so a first scan still
    flags ongoing high-risk resources, but nothing is mislabeled as "new".
    """
    current = [_as_dict(r) for r in resources]

    have_previous = previous_resources is not None
    prev_index = (
        {_identity(_as_dict(p)): _as_dict(p) for p in previous_resources} if have_previous else {}
    )

    alerts: list[Alert] = []
    for resource in current:
        risk = resource.get("risk_level")
        identity = _identity(resource)
        previous = prev_index.get(identity)

        is_new = have_previous and previous is None
        risk_increased = bool(previous) and (
            _RISK_ORDER.get(risk, 0) > _RISK_ORDER.get(previous.get("risk_level"), 0)
        )

        severity, rule = _classify(risk, is_new, risk_increased)
        if severity is None:
            continue

        rtype, region, rid, account_id = identity
        account_suffix = f":{account_id}" if account_id else ""
        alerts.append(
            Alert(
                id=f"{rule}:{rtype}:{region}:{rid}{account_suffix}",
                severity=severity,
                rule=rule,
                title=f"{_RULE_TITLES[rule]}: {rtype} in {region}",
                message=resource.get("monthly_cost_risk") or "",
                resource_type=rtype,
                resource_id=rid,
                region=region,
                risk_level=risk,
                estimated_monthly_cost=resource.get("estimated_monthly_cost"),
            )
        )

    # Within a severity, rank the costliest first (then stable by type/id).
    alerts.sort(
        key=lambda a: (
            _SEVERITY_ORDER[a.severity],
            -(a.estimated_monthly_cost or 0.0),
            a.resource_type,
            a.resource_id,
        )
    )
    return alerts
