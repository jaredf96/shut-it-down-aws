"""Persistence for scan runs in DynamoDB, scoped per workspace.

Each scan is one item:

    pk = "TENANT#<workspace_id>"   sk = scan_id   ("<ISO timestamp>_<short uuid>")

(`TENANT#` is the frozen legacy prefix for what is now a workspace — see
`dynamo.py` and docs/DECISIONS.md D3.)

Because `scan_id` is prefixed with a UTC timestamp, querying a workspace's
partition with `ScanIndexForward=False` returns its most recent scans first —
no GSI needed, and scans are naturally isolated by workspace.

The bulk payload (summary + resources) is stored as JSON strings to keep
serialization simple and avoid DynamoDB Decimal/float quirks. Lightweight
metadata (scan_id, created_at, resource_count) is stored as native attributes
so the history list can be projected cheaply without loading every resource.

`workspace_id` is an optional keyword on every function; when omitted it resolves
to the default workspace (local / single-workspace mode). If persistence is not
configured, every function is a safe no-op.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from boto3.dynamodb.conditions import Key

from app import config

# Re-exported so existing callers (and tests) keep using scan_repository.*
from app.repositories.dynamo import ensure_table, get_table, is_enabled

__all__ = [
    "ensure_table",
    "get_scan",
    "is_enabled",
    "list_scans",
    "list_scans_full",
    "save_scan",
]


def _scan_pk(workspace_id: str | None) -> str:
    return f"TENANT#{workspace_id or config.default_workspace_id()}"


def _new_scan_id() -> str:
    """Time-sortable, URL-safe id: '<ISO-8601 UTC>_<short uuid>'.

    The separator is '_' (not '#') so the id can be used directly in a URL path
    without being mistaken for a fragment.
    """
    ts = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return f"{ts}_{uuid.uuid4().hex[:8]}"


def _serialize_resources(resources: list) -> list[dict]:
    """Accept pydantic Resource objects or plain dicts; return JSON-ready dicts."""
    out = []
    for r in resources:
        out.append(r.model_dump(mode="json") if hasattr(r, "model_dump") else r)
    return out


def save_scan(result: dict, *, workspace_id: str | None = None) -> str | None:
    """Persist a full scan result for a workspace. Returns scan_id, or None if disabled."""
    if not is_enabled():
        return None

    scan_id = _new_scan_id()
    created_at = scan_id.split("_", 1)[0]
    summary = result.get("summary", {})
    resources = _serialize_resources(result.get("resources", []))

    get_table().put_item(
        Item={
            "pk": _scan_pk(workspace_id),
            "sk": scan_id,
            "scan_id": scan_id,
            "created_at": created_at,
            "resource_count": len(resources),
            "summary_json": json.dumps(summary),
            "resources_json": json.dumps(resources),
        }
    )
    return scan_id


def list_scans(limit: int = 20, *, workspace_id: str | None = None) -> list[dict]:
    """Return recent scan metadata for a workspace (newest first). Empty if disabled."""
    if not is_enabled():
        return []

    response = get_table().query(
        KeyConditionExpression=Key("pk").eq(_scan_pk(workspace_id)),
        ScanIndexForward=False,  # newest first
        Limit=limit,
        ProjectionExpression="scan_id, created_at, resource_count, summary_json",
    )
    return [_to_meta(item) for item in response.get("Items", [])]


def list_scans_full(limit: int = 20, *, workspace_id: str | None = None) -> list[dict]:
    """Like list_scans, but includes each scan's resources (one Query).

    Used to compute per-scan "vs previous" deltas without N round trips.
    Returns newest-first; empty if disabled.
    """
    if not is_enabled():
        return []

    response = get_table().query(
        KeyConditionExpression=Key("pk").eq(_scan_pk(workspace_id)),
        ScanIndexForward=False,  # newest first
        Limit=limit,
    )
    return [
        {
            **_to_meta(item),
            "resources": json.loads(item["resources_json"]) if item.get("resources_json") else [],
        }
        for item in response.get("Items", [])
    ]


def get_scan(scan_id: str, *, workspace_id: str | None = None) -> dict | None:
    """Return a single saved scan for a workspace, or None if missing/disabled."""
    if not is_enabled():
        return None

    response = get_table().get_item(Key={"pk": _scan_pk(workspace_id), "sk": scan_id})
    item = response.get("Item")
    if not item:
        return None

    return {
        "scan_id": item["scan_id"],
        "created_at": item["created_at"],
        "summary": json.loads(item["summary_json"]),
        "resources": json.loads(item["resources_json"]),
    }


def _to_meta(item: dict) -> dict:
    return {
        "scan_id": item["scan_id"],
        "created_at": item["created_at"],
        # Numbers come back from DynamoDB as Decimal; normalize to int.
        "resource_count": int(item.get("resource_count", 0)),
        "summary": json.loads(item["summary_json"]) if item.get("summary_json") else {},
    }
