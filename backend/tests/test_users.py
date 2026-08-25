from app.repositories import user_repository

# --- user_repository -----------------------------------------------------


def test_create_list_and_resolve_users(dynamo_table):
    tenant = "class-101"
    user_repository.create_user(tenant, "Instructor", role="admin")

    member = user_repository.create_user(tenant, "Student A", role="member")
    assert member["role"] == "member"
    assert member["api_key"].startswith("clc_")

    users = user_repository.list_users(tenant)
    assert len(users) == 2
    roles = {u["role"] for u in users}
    assert roles == {"admin", "member"}
    # Public listing never leaks the key hash.
    assert all("key_hash" not in u for u in users)

    principal = user_repository.resolve_api_key(member["api_key"])
    assert principal["user_id"] == member["user_id"]
    assert principal["role"] == "member"


def test_invalid_role_defaults_to_member(dynamo_table):
    tenant = "t"
    user = user_repository.create_user(tenant, "X", role="superadmin")
    assert user["role"] == "member"


def test_delete_user_revokes_key(dynamo_table):
    tenant = "t"
    user = user_repository.create_user(tenant, "Temp", role="member")

    assert user_repository.resolve_api_key(user["api_key"]) is not None
    assert user_repository.delete_user(tenant, user["user_id"]) is True
    # Key no longer resolves.
    assert user_repository.resolve_api_key(user["api_key"]) is None
    assert user_repository.delete_user(tenant, user["user_id"]) is False


def test_users_are_isolated_by_tenant(dynamo_table):
    a, b = "tenant-a", "tenant-b"
    user_repository.create_user(a, "A-admin", role="admin")
    user_repository.create_user(a, "A-only")
    user_repository.create_user(b, "B-admin", role="admin")

    a_ids = {u["user_id"] for u in user_repository.list_users(a)}
    b_ids = {u["user_id"] for u in user_repository.list_users(b)}
    assert a_ids.isdisjoint(b_ids)
    assert len(user_repository.list_users(a)) == 2  # admin + member
    assert len(user_repository.list_users(b)) == 1  # admin only
