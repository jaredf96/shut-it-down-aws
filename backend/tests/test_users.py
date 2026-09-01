import pytest

from app.errors import PersistenceUnavailable
from app.repositories import user_repository

# --- user_repository -----------------------------------------------------


def test_create_list_and_resolve_users(dynamo_table):
    workspace = "class-101"
    user_repository.create_user(workspace, "Instructor", role="admin")

    member = user_repository.create_user(workspace, "Student A", role="member")
    assert member["role"] == "member"
    assert member["api_key"].startswith("clc_")

    users = user_repository.list_users(workspace)
    assert len(users) == 2
    roles = {u["role"] for u in users}
    assert roles == {"admin", "member"}
    # Public listing never leaks the key hash.
    assert all("key_hash" not in u for u in users)

    principal = user_repository.resolve_api_key(member["api_key"])
    assert principal["user_id"] == member["user_id"]
    assert principal["role"] == "member"


def test_invalid_role_defaults_to_member(dynamo_table):
    workspace = "t"
    user = user_repository.create_user(workspace, "X", role="superadmin")
    assert user["role"] == "member"


def test_delete_user_revokes_key(dynamo_table):
    workspace = "t"
    user = user_repository.create_user(workspace, "Temp", role="member")

    assert user_repository.resolve_api_key(user["api_key"]) is not None
    assert user_repository.delete_user(workspace, user["user_id"]) is True
    # Key no longer resolves.
    assert user_repository.resolve_api_key(user["api_key"]) is None
    assert user_repository.delete_user(workspace, user["user_id"]) is False


def test_interrupted_delete_never_leaves_a_live_key(dynamo_table, monkeypatch):
    """The delete pair is two independent writes; cut short, the failure mode
    must be a dead key and a retryable user — never a live key whose user row
    is gone, which authenticates forever with no application path to revoke it
    (found by the D10 review)."""
    workspace = "t"
    user = user_repository.create_user(workspace, "Temp", role="member")

    real_get_table = user_repository.get_table

    class _CutShort:
        """Fails the USERS-row delete — the second write in the fixed order."""

        def __init__(self, table):
            self._table = table

        def __getattr__(self, name):
            return getattr(self._table, name)

        def delete_item(self, Key):
            if Key["pk"].startswith("USERS#"):
                raise PersistenceUnavailable("injected outage")
            return self._table.delete_item(Key=Key)

    monkeypatch.setattr(user_repository, "get_table", lambda: _CutShort(real_get_table()))
    with pytest.raises(PersistenceUnavailable):
        user_repository.delete_user(workspace, user["user_id"])

    # The key died first; the user row survived, so a retry can finish the job.
    assert user_repository.resolve_api_key(user["api_key"]) is None
    assert user_repository.get_user(workspace, user["user_id"]) is not None

    monkeypatch.setattr(user_repository, "get_table", real_get_table)
    assert user_repository.delete_user(workspace, user["user_id"]) is True


def test_users_are_isolated_by_workspace(dynamo_table):
    a, b = "workspace-a", "workspace-b"
    user_repository.create_user(a, "A-admin", role="admin")
    user_repository.create_user(a, "A-only")
    user_repository.create_user(b, "B-admin", role="admin")

    a_ids = {u["user_id"] for u in user_repository.list_users(a)}
    b_ids = {u["user_id"] for u in user_repository.list_users(b)}
    assert a_ids.isdisjoint(b_ids)
    assert len(user_repository.list_users(a)) == 2  # admin + member
    assert len(user_repository.list_users(b)) == 1  # admin only
