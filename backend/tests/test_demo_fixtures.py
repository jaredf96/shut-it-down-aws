"""The public demo's fixtures must stay faithful to the real API.

The demo ships curated data, which creates a quiet failure mode: the backend
schema evolves, the fixtures don't, and the public demo slowly starts showing a
shape the API no longer returns. Nobody notices, because the demo never calls
the API.

These tests close that gap. They validate `demo-data/` against the same Pydantic
models the API serves, assert the structural story the demo depends on (two
accounts, two scans, a meaningful diff), and check that nothing real leaked into
a public artifact.

Regenerate with `make demo-fixtures` if one of these fails.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.models import Alert, Resource

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo-data"

RESOURCES = TypeAdapter(list[Resource])
ALERTS = TypeAdapter(list[Alert])

SCAN_FILES = ["current-scan.json", "previous-scan.json"]


def load(name: str) -> dict:
    return json.loads((DEMO_DIR / name).read_text())


@pytest.fixture(scope="module")
def current() -> dict:
    return load("current-scan.json")


@pytest.fixture(scope="module")
def previous() -> dict:
    return load("previous-scan.json")


# --- Schema fidelity -----------------------------------------------------


@pytest.mark.parametrize("filename", SCAN_FILES)
def test_scan_resources_match_the_resource_model(filename):
    """Every fixture resource must validate as the model the API returns."""
    scan = load(filename)
    RESOURCES.validate_python(scan["resources"])


@pytest.mark.parametrize("filename", SCAN_FILES)
def test_scan_envelope_shape(filename):
    scan = load(filename)
    assert set(scan) == {"scan_id", "created_at", "summary", "resources"}
    assert set(scan["summary"]) == {
        "total_resources",
        "by_risk_level",
        "estimated_monthly_cost",
    }


def test_alerts_match_the_alert_model():
    ALERTS.validate_python(load("alerts.json")["alerts"])


def test_accounts_have_the_fields_the_ui_reads():
    for account in load("accounts.json")["accounts"]:
        assert {"account_id", "name", "role_arn"} <= set(account)


# --- Internal consistency ------------------------------------------------


@pytest.mark.parametrize("filename", SCAN_FILES)
def test_summary_agrees_with_resources(filename):
    """A hand-edited fixture usually breaks here first."""
    scan = load(filename)
    resources = scan["resources"]
    summary = scan["summary"]

    assert summary["total_resources"] == len(resources)

    counts: dict[str, int] = {}
    for r in resources:
        counts[r["risk_level"]] = counts.get(r["risk_level"], 0) + 1
    assert summary["by_risk_level"] == counts

    expected = round(sum(r["estimated_monthly_cost"] or 0 for r in resources), 2)
    assert summary["estimated_monthly_cost"] == pytest.approx(expected, abs=0.01)


def test_alerts_reference_resources_that_exist(current):
    ids = {r["resource_id"] for r in current["resources"]}
    for alert in load("alerts.json")["alerts"]:
        assert alert["resource_id"] in ids, f"alert references unknown {alert['resource_id']}"


# --- The story the demo needs to tell ------------------------------------


def test_demo_covers_every_risk_level(current):
    """The dashboard's risk tiles are only convincing if all of them populate."""
    levels = {r["risk_level"] for r in current["resources"]}
    assert {"HIGH", "MEDIUM", "LOW", "REVIEW"} <= levels


def test_demo_spans_two_accounts_and_multiple_regions(current):
    assert len({r["account_id"] for r in current["resources"]}) >= 2
    assert len({r["region"] for r in current["resources"]}) >= 2


def test_diff_between_scans_has_something_in_every_bucket(current, previous):
    """Added, removed, and changed must all be non-empty or the compare view is dull."""

    def identity(r):
        return (r["resource_type"], r["region"], r["resource_id"], r["account_id"])

    before = {identity(r): r for r in previous["resources"]}
    after = {identity(r): r for r in current["resources"]}

    added = [k for k in after if k not in before]
    removed = [k for k in before if k not in after]
    changed = [
        k
        for k in after
        if k in before and any(before[k][f] != after[k][f] for f in ("status", "risk_level"))
    ]

    assert added, "no resources appear only in the current scan"
    assert removed, "no resources disappeared between scans"
    assert changed, "no resource changed status or risk between scans"


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_demo_resources_carry_a_plausible_age(current):
    """ "14 idle instances" is inventory; "oldest running 87 days" is a finding.

    The generator pins these ages deliberately — moto stamps the wall clock, so
    without pinning every demo resource would be zero days old and would churn
    on every regeneration. This fails if that pinning is ever dropped.
    """
    scanned_at = _moment(current["created_at"])
    ages = {
        r["resource_id"]: (scanned_at - _moment(r["created_at"])).days
        for r in current["resources"]
        if r["created_at"]
    }

    assert len(ages) >= 10, "most of the demo should show an age"
    assert all(days > 0 for days in ages.values()), "nothing predates its own creation"
    assert max(ages.values()) >= 60, "no resource is old enough to look like a finding"

    # The one service whose API reports no creation time at all. A blank age
    # column there is correct; a blank one anywhere else means it was dropped.
    undated = {r["resource_type"] for r in current["resources"] if not r["created_at"]}
    assert undated == {"Elastic IP"}


def test_scanner_variety(current):
    """Cover enough services that the demo represents the real scanner set."""
    types = {r["resource_type"].split(" (")[0] for r in current["resources"]}
    assert {"Elastic IP", "EBS Volume", "EC2 Instance", "NAT Gateway", "S3 Bucket"} <= types


# --- Nothing real may leak ------------------------------------------------


def test_fixtures_use_reserved_documentation_account_ids():
    """AWS reserves these ranges for docs, so they cannot be anyone's account."""
    allowed = {"111122223333", "444455556666"}
    for account in load("accounts.json")["accounts"]:
        assert account["account_id"] in allowed
    for filename in SCAN_FILES:
        for r in load(filename)["resources"]:
            assert r["account_id"] in allowed


def test_no_moto_default_account_id_leaks_into_arns():
    """moto stamps 123456789012 into ARNs; the generator rewrites it."""
    for filename in SCAN_FILES + ["alerts.json", "accounts.json"]:
        assert "123456789012" not in (DEMO_DIR / filename).read_text()
