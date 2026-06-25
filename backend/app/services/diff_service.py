"""Compute the difference between two saved scans.

A resource is identified across scans by (resource_type, region, resource_id).
Against that identity we classify each resource as:

  added     - present in the newer scan, absent from the older one
  removed   - present in the older scan, absent from the newer one
  changed   - present in both, but a tracked field differs
  unchanged - present in both with identical tracked fields

We only track `status` and `risk_level` for "changed": those are the fields that
actually signal something worth noticing (an instance stopped, a volume's risk
dropped). The cost/action text is derived from those, so it moves with them.
"""

from __future__ import annotations

from app.repositories import scan_repository

# Fields whose changes are meaningful to surface.
_COMPARED_FIELDS = ("status", "risk_level")


def _identity(resource: dict) -> tuple:
    return (
        resource.get("resource_type"),
        resource.get("region"),
        resource.get("resource_id"),
        resource.get("account_id"),  # distinguishes same id across accounts
    )


def _index(resources: list[dict]) -> dict[tuple, dict]:
    return {_identity(r): r for r in resources}


def _meta(scan: dict) -> dict:
    return {
        "scan_id": scan["scan_id"],
        "created_at": scan["created_at"],
        "summary": scan["summary"],
    }


def diff_resource_lists(from_resources: list[dict], to_resources: list[dict]) -> dict:
    """Core diff over two resource lists (older `from` vs newer `to`).

    Returns {added, removed, changed, summary}. Used both by the full scan diff
    and by the per-scan "vs previous" deltas in the history list.
    """
    from_index = _index(from_resources)
    to_index = _index(to_resources)

    added = [r for key, r in to_index.items() if key not in from_index]
    removed = [r for key, r in from_index.items() if key not in to_index]

    changed: list[dict] = []
    unchanged = 0
    for key, to_res in to_index.items():
        from_res = from_index.get(key)
        if from_res is None:
            continue  # already counted as added
        changes = {
            field: {"from": from_res.get(field), "to": to_res.get(field)}
            for field in _COMPARED_FIELDS
            if from_res.get(field) != to_res.get(field)
        }
        if changes:
            changed.append({"resource": to_res, "changes": changes})
        else:
            unchanged += 1

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "unchanged": unchanged,
        },
    }


def diff_scans(from_id: str, to_id: str, *, tenant_id: str | None = None) -> dict:
    """Diff two saved scans (older `from_id` vs newer `to_id`) for a tenant.

    Raises LookupError(scan_id) if either scan does not exist.
    """
    from_scan = scan_repository.get_scan(from_id, tenant_id=tenant_id)
    if from_scan is None:
        raise LookupError(from_id)
    to_scan = scan_repository.get_scan(to_id, tenant_id=tenant_id)
    if to_scan is None:
        raise LookupError(to_id)

    core = diff_resource_lists(from_scan["resources"], to_scan["resources"])
    return {"from": _meta(from_scan), "to": _meta(to_scan), **core}
