"""Local-endpoint credential isolation and persistence-failure normalization.

Covers three guarantees:

1. A recognized local DynamoDB gets dummy credentials, so local dev keeps
   working with no AWS session — and, critically, an *unrecognized* endpoint
   never receives them.
2. Infrastructure failures surface as a structured 503, not an opaque 500.
3. Error responses still carry CORS headers. Unhandled exceptions bypass
   Starlette's CORS layer, which makes any 500 look like a CORS failure in the
   browser and hides the real cause.
4. The correlation id is readable by the dashboard. It is stamped on every
   response, but a browser hides any response header the CORS layer does not
   name — so without `expose_headers` the id exists on the wire and no client
   can quote it.
"""

import pytest
from botocore.exceptions import ParamValidationError
from fastapi.testclient import TestClient

from app.errors import PersistenceUnavailable, ResultSetTooLarge
from app.main import app
from app.repositories import dynamo, user_repository

client = TestClient(app)

ORIGIN = "http://localhost:5173"


# --- Local-endpoint detection -------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:8001", True),
        ("http://127.0.0.1:8001", True),
        ("http://dynamodb-local:8000", True),
        ("https://dynamodb.us-east-1.amazonaws.com", False),
        ("https://localhost.evil.example.com", False),  # suffix must not match
        (None, False),
        ("", False),
    ],
)
def test_is_local_endpoint(url, expected):
    assert dynamo.is_local_endpoint(url) is expected


def test_local_endpoint_uses_dummy_credentials(monkeypatch):
    """Local DynamoDB must not depend on the developer's AWS session."""
    monkeypatch.setenv("DYNAMODB_ENDPOINT_URL", "http://localhost:8001")
    creds = dynamo._resource().meta.client._request_signer._credentials
    assert creds.get_frozen_credentials().access_key == "local"


def test_remote_endpoint_does_not_get_dummy_credentials(monkeypatch):
    """The safety property: dummy creds never go to an arbitrary endpoint.

    The exact ambient key is whatever the environment supplies (moto swaps in
    its own during tests), so assert only what matters: it is not ours.
    """
    monkeypatch.delenv("DYNAMODB_ENDPOINT_URL", raising=False)
    creds = dynamo._resource().meta.client._request_signer._credentials
    assert creds.get_frozen_credentials().access_key != "local"


# --- Failure normalization ----------------------------------------------


def test_persistence_failure_returns_structured_503(monkeypatch, dynamo_table):
    def boom(*_args, **_kwargs):
        raise PersistenceUnavailable("token expired")

    monkeypatch.setattr(user_repository, "list_users", boom)

    res = client.get("/users")
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "persistence_unavailable"
    assert body["correlation_id"]


def test_unexpected_error_returns_structured_500(monkeypatch, dynamo_table):
    def boom(*_args, **_kwargs):
        raise ValueError("something unforeseen")

    monkeypatch.setattr(user_repository, "list_users", boom)

    res = client.get("/users")
    assert res.status_code == 500
    body = res.json()
    assert body["error"] == "internal_error"
    # The caller gets an ID they can quote; the traceback stays in the logs.
    assert body["correlation_id"] == res.headers["X-Correlation-ID"]


# --- CORS must survive errors -------------------------------------------


def test_cors_headers_present_on_503(monkeypatch, dynamo_table):
    monkeypatch.setattr(
        user_repository,
        "list_users",
        lambda *a, **k: (_ for _ in ()).throw(PersistenceUnavailable("down")),
    )

    res = client.get("/users", headers={"Origin": ORIGIN})
    assert res.status_code == 503
    assert res.headers["access-control-allow-origin"] == ORIGIN


def test_cors_headers_present_on_unhandled_500(monkeypatch, dynamo_table):
    """The regression that made an expired SSO token look like a CORS bug."""
    monkeypatch.setattr(
        user_repository,
        "list_users",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    res = client.get("/users", headers={"Origin": ORIGIN})
    assert res.status_code == 500
    assert res.headers["access-control-allow-origin"] == ORIGIN


# --- Liveness vs readiness ----------------------------------------------


def test_health_is_ok_even_when_persistence_is_broken(monkeypatch):
    """Liveness must not depend on DynamoDB, or a DB blip cycles the task."""
    monkeypatch.setattr(
        dynamo, "ping", lambda: (_ for _ in ()).throw(PersistenceUnavailable("down"))
    )
    assert client.get("/health").status_code == 200


def test_ready_reports_disabled_persistence():
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json()["persistence"] == "disabled"


def test_ready_ok_when_table_reachable(dynamo_table):
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json()["persistence"] == "ok"


def test_ready_503_when_persistence_unreachable(monkeypatch, dynamo_table):
    monkeypatch.setattr(
        dynamo, "ping", lambda: (_ for _ in ()).throw(PersistenceUnavailable("down"))
    )
    res = client.get("/ready")
    assert res.status_code == 503
    assert res.json()["error"] == "persistence_unavailable"


# --- The correlation id has to reach the client that would quote it ------


def test_correlation_id_header_is_exposed_to_the_browser():
    """Stamping the id is half the job; a cross-origin client still cannot read
    a header the CORS layer does not list."""
    res = client.get("/health", headers={"Origin": ORIGIN})
    assert res.headers["X-Correlation-ID"]
    assert "x-correlation-id" in res.headers["access-control-expose-headers"].lower()


def test_route_refusal_carries_the_correlation_id_in_the_header_only():
    """The asymmetry the frontend depends on: a plain HTTPException gets no
    envelope, so most refusals carry the id in the header and nowhere else.
    Moving it into every body, or dropping it from the header, breaks the
    client silently — so pin both halves here instead."""
    res = client.post(
        "/cleanup/execute",
        json={
            "action": "stop_ec2_instance",
            "resource_id": "i-1",
            "confirm_resource_id": "i-1",
            "region": "us-east-1",
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "Cleanup actions are disabled in this environment."
    assert "correlation_id" not in res.json()
    assert res.headers["X-Correlation-ID"]


def test_a_malformed_request_is_not_reported_as_an_unreachable_backend(dynamo_table):
    """`ParamValidationError` is a BotoCoreError subclass raised client-side
    because *we* built a bad request. Translating it to a 503 sent the
    operator off to check a DynamoDB that was never involved."""
    from boto3.dynamodb.conditions import Key

    with pytest.raises(ParamValidationError):
        dynamo.get_table().query(KeyConditionExpression=Key("pk").eq("x"), Limit=0)


def test_result_set_too_large_returns_structured_500(monkeypatch, dynamo_table):
    """A read that could not be completed is nameable, not an anonymous
    `internal_error` — and never a partial answer."""

    def _too_large(*a, **k):
        raise ResultSetTooLarge("read did not complete within 25 pages (60 items)")

    monkeypatch.setattr(user_repository, "list_users", _too_large)

    res = client.get("/users")
    assert res.status_code == 500
    body = res.json()
    assert body["error"] == "result_set_too_large"
    assert body["correlation_id"] == res.headers["X-Correlation-ID"]
