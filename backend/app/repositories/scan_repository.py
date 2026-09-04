"""Persistence for scan runs in DynamoDB, scoped per workspace.

Each scan is one item:

    pk = "TENANT#<workspace_id>"   sk = scan_id   ("<ISO timestamp>_<short uuid>")

(`TENANT#` is the frozen legacy prefix for what is now a workspace — see
`dynamo.py` and docs/DECISIONS.md D3.)

Because `scan_id` is prefixed with a UTC timestamp, querying a workspace's
partition with `ScanIndexForward=False` returns its most recent scans first —
no GSI needed, and scans are naturally isolated by workspace.

The resource list is stored zlib-compressed in `resources_gz` (JSON, then
zlib) so a scan of thousands of resources still fits DynamoDB's 400 KB item
cap; `_resources` reads either that or the plain `resources_json` written by
earlier builds, which is never migrated (D3's reasoning). The summary stays a
plain JSON string and the lightweight metadata (scan_id, created_at,
resource_count) stays native, so the history list projects cheaply and a saved
scan is still legible in the DynamoDB console.

`workspace_id` is an optional keyword on every function; when omitted it resolves
to the default workspace (local / single-workspace mode). If persistence is not
configured, every function is a safe no-op.
"""

from __future__ import annotations

import json
import uuid
import zlib
from datetime import UTC, datetime

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app import config
from app.errors import ScanTooLarge

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


# DynamoDB rejects an item over 400 KB. The ceiling here is well under that on
# purpose. moto — the only backend the test suite runs against — sizes a binary
# attribute by its *base64* length against a 405,000-byte limit, so under moto
# the effective raw ceiling is ~303 KB, not 400 KB. Refusing at 290 KB binds
# first under both accountings with ~13 KB of margin, so the pre-flight gate is
# what fires in tests and in production alike, and the two agree.
_MAX_ITEM_BYTES = 290_000
_COMPRESS_LEVEL = 6


def _attr_size(value) -> int:
    return len(value) if isinstance(value, bytes) else len(str(value).encode())


def _item_size(item: dict) -> int:
    """DynamoDB's accounting: attribute-name bytes plus value bytes.

    Numbers are over-counted (they are stored more compactly), so this can
    refuse slightly early but can never let through something DynamoDB
    rejects.
    """
    return sum(len(name.encode()) + _attr_size(value) for name, value in item.items())


def _compress(payload: str) -> bytes:
    return zlib.compress(payload.encode(), _COMPRESS_LEVEL)


def _resources(item: dict) -> list:
    """The stored resource list, from either storage generation.

    `resources_gz` is zlib-compressed JSON (current). `resources_json` is the
    plain string written by earlier builds and still sitting in every install
    that ran one — read forever, never migrated, for the same reason D3 froze
    the storage names. An item carrying neither is corrupt and raises:
    returning [] would render a scan's resources as "none found".
    """
    if "resources_gz" in item:
        return json.loads(zlib.decompress(bytes(item["resources_gz"])).decode())
    return json.loads(item["resources_json"])


def save_scan(result: dict, *, workspace_id: str | None = None) -> str | None:
    """Persist a full scan result for a workspace. Returns scan_id, or None if disabled."""
    if not is_enabled():
        return None

    scan_id = _new_scan_id()
    created_at = scan_id.split("_", 1)[0]
    summary = result.get("summary", {})
    resources = _serialize_resources(result.get("resources", []))

    item = {
        "pk": _scan_pk(workspace_id),
        "sk": scan_id,
        "scan_id": scan_id,
        "created_at": created_at,
        "resource_count": len(resources),
        "summary_json": json.dumps(summary),
        "resources_gz": _compress(json.dumps(resources)),
    }
    size = _item_size(item)
    if size > _MAX_ITEM_BYTES:
        raise ScanTooLarge(
            f"{len(resources)} resources compress to a {size}-byte item, over the "
            f"{_MAX_ITEM_BYTES}-byte ceiling; the scan was not saved"
        )
    try:
        get_table().put_item(Item=item)
    except ClientError as exc:
        # Backstop for the case where DynamoDB's size accounting disagrees with
        # ours. Matched on the message as well as the code: ValidationException
        # is DynamoDB's generic 400 (malformed expression, bad attribute value,
        # empty key), and relabelling all of those as ScanTooLarge would let
        # `scan_everything` swallow a real fault into `persisted: false`.
        # Everything else keeps passing through as a loud 500, per dynamo.py.
        error = exc.response.get("Error", {})
        too_large = error.get("Code") == "ValidationException" and (
            "size" in error.get("Message", "").lower()
        )
        if too_large:
            raise ScanTooLarge(str(exc)) from exc
        raise
    return scan_id


def list_scans(limit: int = 20, *, workspace_id: str | None = None) -> list[dict]:
    """Return recent scan metadata for a workspace (newest first). Empty if disabled.

    The projection saves bandwidth, not round trips — DynamoDB's 1 MB page cap
    is applied to the items *read*, before projection.
    """
    if not is_enabled():
        return []

    items = get_table().query_items(
        KeyConditionExpression=Key("pk").eq(_scan_pk(workspace_id)),
        ScanIndexForward=False,  # newest first
        limit=limit,
        ProjectionExpression="scan_id, created_at, resource_count, summary_json",
    )
    return [_to_meta(item) for item in items]


def list_scans_full(limit: int = 20, *, workspace_id: str | None = None) -> list[dict]:
    """Like list_scans, but includes each scan's resources (one paged Query).

    Used to compute per-scan "vs previous" deltas without N round trips.
    Returns newest-first; empty if disabled.
    """
    if not is_enabled():
        return []

    items = get_table().query_items(
        KeyConditionExpression=Key("pk").eq(_scan_pk(workspace_id)),
        ScanIndexForward=False,  # newest first
        limit=limit,
    )
    return [{**_to_meta(item), "resources": _resources(item)} for item in items]


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
        "resources": _resources(item),
    }


def _to_meta(item: dict) -> dict:
    return {
        "scan_id": item["scan_id"],
        "created_at": item["created_at"],
        # Numbers come back from DynamoDB as Decimal; normalize to int.
        "resource_count": int(item.get("resource_count", 0)),
        "summary": json.loads(item["summary_json"]) if item.get("summary_json") else {},
    }
