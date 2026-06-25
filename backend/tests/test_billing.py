from fastapi.testclient import TestClient

from app.main import app
from app.repositories import tenant_repository
from app.services import billing_service

client = TestClient(app)


# --- plans & limits ------------------------------------------------------


def test_new_tenant_is_on_free_plan(dynamo_table):
    tenant = tenant_repository.create_tenant("T")["tenant_id"]
    billing = billing_service.get_billing(tenant)
    assert billing["plan"] == "free"
    assert billing["limits"]["max_accounts"] == 1
    # The tenant creator counts as one user.
    assert billing["usage"]["users"] == 1


def test_free_plan_account_limit_enforced(dynamo_table):
    admin = client.post("/tenants", json={"name": "T"}).json()
    headers = {"X-API-Key": admin["api_key"]}

    first = client.post(
        "/accounts",
        json={"name": "A1", "role_arn": "arn:aws:iam::111111111111:role/R"},
        headers=headers,
    )
    assert first.status_code == 201
    # Free plan allows only 1 account.
    second = client.post(
        "/accounts",
        json={"name": "A2", "role_arn": "arn:aws:iam::222222222222:role/R"},
        headers=headers,
    )
    assert second.status_code == 402


def test_upgrading_plan_raises_limit(dynamo_table):
    admin = client.post("/tenants", json={"name": "T"}).json()
    headers = {"X-API-Key": admin["api_key"]}
    tenant = admin["tenant_id"]

    billing_service.set_plan(tenant, "pro")
    # Pro allows many accounts now.
    for i in range(3):
        res = client.post(
            "/accounts",
            json={"name": f"A{i}", "role_arn": f"arn:aws:iam::11111111111{i}:role/R"},
            headers=headers,
        )
        assert res.status_code == 201


def test_free_plan_user_limit_enforced(dynamo_table):
    admin = client.post("/tenants", json={"name": "T"}).json()
    headers = {"X-API-Key": admin["api_key"]}
    # Creator is user #1; free plan allows 3. Add two more, then the 4th fails.
    assert client.post("/users", json={"name": "u2"}, headers=headers).status_code == 201
    assert client.post("/users", json={"name": "u3"}, headers=headers).status_code == 201
    assert client.post("/users", json={"name": "u4"}, headers=headers).status_code == 402


# --- manual plan vs Stripe-managed --------------------------------------


def test_manual_plan_set_when_stripe_unconfigured(dynamo_table):
    admin = client.post("/tenants", json={"name": "T"}).json()
    headers = {"X-API-Key": admin["api_key"]}
    res = client.post("/billing/plan", json={"plan": "pro"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["plan"] == "pro"


def test_unknown_plan_rejected(dynamo_table):
    admin = client.post("/tenants", json={"name": "T"}).json()
    headers = {"X-API-Key": admin["api_key"]}
    res = client.post("/billing/plan", json={"plan": "enterprise"}, headers=headers)
    assert res.status_code == 400


def test_manual_plan_blocked_when_stripe_configured(dynamo_table, monkeypatch):
    monkeypatch.setattr(billing_service, "billing_enabled", lambda: True)
    admin = client.post("/tenants", json={"name": "T"}).json()
    headers = {"X-API-Key": admin["api_key"]}
    res = client.post("/billing/plan", json={"plan": "pro"}, headers=headers)
    assert res.status_code == 409


def test_checkout_and_webhook_503_without_stripe(dynamo_table):
    admin = client.post("/tenants", json={"name": "T"}).json()
    headers = {"X-API-Key": admin["api_key"]}
    assert client.post("/billing/checkout", headers=headers).status_code == 503
    assert client.post("/billing/webhook").status_code == 503


# --- Stripe webhook event handling (no Stripe network) -------------------


def test_apply_checkout_completed_upgrades_to_pro(dynamo_table):
    tenant = tenant_repository.create_tenant("T")["tenant_id"]
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"client_reference_id": tenant, "customer": "cus_123"}},
    }
    result = billing_service.apply_event(event)
    assert result == {"handled": True, "tenant_id": tenant, "plan": "pro"}
    assert billing_service.get_billing(tenant)["plan"] == "pro"


def test_apply_subscription_deleted_downgrades_to_free(dynamo_table):
    tenant = tenant_repository.create_tenant("T")["tenant_id"]
    billing_service.set_plan(tenant, "pro")
    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"metadata": {"tenant_id": tenant}}},
    }
    billing_service.apply_event(event)
    assert billing_service.get_billing(tenant)["plan"] == "free"


def test_apply_event_without_tenant_is_ignored(dynamo_table):
    event = {"type": "checkout.session.completed", "data": {"object": {}}}
    assert billing_service.apply_event(event)["handled"] is False
