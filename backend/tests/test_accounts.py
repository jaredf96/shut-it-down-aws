import boto3
import pytest
from pydantic import ValidationError

from app.aws.session import session_for_account
from app.models.account import AccountCreate
from app.repositories import account_repository
from app.services import diff_scans, scan_accounts
from app.services.multi_account_service import _tag
from tests.conftest import REGION

# --- account_repository --------------------------------------------------


def test_account_id_parsed_from_role_arn():
    arn = "arn:aws:iam::123456789012:role/CloudLabReadOnly"
    assert account_repository.account_id_from_role_arn(arn) == "123456789012"


def test_unparseable_role_arn_raises_instead_of_inventing_an_account_id():
    """A registration that cannot be parsed is a bad request, not an account.

    The old fallback returned `uuid4().hex[:12]` and stored it as the AWS
    account id, so a typo produced a record keyed on a number that matches no
    account in AWS.
    """
    bad = [
        "",
        "not-an-arn",
        "arn:aws:iam::12345:role/TooShort",
        # Not a role. The helper used to return the account id for any IAM ARN.
        "arn:aws:iam::123456789012:user/Alice",
        # A valid ARN inside other text. `re.search` used to find it anyway.
        "prefix arn:aws:iam::123456789012:role/R suffix",
        # Arabic-Indic numerals. `\d` matches these; `[0-9]` does not. Without
        # that, this parsed and returned a non-ASCII string as the account id.
        "arn:aws:iam::\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u0660\u0661\u0662:role/R",
    ]
    for arn in bad:
        with pytest.raises(ValueError, match="Not an IAM role ARN"):
            account_repository.account_id_from_role_arn(arn)


def test_malformed_role_arn_is_rejected_at_the_api_boundary():
    """`AccountCreate` refuses it before the route runs, so it is a 422."""
    with pytest.raises(ValidationError):
        AccountCreate(name="Typo", role_arn="arn:aws:iam::123:role/Nope")

    # An unanchored pattern would accept this: it *contains* a valid ARN, but
    # the account id parsed back out would be the wrong twelve digits.
    with pytest.raises(ValidationError):
        AccountCreate(name="Smuggled", role_arn="999999999999 arn:aws:iam::111111111111:role/R")

    # Non-ASCII digits must not satisfy the twelve-digit account id.
    with pytest.raises(ValidationError):
        AccountCreate(
            name="Unicode",
            role_arn="arn:aws:iam::\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u0660\u0661\u0662:role/R",
        )

    # Partitions and role paths stay valid.
    assert AccountCreate(name="GovCloud", role_arn="arn:aws-us-gov:iam::111111111111:role/R")
    assert AccountCreate(name="Path", role_arn="arn:aws:iam::111111111111:role/team/Read")


def test_create_list_get_delete_account(dynamo_table):
    created = account_repository.create_account(
        "workspace-1",
        {"name": "Sandbox", "role_arn": "arn:aws:iam::111111111111:role/Read"},
    )
    assert created["account_id"] == "111111111111"
    assert "pk" not in created and "sk" not in created

    listed = account_repository.list_accounts("workspace-1")
    assert len(listed) == 1

    assert account_repository.get_account("workspace-1", "111111111111") is not None
    assert account_repository.delete_account("workspace-1", "111111111111") is True
    assert account_repository.list_accounts("workspace-1") == []


def test_accounts_are_isolated_by_workspace(dynamo_table):
    account_repository.create_account(
        "workspace-a", {"name": "A", "role_arn": "arn:aws:iam::111111111111:role/R"}
    )
    assert len(account_repository.list_accounts("workspace-a")) == 1
    assert account_repository.list_accounts("workspace-b") == []


# --- assume-role session -------------------------------------------------


def test_session_for_account_assumes_role(dynamo_table):
    # moto's STS returns usable temp credentials for any role ARN.
    session = session_for_account(
        {"role_arn": "arn:aws:iam::222222222222:role/Read", "external_id": None}
    )
    assert isinstance(session, boto3.Session)
    assert session.get_credentials() is not None


# --- multi-account scan tagging ------------------------------------------


def test_scan_accounts_falls_back_to_default_when_none_registered(dynamo_table):
    boto3.client("ec2", region_name=REGION).run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1
    )
    result = scan_accounts("workspace-1")  # no accounts registered
    assert "accounts_scanned" not in result  # default single-account path
    assert result["summary"]["total_resources"] >= 1


def test_scan_accounts_tags_resources(dynamo_table, monkeypatch):
    # Register two accounts; make assume-role a no-op (use the moto default session).
    account_repository.create_account(
        "workspace-1", {"name": "Acct One", "role_arn": "arn:aws:iam::111111111111:role/R"}
    )
    account_repository.create_account(
        "workspace-1", {"name": "Acct Two", "role_arn": "arn:aws:iam::222222222222:role/R"}
    )
    monkeypatch.setattr(
        "app.services.multi_account_service.session_for_account",
        lambda account, principal=None: boto3.Session(),
    )
    boto3.client("ec2", region_name=REGION).run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1
    )

    result = scan_accounts("workspace-1")
    assert len(result["accounts_scanned"]) == 2
    assert result["account_errors"] == []
    # Every resource is tagged with one of the two account ids.
    account_ids = {r.account_id for r in result["resources"]}
    assert account_ids <= {"111111111111", "222222222222"}
    assert all(r.account_label in ("Acct One", "Acct Two") for r in result["resources"])


def test_scan_accounts_collects_per_account_errors(dynamo_table, monkeypatch):
    account_repository.create_account(
        "workspace-1", {"name": "Broken", "role_arn": "arn:aws:iam::333333333333:role/R"}
    )

    def boom(account, principal=None):
        raise RuntimeError("assume role denied")

    monkeypatch.setattr("app.services.multi_account_service.session_for_account", boom)

    result = scan_accounts("workspace-1")
    assert result["resources"] == []
    assert len(result["account_errors"]) == 1
    assert "denied" in result["account_errors"][0]["error"]


# --- account-aware diffing -----------------------------------------------


def test_diff_identity_includes_account(dynamo_table):
    from app.repositories import scan_repository

    def res(account_id):
        return {
            "resource_type": "EC2 Instance",
            "resource_id": "i-1",
            "region": "us-east-1",
            "status": "running",
            "risk_level": "MEDIUM",
            "account_id": account_id,
        }

    older = scan_repository.save_scan({"summary": {}, "resources": [res("111111111111")]})
    newer = scan_repository.save_scan({"summary": {}, "resources": [res("222222222222")]})

    # Same resource_id but different accounts -> added + removed, not "unchanged".
    result = diff_scans(older, newer)
    assert result["summary"]["added"] == 1
    assert result["summary"]["removed"] == 1
    assert result["summary"]["unchanged"] == 0


def test_tag_sets_account_fields():
    from app.models import Resource

    r = Resource(
        resource_type="EC2 Instance",
        resource_id="i-1",
        region="us-east-1",
        status="running",
        risk_level="MEDIUM",
        monthly_cost_risk="x",
        suggested_action="y",
    )
    tagged = _tag(r, {"account_id": "123456789012", "name": "Prod"})
    assert tagged.account_id == "123456789012"
    assert tagged.account_label == "Prod"
    # Original is untouched (model_copy).
    assert r.account_id is None


# --- the external ID is written once and never listed ---------------------


def test_registration_echoes_the_external_id_but_listing_never_does(dynamo_table):
    """Same treatment as an API key, and for the same reason.

    `POST`/`DELETE /accounts` are admin-only; `GET /accounts` is open to every
    workspace member, so the value that has to be stored in plaintext does not
    go back out through the route with the widest audience.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)

    created = client.post(
        "/accounts",
        json={
            "name": "Sandbox",
            "role_arn": "arn:aws:iam::111111111111:role/ShutItDownScannerRole",
            "external_id": "an-external-id-long-enough",
        },
    )
    assert created.status_code == 201
    assert created.json()["external_id"] == "an-external-id-long-enough"

    listed = client.get("/accounts").json()["accounts"]
    assert len(listed) == 1
    assert "external_id" not in listed[0]
    assert listed[0]["has_external_id"] is True
    # Everything an operator needs to identify the registration is still there.
    assert listed[0]["role_arn"] == "arn:aws:iam::111111111111:role/ShutItDownScannerRole"


def test_an_account_without_an_external_id_is_distinguishable(dynamo_table):
    """`has_external_id` exists so redaction does not erase the distinction.

    The API accepts role ARNs with no external ID (manually-configured roles),
    and "redacted" must not look the same as "never had one".
    """
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    client.post(
        "/accounts",
        json={"name": "Manual", "role_arn": "arn:aws:iam::222222222222:role/Manual"},
    )
    listed = client.get("/accounts").json()["accounts"]
    assert listed[0]["has_external_id"] is False


def test_scanning_still_receives_the_real_external_id(dynamo_table, monkeypatch):
    """The redaction is at the API boundary, not in the repository.

    `multi_account_service` lists accounts through the same repository function
    the route uses. Redacting there would strip the value out from under
    `session_for_account`, and every registered account would fail to assume.
    """
    account_repository.create_account(
        "workspace-1",
        {
            "name": "Sandbox",
            "role_arn": "arn:aws:iam::111111111111:role/ShutItDownScannerRole",
            "external_id": "an-external-id-long-enough",
        },
    )

    seen = {}

    def capture(account, principal=None):
        seen.update(account)
        raise RuntimeError("stop here — we only care what was handed over")

    monkeypatch.setattr("app.services.multi_account_service.session_for_account", capture)
    scan_accounts("workspace-1")

    assert seen["external_id"] == "an-external-id-long-enough"
