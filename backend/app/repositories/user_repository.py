"""Users within a workspace, and their API keys (same table as scans).

    pk = "USERS#<workspace_id>"   sk = <user_id>   -> user record (+ key hash)
    pk = "APIKEY#<sha256(key)>"   sk = "#"         -> principal lookup

Each user has one API key (high-entropy random token); only its SHA-256 hash is
stored. The user record also keeps the hash so deleting a user can revoke the
key. A user has a role: "admin" (can manage accounts + users) or "member".

The API-key record is the one place a workspace id is persisted as an
*attribute* rather than only inside a partition key, and it is the only stored
`tenant_id` that crosses a public boundary. Storage is frozen legacy (D3), so
the attribute keeps its old name and the translation happens here, explicitly,
in `_principal_to_storage` / `_principal_from_storage`.
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


def _users_pk(workspace_id: str) -> str:
    return f"USERS#{workspace_id}"


# The frozen attribute name under which a principal's workspace is stored.
# Renaming it would rewrite every API-key row in every self-hosted install for
# a name no caller can see. See docs/DECISIONS.md D3.
_STORED_WORKSPACE_ATTR = "tenant_id"


def _principal_to_storage(principal: dict) -> dict:
    """Logical principal -> the attribute names the table actually stores."""
    stored = {k: v for k, v in principal.items() if k != "workspace_id"}
    stored[_STORED_WORKSPACE_ATTR] = principal["workspace_id"]
    return stored


def _principal_from_storage(item: dict) -> dict:
    """A stored API-key item -> the logical principal callers receive."""
    return {
        "workspace_id": item[_STORED_WORKSPACE_ATTR],
        "user_id": item["user_id"],
        "role": item.get("role", "member"),
        "name": item.get("name"),
    }


def create_user(workspace_id: str, name: str, role: str = "member") -> dict:
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
            "pk": _users_pk(workspace_id),
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
            **_principal_to_storage(
                {
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "role": role,
                    "name": name,
                }
            ),
            "created_at": created_at,
        }
    )
    return {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "name": name,
        "role": role,
        "api_key": api_key,
    }


def list_users(workspace_id: str) -> list[dict]:
    if not is_enabled():
        return []
    items = get_table().query_items(KeyConditionExpression=Key("pk").eq(_users_pk(workspace_id)))
    return [{k: item.get(k) for k in _PUBLIC_FIELDS} for item in items]


def _get_raw(workspace_id: str, user_id: str) -> dict | None:
    response = get_table().get_item(Key={"pk": _users_pk(workspace_id), "sk": user_id})
    return response.get("Item")


def get_user(workspace_id: str, user_id: str) -> dict | None:
    item = _get_raw(workspace_id, user_id)
    return {k: item.get(k) for k in _PUBLIC_FIELDS} if item else None


def delete_user(workspace_id: str, user_id: str) -> bool:
    """Delete a user and revoke their API key. Returns True if it existed.

    The key row goes first. These are two independent deletes, and only one
    order fails safe: if the second delete is lost, this order leaves a listed
    user with a dead key and a retry that works, while the reverse leaves a
    live key whose user row is gone — authenticating forever, unrevokable,
    because a retry 404s before reaching the key.
    """
    if not is_enabled():
        return False
    item = _get_raw(workspace_id, user_id)
    if not item:
        return False

    table = get_table()
    if item.get("key_hash"):
        table.delete_item(Key={"pk": f"APIKEY#{item['key_hash']}", "sk": "#"})
    table.delete_item(Key={"pk": _users_pk(workspace_id), "sk": user_id})
    return True


def resolve_api_key(api_key: str) -> dict | None:
    """Return the principal {workspace_id, user_id, role, name} for a key, or None.

    The read is strongly consistent on purpose: revocation must take effect the
    moment `delete_user` returns, and an eventually consistent read could hand
    back a just-deleted key row and authenticate it one more time.
    """
    if not is_enabled() or not api_key:
        return None
    response = get_table().get_item(
        Key={"pk": f"APIKEY#{_hash_key(api_key)}", "sk": "#"}, ConsistentRead=True
    )
    item = response.get("Item")
    if not item:
        return None
    return _principal_from_storage(item)
