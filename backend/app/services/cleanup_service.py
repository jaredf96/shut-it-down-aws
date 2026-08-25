"""Guided cleanup orchestration — safe by construction.

What this layer contributes to the defense in depth (the route enforces the
env flag and the admin role *before* calling this; the full end-to-end sequence
is numbered in README.md and docs/SECURITY.md, and counts a wider scope than
these):

- **Catalog check** — the action must be in the supported catalog
  (terminate/delete-S3/RDS/NAT are simply absent, so they are refused).
- **Typed confirmation** — `confirm_resource_id` must exactly equal
  `resource_id`.
- **Target account ownership** — a named `account_id` must be one this tenant
  has registered; there is no fallback to the server's own credentials.
- **Live precondition re-check** — the action re-verifies AWS state before
  mutating; the client is never trusted.
- **Dry run** — `dry_run` (default True at the API) reports what *would*
  happen.
- **Audit** — every attempt, refused, failed, dry-run or executed, is recorded.
"""

from __future__ import annotations

import logging

from app.aws.session import default_session, session_for_account
from app.repositories import account_repository, audit_repository
from app.services.cleanup_actions import ACTIONS, PreconditionError

logger = logging.getLogger(__name__)


class UnknownAccountError(Exception):
    """The caller named an AWS account this tenant has not registered."""


def _session(tenant_id: str, account_id: str | None):
    """Default credentials, or assume-role into a registered account.

    A named account must resolve to a registration this tenant owns. Falling
    back to `default_session()` when the lookup misses would point a mutating
    action at the *server's own* credentials rather than the account the caller
    asked for — and `execute()` would then audit that misfire as a success.
    """
    if account_id:
        account = account_repository.get_account(tenant_id, account_id)
        if account is None:
            raise UnknownAccountError(f"AWS account {account_id} is not registered.")
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
    unknown_account | precondition_failed | error
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
    except UnknownAccountError as exc:
        # Ahead of the broad handler below, and inside this try so an STS
        # failure while assuming a *registered* role is still audited.
        return _finish(base, tenant_id, user_id, "unknown_account", str(exc))
    except PreconditionError as exc:
        return _finish(base, tenant_id, user_id, "precondition_failed", str(exc))
    except Exception as exc:  # AWS / unexpected error — still audited
        return _finish(base, tenant_id, user_id, "error", f"{type(exc).__name__}: {exc}")

    return _finish(base, tenant_id, user_id, "dry_run" if dry_run else "success", detail)
