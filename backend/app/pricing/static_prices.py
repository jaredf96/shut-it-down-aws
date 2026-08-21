"""Static price baseline (approximate us-east-1, USD).

These are intentionally rough on-demand list prices for common lab resources —
enough to give a credible "at least $X/month" figure. They are the fallback
whenever the live Pricing API is disabled or doesn't cover a resource type.
Prices drift over time; treat every figure as approximate.

Note what is *not* here: NAT Gateway data processing and S3 storage. Anything
derived from this map is therefore a floor. See `pricing_service` for why that
matters and what the remaining two would cost to add.
"""

from __future__ import annotations

HOURS_PER_MONTH = 730

# Flat hourly charges.
NAT_GATEWAY_HOURLY = 0.045
# Since February 2024 AWS charges for every public IPv4 address, associated or not.
PUBLIC_IPV4_HOURLY = 0.005
ALB_HOURLY = 0.0225
NLB_HOURLY = 0.0225
CLB_HOURLY = 0.025

# EBS storage, USD per GB-month, by volume type.
EBS_GB_MONTH = {
    "gp3": 0.08,
    "gp2": 0.10,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
    "standard": 0.05,
}
DEFAULT_EBS_GB_MONTH = 0.10

# EC2 on-demand hourly, common lab instance types.
EC2_HOURLY = {
    "t2.micro": 0.0116,
    "t2.small": 0.023,
    "t2.medium": 0.0464,
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "t3a.micro": 0.0094,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "c5.large": 0.085,
}

# RDS allocated storage, USD per GB-month. General Purpose SSD (gp2 and gp3
# price the same) — the default for every lab-sized instance. Provisioned IOPS
# is 0.125 and magnetic 0.10, close enough at lab volumes that a per-type map
# would be false precision on top of prices that already drift.
RDS_STORAGE_GB_MONTH = 0.115

# RDS on-demand hourly (single-AZ), common lab instance classes.
RDS_HOURLY = {
    "db.t2.micro": 0.017,
    "db.t3.micro": 0.017,
    "db.t3.small": 0.034,
    "db.t3.medium": 0.068,
    "db.t4g.micro": 0.016,
    "db.t4g.small": 0.032,
    "db.m5.large": 0.171,
}


def monthly(hourly: float | None) -> float | None:
    return round(hourly * HOURS_PER_MONTH, 2) if hourly is not None else None
