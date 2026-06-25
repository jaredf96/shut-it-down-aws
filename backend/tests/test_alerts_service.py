from app.models import AlertSeverity
from app.services import evaluate_alerts


def _r(rid, risk, rtype="EC2 Instance", region="us-east-1", status="running"):
    return {
        "resource_type": rtype,
        "resource_id": rid,
        "name": rid,
        "region": region,
        "status": status,
        "risk_level": risk,
        "monthly_cost_risk": "costs money",
        "suggested_action": "review it",
    }


def test_standing_high_risk_is_a_warning_with_no_history():
    alerts = evaluate_alerts([_r("nat-1", "HIGH", rtype="NAT Gateway")])
    assert len(alerts) == 1
    assert alerts[0].severity == AlertSeverity.WARNING
    assert alerts[0].rule == "high_risk_resource"


def test_low_and_standing_medium_do_not_alert():
    alerts = evaluate_alerts([_r("i-1", "LOW", status="stopped"), _r("i-2", "MEDIUM")])
    assert alerts == []


def test_new_billable_resource_is_critical():
    previous = [_r("i-1", "MEDIUM")]
    current = [_r("i-1", "MEDIUM"), _r("nat-1", "HIGH", rtype="NAT Gateway")]
    alerts = evaluate_alerts(current, previous)
    # nat-1 is new + billable -> CRITICAL; i-1 is standing MEDIUM -> no alert.
    assert len(alerts) == 1
    assert alerts[0].severity == AlertSeverity.CRITICAL
    assert alerts[0].rule == "new_billable_resource"
    assert alerts[0].resource_id == "nat-1"


def test_risk_increase_is_critical():
    previous = [_r("vol-1", "LOW", rtype="EBS Volume")]
    current = [_r("vol-1", "MEDIUM", rtype="EBS Volume")]
    alerts = evaluate_alerts(current, previous)
    assert len(alerts) == 1
    assert alerts[0].rule == "risk_increased"
    assert alerts[0].severity == AlertSeverity.CRITICAL


def test_new_review_resource_is_info():
    previous = []
    current = [_r("bucket-1", "REVIEW", rtype="S3 Bucket", status="active")]
    alerts = evaluate_alerts(current, previous)
    assert len(alerts) == 1
    assert alerts[0].severity == AlertSeverity.INFO
    assert alerts[0].rule == "new_review_resource"


def test_one_alert_per_resource_and_sorted_by_severity():
    previous = [_r("i-1", "LOW")]
    current = [
        _r("nat-1", "HIGH", rtype="NAT Gateway"),  # standing HIGH but new here -> CRITICAL
        _r("i-1", "MEDIUM"),  # LOW -> MEDIUM: risk increased -> CRITICAL
        _r("eip-1", "HIGH", rtype="Elastic IP", status="unassociated"),  # new HIGH -> CRITICAL
    ]
    alerts = evaluate_alerts(current, previous)
    # exactly one alert per resource
    assert len(alerts) == 3
    assert len({a.resource_id for a in alerts}) == 3
    # CRITICAL first
    assert alerts[0].severity == AlertSeverity.CRITICAL


def test_no_previous_means_nothing_is_flagged_new():
    # Without history, a HIGH resource is a standing WARNING, never "new".
    alerts = evaluate_alerts([_r("nat-1", "HIGH", rtype="NAT Gateway")], None)
    assert alerts[0].rule == "high_risk_resource"
