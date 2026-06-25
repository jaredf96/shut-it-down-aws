"""Users within a tenant, and their API keys (same table as scans).

    pk = "USERS#<tenant_id>"     sk = <user_id>   -> user record (+ key hash)
    pk = "APIKEY#<sha256(key)>"  sk = "#"          -> principal lookup

Each user has one API key (high-entropy random token); only its SHA-256 hash is
stored. The user record also keeps the hash so deleting a user can revoke the
key. A user has a role: "admin" (can manage accounts + users) or "member".
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from boto3.dynamodb.conditions import Key

from app.repositories.dynamo import get_table, is_enabled

_KEY_PREFIX = "clc_"
ROLES = {"admin", "member"}
_PUBLIC_FIELDS = ("user_id", "name", "role", "created_at")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _users_pk(tenant_id: str) -> str:
    return f"USERS#{tenant_id}"


def create_user(tenant_id: str, name: str, role: str = "member") -> dict:
    """Create a user + API key. Returns the record incl. the plaintext key (once)."""
    if not is_enabled():
        raise RuntimeError("Persistence is required to create users")
    if role not in ROLES:
        role = "member"

    user_id = uuid.uuid4().hex
    api_key = _KEY_PREFIX + secrets.token_urlsafe(32)
    key_hash = _hash_key(api_key)
    created_at = _now()
    table = get_table()

    table.put_item(
        Item={
            "pk": _users_pk(tenant_id),
            "sk": user_id,
            "user_id": user_id,
            "name": name,
            "role": role,
            "key_hash": key_hash,
            "created_at": created_at,
        }
    )
    table.put_item(
        Item={
            "pk": f"APIKEY#{key_hash}",
            "sk": "#",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": role,
            "name": name,
            "created_at": created_at,
        }
    )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "name": name,
        "role": role,
        "api_key": api_key,
    }


def list_users(tenant_id: str) -> list[dict]:
    if not is_enabled():
        return []
    response = get_table().query(KeyConditionExpression=Key("pk").eq(_users_pk(tenant_id)))
    return [{k: item.get(k) for k in _PUBLIC_FIELDS} for item in response.get("Items", [])]


def _get_raw(tenant_id: str, user_id: str) -> dict | None:
    response = get_table().get_item(Key={"pk": _users_pk(tenant_id), "sk": user_id})
    return response.get("Item")


def get_user(tenant_id: str, user_id: str) -> dict | None:
    item = _get_raw(tenant_id, user_id)
    return {k: item.get(k) for k in _PUBLIC_FIELDS} if item else None


def delete_user(tenant_id: str, user_id: str) -> bool:
    """Delete a user and revoke their API key. Returns True if it existed."""
    if not is_enabled():
        return False
    item = _get_raw(tenant_id, user_id)
    if not item:
        return False

    table = get_table()
    table.delete_item(Key={"pk": _users_pk(tenant_id), "sk": user_id})
    if item.get("key_hash"):
        table.delete_item(Key={"pk": f"APIKEY#{item['key_hash']}", "sk": "#"})
    return True


def resolve_api_key(api_key: str) -> dict | None:
    """Return the principal {tenant_id, user_id, role, name} for a key, or None."""
    if not is_enabled() or not api_key:
        return None
    response = get_table().get_item(Key={"pk": f"APIKEY#{_hash_key(api_key)}", "sk": "#"})
    item = response.get("Item")
    if not item:
        return None
    return {
        "tenant_id": item["tenant_id"],
        "user_id": item["user_id"],
        "role": item.get("role", "member"),
        "name": item.get("name"),
    }
