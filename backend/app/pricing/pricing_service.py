"""Cost floors: static baseline, with optional live Pricing API overrides.

**What this produces is a minimum, not an estimate.** Only fixed hourly rates
and EBS GB-month storage are priced. NAT Gateway data processing, RDS allocated
storage, and S3 storage are all unpriced, so the number returned here can only
be lower than the real bill — never higher. The UI and docs say "minimum monthly
exposure" for that reason; the field is still named `estimated_monthly_cost`
because renaming it would churn the persisted scans, the alert model, and the
provider contract for no gain in accuracy.

Pricing the missing dimensions properly is the better long-term answer. Two of
the three need data a Describe call does not return (bytes processed, bytes
stored), so they would mean CloudWatch reads and a wider IAM policy; RDS
allocated storage is already in `describe_db_instances` and is the cheapest one
to add next.

`estimate(resource)` returns the monthly figure and a `source`:
  - "static"  — from the built-in price map
  - "live"    — from the AWS Pricing API (when enabled and it covers the type)
  - "unknown" — cost depends on usage we can't see (e.g. S3, unknown type)

`annotate(resources)` stamps each Resource with the figure. Live pricing is
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
        # Hourly only — data processing ($/GB) needs CloudWatch, so this is a floor.
        return sp.monthly(sp.NAT_GATEWAY_HOURLY)

    if rtype == "Elastic IP":
        # All public IPv4 addresses are billed hourly, associated or not.
        return sp.monthly(sp.PUBLIC_IPV4_HOURLY)

    if rtype.startswith("Load Balancer"):
        hourly = sp.CLB_HOURLY if "CLASSIC" in rtype else sp.ALB_HOURLY
        return sp.monthly(hourly)

    if rtype == "RDS Database":
        # Compute only — allocated storage is not priced yet, so this is a floor.
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
    """Return {estimated_monthly_cost, cost_currency, cost_source} for a resource.

    The amount is a lower bound on the monthly charge, not a prediction of it.
    """
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
    """Return copies of the resources stamped with their monthly cost floor."""
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
