"""Scan Elastic IP addresses across regions. Read-only."""

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
    response = ec2.describe_addresses()
    for address in response.get("Addresses", []):
        # An EIP is "associated" if attached to an instance or interface.
        associated = bool(address.get("AssociationId"))

        if not associated:
            risk = RiskLevel.HIGH
            status = "unassociated"
            cost = (
                "AWS charges hourly for every public IPv4 address, and this "
                "one is not even attached to a running resource."
            )
            action = (
                "Release this Elastic IP manually if you no longer need a "
                "static address. It is likely leftover from a deleted instance."
            )
        else:
            risk = RiskLevel.LOW
            status = "associated"
            cost = (
                "Since February 2024 AWS charges hourly for all public IPv4 "
                "addresses, including Elastic IPs attached to an instance."
            )
            action = "Keep while the attached resource is in use."

        # No `created_at`: describe_addresses reports no allocation time, so the
        # age column is genuinely blank for Elastic IPs rather than unpopulated.
        resources.append(
            Resource(
                resource_type="Elastic IP",
                resource_id=address.get("AllocationId", address.get("PublicIp", "unknown")),
                name=_name_from_tags(address.get("Tags")) or address.get("PublicIp"),
                region=region,
                status=status,
                risk_level=risk,
                monthly_cost_risk=cost,
                suggested_action=action,
            )
        )
    return resources


def scan(
    regions: list[str] | None = None,
    session: boto3.Session | None = None,
    failed_regions: dict[str, str] | None = None,
) -> list[Resource]:
    """Return all Elastic IPs as Resource objects."""
    session = session or boto3.Session()
    regions = regions or get_regions(session)
    return scan_regions(
        lambda region: _scan_region(region, session),
        regions,
        session,
        failed_regions=failed_regions,
    )
