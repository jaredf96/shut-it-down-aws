import boto3
import pytest
from botocore.exceptions import ClientError

from app.models import RiskLevel
from app.scanners import s3_scanner
from tests.conftest import REGION


def test_bucket_is_review_risk():
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="my-lab-bucket")

    results = s3_scanner.scan()

    assert len(results) == 1
    r = results[0]
    assert r.resource_type == "S3 Bucket"
    assert r.resource_id == "my-lab-bucket"
    assert r.risk_level == RiskLevel.REVIEW


def test_no_buckets_returns_empty():
    assert s3_scanner.scan() == []


def test_unreadable_s3_raises_rather_than_reporting_no_buckets(monkeypatch):
    """An empty list must only ever mean "this account has no buckets".

    S3 is global, so there is no region for `failed_regions` to blame. The
    scanner therefore lets the failure out and `scan_service` records the whole
    scanner as unavailable — see test_scan_service.
    """

    def denied(**kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "ListBuckets")

    class _Blocked:
        list_buckets = staticmethod(denied)

    monkeypatch.setattr(boto3.Session, "client", lambda self, *a, **k: _Blocked())

    with pytest.raises(ClientError):
        s3_scanner.scan()


def test_a_bucket_whose_region_cannot_be_read_is_still_reported(monkeypatch):
    """One unreadable location must not hide the bucket, or the rest of them."""
    boto3.client("s3", region_name=REGION).create_bucket(Bucket="opaque-bucket")
    monkeypatch.setattr(
        s3_scanner,
        "_bucket_region",
        lambda s3, name: "unknown",
    )

    results = s3_scanner.scan()

    assert [(r.resource_id, r.region) for r in results] == [("opaque-bucket", "unknown")]
