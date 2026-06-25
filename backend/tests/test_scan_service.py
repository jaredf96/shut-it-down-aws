import boto3

from app.models import Resource
from app.services import scan_all, scan_one
from tests.conftest import REGION


def test_scan_one_unknown_key_raises():
    try:
        scan_one("does-not-exist")
    except KeyError:
        return
    raise AssertionError("expected KeyError for an unknown scanner key")


def test_scan_all_aggregates_and_summarizes():
    # Create one resource the EC2 and S3 scanners will each find.
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="another-lab-bucket")

    result = scan_all()

    assert set(result.keys()) == {"summary", "resources"}
    assert all(isinstance(r, Resource) for r in result["resources"])

    summary = result["summary"]
    assert summary["total_resources"] == len(result["resources"])
    # Running EC2 (MEDIUM) and S3 bucket (REVIEW) should both be counted.
    assert summary["by_risk_level"].get("MEDIUM", 0) >= 1
    assert summary["by_risk_level"].get("REVIEW", 0) >= 1
