import boto3
from botocore.exceptions import ClientError

from app.models import Resource, RiskLevel
from app.services import scan_all, scan_one
from app.utils.concurrency import scan_regions
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

    assert set(result.keys()) == {"summary", "resources", "regions_failed"}
    assert result["regions_failed"] == []  # nothing was unreadable
    assert all(isinstance(r, Resource) for r in result["resources"])

    summary = result["summary"]
    assert summary["total_resources"] == len(result["resources"])
    # Running EC2 (MEDIUM) and S3 bucket (REVIEW) should both be counted.
    assert summary["by_risk_level"].get("MEDIUM", 0) >= 1
    assert summary["by_risk_level"].get("REVIEW", 0) >= 1


# --- Regions we could not read -------------------------------------------
#
# A disabled, throttled, or unpermitted region returns no resources, which is
# byte-for-byte what a genuinely empty region returns. For a tool whose claim is
# "here is what you have running", reporting "couldn't see" as "nothing there"
# is the worst answer it can give, so the sweep has to say which regions it
# failed to read.


def _fake(region: str) -> Resource:
    return Resource(
        resource_type="EC2 Instance",
        resource_id=f"i-{region}",
        region=region,
        status="running",
        risk_level=RiskLevel.MEDIUM,
        monthly_cost_risk="x",
        suggested_action="y",
    )


def _denied(code: str = "AuthFailure") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "not authorized"}}, "DescribeInstances")


def test_scan_regions_records_an_unreadable_region_in_the_pooled_path():
    failed: dict[str, str] = {}

    def scan_region(region: str):
        if region == "us-west-1":
            raise _denied()
        return [_fake(region)]

    found = scan_regions(
        scan_region, ["us-east-1", "us-west-1"], boto3.Session(), failed_regions=failed
    )

    assert [r.region for r in found] == ["us-east-1"]
    assert failed == {"us-west-1": "AuthFailure"}


def test_scan_regions_records_an_unreadable_region_in_the_single_region_path():
    failed: dict[str, str] = {}

    def scan_region(region: str):
        raise _denied("UnauthorizedOperation")

    assert scan_regions(scan_region, [REGION], boto3.Session(), failed_regions=failed) == []
    assert failed == {REGION: "UnauthorizedOperation"}


def test_scan_regions_without_a_collector_still_swallows_the_failure():
    """The out-parameter is optional; omitting it keeps the old behavior."""

    def scan_region(region: str):
        raise _denied()

    assert scan_regions(scan_region, [REGION], boto3.Session()) == []


def test_scan_all_reports_the_region_it_could_not_read(monkeypatch):
    from app.scanners import ec2_scanner

    def boom(region, session):
        raise _denied("UnauthorizedOperation")

    monkeypatch.setattr(ec2_scanner, "_scan_region", boom)

    result = scan_all(regions=[REGION])

    assert result["regions_failed"] == [
        {
            "region": REGION,
            "reason": "UnauthorizedOperation",
            "account_id": None,
            "account_label": None,
        }
    ]


# --- Resource age ---------------------------------------------------------


def test_scanners_capture_the_creation_time_their_api_reports():
    """Every API that reports a creation time must have it carried through.

    An unpopulated `created_at` is indistinguishable from an API that does not
    report one, so this pins which is which: `describe_addresses` genuinely
    returns no allocation time for an Elastic IP, and everything else does.
    """
    ec2 = boto3.client("ec2", region_name=REGION)
    _vpc, subnets = _network(ec2)
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=8)
    alloc = ec2.allocate_address(Domain="vpc")["AllocationId"]
    ec2.create_nat_gateway(SubnetId=subnets[0], AllocationId=alloc)
    boto3.client("elbv2", region_name=REGION).create_load_balancer(
        Name="lab-alb", Subnets=subnets, Type="application", Scheme="internet-facing"
    )
    boto3.client("rds", region_name=REGION).create_db_instance(
        DBInstanceIdentifier="lab-db",
        DBInstanceClass="db.t3.micro",
        Engine="postgres",
        MasterUsername="admin",
        MasterUserPassword="not-a-real-password",
        AllocatedStorage=20,
    )
    boto3.client("s3", region_name=REGION).create_bucket(Bucket="lab-age-bucket")

    scanned = scan_all(regions=[REGION])["resources"]
    dated = {r.resource_type.split(" (")[0]: r.created_at for r in scanned}

    for kind in ("EC2 Instance", "EBS Volume", "NAT Gateway", "RDS Database", "S3 Bucket"):
        assert dated[kind] is not None, kind
        assert dated[kind].tzinfo is not None, kind
    assert dated["Load Balancer"] is not None

    # describe_addresses reports no allocation time — blank, not forgotten.
    assert dated["Elastic IP"] is None


def _network(ec2):
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnets = [
        ec2.create_subnet(
            VpcId=vpc, CidrBlock=f"10.0.{i + 1}.0/24", AvailabilityZone=f"{REGION}{az}"
        )["Subnet"]["SubnetId"]
        for i, az in enumerate("ab")
    ]
    return vpc, subnets
