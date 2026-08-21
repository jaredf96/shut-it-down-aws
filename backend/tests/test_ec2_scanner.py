import boto3

from app.models import RiskLevel
from app.scanners import ec2_scanner
from tests.conftest import REGION


def test_running_instance_is_medium_risk():
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[
            {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "lab-box"}]}
        ],
    )

    results = ec2_scanner.scan([REGION])

    assert len(results) == 1
    r = results[0]
    assert r.resource_type == "EC2 Instance"
    assert r.name == "lab-box"
    assert r.region == REGION
    assert r.status == "running"
    assert r.risk_level == RiskLevel.MEDIUM
    assert r.resource_id.startswith("i-")


def test_stopped_instance_is_low_risk():
    ec2 = boto3.client("ec2", region_name=REGION)
    run = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    instance_id = run["Instances"][0]["InstanceId"]
    ec2.stop_instances(InstanceIds=[instance_id])

    results = ec2_scanner.scan([REGION])

    assert len(results) == 1
    assert results[0].status == "stopped"
    assert results[0].risk_level == RiskLevel.LOW


def test_no_instances_returns_empty():
    assert ec2_scanner.scan([REGION]) == []


def test_instance_carries_its_launch_time():
    """Age is what separates "14 idle instances" from "14 idle instances, the
    oldest running 87 days"."""
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)

    resource = ec2_scanner.scan([REGION])[0]

    assert resource.created_at is not None
    assert resource.created_at.tzinfo is not None  # comparable without guessing a zone
