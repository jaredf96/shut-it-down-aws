"""Scan NAT Gateways across regions. Read-only."""

from __future__ import annotations

import boto3

from app.models import Resource, RiskLevel
from app.utils import get_regions
from app.utils.concurrency import make_client, scan_regions


def _name_from_tags(tags) -> str | None:
    for tag in tags or []:
        if tag.get("Key") == "Name":
            return tag.get("Value")
    return None


def _scan_region(region: str, session: boto3.Session) -> list[Resource]:
    resources: list[Resource] = []
    ec2 = make_client(session, "ec2", region)
    paginator = ec2.get_paginator("describe_nat_gateways")
    for page in paginator.paginate():
        for nat in page.get("NatGateways", []):
            state = nat.get("State", "unknown")  # available | deleted | ...
            if state == "deleted":
                continue

            resources.append(
                Resource(
                    resource_type="NAT Gateway",
                    resource_id=nat["NatGatewayId"],
                    name=_name_from_tags(nat.get("Tags")),
                    region=region,
                    status=state,
                    risk_level=RiskLevel.HIGH,
                    monthly_cost_risk=(
                        "NAT Gateways bill an hourly charge plus data processing "
                        "fees and are one of the most common surprise costs."
                    ),
                    suggested_action=(
                        "Confirm you still need outbound internet for a private "
                        "subnet. If this is leftover lab infrastructure, delete it "
                        "manually."
                    ),
                )
            )
    return resources


def scan(
    regions: list[str] | None = None,
    session: boto3.Session | None = None,
    failed_regions: dict[str, str] | None = None,
) -> list[Resource]:
    """Return all NAT Gateways as Resource objects."""
    session = session or boto3.Session()
    regions = regions or get_regions(session)
    return scan_regions(
        lambda region: _scan_region(region, session),
        regions,
        session,
        failed_regions=failed_regions,
    )
