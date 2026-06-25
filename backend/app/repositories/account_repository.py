"""Per-tenant AWS account registrations (same table as scans).

    pk = "ACCOUNTS#<tenant_id>"   sk = <account_id>   -> account record

A distinct partition prefix keeps these out of the tenant's scan partition
(`TENANT#<tenant_id>`), so listing scans never sees account records.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from boto3.dynamodb.conditions import Key

from app.repositories.dynamo import get_table, is_enabled

_ROLE_ARN_ACCOUNT = re.compile(r"arn:aws[^:]*:iam::(\d{12}):")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _accounts_pk(tenant_id: str) -> str:
    return f"ACCOUNTS#{tenant_id}"


def account_id_from_role_arn(role_arn: str) -> str:
    """Parse the 12-digit account id from a role ARN, or a short uuid fallback."""
    match = _ROLE_ARN_ACCOUNT.search(role_arn or "")
    return match.group(1) if match else uuid.uuid4().hex[:12]


def create_account(tenant_id: str, payload: dict) -> dict:
    """Register an account for a tenant. Returns the stored record."""
    if not is_enabled():
        raise RuntimeError("Persistence is required to register accounts")

    account_id = payload.get("account_id") or account_id_from_role_arn(payload["role_arn"])
    item = {
        "pk": _accounts_pk(tenant_id),
        "sk": account_id,
        "account_id": account_id,
        "name": payload["name"],
        "role_arn": payload["role_arn"],
        "external_id": payload.get("external_id"),
        "regions": payload.get("regions"),
        "created_at": _now(),
    }
    get_table().put_item(Item=item)
    return _strip_keys(item)


def list_accounts(tenant_id: str) -> list[dict]:
    """All accounts registered by a tenant. Empty if disabled."""
    if not is_enabled():
        return []
    response = get_table().query(KeyConditionExpression=Key("pk").eq(_accounts_pk(tenant_id)))
    return [_strip_keys(item) for item in response.get("Items", [])]


def get_account(tenant_id: str, account_id: str) -> dict | None:
    if not is_enabled():
        return None
    response = get_table().get_item(Key={"pk": _accounts_pk(tenant_id), "sk": account_id})
    item = response.get("Item")
    return _strip_keys(item) if item else None


def delete_account(tenant_id: str, account_id: str) -> bool:
    """Delete an account registration. Returns True if it existed."""
    if not is_enabled():
        return False
    existed = get_account(tenant_id, account_id) is not None
    get_table().delete_item(Key={"pk": _accounts_pk(tenant_id), "sk": account_id})
    return existed


def _strip_keys(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("pk", "sk")}
