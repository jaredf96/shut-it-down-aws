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
    assert set(item.keys()) == {
        "scan_id",
        "created_at",
        "resource_count",
        "summary",
        "complete",
        "vs_previous",
        "previous",
    }
    assert item["resource_count"] == 1
    # The first scan ever has nothing before it.
    assert item["previous"] is None


def test_the_last_scan_on_a_page_still_names_its_predecessor(dynamo_table):
    ids = sorted(_save([_resource("i-1")]) for _ in range(4))  # oldest first

    newest, last_on_page = list_with_deltas(limit=2)

    assert newest["scan_id"] == ids[3]
    assert newest["previous"]["scan_id"] == ids[2]
    # Past the end of the page, but fetched for `vs_previous` anyway — so a client
    # comparing the last row with the scan before it needs no second request.
    assert last_on_page["previous"]["scan_id"] == ids[1]
    assert set(last_on_page["previous"]) == {"scan_id", "created_at", "summary", "complete"}


def test_a_predecessor_carries_its_completeness(dynamo_table, monkeypatch):
    # Fixed ids, so which scan is older does not depend on two saves landing in
    # different milliseconds.
    ids = iter(["2026-01-01T00:00:00.000Z_aaaaaaaa", "2026-01-02T00:00:00.000Z_bbbbbbbb"])
    monkeypatch.setattr(scan_repository, "_new_scan_id", lambda: next(ids))
    gap = {
        "region": "us-west-1",
        "reason": "AuthFailure",
        "account_id": None,
        "account_label": None,
    }
    scan_repository.save_scan({"summary": {}, "resources": [], "regions_failed": [gap]})
    scan_repository.save_scan({"summary": {}, "resources": []})

    newest, oldest = list_with_deltas()

    assert newest["complete"] is True
    assert newest["previous"]["complete"] is False
    assert oldest["complete"] is False
