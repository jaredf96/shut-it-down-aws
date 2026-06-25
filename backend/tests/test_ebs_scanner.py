import boto3

from app.models import RiskLevel
from app.scanners import ebs_scanner
from tests.conftest import REGION


def test_unattached_volume_is_medium_risk():
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.create_volume(AvailabilityZone="us-east-1a", Size=8)

    results = ebs_scanner.scan([REGION])

    assert len(results) == 1
    r = results[0]
    assert r.resource_type == "EBS Volume"
    assert r.status == "available"
    assert r.risk_level == RiskLevel.MEDIUM
    assert r.resource_id.startswith("vol-")


def test_attached_volume_is_low_risk():
    ec2 = boto3.client("ec2", region_name=REGION)
    run = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    instance_id = run["Instances"][0]["InstanceId"]
    vol_id = ec2.create_volume(AvailabilityZone="us-east-1a", Size=8)["VolumeId"]
    ec2.attach_volume(VolumeId=vol_id, InstanceId=instance_id, Device="/dev/sdf")

    results = ebs_scanner.scan([REGION])

    # The instance's root volume plus our attached volume — all in-use.
    assert len(results) >= 1
    assert all(r.risk_level == RiskLevel.LOW for r in results)
    assert all(r.status == "in-use" for r in results)
