"""Guided cleanup orchestration — safe by construction.

Every gate lives here, in one audited sequence — including the admin-role and
env-flag checks that used to sit in the route, whose refusals were the one kind
of attempt the audit trail never saw (D13). The route resolves the principal,
calls `execute`, and maps statuses to HTTP codes; the full end-to-end sequence
is numbered in README.md and docs/SECURITY.md:

- **Admin role** — checked first, so a non-admin never learns whether cleanup
  is even enabled.
- **Env flag** — `ENABLE_CLEANUP_ACTIONS` off refuses with the exact pinned
  message.
- **Catalog check** — the action must be in the supported catalog
  (terminate/delete-S3/RDS/NAT are simply absent, so they are refused).
- **Typed confirmation** — `confirm_resource_id` must exactly equal
  `resource_id`.
- **Target account ownership** — a named `account_id` must be one this workspace
  has registered; there is no fallback to the server's own credentials.
- **Live precondition re-check** — the action re-verifies AWS state before
  mutating; the client is never trusted.
- **Dry run** — `dry_run` (default True at the API) reports what *would*
  happen.
- **Audit** — every attempt, refused, failed, dry-run or executed, is recorded.
  With persistence on, a real mutation is additionally preceded by a durable
  `initiated` entry and refused outright if that entry cannot be written (D13):
  no mutation starts without durable evidence of intent, and a persistence
  failure *after* the mutation leaves the initiated row standing as
  outcome-unknown instead of losing the attempt. Zero-config installs are
  log-only, here as everywhere.
"""

from __future__ import annotations

import logging

from botocore.exceptions import ClientError

from app import config
from app.aws.session import default_session, session_for_account
from app.errors import PersistenceUnavailable
from app.repositories import account_repository, audit_repository
from app.services.cleanup_actions import ACTIONS, PreconditionError

logger = logging.getLogger(__name__)

# Pinned by tests and CLAUDE.md — the exact refusal message for the env flag.
DISABLED_DETAIL = "Cleanup actions are disabled in this environment."


class UnknownAccountError(Exception):
    """The caller named an AWS account this workspace has not registered."""


def _session(workspace_id: str, account_id: str | None):
    """Default credentials, or assume-role into a registered account.

    A named account must resolve to a registration this workspace owns. Falling
    back to `default_session()` when the lookup misses would point a mutating
    action at the *server's own* credentials rather than the account the caller
    asked for — and `execute()` would then audit that misfire as a success.
    """
    if account_id:
        account = account_repository.get_account(workspace_id, account_id)
        if account is None:
            raise UnknownAccountError(f"AWS account {account_id} is not registered.")
        return session_for_account(account)
    return default_session()


def _finish(base: dict, workspace_id: str, user_id: str, status: str, detail: str) -> dict:
    """Log the attempt, then persist it (always both) and return the record.

    The log line comes first so a persistence failure cannot also swallow the
    application-log record; `append` raising `PersistenceUnavailable` then
    surfaces as a structured 503 with nothing mutated — callers past the
    mutation boundary use `_finish_after_mutation` instead.
    """
    entry = {**base, "user_id": user_id, "status": status, "detail": detail}
    logger.info(
        "cleanup attempt: workspace=%s user=%s status=%s detail=%s",
        workspace_id,
        user_id,
        status,
        detail,
    )
    return audit_repository.append(workspace_id, entry)


def _finish_after_mutation(
    base: dict, workspace_id: str, user_id: str, status: str, detail: str
) -> dict:
    """`_finish`, for exits where the AWS call may already have run.

    A failed audit write here must not turn a known outcome into a 500: the
    `initiated` row written before the mutation stands as outcome-unknown, the
    outcome is logged at error level, and the caller still gets the result.
    The catch is deliberately broad — connectivity failures arrive as
    `PersistenceUnavailable`, but DynamoDB answering with an error
    (`ClientError`: access denied, throttling) loses the outcome just the same.
    """
    try:
        return _finish(base, workspace_id, user_id, status, detail)
    except (PersistenceUnavailable, ClientError) as exc:
        logger.error(
            "cleanup outcome could not be persisted; the initiated entry stands as "
            "outcome-unknown: workspace=%s user=%s status=%s detail=%s error=%s",
            workspace_id,
            user_id,
            status,
            detail,
            exc,
        )
        return audit_repository.build_record(
            {**base, "user_id": user_id, "status": status, "detail": detail}
        )


def execute(
    *,
    action: str,
    resource_id: str,
    confirm_resource_id: str,
    region: str,
    principal: dict,
    account_id: str | None = None,
    dry_run: bool = True,
) -> dict:
    """Run one cleanup action for `principal`. Returns an audited result dict
    with a `status`:

    success | dry_run | forbidden | disabled | confirmation_mismatch |
    unsupported_action | unknown_account | precondition_failed | error |
    audit_unavailable

    (`initiated` additionally appears in the audit log — never as a return —
    marking that a real mutation was about to run.)
    """
    workspace_id = principal["workspace_id"]
    user_id = principal["user_id"]
    base = {
        "action": action,
        "resource_id": resource_id,
        "region": region,
        "account_id": account_id,
        "dry_run": dry_run,
    }

    # Role before flag: the refusal a non-admin sees must not reveal whether
    # cleanup is enabled (this preserves the order the route used to enforce).
    if principal.get("role") != "admin":
        return _finish(base, workspace_id, user_id, "forbidden", "Admin role required.")

    if not config.cleanup_enabled():
        return _finish(base, workspace_id, user_id, "disabled", DISABLED_DETAIL)

    spec = ACTIONS.get(action)
    if spec is None:
        return _finish(
            base,
            workspace_id,
            user_id,
            "unsupported_action",
            f"Unsupported cleanup action: {action}.",
        )

    if confirm_resource_id != resource_id:
        return _finish(
            base,
            workspace_id,
            user_id,
            "confirmation_mismatch",
            "Confirmation does not match the resource id.",
        )

    # Write-ahead audit: with persistence on, no real mutation starts without
    # durable evidence of intent. Dry runs skip this — they mutate nothing, so
    # their single audited exit is enough. With persistence disabled entirely
    # (zero-config local mode) `append` is a documented no-op and the gate
    # passes; what this refuses is persistence *enabled but not writable* —
    # unreachable (`PersistenceUnavailable`) or answering with an error
    # (`ClientError`) — where acting would leave no record.
    if not dry_run:
        try:
            _finish(
                base,
                workspace_id,
                user_id,
                "initiated",
                f"About to run {action} on {resource_id}; the outcome follows as its own entry.",
            )
        except (PersistenceUnavailable, ClientError) as exc:
            detail = "Refusing to act: the audit store could not durably record this attempt."
            logger.error(
                "cleanup refused, audit store unavailable: workspace=%s user=%s "
                "action=%s resource=%s error=%s",
                workspace_id,
                user_id,
                action,
                resource_id,
                exc,
            )
            return audit_repository.build_record(
                {**base, "user_id": user_id, "status": "audit_unavailable", "detail": detail}
            )

    finish = _finish if dry_run else _finish_after_mutation
    try:
        session = _session(workspace_id, account_id)
        detail = spec["run"](session, region, resource_id, dry_run)
    except UnknownAccountError as exc:
        # Ahead of the broad handler below, and inside this try so an STS
        # failure while assuming a *registered* role is still audited.
        return finish(base, workspace_id, user_id, "unknown_account", str(exc))
    except PreconditionError as exc:
        return finish(base, workspace_id, user_id, "precondition_failed", str(exc))
    except Exception as exc:  # AWS / unexpected error — still audited
        return finish(base, workspace_id, user_id, "error", f"{type(exc).__name__}: {exc}")

    return finish(base, workspace_id, user_id, "dry_run" if dry_run else "success", detail)
