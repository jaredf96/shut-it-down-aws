"""Cost estimation: static baseline, with optional live Pricing API overrides.

`estimate(resource)` returns a rough monthly figure and a `source`:
  - "static"  — from the built-in price map
  - "live"    — from the AWS Pricing API (when enabled and it covers the type)
  - "unknown" — cost depends on usage we can't see (e.g. S3, unknown type)

`annotate(resources)` stamps each Resource with the estimate. Live pricing is
opt-in via ENABLE_LIVE_PRICING and degrades gracefully to static.
"""

from __future__ import annotations

from app import config
from app.pricing import static_prices as sp
from app.pricing.live_prices import LivePricer

# Process-wide pricer (keeps its cache warm across scans).
_pricer: LivePricer | None = None


def _get_pricer() -> LivePricer | None:
    global _pricer
    if not config.live_pricing_enabled():
        return None
    if _pricer is None:
        _pricer = LivePricer()
    return _pricer


def _static_estimate(resource: dict) -> float | None:
    rtype = resource.get("resource_type", "")
    status = resource.get("status")
    details = resource.get("details") or {}

    if rtype == "EC2 Instance":
        if status != "running":
            return 0.0  # stopped -> no compute charge (storage billed separately)
        return sp.monthly(sp.EC2_HOURLY.get(details.get("instance_type")))

    if rtype == "EBS Volume":
        size = details.get("size_gb")
        if not size:
            return None
        rate = sp.EBS_GB_MONTH.get(details.get("volume_type"), sp.DEFAULT_EBS_GB_MONTH)
        return round(size * rate, 2)

    if rtype == "NAT Gateway":
        return sp.monthly(sp.NAT_GATEWAY_HOURLY)

    if rtype == "Elastic IP":
        return sp.monthly(sp.EIP_UNASSOCIATED_HOURLY) if status == "unassociated" else 0.0

    if rtype.startswith("Load Balancer"):
        hourly = sp.CLB_HOURLY if "CLASSIC" in rtype else sp.ALB_HOURLY
        return sp.monthly(hourly)

    if rtype == "RDS Database":
        return sp.monthly(sp.RDS_HOURLY.get(details.get("instance_class")))

    # S3 buckets and anything else: usage-dependent / unknown.
    return None


def _live_estimate(resource: dict, pricer: LivePricer) -> float | None:
    """Live override for the (currently small) set of supported types."""
    rtype = resource.get("resource_type", "")
    region = resource.get("region", "")

    if rtype == "NAT Gateway":
        return pricer.nat_gateway_monthly(region)

    if rtype == "EBS Volume":
        details = resource.get("details") or {}
        size = details.get("size_gb")
        rate = pricer.ebs_gb_month(region, details.get("volume_type"))
        if size and rate is not None:
            return round(size * rate, 2)

    return None


def estimate(resource: dict, pricer: LivePricer | None = None) -> dict:
    """Return {estimated_monthly_cost, cost_currency, cost_source} for a resource."""
    amount = _static_estimate(resource)
    source = "static" if amount is not None else "unknown"

    if pricer is not None:
        live = _live_estimate(resource, pricer)
        if live is not None:
            amount, source = live, "live"

    return {
        "estimated_monthly_cost": amount,
        "cost_currency": "USD",
        "cost_source": source,
    }


def annotate(resources: list) -> list:
    """Return copies of the resources stamped with cost estimates."""
    pricer = _get_pricer()
    annotated = []
    for resource in resources:
        as_dict = resource.model_dump() if hasattr(resource, "model_dump") else resource
        est = estimate(as_dict, pricer)
        if hasattr(resource, "model_copy"):
            annotated.append(resource.model_copy(update=est))
        else:
            annotated.append({**resource, **est})
    return annotated
