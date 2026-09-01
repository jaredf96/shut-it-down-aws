import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.errors import PersistenceUnavailable
from app.main import app
from app.repositories import audit_repository
from app.services import cleanup_service
from tests.conftest import REGION

client = TestClient(app)

ADMIN = {"workspace_id": "t", "user_id": "u", "role": "admin"}


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


def test_disabled_refusal_is_audited(dynamo_table):
    """The env-flag refusal used to 403 in the route, invisibly to the audit
    trail — the exact gap the D10 review found. It now flows through the
    service like every other refused attempt."""
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
    entries = client.get("/cleanup/audit").json()["entries"]
    refusal = next(e for e in entries if e["status"] == "disabled")
    assert refusal["resource_id"] == "i-1"


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
    # A dry run mutates nothing, so it gets no write-ahead `initiated` entry.
    entries = client.get("/cleanup/audit").json()["entries"]
    assert not any(e["status"] == "initiated" for e in entries)


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
    # A real mutation leaves two entries: the write-ahead `initiated` row and
    # the outcome. (No order assertion — both can land in the same millisecond,
    # where the sort key's uuid suffix breaks the tie arbitrarily.)
    entries = client.get("/cleanup/audit").json()["entries"]
    statuses = sorted(e["status"] for e in entries if e["resource_id"] == iid)
    assert statuses == ["initiated", "success"]


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
    # The refusal must not reveal whether cleanup is even enabled.
    assert res.json()["detail"] == "Admin role required."
    # ...and it is audited, under the member's own workspace (D13).
    refusals = [e for e in audit_repository.list_entries("t") if e["status"] == "forbidden"]
    assert len(refusals) == 1
    assert refusals[0]["resource_id"] == "i-1"


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
        principal=ADMIN,
    )
    assert record["status"] == "confirmation_mismatch"
    assert record["id"]  # audit record was created
    # Nothing persisted (disabled), so listing is empty.
    assert audit_repository.list_entries("t") == []


# --- Write-ahead audit (D13) ----------------------------------------------

# Both ways a persistence-enabled audit write fails: the store unreachable
# (translated to PersistenceUnavailable) and the store answering with an error
# (ClientError passes through dynamo.py untranslated, on purpose).
_STORE_FAILURES = [
    PersistenceUnavailable("injected outage"),
    ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "PutItem"),
]


@pytest.mark.parametrize("failure", _STORE_FAILURES, ids=["unreachable", "client_error"])
def test_unauditable_mutation_is_refused_before_acting(
    dynamo_table, cleanup_on, monkeypatch, failure
):
    """Persistence enabled but not writable -> no real mutation may start.

    The write-ahead `initiated` row IS the pre-flight check: if it cannot be
    written, there would be no durable record that anything ran, so the
    service refuses before touching AWS.
    """
    ec2 = boto3.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]

    def _down(workspace_id, entry):
        raise failure

    monkeypatch.setattr(audit_repository, "append", _down)

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
    assert res.status_code == 503
    assert "could not durably record" in res.json()["detail"]
    # Refused before the mutation boundary: still running.
    state = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["State"][
        "Name"
    ]
    assert state == "running"


@pytest.mark.parametrize("failure", _STORE_FAILURES, ids=["unreachable", "client_error"])
def test_late_audit_failure_keeps_the_outcome_and_the_initiated_row(
    dynamo_table, cleanup_on, monkeypatch, failure
):
    """The store dies AFTER the mutation -> the client still learns the
    outcome, and the initiated row stands as outcome-unknown instead of the
    attempt vanishing into a 500."""
    ec2 = boto3.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]

    real_append = audit_repository.append
    calls = {"n": 0}

    def _dies_after_initiated(workspace_id, entry):
        calls["n"] += 1
        if calls["n"] == 1:  # the write-ahead row goes through
            return real_append(workspace_id, entry)
        raise failure

    monkeypatch.setattr(audit_repository, "append", _dies_after_initiated)

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
    # Only the initiated row persisted — the trail shows intent, not a hole.
    entries = client.get("/cleanup/audit").json()["entries"]
    statuses = [e["status"] for e in entries if e["resource_id"] == iid]
    assert statuses == ["initiated"]
