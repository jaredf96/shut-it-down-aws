from app.repositories import scan_repository
from app.services import list_with_deltas


def _resource(rid, status="running", risk="MEDIUM", rtype="EC2 Instance", region="us-east-1"):
    return {
        "resource_type": rtype,
        "resource_id": rid,
        "name": rid,
        "region": region,
        "status": status,
        "risk_level": risk,
        "monthly_cost_risk": "…",
        "suggested_action": "…",
    }


def _save(resources):
    return scan_repository.save_scan(
        {"summary": {"total_resources": len(resources)}, "resources": resources}
    )


def test_deltas_are_relative_to_previous_scan(dynamo_table):
    # Saved oldest -> newest.
    _save([_resource("i-1")])  # scan 1
    _save([_resource("i-1"), _resource("i-2")])  # scan 2: +1 added
    _save([_resource("i-1", status="stopped", risk="LOW")])  # scan 3: -1 removed, ~1 changed

    history = list_with_deltas()
    # Returned newest-first.
    assert len(history) == 3
    newest, middle, oldest = history

    # Newest vs middle: i-2 removed, i-1 changed (status+risk).
    assert newest["vs_previous"] == {"added": 0, "removed": 1, "changed": 1, "unchanged": 0}
    # Middle vs oldest: i-2 added, i-1 unchanged.
    assert middle["vs_previous"] == {"added": 1, "removed": 0, "changed": 0, "unchanged": 1}
    # Oldest has no predecessor.
    assert oldest["vs_previous"] is None


def test_oldest_in_page_still_compares_to_earlier_scan(dynamo_table):
    for _ in range(4):
        _save([_resource("i-1")])

    # Page of 2: both items should have a non-null delta because the service
    # fetches one extra scan as the oldest item's predecessor.
    history = list_with_deltas(limit=2)
    assert len(history) == 2
    assert all(item["vs_previous"] is not None for item in history)


def test_each_scan_keeps_its_metadata(dynamo_table):
    _save([_resource("i-1")])
    item = list_with_deltas()[0]
    assert set(item.keys()) == {"scan_id", "created_at", "resource_count", "summary", "vs_previous"}
    assert item["resource_count"] == 1
