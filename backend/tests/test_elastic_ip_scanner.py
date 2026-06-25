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


def test_no_eips_returns_empty():
    assert elastic_ip_scanner.scan([REGION]) == []
