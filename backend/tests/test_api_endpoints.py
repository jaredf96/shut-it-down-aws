import boto3
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import REGION

client = TestClient(app)


def _admin_user(tenant: str = "class", name: str = "Instructor") -> dict:
    """Mint an admin API key directly — how a shared deployment gets its first."""
    from app.repositories import user_repository

    return user_repository.create_user(tenant, name, role="admin")


def test_health_does_not_touch_aws():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"


def test_scan_all_endpoint_shape():
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="api-test-bucket")

    res = client.get("/scan")
    assert res.status_code == 200
    body = res.json()
    assert "summary" in body and "resources" in body
    assert body["summary"]["total_resources"] >= 1
    # Always present, so a caller can tell "saw everything" from "saw nothing".
    assert body["regions_failed"] == []
    assert body["scanners_failed"] == []


def test_scan_endpoint_reports_regions_it_could_not_read(monkeypatch):
    from botocore.exceptions import ClientError

    from app.scanners import ec2_scanner

    def boom(region, session):
        raise ClientError({"Error": {"Code": "AuthFailure"}}, "DescribeInstances")

    monkeypatch.setattr(ec2_scanner, "_scan_region", boom)

    body = client.get("/scan").json()
    assert body["regions_failed"] == [
        {"region": REGION, "reason": "AuthFailure", "account_id": None, "account_label": None}
    ]


def test_scan_endpoint_reports_a_scanner_that_could_not_run(monkeypatch):
    """S3 is global — no region to blame, so it gets its own array."""
    from botocore.exceptions import ClientError

    from app.scanners import s3_scanner

    def boom(*args, **kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "ListBuckets")

    monkeypatch.setattr(s3_scanner, "scan", boom)

    body = client.get("/scan").json()
    assert body["scanners_failed"] == [
        {
            "scanner": "s3",
            "label": "S3 buckets",
            "reason": "AccessDenied",
            "account_id": None,
            "account_label": None,
        }
    ]
    assert body["regions_failed"] == []


def test_there_are_no_per_service_scan_endpoints():
    """`/scan/<service>` bypassed the multi-account path and answered with the
    *server's* inventory, while `/scan` returned the tenant's — the same caller
    got two different accounts' data with nothing to tell them apart.

    The endpoints are gone. Registering a scanner used to make one "come free",
    so this guards against the registry quietly handing them back.
    """
    from app.scanners import SCANNERS

    for slug in [*SCANNERS, "lambda"]:
        assert client.get(f"/scan/{slug}").status_code == 404, slug


# --- Persistence / history endpoints ------------------------------------


def test_scan_does_not_persist_when_disabled():
    res = client.get("/scan")
    assert res.status_code == 200
    body = res.json()
    assert body["persisted"] is False
    assert body["scan_id"] is None


def test_history_endpoints_return_503_when_disabled():
    assert client.get("/scans").status_code == 503
    assert client.get("/scans/whatever").status_code == 503


def test_scan_persists_then_history_endpoints_work(dynamo_table):
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="history-test-bucket")

    # Running /scan should now save and return a scan_id.
    scan_res = client.get("/scan").json()
    assert scan_res["persisted"] is True
    scan_id = scan_res["scan_id"]
    assert scan_id

    # It should show up in the history list, with a vs_previous field present.
    listed = client.get("/scans").json()["scans"]
    assert any(s["scan_id"] == scan_id for s in listed)
    assert all("vs_previous" in s for s in listed)

    # And be fetchable by id with the same resource shape.
    fetched = client.get(f"/scans/{scan_id}")
    assert fetched.status_code == 200
    assert fetched.json()["scan_id"] == scan_id

    # save=false skips persistence even when enabled.
    skipped = client.get("/scan?save=false").json()
    assert skipped["persisted"] is False


def test_get_unknown_scan_id_is_404(dynamo_table):
    res = client.get("/scans/2026-01-01T00:00:00.000Z_missing")
    assert res.status_code == 404


# --- Diff endpoint -------------------------------------------------------


def test_diff_endpoint_disabled_returns_503():
    res = client.get("/scans/diff", params={"from_id": "a", "to_id": "b"})
    assert res.status_code == 503


def test_diff_endpoint_compares_two_scans(dynamo_table):
    from app.repositories import scan_repository

    older = scan_repository.save_scan(
        {
            "summary": {"total_resources": 1},
            "resources": [
                {
                    "resource_type": "EC2 Instance",
                    "resource_id": "i-1",
                    "region": "us-east-1",
                    "status": "running",
                    "risk_level": "MEDIUM",
                }
            ],
        }
    )
    newer = scan_repository.save_scan({"summary": {"total_resources": 0}, "resources": []})

    res = client.get("/scans/diff", params={"from_id": older, "to_id": newer})
    assert res.status_code == 200
    body = res.json()
    assert body["summary"] == {"added": 0, "removed": 1, "changed": 0, "unchanged": 0}
    assert body["removed"][0]["resource_id"] == "i-1"


def test_diff_endpoint_missing_scan_is_404(dynamo_table):
    from app.repositories import scan_repository

    real = scan_repository.save_scan({"summary": {}, "resources": []})
    res = client.get("/scans/diff", params={"from_id": real, "to_id": "nope"})
    assert res.status_code == 404


# --- Alerts --------------------------------------------------------------


def test_scan_response_includes_alerts():
    # A standing high-risk resource should yield a warning alert inline.
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.allocate_address(Domain="vpc")  # unassociated EIP -> HIGH

    body = client.get("/scan").json()
    assert "alerts" in body
    assert any(a["severity"] == "WARNING" for a in body["alerts"])


def test_alerts_endpoint_503_when_disabled():
    assert client.get("/alerts").status_code == 503


def test_alerts_endpoint_uses_latest_saved_scan(dynamo_table):
    from app.repositories import scan_repository

    scan_id = scan_repository.save_scan(
        {
            "summary": {"total_resources": 1},
            "resources": [
                {
                    "resource_type": "NAT Gateway",
                    "resource_id": "nat-1",
                    "region": "us-east-1",
                    "status": "available",
                    "risk_level": "HIGH",
                    "monthly_cost_risk": "costs",
                }
            ],
        }
    )
    body = client.get("/alerts").json()
    assert body["based_on"] == scan_id
    assert len(body["alerts"]) == 1
    assert body["alerts"][0]["severity"] == "WARNING"


# --- Tenancy / auth ------------------------------------------------------


def test_auth_required_rejects_missing_key(dynamo_table, monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    assert client.get("/scan").status_code == 401


def test_auth_required_accepts_valid_key_and_scopes_data(dynamo_table, monkeypatch):
    # Issue a key before turning auth on — API keys are the opt-in path for a
    # shared deployment, minted by the operator rather than self-registered.
    from app.repositories import user_repository

    api_key = user_repository.create_user("acme", "Acme admin", role="admin")["api_key"]
    monkeypatch.setenv("AUTH_REQUIRED", "true")

    headers = {"X-API-Key": api_key}
    scan = client.get("/scan", headers=headers).json()
    assert scan["persisted"] is True

    # The tenant sees its own scan in history.
    listed = client.get("/scans", headers=headers).json()["scans"]
    assert len(listed) == 1


def test_auth_required_rejects_invalid_key(dynamo_table, monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    assert client.get("/scan", headers={"X-API-Key": "clc_bogus"}).status_code == 401


# --- Notifications -------------------------------------------------------


def test_notify_503_without_persistence():
    assert client.post("/notify").status_code == 503


def test_notify_delivers_latest_scan_alerts(dynamo_table, monkeypatch):
    from app.repositories import scan_repository

    sent = {}

    class _Recorder:
        name = "test"

        def send(self, alerts):
            sent["count"] = len(alerts)

    # Inject a fake channel so nothing is actually sent.
    monkeypatch.setattr(
        "app.services.notification_service.notifiers_from_env", lambda: [_Recorder()]
    )

    scan_id = scan_repository.save_scan(
        {
            "summary": {"total_resources": 1},
            "resources": [
                {
                    "resource_type": "NAT Gateway",
                    "resource_id": "nat-1",
                    "region": "us-east-1",
                    "status": "available",
                    "risk_level": "HIGH",
                    "monthly_cost_risk": "costs",
                }
            ],
        }
    )

    body = client.post("/notify").json()
    assert body["based_on"] == scan_id
    assert body["sent_count"] == 1
    assert sent["count"] == 1
    assert body["channels"][0]["status"] == "sent"


# --- Accounts (multi-account) --------------------------------------------


def test_accounts_503_without_persistence():
    assert client.get("/accounts").status_code == 503
    assert client.post("/accounts", json={"name": "x", "role_arn": "y"}).status_code == 503


def test_account_crud_endpoints(dynamo_table):
    created = client.post(
        "/accounts",
        json={"name": "Sandbox", "role_arn": "arn:aws:iam::123456789012:role/Read"},
    )
    assert created.status_code == 201
    account_id = created.json()["account_id"]
    assert account_id == "123456789012"

    listed = client.get("/accounts").json()["accounts"]
    assert len(listed) == 1

    deleted = client.delete(f"/accounts/{account_id}")
    assert deleted.status_code == 200
    assert client.get("/accounts").json()["accounts"] == []


def test_delete_unknown_account_is_404(dynamo_table):
    assert client.delete("/accounts/000000000000").status_code == 404


def test_scan_tags_resources_when_accounts_registered(dynamo_table, monkeypatch):
    import boto3

    client.post(
        "/accounts",
        json={"name": "Acct One", "role_arn": "arn:aws:iam::111111111111:role/Read"},
    )
    monkeypatch.setattr(
        "app.services.multi_account_service.session_for_account",
        lambda account: boto3.Session(),
    )
    boto3.client("ec2", region_name=REGION).allocate_address(Domain="vpc")

    body = client.get("/scan").json()
    assert body["accounts_scanned"][0]["account_id"] == "111111111111"
    assert all(r["account_id"] == "111111111111" for r in body["resources"])


def test_unreadable_regions_are_attributed_to_their_account(dynamo_table, monkeypatch):
    """With several accounts registered, "us-west-1 failed" is meaningless
    without saying whose us-west-1."""
    import boto3
    from botocore.exceptions import ClientError

    from app.scanners import ec2_scanner

    client.post(
        "/accounts",
        json={"name": "Acct One", "role_arn": "arn:aws:iam::111111111111:role/Read"},
    )
    monkeypatch.setattr(
        "app.services.multi_account_service.session_for_account",
        lambda account: boto3.Session(),
    )

    def boom(region, session):
        raise ClientError({"Error": {"Code": "AuthFailure"}}, "DescribeInstances")

    monkeypatch.setattr(ec2_scanner, "_scan_region", boom)

    body = client.get("/scan").json()
    assert body["regions_failed"] == [
        {
            "region": REGION,
            "reason": "AuthFailure",
            "account_id": "111111111111",
            "account_label": "Acct One",
        }
    ]


def test_unavailable_scanners_are_attributed_to_their_account(dynamo_table, monkeypatch):
    """Same reason as regions: "S3 was unreadable" is meaningless across
    accounts without saying whose S3."""
    import boto3
    from botocore.exceptions import ClientError

    from app.scanners import s3_scanner

    client.post(
        "/accounts",
        json={"name": "Acct One", "role_arn": "arn:aws:iam::111111111111:role/Read"},
    )
    monkeypatch.setattr(
        "app.services.multi_account_service.session_for_account",
        lambda account: boto3.Session(),
    )

    def boom(*args, **kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "ListBuckets")

    monkeypatch.setattr(s3_scanner, "scan", boom)

    body = client.get("/scan").json()
    assert body["scanners_failed"] == [
        {
            "scanner": "s3",
            "label": "S3 buckets",
            "reason": "AccessDenied",
            "account_id": "111111111111",
            "account_label": "Acct One",
        }
    ]


# --- Team / users / roles ------------------------------------------------


def test_me_is_admin_in_local_mode():
    body = client.get("/me").json()
    assert body["role"] == "admin"
    assert body["tenant_id"]


def test_users_503_without_persistence():
    assert client.get("/users").status_code == 503


def test_admin_can_add_member_and_member_is_restricted(dynamo_table):
    admin = _admin_user()
    admin_headers = {"X-API-Key": admin["api_key"]}

    # Admin adds a member.
    created = client.post(
        "/users", json={"name": "Student", "role": "member"}, headers=admin_headers
    )
    assert created.status_code == 201
    member = created.json()
    assert member["role"] == "member"
    member_headers = {"X-API-Key": member["api_key"]}

    # Both members see the team (admin + member) and shared accounts list.
    assert len(client.get("/users", headers=member_headers).json()["users"]) == 2
    assert client.get("/accounts", headers=member_headers).status_code == 200

    # Member cannot manage users or accounts.
    assert client.post("/users", json={"name": "X"}, headers=member_headers).status_code == 403
    assert (
        client.post(
            "/accounts",
            json={"name": "A", "role_arn": "arn:aws:iam::111111111111:role/R"},
            headers=member_headers,
        ).status_code
        == 403
    )

    # /me reflects the member role.
    assert client.get("/me", headers=member_headers).json()["role"] == "member"


def test_admin_cannot_remove_self(dynamo_table):
    admin = _admin_user()
    headers = {"X-API-Key": admin["api_key"]}
    res = client.delete(f"/users/{admin['user_id']}", headers=headers)
    assert res.status_code == 400


def test_admin_removes_member_revokes_access(dynamo_table):
    admin = _admin_user()
    admin_headers = {"X-API-Key": admin["api_key"]}
    member = client.post(
        "/users", json={"name": "Temp", "role": "member"}, headers=admin_headers
    ).json()
    member_headers = {"X-API-Key": member["api_key"]}

    assert client.get("/me", headers=member_headers).status_code == 200
    assert client.delete(f"/users/{member['user_id']}", headers=admin_headers).status_code == 200
    # Revoked key no longer authenticates.
    assert client.get("/me", headers=member_headers).status_code == 401
