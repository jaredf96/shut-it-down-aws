"""Scan EC2 instances across regions. Read-only."""

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
    """Return all EC2 instances as Resource objects."""
    session = session or boto3.Session()
    regions = regions or get_regions(session)
    resources: list[Resource] = []

    for region in regions:
        try:
            ec2 = session.client("ec2", region_name=region)
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        state = instance.get("State", {}).get("Name", "unknown")
                        # Skip terminated instances: they cost nothing.
                        if state == "terminated":
                            continue

                        if state == "running":
                            risk = RiskLevel.MEDIUM
                            cost = "Can generate compute charges while running."
                            action = (
                                "Review whether this instance is still needed. "
                                "Stop it manually if it is only for a completed tutorial."
                            )
                        else:
                            risk = RiskLevel.LOW
                            cost = (
                                "Stopped instances do not incur compute charges, "
                                "but attached EBS volumes may still cost money."
                            )
                            action = (
                                "Confirm you no longer need this instance. "
                                "Consider terminating it and deleting unused volumes."
                            )

                        resources.append(
                            Resource(
                                resource_type="EC2 Instance",
                                resource_id=instance["InstanceId"],
                                name=_name_from_tags(instance.get("Tags")),
                                region=region,
                                status=state,
                                risk_level=risk,
                                monthly_cost_risk=cost,
                                suggested_action=action,
                                details={"instance_type": instance.get("InstanceType")},
                            )
                        )
        except (BotoCoreError, ClientError):
            # Region may be disabled or lack permissions; skip it.
            continue

    return resources
