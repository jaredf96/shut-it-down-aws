"""Every repository read follows `LastEvaluatedKey`.

DynamoDB caps a Query at 1 MB of items *read* and reports the cut with a
continuation key. A caller that ignores it gets a short page that is
indistinguishable from an exhausted partition — "couldn't see" rendered as
"nothing there", which is the failure mode `CLAUDE.md`'s scanner contract
forbids by name.

This is not a scale hypothetical. `history_service.list_with_deltas` asks
`list_scans_full(limit + 1)` = 21 full scans, so the cap bites at
1_000_000 / 21 ≈ 47.6 KB per scan — about 75 resources — and `/scans?limit=20`
silently rendered 20 saved scans as a handful.

Every test here seeds items large enough to force a real page boundary under
moto, which enforces the same 1 MB cap.
"""

import json
import random

import pytest

from app.errors import ResultSetTooLarge
from app.repositories import (
    account_repository,
    audit_repository,
    dynamo,
    scan_repository,
    user_repository,
)

WORKSPACE = "default"

# Incompressible padding: hex of random bytes. A repeated string would be
# packed down by the storage change and stop crossing a page boundary at all.
_PAD = random.Random(1234).randbytes(150_000).hex()


def _big_scan_item(pk, sk):
    """A legacy-shaped scan row — `resources_json`, no `resources_gz`.

    Deliberately the old shape: these tests then pin paging *and* the
    backward-compatible read at once.
    """
    return {
        "pk": pk,
        "sk": sk,
        "scan_id": sk,
        "created_at": sk.split("_", 1)[0],
        "resource_count": 1,
        "summary_json": json.dumps({"total": 1}),
        "resources_json": json.dumps([{"resource_id": sk, "pad": _PAD}]),
    }


def _big_row(pk, sk, extra):
    return {"pk": pk, "sk": sk, "pad": _PAD, **extra}


def _seed(items):
    table = dynamo.get_table()
    for item in items:
        table.put_item(Item=item)


def _scan_ids(n):
    """Descending-sortable ids, oldest first, in the repo's own format."""
    return [f"2026-09-0{i + 1}T00:00:00.000Z_{i:08x}" for i in range(n)]


# --- The control -----------------------------------------------------------


def test_moto_really_paginates(dynamo_table):
    """Without this, every other test here could pass while proving nothing:
    if moto stopped enforcing the 1 MB cap they would all run against a single
    page and go green either way."""
    from boto3.dynamodb.conditions import Key

    pk = f"TENANT#{WORKSPACE}"
    _seed([_big_scan_item(pk, sk) for sk in _scan_ids(4)])

    response = dynamo.get_table().query(KeyConditionExpression=Key("pk").eq(pk), Limit=4)

    assert len(response["Items"]) < 4
    assert "LastEvaluatedKey" in response


# --- The five reads --------------------------------------------------------


def test_list_scans_full_crosses_the_page_boundary(dynamo_table):
    ids = _scan_ids(4)
    _seed([_big_scan_item(f"TENANT#{WORKSPACE}", sk) for sk in ids])

    scans = scan_repository.list_scans_full(4)

    assert len(scans) == 4
    assert [s["scan_id"] for s in scans] == list(reversed(ids))


def test_list_scans_metadata_crosses_the_page_boundary(dynamo_table):
    """The counterintuitive half: `ProjectionExpression` does not exempt the
    read. The 1 MB cap is applied to the items read, before projection, so
    projecting saves bandwidth and not round trips."""
    _seed([_big_scan_item(f"TENANT#{WORKSPACE}", sk) for sk in _scan_ids(4)])

    assert len(scan_repository.list_scans(4)) == 4


def test_audit_trail_crosses_the_page_boundary(dynamo_table):
    _seed(
        [
            _big_row(f"AUDIT#{WORKSPACE}", sk, {"status": "dry_run", "resource_id": "i-1"})
            for sk in _scan_ids(4)
        ]
    )

    entries = audit_repository.list_entries(WORKSPACE, 4)

    assert len(entries) == 4
    assert all("pk" not in e and "sk" not in e for e in entries)


@pytest.mark.parametrize(
    "read,prefix,extra",
    [
        (account_repository.list_accounts, "ACCOUNTS#", {"account_id": "1", "name": "n"}),
        (user_repository.list_users, "USERS#", {"user_id": "u", "name": "n", "role": "member"}),
    ],
    ids=["accounts", "users"],
)
def test_unlimited_reads_cross_the_page_boundary(dynamo_table, read, prefix, extra):
    """The two reads that pass no limit at all — `query_items`' limit=None path."""
    _seed([_big_row(f"{prefix}{WORKSPACE}", f"s{i}", extra) for i in range(4)])

    assert len(read(WORKSPACE)) == 4


# --- What bounds the loop --------------------------------------------------


def test_a_bounded_read_above_the_page_floor_still_completes(dynamo_table, monkeypatch):
    """A page carries ~3 of these, so 6 scans need more than 2 round trips.
    The budget is `max(_MAX_PAGES, limit)` precisely so a caller-supplied limit
    above the floor cannot be refused for exceeding it."""
    monkeypatch.setattr(dynamo, "_MAX_PAGES", 2)
    _seed([_big_scan_item(f"TENANT#{WORKSPACE}", sk) for sk in _scan_ids(6)])

    assert len(scan_repository.list_scans_full(6)) == 6


def test_page_budget_raises_rather_than_returning_a_short_list(dynamo_table, monkeypatch):
    """The one place unbounded pagination stops does not stop by quietly
    answering short."""
    monkeypatch.setattr(dynamo, "_MAX_PAGES", 1)
    _seed(
        [
            _big_row(f"ACCOUNTS#{WORKSPACE}", f"s{i}", {"account_id": str(i), "name": "n"})
            for i in range(4)
        ]
    )

    with pytest.raises(ResultSetTooLarge):
        account_repository.list_accounts(WORKSPACE)


# --- What `limit` means now ------------------------------------------------


def test_limit_is_a_count_of_results(dynamo_table):
    """The compatibility half of the semantics change: `limit` used to be
    DynamoDB's scan-forward cap and is now a count of items returned. In the
    ordinary case a caller must not be able to tell."""
    saved = [
        scan_repository.save_scan({"summary": {}, "resources": [{"resource_id": f"i-{i}"}]})
        for i in range(5)
    ]

    listed = scan_repository.list_scans(3)

    assert [s["scan_id"] for s in listed] == list(reversed(saved[-3:]))


def test_query_items_refuses_a_raw_limit(dynamo_table):
    """The exact distinction the bug was made of: DynamoDB's `Limit` caps how
    far one request scans forward, not how many results come back."""
    from boto3.dynamodb.conditions import Key

    condition = Key("pk").eq(f"TENANT#{WORKSPACE}")

    with pytest.raises(TypeError):
        dynamo.get_table().query_items(KeyConditionExpression=condition, Limit=5)

    with pytest.raises(TypeError):
        dynamo.get_table().query_items(
            KeyConditionExpression=condition, ExclusiveStartKey={"pk": "x", "sk": "y"}
        )


def test_zero_limit_returns_nothing_instead_of_calling_dynamodb(dynamo_table):
    """`Limit=0` is rejected client-side by botocore as a `ParamValidationError`,
    which used to be translated into a 503 blaming the store."""
    assert scan_repository.list_scans(0) == []
    assert audit_repository.list_entries(WORKSPACE, 0) == []
