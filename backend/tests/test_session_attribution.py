"""What a scanned account's own CloudTrail says about who caused a call.

The app's audit trail names the user. The *scanned* account's trail sees only
`assumed-role/<RoleName>/<session name>` — and that session name was one
constant, so every call from every user of every workspace was one principal
string in the one log the account's owner actually reads.

These tests pin the name's shape, its IAM validity, and that both callers with
a principal in hand forward it.
"""

import re

import boto3
import pytest
from fastapi.testclient import TestClient

from app.aws.session import (
    _MAX_SESSION_NAME,
    _PREFIX,
    _UID_LIMIT,
    session_for_account,
    session_name_for,
)
from app.main import app
from app.repositories import account_repository, user_repository
from tests.conftest import REGION

client = TestClient(app)

# What IAM accepts for a RoleSessionName.
_IAM_SESSION_NAME = re.compile(r"[\w+=,.@-]{2,64}")


def test_the_session_name_carries_the_workspace_and_the_user():
    assert session_name_for({"workspace_id": "default", "user_id": "local"}) == (
        "shutitdown.default.local"
    )

    uid = "4f3c" * 8  # a uuid4 hex is 32 chars and is never shortened
    assert session_name_for({"workspace_id": "class-101", "user_id": uid}) == (
        f"shutitdown.class-101.{uid}"
    )


def test_the_name_always_fits_what_iam_accepts():
    name = session_name_for({"workspace_id": "w" * 200, "user_id": "u" * 200})

    assert len(name) <= _MAX_SESSION_NAME
    assert _IAM_SESSION_NAME.fullmatch(name)

    # Pinned as arithmetic, not just as an example: lengthening the prefix
    # later must not silently squeeze the workspace field out of existence.
    assert _MAX_SESSION_NAME - len(_PREFIX) - 2 - _UID_LIMIT >= 8


def test_a_shortened_field_is_marked_and_never_ambiguous():
    shared = "workspace-with-a-very-long-name-" * 3
    first = session_name_for({"workspace_id": shared + "aaa", "user_id": "u" * 32})
    second = session_name_for({"workspace_id": shared + "bbb", "user_id": "u" * 32})

    # The digest is over the whole original, so a shared prefix does not collide.
    assert first != second

    # "." separates fields and "=" marks a shortened one, so neither can occur
    # inside a field and the name always splits back into its parts.
    messy = session_name_for({"workspace_id": "team/one.two", "user_id": "u"})
    assert len(messy.split(".")) == 3
    assert "=" in messy.split(".")[1]
    assert "=" not in session_name_for({"workspace_id": "clean", "user_id": "u"})


def test_no_principal_is_named_unattributed_rather_than_borrowed():
    """A caller with no request behind it degrades to an honest name. Two
    fields, never three, so it cannot collide with a real principal's."""
    assert session_name_for(None) == "shutitdown.unattributed"
    assert session_name_for({}) == "shutitdown.unattributed"
    assert len(session_name_for(None).split(".")) == 2


def test_the_assumed_role_arn_carries_the_session_name(dynamo_table):
    """The observable half: not our kwargs, but the principal string the target
    account's trail would record."""
    uid = "u" * 32
    session = session_for_account(
        {"role_arn": "arn:aws:iam::222222222222:role/ShutItDownScannerRole"},
        principal={"workspace_id": "class-101", "user_id": uid},
    )

    arn = session.client("sts", region_name=REGION).get_caller_identity()["Arn"]
    assert arn.endswith(f":assumed-role/ShutItDownScannerRole/shutitdown.class-101.{uid}")


def test_scan_forwards_the_authenticated_principal_to_the_assume_role(dynamo_table, monkeypatch):
    user = user_repository.create_user("class-101", "TA", role="admin")
    account_repository.create_account(
        "class-101",
        {"name": "Sandbox", "role_arn": "arn:aws:iam::111111111111:role/Read"},
    )

    seen = {}

    def capture(account, *, principal=None):
        seen.update(principal or {})
        return boto3.Session()

    monkeypatch.setattr("app.services.multi_account_service.session_for_account", capture)

    res = client.get("/scan?save=false", headers={"X-API-Key": user["api_key"]})

    assert res.status_code == 200
    assert seen["user_id"] == user["user_id"]
    assert seen["workspace_id"] == "class-101"


def test_cleanup_forwards_the_authenticated_principal_to_the_assume_role(dynamo_table, monkeypatch):
    monkeypatch.setenv("ENABLE_CLEANUP_ACTIONS", "true")
    user = user_repository.create_user("class-101", "TA", role="admin")
    account = account_repository.create_account(
        "class-101",
        {"name": "Sandbox", "role_arn": "arn:aws:iam::111111111111:role/Read"},
    )

    ec2 = boto3.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]

    seen = {}

    def capture(acct, *, principal=None):
        seen.update(principal or {})
        return boto3.Session()

    monkeypatch.setattr("app.services.cleanup_service.session_for_account", capture)

    res = client.post(
        "/cleanup/execute",
        json={
            "action": "stop_ec2_instance",
            "resource_id": iid,
            "confirm_resource_id": iid,
            "region": REGION,
            "account_id": account["account_id"],
            "dry_run": True,
        },
        headers={"X-API-Key": user["api_key"]},
    )

    assert res.status_code == 200
    assert seen["user_id"] == user["user_id"]
    assert seen["workspace_id"] == "class-101"


def test_zero_config_mode_names_the_install_not_the_person(dynamo_table, monkeypatch):
    """With `AUTH_REQUIRED` unset there is exactly one principal, so the name
    is the same for everyone using that install — well-formed, and honest about
    what it can distinguish. Per-user attribution in the target account's trail
    needs `AUTH_REQUIRED=true` and a key per user."""
    account_repository.create_account(
        "default",
        {"name": "Sandbox", "role_arn": "arn:aws:iam::111111111111:role/Read"},
    )

    seen = {}

    def capture(account, *, principal=None):
        seen.update(principal or {})
        return boto3.Session()

    monkeypatch.setattr("app.services.multi_account_service.session_for_account", capture)

    assert client.get("/scan?save=false").status_code == 200
    assert session_name_for(seen) == "shutitdown.default.local"


@pytest.mark.parametrize(
    "principal",
    [
        {"workspace_id": "default", "user_id": "local"},
        {"workspace_id": "w" * 200, "user_id": "u" * 200},
        {},
        None,
    ],
)
def test_every_name_this_can_produce_is_one_iam_would_accept(principal):
    assert _IAM_SESSION_NAME.fullmatch(session_name_for(principal))
