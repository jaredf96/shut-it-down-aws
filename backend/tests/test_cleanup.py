import boto3
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories import audit_repository
from app.services import cleanup_service
from tests.conftest import REGION

client = TestClient(app)


@pytest.fixture
def cleanup_on(monkeypatch):
    monkeypatch.setenv("ENABLE_CLEANUP_ACTIONS", "true")


# --- Hard safety gate ----------------------------------------------------


def test_cleanup_disabled_by_default_returns_clear_error():
    res = client.post(
        "/cleanup/execute",
        json={
            "action": "stop_ec2_instance",
            "resource_id": "i-1",
            "confirm_resource_id": "i-1",
            "region": REGION,
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "Cleanup actions are disabled in this environment."


def test_catalog_excludes_dangerous_actions():
    body = client.get("/cleanup/actions").json()
    keys = {a["key"] for a in body["actions"]}
    # Only the safe trio is supported.
    assert keys == {"stop_ec2_instance", "release_elastic_ip", "delete_unattached_ebs_volume"}
    # Dangerous ones are documented as not supported.
    not_supported = {n["resource_type"] for n in body["not_supported"]}
    assert {"NAT Gateway", "S3 Bucket", "RDS Database"} <= not_supported


# --- Confirmation + unsupported (audited refusals) -----------------------


def test_confirmation_mismatch_is_rejected_and_audited(dynamo_table, cleanup_on):
    res = client.post(
        "/cleanup/execute",
        json={
            "action": "stop_ec2_instance",
            "resource_id": "i-1",
            "confirm_resource_id": "i-WRONG",
            "region": REGION,
        },
    )
    assert res.status_code == 400
    entries = client.get("/cleanup/audit").json()["entries"]
    assert any(e["status"] == "confirmation_mismatch" for e in entries)


def test_unsupported_action_is_refused_and_audited(dynamo_table, cleanup_on):
    res = client.post(
        "/cleanup/execute",
        json={
            "action": "terminate_ec2_instance",  # not in the catalog
            "resource_id": "i-1",
            "confirm_resource_id": "i-1",
            "region": REGION,
        },
    )
    assert res.status_code == 400
    entries = client.get("/cleanup/audit").json()["entries"]
    assert any(e["status"] == "unsupported_action" for e in entries)


# --- Dry run vs real execution ------------------------------------------


def test_stop_ec2_dry_run_does_not_stop(dynamo_table, cleanup_on):
    ec2 = boto3.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]

    res = client.post(
        "/cleanup/execute",
        json={
            "action": "stop_ec2_instance",
            "resource_id": iid,
            "confirm_resource_id": iid,
            "region": REGION,
            "dry_run": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "dry_run"
    # Still running.
    state = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["State"][
        "Name"
    ]
    assert state == "running"


def test_stop_ec2_real_execution_stops_and_audits_success(dynamo_table, cleanup_on):
    ec2 = boto3.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]

    res = client.post(
        "/cleanup/execute",
        json={
            "action": "stop_ec2_instance",
            "resource_id": iid,
            "confirm_resource_id": iid,
            "region": REGION,
            "dry_run": False,
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    state = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["State"][
        "Name"
    ]
    assert state in ("stopping", "stopped")
    entries = client.get("/cleanup/audit").json()["entries"]
    assert any(e["status"] == "success" and e["resource_id"] == iid for e in entries)


# --- Preconditions (live state re-check) ---------------------------------


def test_release_associated_eip_is_blocked(dynamo_table, cleanup_on):
    ec2 = boto3.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]
    alloc = ec2.allocate_address(Domain="vpc")["AllocationId"]
    ec2.associate_address(InstanceId=iid, AllocationId=alloc)

    res = client.post(
        "/cleanup/execute",
        json={
            "action": "release_elastic_ip",
            "resource_id": alloc,
            "confirm_resource_id": alloc,
            "region": REGION,
            "dry_run": False,
        },
    )
    assert res.status_code == 409  # precondition failed
    entries = client.get("/cleanup/audit").json()["entries"]
    assert any(e["status"] == "precondition_failed" for e in entries)


def test_release_unassociated_eip_succeeds(dynamo_table, cleanup_on):
    ec2 = boto3.client("ec2", region_name=REGION)
    alloc = ec2.allocate_address(Domain="vpc")["AllocationId"]

    res = client.post(
        "/cleanup/execute",
        json={
            "action": "release_elastic_ip",
            "resource_id": alloc,
            "confirm_resource_id": alloc,
            "region": REGION,
            "dry_run": False,
        },
    )
    assert res.status_code == 200
    assert ec2.describe_addresses().get("Addresses") == []


def test_delete_attached_volume_is_blocked(dynamo_table, cleanup_on):
    ec2 = boto3.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]
    vol = ec2.create_volume(AvailabilityZone="us-east-1a", Size=8)["VolumeId"]
    ec2.attach_volume(VolumeId=vol, InstanceId=iid, Device="/dev/sdf")

    res = client.post(
        "/cleanup/execute",
        json={
            "action": "delete_unattached_ebs_volume",
            "resource_id": vol,
            "confirm_resource_id": vol,
            "region": REGION,
            "dry_run": False,
        },
    )
    assert res.status_code == 409


def test_delete_unattached_volume_succeeds(dynamo_table, cleanup_on):
    ec2 = boto3.client("ec2", region_name=REGION)
    vol = ec2.create_volume(AvailabilityZone="us-east-1a", Size=8)["VolumeId"]

    res = client.post(
        "/cleanup/execute",
        json={
            "action": "delete_unattached_ebs_volume",
            "resource_id": vol,
            "confirm_resource_id": vol,
            "region": REGION,
            "dry_run": False,
        },
    )
    assert res.status_code == 200
    assert ec2.describe_volumes().get("Volumes") == []


# --- Account targeting ---------------------------------------------------


def test_unregistered_account_is_refused_and_never_uses_default_credentials(
    dynamo_table, cleanup_on, monkeypatch
):
    """A cleanup naming an unregistered account must be refused outright.

    The failure this guards against is not cross-workspace data loss — `get_account`
    is workspace-scoped, so another workspace's registration is unreachable. It is
    silent *retargeting*: the lookup missed, the service fell through to the
    server's own default credentials, and the destructive call landed on the
    host account while the audit recorded a success.
    """
    ec2 = boto3.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]

    # Record any attempt to resolve credentials. Reaching either of these at all
    # means the action was about to run against *some* account.
    resolved: list[str] = []
    monkeypatch.setattr(cleanup_service, "default_session", lambda: resolved.append("default"))
    monkeypatch.setattr(
        cleanup_service, "session_for_account", lambda account: resolved.append("assumed")
    )

    res = client.post(
        "/cleanup/execute",
        json={
            "action": "stop_ec2_instance",
            "resource_id": iid,
            "confirm_resource_id": iid,
            "region": REGION,
            "account_id": "999999999999",  # never registered by this workspace
            "dry_run": False,
        },
    )

    # Asserted first: against the old code this reads `['default'] == []`, which
    # names the defect exactly — the host's own credentials were resolved.
    assert resolved == []
    assert res.status_code == 404

    # The host account's instance — the one default credentials can see — is untouched.
    state = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["State"][
        "Name"
    ]
    assert state == "running"

    entries = client.get("/cleanup/audit").json()["entries"]
    refusal = next(e for e in entries if e["status"] == "unknown_account")
    assert refusal["account_id"] == "999999999999"
    assert refusal["resource_id"] == iid


def test_registered_account_still_assumes_its_role(dynamo_table, cleanup_on, monkeypatch):
    """The refusal must not swallow the legitimate multi-account path."""
    created = client.post(
        "/accounts",
        json={"name": "Sandbox", "role_arn": "arn:aws:iam::111111111111:role/Read"},
    ).json()

    assumed: list[dict] = []

    def _fake_assume(account):
        assumed.append(account)
        return boto3.Session()

    monkeypatch.setattr(cleanup_service, "session_for_account", _fake_assume)

    ec2 = boto3.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]

    res = client.post(
        "/cleanup/execute",
        json={
            "action": "stop_ec2_instance",
            "resource_id": iid,
            "confirm_resource_id": iid,
            "region": REGION,
            "account_id": created["account_id"],
            "dry_run": True,
        },
    )

    assert res.status_code == 200
    assert res.json()["status"] == "dry_run"
    assert [a["account_id"] for a in assumed] == ["111111111111"]


# --- Role gating ---------------------------------------------------------


def test_member_cannot_execute_cleanup(dynamo_table, cleanup_on):
    from app.repositories import user_repository

    member_key = user_repository.create_user("t", "M", role="member")["api_key"]

    res = client.post(
        "/cleanup/execute",
        headers={"X-API-Key": member_key},
        json={
            "action": "stop_ec2_instance",
            "resource_id": "i-1",
            "confirm_resource_id": "i-1",
            "region": REGION,
        },
    )
    assert res.status_code == 403  # admin role required


# --- Service-level audit guarantee ---------------------------------------


def test_failed_attempt_is_audited_even_without_persistence(monkeypatch):
    # No dynamo_table fixture -> persistence disabled. append() returns the
    # entry (logged) without storing. The attempt must still produce a record.
    monkeypatch.setenv("ENABLE_CLEANUP_ACTIONS", "true")
    record = cleanup_service.execute(
        action="stop_ec2_instance",
        resource_id="i-1",
        confirm_resource_id="i-2",
        region=REGION,
        workspace_id="t",
        user_id="u",
    )
    assert record["status"] == "confirmation_mismatch"
    assert record["id"]  # audit record was created
    # Nothing persisted (disabled), so listing is empty.
    assert audit_repository.list_entries("t") == []
