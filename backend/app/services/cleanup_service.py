"""Guided cleanup orchestration — safe by construction.

Defense in depth (the route enforces the env flag and admin role *before*
calling this; this layer adds the rest):

  1. The action must be in the supported catalog (terminate/delete-S3/RDS/NAT
     are simply absent, so they are refused).
  2. `confirm_resource_id` must exactly equal `resource_id`.
  3. The action re-checks live AWS state (precondition) before mutating.
  4. `dry_run` (default True at the API) reports what *would* happen.
  5. Every attempt — refused, failed, dry-run, or executed — is audited.
"""

from __future__ import annotations

import logging

from app.aws.session import default_session, session_for_account
from app.repositories import account_repository, audit_repository
from app.services.cleanup_actions import ACTIONS, PreconditionError

logger = logging.getLogger(__name__)


def _session(tenant_id: str, account_id: str | None):
    """Default credentials, or assume-role into a registered account."""
    if account_id:
        account = account_repository.get_account(tenant_id, account_id)
        if account:
            return session_for_account(account)
    return default_session()


def _finish(base: dict, tenant_id: str, user_id: str, status: str, detail: str) -> dict:
    """Audit the attempt (always) and return the result."""
    entry = {**base, "user_id": user_id, "status": status, "detail": detail}
    record = audit_repository.append(tenant_id, entry)
    logger.info(
        "cleanup attempt: tenant=%s user=%s status=%s detail=%s", tenant_id, user_id, status, detail
    )
    return record


def execute(
    *,
    action: str,
    resource_id: str,
    confirm_resource_id: str,
    region: str,
    tenant_id: str,
    user_id: str,
    account_id: str | None = None,
    dry_run: bool = True,
) -> dict:
    """Run one cleanup action. Returns an audited result dict with a `status`:

    success | dry_run | confirmation_mismatch | unsupported_action |
    precondition_failed | error
    """
    base = {
        "action": action,
        "resource_id": resource_id,
        "region": region,
        "account_id": account_id,
        "dry_run": dry_run,
    }

    spec = ACTIONS.get(action)
    if spec is None:
        return _finish(
            base, tenant_id, user_id, "unsupported_action", f"Unsupported cleanup action: {action}."
        )

    if confirm_resource_id != resource_id:
        return _finish(
            base,
            tenant_id,
            user_id,
            "confirmation_mismatch",
            "Confirmation does not match the resource id.",
        )

    try:
        session = _session(tenant_id, account_id)
        detail = spec["run"](session, region, resource_id, dry_run)
    except PreconditionError as exc:
        return _finish(base, tenant_id, user_id, "precondition_failed", str(exc))
    except Exception as exc:  # AWS / unexpected error — still audited
        return _finish(base, tenant_id, user_id, "error", f"{type(exc).__name__}: {exc}")

    return _finish(base, tenant_id, user_id, "dry_run" if dry_run else "success", detail)
