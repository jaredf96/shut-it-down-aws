"""Scan history enriched with per-scan deltas.

Each scan in the history list carries a `vs_previous` summary describing how it
changed relative to the immediately older scan — so the dashboard can show
"+2 / −1 / ~3" badges without the user manually comparing scans — and
`previous`, that older scan itself, so a client comparing the two needs nothing
beyond the page it was given.

The newest scan in any page is compared to the one just below it; to make the
oldest item in a page comparable too, we fetch one extra scan and use it only
as that item's predecessor. The very first scan ever has no predecessor, so its
`vs_previous` and `previous` are None.
"""

from __future__ import annotations

from app.repositories import scan_repository
from app.services.diff_service import diff_resource_lists


def _ref(scan: dict) -> dict:
    """The predecessor, as much of it as a comparison needs — its completeness
    included, because a scan that could not read everything is no baseline."""
    return {key: scan[key] for key in ("scan_id", "created_at", "summary", "complete")}


def list_with_deltas(limit: int = 20, *, workspace_id: str | None = None) -> list[dict]:
    """Return recent scans (newest first), each with `vs_previous` and `previous`.

    `vs_previous` is None for the earliest scan, otherwise a summary dict:
    {"added": n, "removed": n, "changed": n, "unchanged": n}. `previous` is the
    scan before it as {scan_id, created_at, summary, complete}, or None.
    """
    # Fetch one extra so the oldest item in the page still has a predecessor.
    full = scan_repository.list_scans_full(limit + 1, workspace_id=workspace_id)
    page = full[:limit]

    enriched: list[dict] = []
    for i, scan in enumerate(page):
        older = full[i + 1] if i + 1 < len(full) else None
        vs_previous = (
            diff_resource_lists(older["resources"], scan["resources"])["summary"]
            if older is not None
            else None
        )
        enriched.append(
            {
                "scan_id": scan["scan_id"],
                "created_at": scan["created_at"],
                "resource_count": scan["resource_count"],
                "summary": scan["summary"],
                "complete": scan["complete"],
                "vs_previous": vs_previous,
                "previous": _ref(older) if older is not None else None,
            }
        )
    return enriched
