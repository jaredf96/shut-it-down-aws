import boto3

from app.repositories import scan_repository
from app.services import scan_all
from tests.conftest import REGION


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
