"""Scan Elastic IP addresses across regions. Read-only."""

from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.models import Resource, RiskLevel
from app.utils import get_regions


def _name_from_tags(tags) -> str | None:
    for tag in tags or []:
        if tag.get("Key") == "Name":
            return tag.get("Value")
    return None


def scan(regions: list[str] | None = None, session: boto3.Session | None = None) -> list[Resource]:
    """Return all Elastic IPs as Resource objects."""
    session = session or boto3.Session()
    regions = regions or get_regions(session)
    resources: list[Resource] = []

    for region in regions:
        try:
            ec2 = session.client("ec2", region_name=region)
            response = ec2.describe_addresses()
            for address in response.get("Addresses", []):
                # An EIP is "associated" if attached to an instance or interface.
                associated = bool(address.get("AssociationId"))

                if not associated:
                    risk = RiskLevel.HIGH
                    status = "unassociated"
                    cost = (
                        "AWS charges hourly for Elastic IPs that are allocated "
                        "but not attached to a running resource."
                    )
                    action = (
                        "Release this Elastic IP manually if you no longer need a "
                        "static address. It is likely leftover from a deleted instance."
                    )
                else:
                    risk = RiskLevel.LOW
                    status = "associated"
                    cost = "Associated Elastic IPs attached to a running instance are free."
                    action = "Keep while the attached resource is in use."

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
        except (BotoCoreError, ClientError):
            continue

    return resources
