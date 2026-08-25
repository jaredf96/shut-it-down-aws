"""Append-only audit log for cleanup attempts (same table as scans).

    pk = "AUDIT#<workspace_id>"   sk = "<ISO-8601 UTC>_<short uuid>"

Every cleanup attempt — success, failure, or refusal — is recorded here so there
is always a trail of who tried to change what. Entries are time-sortable, so the
log lists newest-first with a single Query.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from boto3.dynamodb.conditions import Key

from app.repositories.dynamo import get_table, is_enabled


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def append(workspace_id: str, entry: dict) -> dict:
    """Persist an audit entry and return it (with id + created_at).

    When persistence is disabled the entry is returned but not stored — the
    cleanup service additionally logs every entry to the application logger, so
    there is always a record somewhere.
    """
    created_at = _now()
    record = {**entry, "created_at": created_at, "id": f"{created_at}_{uuid.uuid4().hex[:8]}"}

    if is_enabled():
        get_table().put_item(Item={"pk": f"AUDIT#{workspace_id}", "sk": record["id"], **record})

    return record


def list_entries(workspace_id: str, limit: int = 50) -> list[dict]:
    """Return recent audit entries for a workspace (newest first). Empty if disabled."""
    if not is_enabled():
        return []
    response = get_table().query(
        KeyConditionExpression=Key("pk").eq(f"AUDIT#{workspace_id}"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [{k: v for k, v in item.items() if k not in ("pk", "sk")} for item in response["Items"]]
