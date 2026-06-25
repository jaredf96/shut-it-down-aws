"""Request authentication -> resolves the calling principal (tenant + user + role).

Auth is **optional**. By default (AUTH_REQUIRED unset) requests with no API key
run as the default tenant with an admin "local" user, so local dev needs no
credentials and can manage everything. In SaaS mode (AUTH_REQUIRED=true) a valid
API key is mandatory.

A key may be sent as either:
    Authorization: Bearer <key>
    X-API-Key: <key>
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from app import config
from app.repositories import scan_repository, user_repository


def _key_from_headers(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def get_current_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> dict:
    """Return {tenant_id, user_id, role, name} for the request."""
    api_key = _key_from_headers(authorization, x_api_key)

    if api_key:
        if not scan_repository.is_enabled():
            raise HTTPException(
                status_code=503,
                detail="Persistence is required for API-key authentication.",
            )
        principal = user_repository.resolve_api_key(api_key)
        if not principal:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        return principal

    if config.auth_required():
        raise HTTPException(status_code=401, detail="API key required.")

    # Local / single-tenant mode: an admin "local" user of the default tenant.
    return {
        "tenant_id": config.default_tenant_id(),
        "user_id": "local",
        "role": "admin",
        "name": "local",
    }


def get_current_tenant(principal: dict = Depends(get_current_principal)) -> str:
    """Convenience dependency for endpoints that only need the tenant id."""
    return principal["tenant_id"]


def require_admin(principal: dict = Depends(get_current_principal)) -> dict:
    """Dependency that allows only admins; returns the principal."""
    if principal.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    return principal
