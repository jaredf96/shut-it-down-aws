"""Tenant records (same table as scans).

    pk = "TENANTMETA#<tenant_id>"  sk = "#"   -> {name, created_at}

Creating a tenant also creates its first **admin** user (see user_repository),
and returns that user's API key — shown once.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.repositories import user_repository
from app.repositories.dynamo import get_table, is_enabled


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def create_tenant(name: str) -> dict:
    """Create a tenant + its first admin user.

    Returns {tenant_id, name, user_id, role, api_key}. The api_key is plaintext
    and only returned here. Raises RuntimeError if persistence is disabled.
    """
    if not is_enabled():
        raise RuntimeError("Persistence is required to create tenants")

    tenant_id = uuid.uuid4().hex
    get_table().put_item(
        Item={
            "pk": f"TENANTMETA#{tenant_id}",
            "sk": "#",
            "tenant_id": tenant_id,
            "name": name,
            "created_at": _now(),
        }
    )

    admin = user_repository.create_user(tenant_id, name=f"{name} admin", role="admin")
    return {
        "tenant_id": tenant_id,
        "name": name,
        "user_id": admin["user_id"],
        "role": admin["role"],
        "api_key": admin["api_key"],
    }
