from app.repositories import scan_repository
from app.services import diff_scans


def _resource(rtype, rid, region, status, risk, name=None):
    return {
        "resource_type": rtype,
        "resource_id": rid,
        "name": name or rid,
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


def test_diff_classifies_added_removed_changed_unchanged(dynamo_table):
    older = _save(
        [
            _resource("EC2 Instance", "i-1", "us-east-1", "running", "MEDIUM"),
            _resource("EBS Volume", "vol-1", "us-east-1", "available", "MEDIUM"),
            _resource("Elastic IP", "eip-1", "us-east-1", "unassociated", "HIGH"),
        ]
    )
    newer = _save(
        [
            # i-1 was stopped: status + risk_level both changed.
            _resource("EC2 Instance", "i-1", "us-east-1", "stopped", "LOW"),
            # vol-1 identical: unchanged.
            _resource("EBS Volume", "vol-1", "us-east-1", "available", "MEDIUM"),
            # bucket is new: added. (eip-1 is gone: removed.)
            _resource("S3 Bucket", "my-bucket", "us-east-1", "active", "REVIEW"),
        ]
    )

    result = diff_scans(older, newer)

    assert result["summary"] == {"added": 1, "removed": 1, "changed": 1, "unchanged": 1}

    assert [r["resource_id"] for r in result["added"]] == ["my-bucket"]
    assert [r["resource_id"] for r in result["removed"]] == ["eip-1"]

    assert len(result["changed"]) == 1
    change = result["changed"][0]
    assert change["resource"]["resource_id"] == "i-1"
    assert change["changes"]["status"] == {"from": "running", "to": "stopped"}
    assert change["changes"]["risk_level"] == {"from": "MEDIUM", "to": "LOW"}

    assert result["from"]["scan_id"] == older
    assert result["to"]["scan_id"] == newer


def test_diff_identical_scans_has_no_changes(dynamo_table):
    resources = [_resource("EC2 Instance", "i-9", "us-west-2", "running", "MEDIUM")]
    a = _save(resources)
    b = _save(resources)

    result = diff_scans(a, b)
    assert result["summary"] == {"added": 0, "removed": 0, "changed": 0, "unchanged": 1}


def test_diff_missing_scan_raises_lookuperror(dynamo_table):
    real = _save([])
    try:
        diff_scans(real, "2026-01-01T00:00:00.000Z_missing")
    except LookupError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected LookupError for a missing scan id")


def test_same_id_different_region_are_distinct(dynamo_table):
    # Same resource_id in two regions must not be treated as one resource.
    older = _save([_resource("EC2 Instance", "i-1", "us-east-1", "running", "MEDIUM")])
    newer = _save([_resource("EC2 Instance", "i-1", "us-west-2", "running", "MEDIUM")])

    result = diff_scans(older, newer)
    assert result["summary"]["added"] == 1
    assert result["summary"]["removed"] == 1
    assert result["summary"]["changed"] == 0
