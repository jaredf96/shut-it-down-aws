import boto3

from app.models import RiskLevel
from app.scanners import rds_scanner
from tests.conftest import REGION


def test_rds_instance_is_high_risk():
    rds = boto3.client("rds", region_name=REGION)
    rds.create_db_instance(
        DBInstanceIdentifier="lab-db",
        DBInstanceClass="db.t3.micro",
        Engine="postgres",
        MasterUsername="admin",
        MasterUserPassword="supersecret123",
        AllocatedStorage=20,
    )

    results = rds_scanner.scan([REGION])

    assert len(results) == 1
    r = results[0]
    assert r.resource_type == "RDS Database"
    assert r.resource_id == "lab-db"
    assert r.risk_level == RiskLevel.HIGH
    assert "postgres" in r.name
    # Storage is priced, so it has to survive the scan.
    assert r.details["allocated_storage_gb"] == 20


def test_no_databases_returns_empty():
    assert rds_scanner.scan([REGION]) == []
