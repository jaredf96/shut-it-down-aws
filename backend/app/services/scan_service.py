"""Orchestrates the individual scanners.

This is the single place the API talks to. Keeping the orchestration here
(instead of in main.py) makes it easy to later add caching, persistence to
DynamoDB, or background jobs without touching the route handlers.
"""

from __future__ import annotations

from app.models import Resource
from app.pricing import pricing_service
from app.scanners import SCANNERS


def scan_one(scanner_key: str, regions: list[str] | None = None, session=None) -> list[Resource]:
    """Run a single scanner by its key (e.g. "ec2"). Raises KeyError if unknown.

    `session` is an optional boto3 Session, used to scan a specific
    (assumed-role) account; None uses the default credential chain. Returned
    resources are stamped with cost estimates.
    """
    scanner = SCANNERS[scanner_key]
    return pricing_service.annotate(scanner.scan(regions, session=session))


def scan_all(regions: list[str] | None = None, session=None) -> dict[str, object]:
    """Run every scanner and return a combined, summarized result."""
    all_resources: list[Resource] = []

    for key in SCANNERS:
        try:
            found = scan_one(key, regions, session=session)
        except Exception:
            # One failing scanner should never break the whole scan.
            found = []
        all_resources.extend(found)

    return {
        "summary": summarize(all_resources),
        "resources": all_resources,
    }


def summarize(resources: list[Resource]) -> dict[str, object]:
    """Small rollup the frontend can show at the top of the dashboard."""
    by_risk: dict[str, int] = {}
    cost_total = 0.0
    for r in resources:
        by_risk[r.risk_level.value] = by_risk.get(r.risk_level.value, 0) + 1
        if r.estimated_monthly_cost:
            cost_total += r.estimated_monthly_cost

    return {
        "total_resources": len(resources),
        "by_risk_level": by_risk,
        "estimated_monthly_cost": round(cost_total, 2),
    }
