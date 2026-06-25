"""Helpers for working with AWS regions.

For an MVP we discover regions dynamically from EC2 so the dashboard works
no matter which regions the account has enabled. A small fallback list keeps
things working if that call fails (e.g. limited permissions).
"""

from __future__ import annotations

import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Sensible defaults if we cannot describe regions dynamically.
FALLBACK_REGIONS: list[str] = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
]


def default_region() -> str:
    """Region used for global-ish calls. Honors the standard AWS env vars."""
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def get_regions(session: boto3.Session | None = None) -> list[str]:
    """Return the list of regions enabled for this account.

    Pass a boto3 Session to discover regions for a specific (assumed-role)
    account. Falls back to a static list if the describe call is not permitted.
    """
    client_source = session or boto3
    try:
        ec2 = client_source.client("ec2", region_name=default_region())
        response = ec2.describe_regions(AllRegions=False)
        regions = [r["RegionName"] for r in response.get("Regions", [])]
        return sorted(regions) if regions else FALLBACK_REGIONS
    except (BotoCoreError, ClientError):
        return FALLBACK_REGIONS
