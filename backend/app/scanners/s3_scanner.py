"""Scan S3 buckets. S3 is a global service, so there is no per-region loop.

Read-only. We resolve each bucket's region for display but never read objects.
"""

from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.models import Resource, RiskLevel


def _bucket_region(s3, bucket_name: str) -> str:
    try:
        location = s3.get_bucket_location(Bucket=bucket_name)
        # us-east-1 is reported as None by the API.
        return location.get("LocationConstraint") or "us-east-1"
    except (BotoCoreError, ClientError):
        return "unknown"


def scan(regions: list[str] | None = None, session: boto3.Session | None = None) -> list[Resource]:
    """Return all S3 buckets as Resource objects.

    `regions` is accepted for a uniform scanner signature but ignored, since
    list_buckets is global.
    """
    session = session or boto3.Session()
    resources: list[Resource] = []
    try:
        s3 = session.client("s3")
        response = s3.list_buckets()
        for bucket in response.get("Buckets", []):
            name = bucket["Name"]
            resources.append(
                Resource(
                    resource_type="S3 Bucket",
                    resource_id=name,
                    name=name,
                    region=_bucket_region(s3, name),
                    status="active",
                    risk_level=RiskLevel.REVIEW,
                    monthly_cost_risk=(
                        "S3 cost depends on how much data is stored and how often it is "
                        "accessed. An empty bucket is nearly free; a bucket full of lab "
                        "data or old backups can add up."
                    ),
                    suggested_action=(
                        "Review the contents and size of this bucket. Empty and delete it "
                        "manually if it only holds leftover tutorial data."
                    ),
                )
            )
    except (BotoCoreError, ClientError):
        pass

    return resources
