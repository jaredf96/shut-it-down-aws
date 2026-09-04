import json
import random
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError

from app.errors import ScanTooLarge
from app.repositories import dynamo, scan_repository
from app.services import scan_all
from tests.conftest import REGION

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo-data"


def test_persistence_disabled_by_default():
    # No DYNAMODB_TABLE_NAME set -> every repository call is a safe no-op.
    assert scan_repository.is_enabled() is False
    assert scan_repository.save_scan({"summary": {}, "resources": []}) is None
    assert scan_repository.list_scans() == []
    assert scan_repository.get_scan("anything") is None


def test_save_list_and_get_roundtrip(dynamo_table):
    # Create something for the scanners to find.
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)

    result = scan_all()
    scan_id = scan_repository.save_scan(result)
    assert scan_id is not None

    scans = scan_repository.list_scans()
    assert len(scans) == 1
    meta = scans[0]
    assert meta["scan_id"] == scan_id
    assert meta["resource_count"] == result["summary"]["total_resources"]
    assert "summary" in meta

    full = scan_repository.get_scan(scan_id)
    assert full is not None
    assert full["scan_id"] == scan_id
    assert len(full["resources"]) == result["summary"]["total_resources"]
    # Stored resources keep the same JSON shape as a live scan.
    assert full["resources"][0]["resource_type"] == "EC2 Instance"
    assert full["resources"][0]["risk_level"] == "MEDIUM"


def test_list_orders_newest_first(dynamo_table):
    a = scan_repository.save_scan({"summary": {"total_resources": 0}, "resources": []})
    b = scan_repository.save_scan({"summary": {"total_resources": 0}, "resources": []})

    ids = [s["scan_id"] for s in scan_repository.list_scans()]
    # scan_ids are time-prefixed and returned in descending (newest-first) order.
    assert ids == sorted([a, b], reverse=True)


def test_get_missing_scan_returns_none(dynamo_table):
    assert scan_repository.get_scan("2026-01-01T00:00:00.000Z_deadbeef") is None


# --- Storage shape: one item has to hold the whole scan -------------------


def _scan_shaped(n, rng):
    """Resources the way production makes them: a fixed prose catalog with
    per-resource identity fields varying. Randomising the prose too would
    understate compression by an order of magnitude and make the ceiling
    below meaningless."""
    templates = json.loads((DEMO_DIR / "current-scan.json").read_text())["resources"]
    out = []
    for i in range(n):
        base = dict(templates[i % len(templates)])
        base["resource_id"] = f"i-{rng.randrange(16**16):016x}"
        base["name"] = f"lab-{rng.randrange(10**6)}"
        base["region"] = rng.choice(["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"])
        base["account_id"] = f"{rng.randrange(10**12):012d}"
        base["created_at"] = f"2026-0{rng.randrange(1, 10)}-1{rng.randrange(10)}T00:00:00Z"
        base["estimated_monthly_cost"] = round(rng.uniform(0.5, 90.0), 2)
        out.append(base)
    return out


def test_resources_are_stored_compressed(dynamo_table):
    resources = [{"resource_id": f"i-{i}", "note": "left running after a lab"} for i in range(200)]
    scan_id = scan_repository.save_scan({"summary": {"total": 200}, "resources": resources})

    raw = dynamo.get_table().get_item(Key={"pk": "TENANT#default", "sk": scan_id})["Item"]
    assert "resources_gz" in raw
    assert "resources_json" not in raw
    assert len(bytes(raw["resources_gz"])) < len(json.dumps(resources)) / 5
    assert int(raw["resource_count"]) == 200
    # The summary stays plain, so a saved scan is still legible in the console.
    assert json.loads(raw["summary_json"]) == {"total": 200}

    assert scan_repository.get_scan(scan_id)["resources"] == resources


def test_legacy_uncompressed_scan_still_reads(dynamo_table):
    """Anything an earlier build stored is read forever and never migrated —
    the same reason D3 froze the storage names. This goes red the moment
    someone deletes the fallback branch as dead code."""
    resources = [{"resource_id": "i-legacy"}]
    scan_id = "2026-01-01T00:00:00.000Z_legacy00"
    dynamo.get_table().put_item(
        Item={
            "pk": "TENANT#default",
            "sk": scan_id,
            "scan_id": scan_id,
            "created_at": "2026-01-01T00:00:00.000Z",
            "resource_count": 1,
            "summary_json": json.dumps({"total": 1}),
            "resources_json": json.dumps(resources),
        }
    )

    assert scan_repository.get_scan(scan_id)["resources"] == resources
    assert scan_repository.list_scans_full(1)[0]["resources"] == resources


def test_scan_ceiling_is_where_the_docs_say(dynamo_table):
    """The number the docs quote, measured rather than asserted.

    A scan shaped like a real one is 624 B/resource raw and compresses 14.7x,
    so the 290 KB ceiling lands near 6,800 resources. 5,000 compresses to
    ~213 KB and 8,000 to ~340 KB, so both sides of this test have ~50 KB of
    margin and neither is a coin flip.
    """
    rng = random.Random(1234)

    scan_id = scan_repository.save_scan({"summary": {}, "resources": _scan_shaped(5000, rng)})
    assert len(scan_repository.get_scan(scan_id)["resources"]) == 5000

    with pytest.raises(ScanTooLarge):
        scan_repository.save_scan({"summary": {}, "resources": _scan_shaped(8000, rng)})


def test_oversized_scan_is_refused_and_writes_nothing(dynamo_table, monkeypatch):
    """The refusal is a pre-flight gate, so it leaves no partial row behind."""
    monkeypatch.setattr(scan_repository, "_compress", lambda payload: payload.encode())
    resources = [{"resource_id": f"i-{i}", "pad": "x" * 600} for i in range(700)]

    with pytest.raises(ScanTooLarge):
        scan_repository.save_scan({"summary": {}, "resources": resources})

    assert scan_repository.list_scans() == []


def test_dynamodb_size_rejection_is_translated(dynamo_table, monkeypatch):
    """The backstop for the case where DynamoDB's size accounting disagrees
    with ours. Also proves the store really does enforce the item limit."""
    monkeypatch.setattr(scan_repository, "_compress", lambda payload: payload.encode())
    monkeypatch.setattr(scan_repository, "_MAX_ITEM_BYTES", 10_000_000)
    resources = [{"resource_id": f"i-{i}", "pad": "x" * 600} for i in range(700)]

    with pytest.raises(ScanTooLarge):
        scan_repository.save_scan({"summary": {}, "resources": resources})


def test_an_unrelated_validation_error_is_not_relabelled_as_too_large(dynamo_table, monkeypatch):
    """ValidationException is DynamoDB's generic 400. Relabelling all of them
    would let `scan_everything` swallow a real fault into `persisted: false`,
    indistinguishable from persistence being switched off."""

    class _Stub:
        def put_item(self, **kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "ValidationException",
                        "Message": "ExpressionAttributeNames contains invalid key",
                    }
                },
                "PutItem",
            )

    monkeypatch.setattr(scan_repository, "get_table", lambda: _Stub())

    with pytest.raises(ClientError):
        scan_repository.save_scan({"summary": {}, "resources": [{"resource_id": "i-1"}]})


def test_corrupt_scan_item_raises_rather_than_reporting_no_resources(dynamo_table):
    """Before this change the missing-payload branch returned [], so a corrupt
    row read back as a scan that found nothing."""
    scan_id = "2026-01-01T00:00:00.000Z_corrupt0"
    dynamo.get_table().put_item(
        Item={
            "pk": "TENANT#default",
            "sk": scan_id,
            "scan_id": scan_id,
            "created_at": "2026-01-01T00:00:00.000Z",
            "resource_count": 1,
            "summary_json": json.dumps({}),
        }
    )

    with pytest.raises(KeyError):
        scan_repository.list_scans_full(1)
