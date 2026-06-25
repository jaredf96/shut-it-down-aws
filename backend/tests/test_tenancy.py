from app.repositories import scan_repository, tenant_repository, user_repository


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


def test_create_tenant_and_resolve_api_key(dynamo_table):
    created = tenant_repository.create_tenant("Acme Labs")
    assert created["name"] == "Acme Labs"
    assert created["api_key"].startswith("clc_")
    assert created["tenant_id"]
    # The tenant creator is an admin.
    assert created["role"] == "admin"

    # The plaintext key resolves to the full principal.
    principal = user_repository.resolve_api_key(created["api_key"])
    assert principal["tenant_id"] == created["tenant_id"]
    assert principal["role"] == "admin"
    assert principal["user_id"] == created["user_id"]


def test_unknown_api_key_resolves_to_none(dynamo_table):
    assert user_repository.resolve_api_key("clc_does-not-exist") is None


def test_scans_are_isolated_by_tenant(dynamo_table):
    a = tenant_repository.create_tenant("Tenant A")["tenant_id"]
    b = tenant_repository.create_tenant("Tenant B")["tenant_id"]

    scan_repository.save_scan(_scan("i-a"), tenant_id=a)

    # Tenant A sees its scan; tenant B sees nothing.
    a_scans = scan_repository.list_scans(tenant_id=a)
    b_scans = scan_repository.list_scans(tenant_id=b)
    assert len(a_scans) == 1
    assert b_scans == []


def test_get_scan_is_scoped_to_tenant(dynamo_table):
    a = tenant_repository.create_tenant("Tenant A")["tenant_id"]
    b = tenant_repository.create_tenant("Tenant B")["tenant_id"]

    scan_id = scan_repository.save_scan(_scan("i-a"), tenant_id=a)

    # Same scan_id is invisible to another tenant.
    assert scan_repository.get_scan(scan_id, tenant_id=a) is not None
    assert scan_repository.get_scan(scan_id, tenant_id=b) is None


def test_default_tenant_used_when_unspecified(dynamo_table):
    # No tenant_id -> default tenant; both calls hit the same partition.
    scan_id = scan_repository.save_scan(_scan("i-default"))
    assert scan_repository.get_scan(scan_id) is not None
    assert len(scan_repository.list_scans()) == 1
