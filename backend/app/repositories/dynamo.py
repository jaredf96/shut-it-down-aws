"""Shared DynamoDB plumbing: table accessor + idempotent table creation.

The whole app uses a single table with prefixed partition keys:

    pk = "TENANT#<tenant_id>"      sk = <scan_id>     -> a saved scan
    pk = "TENANTMETA#<tenant_id>"  sk = "#"           -> tenant record
    pk = "APIKEY#<sha256(key)>"    sk = "#"           -> api key -> tenant lookup

Distinct prefixes keep these record types from colliding in one partition, so
scoping scans by tenant is just a different `pk` value — no schema change.
"""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from app import config
from app.utils import default_region


def is_enabled() -> bool:
    return config.persistence_enabled()


def get_table():
    resource = boto3.resource(
        "dynamodb",
        region_name=default_region(),
        endpoint_url=config.get_dynamodb_endpoint_url(),
    )
    return resource.Table(config.get_table_name())


def ensure_table() -> None:
    """Create the single app table if it does not already exist (idempotent)."""
    name = config.get_table_name()
    if not name:
        raise RuntimeError("DYNAMODB_TABLE_NAME is not set")

    resource = boto3.resource(
        "dynamodb",
        region_name=default_region(),
        endpoint_url=config.get_dynamodb_endpoint_url(),
    )
    try:
        table = resource.create_table(
            TableName=name,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceInUseException":
            return
        raise
