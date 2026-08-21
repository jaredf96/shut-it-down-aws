"""Scan Elastic Load Balancers (ALB/NLB v2 and classic) across regions. Read-only."""

from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.models import Resource, RiskLevel
from app.utils import get_regions
from app.utils.concurrency import make_client, scan_regions


def _scan_v2(region: str, session: boto3.Session) -> list[Resource]:
    """Application and Network Load Balancers (elbv2)."""
    resources: list[Resource] = []
    elbv2 = make_client(session, "elbv2", region)
    paginator = elbv2.get_paginator("describe_load_balancers")
    for page in paginator.paginate():
        for lb in page.get("LoadBalancers", []):
            lb_type = lb.get("Type", "load-balancer").upper()
            resources.append(
                Resource(
                    resource_type=f"Load Balancer ({lb_type})",
                    resource_id=lb["LoadBalancerArn"],
                    name=lb.get("LoadBalancerName"),
                    region=region,
                    status=lb.get("State", {}).get("Code", "unknown"),
                    risk_level=RiskLevel.MEDIUM,
                    monthly_cost_risk=(
                        "Load balancers bill an hourly charge plus capacity units "
                        "even with no traffic."
                    ),
                    suggested_action=(
                        "Review whether any app still sits behind this load balancer. "
                        "Delete it manually if the backing service is gone."
                    ),
                )
            )
    return resources


def _scan_classic(region: str, session: boto3.Session) -> list[Resource]:
    """Classic Load Balancers (elb)."""
    resources: list[Resource] = []
    elb = make_client(session, "elb", region)
    paginator = elb.get_paginator("describe_load_balancers")
    for page in paginator.paginate():
        for lb in page.get("LoadBalancerDescriptions", []):
            resources.append(
                Resource(
                    resource_type="Load Balancer (CLASSIC)",
                    resource_id=lb["LoadBalancerName"],
                    name=lb.get("LoadBalancerName"),
                    region=region,
                    status="active",
                    risk_level=RiskLevel.MEDIUM,
                    monthly_cost_risk=(
                        "Classic load balancers bill an hourly charge plus data "
                        "transfer even with no traffic."
                    ),
                    suggested_action=(
                        "Review whether this classic load balancer is still in use. "
                        "Delete it manually if the backing service is gone."
                    ),
                )
            )
    return resources


def _scan_region(region: str, session: boto3.Session) -> list[Resource]:
    # v2 and classic are billed and queried independently: a failure in one
    # (e.g. an endpoint not present in a region) must not hide the other.
    resources: list[Resource] = []
    failures: list[Exception] = []
    for query in (_scan_v2, _scan_classic):
        try:
            resources.extend(query(region, session))
        except (BotoCoreError, ClientError) as exc:
            failures.append(exc)

    # Both halves failing is not a partial result — the region could not be
    # read at all. Swallowing that here would report it upward as empty, which
    # is exactly the confusion `scan_regions`' failure tracking exists to stop.
    if len(failures) == 2:
        raise failures[0]
    return resources


def scan(
    regions: list[str] | None = None,
    session: boto3.Session | None = None,
    failed_regions: dict[str, str] | None = None,
) -> list[Resource]:
    """Return all load balancers (ALB/NLB/Classic) as Resource objects."""
    session = session or boto3.Session()
    regions = regions or get_regions(session)
    return scan_regions(
        lambda region: _scan_region(region, session),
        regions,
        session,
        failed_regions=failed_regions,
    )
