from app.models import RiskLevel
from app.scanners import nat_gateway_scanner
from tests.conftest import REGION, make_vpc_with_subnets


def test_nat_gateway_is_high_risk():
    ec2, _vpc, subnets = make_vpc_with_subnets(num_subnets=1)
    allocation_id = ec2.allocate_address(Domain="vpc")["AllocationId"]
    ec2.create_nat_gateway(SubnetId=subnets[0], AllocationId=allocation_id)

    results = nat_gateway_scanner.scan([REGION])

    assert len(results) == 1
    r = results[0]
    assert r.resource_type == "NAT Gateway"
    assert r.risk_level == RiskLevel.HIGH
    assert r.resource_id.startswith("nat-")


def test_no_nat_gateways_returns_empty():
    assert nat_gateway_scanner.scan([REGION]) == []
