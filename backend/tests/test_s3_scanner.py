import boto3

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
