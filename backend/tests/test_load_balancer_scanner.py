import boto3
from botocore.exceptions import ClientError

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


def test_region_where_both_apis_fail_is_reported_not_treated_as_empty(monkeypatch):
    """v2 and classic are queried independently, but if BOTH fail the region was
    not read at all — swallowing that would report it upward as "no load
    balancers here"."""
    denied = ClientError({"Error": {"Code": "AuthFailure"}}, "DescribeLoadBalancers")

    def boom(region, session):
        raise denied

    monkeypatch.setattr(load_balancer_scanner, "_scan_v2", boom)
    monkeypatch.setattr(load_balancer_scanner, "_scan_classic", boom)

    failed: dict[str, str] = {}
    assert load_balancer_scanner.scan([REGION], failed_regions=failed) == []
    assert failed == {REGION: "AuthFailure"}


def test_one_failing_api_still_returns_the_other_and_reports_nothing(monkeypatch):
    _ec2, _vpc, subnets = make_vpc_with_subnets(num_subnets=2)
    boto3.client("elbv2", region_name=REGION).create_load_balancer(
        Name="lab-alb", Subnets=subnets, Type="application", Scheme="internet-facing"
    )

    def boom(region, session):
        raise ClientError({"Error": {"Code": "AuthFailure"}}, "DescribeLoadBalancers")

    monkeypatch.setattr(load_balancer_scanner, "_scan_classic", boom)

    failed: dict[str, str] = {}
    results = load_balancer_scanner.scan([REGION], failed_regions=failed)

    assert [r.name for r in results] == ["lab-alb"]
    assert failed == {}  # a partial result is still a result
