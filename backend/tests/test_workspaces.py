import logging

from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.repositories import scan_repository, user_repository
from app.repositories.dynamo import get_table

client = TestClient(app)


def _scan(rid):
    return {
        "summary": {"total_resources": 1},
        "resources": [
            {
                "resource_type": "EC2 Instance",
                "resource_id": rid,
                "region": "us-east-1",
                "status": "running",
                "risk_level": "MEDIUM",
            }
        ],
    }


def test_api_key_resolves_to_its_principal(dynamo_table):
    created = user_repository.create_user("acme", "Acme admin", role="admin")
    assert created["api_key"].startswith("clc_")

    # The plaintext key resolves to the full principal.
    principal = user_repository.resolve_api_key(created["api_key"])
    assert principal["workspace_id"] == "acme"
    assert principal["role"] == "admin"
    assert principal["user_id"] == created["user_id"]


def test_unknown_api_key_resolves_to_none(dynamo_table):
    assert user_repository.resolve_api_key("clc_does-not-exist") is None


def test_scans_are_isolated_by_workspace(dynamo_table):
    a, b = "workspace-a", "workspace-b"

    scan_repository.save_scan(_scan("i-a"), workspace_id=a)

    # Workspace A sees its scan; workspace B sees nothing.
    a_scans = scan_repository.list_scans(workspace_id=a)
    b_scans = scan_repository.list_scans(workspace_id=b)
    assert len(a_scans) == 1
    assert b_scans == []


def test_get_scan_is_scoped_to_workspace(dynamo_table):
    a, b = "workspace-a", "workspace-b"

    scan_id = scan_repository.save_scan(_scan("i-a"), workspace_id=a)

    # Same scan_id is invisible to another workspace.
    assert scan_repository.get_scan(scan_id, workspace_id=a) is not None
    assert scan_repository.get_scan(scan_id, workspace_id=b) is None


def test_default_workspace_used_when_unspecified(dynamo_table):
    # No workspace_id -> default workspace; both calls hit the same partition.
    scan_id = scan_repository.save_scan(_scan("i-default"))
    assert scan_repository.get_scan(scan_id) is not None
    assert len(scan_repository.list_scans()) == 1


# --- The logical/storage boundary ----------------------------------------
#
# The logical model is `workspace`; the table still stores `TENANT#` prefixes
# and a `tenant_id` attribute on the API-key record (D3: frozen storage, no
# migration). These tests pin both sides so the two cannot drift into each
# other — a caller must never see `tenant_id`, and a write must never stop
# producing it.


def test_public_responses_say_workspace_and_never_tenant(dynamo_table):
    """The rename is only real if `tenant_id` cannot escape to a caller."""
    created = user_repository.create_user("acme", "Acme admin", role="admin")
    assert created["workspace_id"] == "acme"
    assert "tenant_id" not in created

    me = client.get("/me", headers={"X-API-Key": created["api_key"]}).json()
    assert me["workspace_id"] == "acme"
    assert "tenant_id" not in me


def test_new_writes_still_produce_the_frozen_storage_shape(dynamo_table):
    """A write must keep the legacy attribute name, or existing rows split into
    two incompatible generations."""
    created = user_repository.create_user("acme", "Acme admin", role="admin")

    key_hash = user_repository._hash_key(created["api_key"])
    item = get_table().get_item(Key={"pk": f"APIKEY#{key_hash}", "sk": "#"})["Item"]

    assert item["tenant_id"] == "acme"
    assert "workspace_id" not in item


def test_legacy_api_key_row_resolves(dynamo_table):
    """A row written before the rename — the only shape on disk anywhere — must
    still resolve. This is the read half of the translation."""
    api_key = "clc_legacy-key"
    get_table().put_item(
        Item={
            "pk": f"APIKEY#{user_repository._hash_key(api_key)}",
            "sk": "#",
            "tenant_id": "legacy-workspace",
            "user_id": "u-1",
            "role": "admin",
            "name": "Legacy admin",
        }
    )

    principal = user_repository.resolve_api_key(api_key)
    assert principal["workspace_id"] == "legacy-workspace"
    assert principal["user_id"] == "u-1"
    assert principal["role"] == "admin"
    assert "tenant_id" not in principal


# --- Env var: canonical name, deprecated fallback -------------------------


def test_canonical_env_var_wins_over_the_legacy_one(monkeypatch):
    monkeypatch.setenv("DEFAULT_WORKSPACE_ID", "canonical")
    monkeypatch.setenv("DEFAULT_TENANT_ID", "legacy")
    assert config.default_workspace_id() == "canonical"


def test_legacy_env_var_still_works(monkeypatch):
    monkeypatch.delenv("DEFAULT_WORKSPACE_ID", raising=False)
    monkeypatch.setenv("DEFAULT_TENANT_ID", "legacy")
    assert config.default_workspace_id() == "legacy"


def test_unset_env_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("DEFAULT_WORKSPACE_ID", raising=False)
    monkeypatch.delenv("DEFAULT_TENANT_ID", raising=False)
    assert config.default_workspace_id() == "default"


def test_legacy_env_warning_fires_once_per_process(monkeypatch, caplog):
    """Config resolvers are functions called per request, so an unguarded
    warning would fire on every read rather than once."""
    monkeypatch.delenv("DEFAULT_WORKSPACE_ID", raising=False)
    monkeypatch.setenv("DEFAULT_TENANT_ID", "legacy")
    config._warn_legacy_workspace_env.cache_clear()

    # `configure_logging` stops the `app` tree propagating so nothing
    # double-logs through uvicorn's handlers, which also hides these records
    # from caplog's root handler. Let them through for this test only.
    monkeypatch.setattr(logging.getLogger("app"), "propagate", True)

    with caplog.at_level(logging.WARNING, logger="app.config"):
        for _ in range(5):
            assert config.default_workspace_id() == "legacy"

    warnings = [r for r in caplog.records if "DEFAULT_TENANT_ID" in r.getMessage()]
    assert len(warnings) == 1
    assert "DEFAULT_WORKSPACE_ID" in warnings[0].getMessage()
