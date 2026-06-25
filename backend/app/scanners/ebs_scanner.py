"""Scan EBS volumes across regions. Read-only."""

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
    """Return all EBS volumes as Resource objects."""
    session = session or boto3.Session()
    regions = regions or get_regions(session)
    resources: list[Resource] = []

    for region in regions:
        try:
            ec2 = session.client("ec2", region_name=region)
            paginator = ec2.get_paginator("describe_volumes")
            for page in paginator.paginate():
                for volume in page.get("Volumes", []):
                    state = volume.get("State", "unknown")  # available | in-use
                    attached = bool(volume.get("Attachments"))

                    if not attached:
                        risk = RiskLevel.MEDIUM
                        cost = (
                            "Unattached volumes still cost money per GB-month "
                            "even though nothing is using them."
                        )
                        action = (
                            "Review this orphaned volume. If it holds no data you "
                            "need, snapshot it (optional) and delete it manually."
                        )
                    else:
                        risk = RiskLevel.LOW
                        cost = "Attached volumes cost money but are in active use by an instance."
                        action = (
                            "Keep if the attached instance is still needed. "
                            "It will be cleaned up when you remove that instance."
                        )

                    resources.append(
                        Resource(
                            resource_type="EBS Volume",
                            resource_id=volume["VolumeId"],
                            name=_name_from_tags(volume.get("Tags")),
                            region=region,
                            status=state,
                            risk_level=risk,
                            monthly_cost_risk=cost,
                            suggested_action=action,
                            details={
                                "size_gb": volume.get("Size"),
                                "volume_type": volume.get("VolumeType"),
                            },
                        )
                    )
        except (BotoCoreError, ClientError):
            continue

    return resources
