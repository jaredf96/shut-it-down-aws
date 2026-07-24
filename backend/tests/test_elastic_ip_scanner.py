import boto3

from app.models import RiskLevel
from app.scanners import elastic_ip_scanner
from tests.conftest import REGION


def test_unassociated_eip_is_high_risk():
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.allocate_address(Domain="vpc")

    results = elastic_ip_scanner.scan([REGION])

    assert len(results) == 1
    r = results[0]
    assert r.resource_type == "Elastic IP"
    assert r.status == "unassociated"
    assert r.risk_level == RiskLevel.HIGH


def test_associated_eip_is_low_risk_but_not_free():
    ec2 = boto3.client("ec2", region_name=REGION)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    eni = ec2.create_network_interface(SubnetId=subnet)["NetworkInterface"]["NetworkInterfaceId"]
    allocation = ec2.allocate_address(Domain="vpc")["AllocationId"]
    ec2.associate_address(AllocationId=allocation, NetworkInterfaceId=eni)

    results = elastic_ip_scanner.scan([REGION])

    assert len(results) == 1
    r = results[0]
    assert r.status == "associated"
    assert r.risk_level == RiskLevel.LOW
    assert "free" not in r.monthly_cost_risk.lower()
    assert "charges hourly" in r.monthly_cost_risk


def test_no_eips_returns_empty():
    assert elastic_ip_scanner.scan([REGION]) == []
