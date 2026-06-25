import boto3

from app.models import RiskLevel
from app.scanners import load_balancer_scanner
from tests.conftest import REGION, make_vpc_with_subnets


def test_application_load_balancer_is_medium_risk():
    _ec2, _vpc, subnets = make_vpc_with_subnets(num_subnets=2)
    elbv2 = boto3.client("elbv2", region_name=REGION)
    elbv2.create_load_balancer(
        Name="lab-alb",
        Subnets=subnets,
        Type="application",
        Scheme="internet-facing",
    )

    results = load_balancer_scanner.scan([REGION])

    assert len(results) == 1
    r = results[0]
    assert "Load Balancer" in r.resource_type
    assert r.name == "lab-alb"
    assert r.risk_level == RiskLevel.MEDIUM


def test_no_load_balancers_returns_empty():
    assert load_balancer_scanner.scan([REGION]) == []
