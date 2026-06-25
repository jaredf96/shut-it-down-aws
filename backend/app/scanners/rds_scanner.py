"""Scan RDS database instances across regions. Read-only."""

from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.models import Resource, RiskLevel
from app.utils import get_regions


def scan(regions: list[str] | None = None, session: boto3.Session | None = None) -> list[Resource]:
    """Return all RDS DB instances as Resource objects."""
    session = session or boto3.Session()
    regions = regions or get_regions(session)
    resources: list[Resource] = []

    for region in regions:
        try:
            rds = session.client("rds", region_name=region)
            paginator = rds.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    status = db.get("DBInstanceStatus", "unknown")
                    engine = db.get("Engine", "db")
                    db_class = db.get("DBInstanceClass", "")
                    resources.append(
                        Resource(
                            resource_type="RDS Database",
                            resource_id=db["DBInstanceIdentifier"],
                            name=f"{db.get('DBInstanceIdentifier')} ({engine} {db_class})".strip(),
                            region=region,
                            status=status,
                            risk_level=RiskLevel.HIGH,
                            monthly_cost_risk=(
                                "RDS databases bill for compute and storage continuously. "
                                "Even a stopped instance is auto-started after 7 days and "
                                "keeps paying for storage."
                            ),
                            suggested_action=(
                                "Confirm you still need this database. If it was for a lab, "
                                "take a final snapshot (optional) and delete it manually."
                            ),
                            details={"instance_class": db_class, "engine": engine},
                        )
                    )
        except (BotoCoreError, ClientError):
            continue

    return resources
