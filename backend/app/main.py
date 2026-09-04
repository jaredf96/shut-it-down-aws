"""FastAPI entrypoint for Shut It Down.

Scanning is read-only. Mutating cleanup actions exist only under `/cleanup/*`
and are OFF by default — they require `ENABLE_CLEANUP_ACTIONS=true`, an admin
role, an exact per-resource confirmation, default to dry-run, and audit every
attempt. See `app/services/cleanup_service.py`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app import config
from app.auth import get_current_principal, get_current_workspace, require_admin
from app.errors import PersistenceUnavailable
from app.logging_setup import configure_logging
from app.models import AccountCreate, CleanupRequest, UserCreate
from app.repositories import (
    account_repository,
    audit_repository,
    dynamo,
    scan_repository,
    user_repository,
)
from app.services import (
    cleanup_service,
    diff_scans,
    evaluate_alerts,
    list_with_deltas,
    notify,
    scan_accounts,
)
from app.services.cleanup_actions import NOT_SUPPORTED
from app.services.cleanup_actions import catalog as cleanup_catalog

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """For local dev: optionally create the history table on boot."""
    if scan_repository.is_enabled() and config.auto_create_enabled():
        try:
            scan_repository.ensure_table()
        except Exception:  # never block startup on table creation
            logger.warning("Could not auto-create DynamoDB table", exc_info=True)
    yield


app = FastAPI(
    title="Shut It Down",
    description="Read-only scanner that finds AWS resources left over from labs and tutorials.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(PersistenceUnavailable)
async def _persistence_unavailable(request: Request, exc: PersistenceUnavailable):
    """Infrastructure failure -> structured 503 rather than an opaque 500."""
    correlation_id = getattr(request.state, "correlation_id", None)
    logger.warning(
        "persistence unavailable path=%s correlation_id=%s: %s",
        request.url.path,
        correlation_id,
        exc,
    )
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Persistence backend is unavailable.",
            "error": "persistence_unavailable",
            "correlation_id": correlation_id,
        },
    )


class ErrorEnvelopeMiddleware(BaseHTTPMiddleware):
    """Tag every request with a correlation ID; turn any escape into JSON.

    This must sit *inside* CORSMiddleware. Starlette's outermost error handler
    runs outside the CORS layer, so an unhandled exception returns a bare 500
    with no `Access-Control-Allow-Origin` header — which a browser reports as a
    CORS failure, hiding the actual error. Converting the exception here means
    CORS still sees a normal response and attaches its headers.
    """

    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or uuid4().hex[:12]
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled error path=%s correlation_id=%s",
                request.url.path,
                correlation_id,
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error.",
                    "error": "internal_error",
                    "correlation_id": correlation_id,
                },
            )
        response.headers["X-Correlation-ID"] = correlation_id
        return response


# Order matters: middleware added later wraps middleware added earlier, so CORS
# must come last to remain the outermost layer and decorate error envelopes too.
app.add_middleware(ErrorEnvelopeMiddleware)

# Allow the local Vite dev server to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    # The dashboard is a different origin from the API, so the browser hides
    # every response header not named here. Without this, the correlation id
    # the middleware stamps on every response is unreadable by the one client
    # that would quote it in a bug report.
    expose_headers=["X-Correlation-ID"],
)


@app.get("/health")
def health():
    """Liveness: is the process up? Touches no dependency (no AWS, no DynamoDB).

    Safe for a load balancer to poll frequently. Use `/ready` to check whether
    the persistence backend is actually reachable.
    """
    return {
        "status": "ok",
        "service": "shut-it-down-aws",
        "version": "0.1.0",
        "persistence_enabled": scan_repository.is_enabled(),
        "auth_required": config.auth_required(),
    }


@app.get("/ready")
def ready():
    """Readiness: can we actually reach the persistence backend?

    Returns 503 (via the `PersistenceUnavailable` handler) when DynamoDB is
    configured but unreachable. With persistence disabled the app is still able
    to serve scans, so that is reported as ready.
    """
    if not scan_repository.is_enabled():
        return {"ready": True, "persistence": "disabled"}
    dynamo.ping()
    return {"ready": True, "persistence": "ok"}


def _require_persistence() -> None:
    if not scan_repository.is_enabled():
        raise HTTPException(status_code=503, detail="Persistence is required for this endpoint.")


@app.get("/me")
def whoami(principal: dict = Depends(get_current_principal)):
    """Return the calling principal (workspace, user, role) — handy for the UI."""
    return principal


# --- Users (team members) ------------------------------------------------


@app.get("/users")
def list_users(workspace: str = Depends(get_current_workspace)):
    """List the team members of this workspace."""
    _require_persistence()
    return {"users": user_repository.list_users(workspace)}


@app.post("/users", status_code=201)
def add_user(payload: UserCreate, principal: dict = Depends(require_admin)):
    """Create a team member and return their API key (admin only, shown once)."""
    _require_persistence()
    return user_repository.create_user(principal["workspace_id"], payload.name, payload.role)


@app.delete("/users/{user_id}")
def remove_user(user_id: str, principal: dict = Depends(require_admin)):
    """Remove a team member and revoke their API key (admin only)."""
    _require_persistence()
    if user_id == principal["user_id"]:
        raise HTTPException(status_code=400, detail="You cannot remove yourself.")
    if not user_repository.delete_user(principal["workspace_id"], user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return {"deleted": user_id}


# --- Accounts (multi-account) --------------------------------------------


def _without_external_id(account: dict) -> dict:
    """Strip the external ID from an account record on its way out of the API.

    It is returned once, by the registration that set it, and never listed
    again — the treatment an API key gets (hard invariant 5) for the same
    reason: nothing on the client needs to read it back, and unlike the POST
    and DELETE beside it this route is open to every workspace member, not just
    admins. `has_external_id` keeps the part an operator does need, which is
    whether a registration has one at all.

    The redaction belongs here and not in `account_repository`:
    `multi_account_service` lists accounts through that same function and needs
    the real value to assume the role.
    """
    redacted = {k: v for k, v in account.items() if k != "external_id"}
    redacted["has_external_id"] = bool(account.get("external_id"))
    return redacted


@app.get("/accounts")
def list_accounts(workspace: str = Depends(get_current_workspace)):
    """List the AWS accounts registered for this workspace."""
    _require_persistence()
    accounts = account_repository.list_accounts(workspace)
    return {"accounts": [_without_external_id(account) for account in accounts]}


@app.post("/accounts", status_code=201)
def add_account(payload: AccountCreate, principal: dict = Depends(require_admin)):
    """Register an AWS account (admin only)."""
    _require_persistence()
    return account_repository.create_account(principal["workspace_id"], payload.model_dump())


@app.delete("/accounts/{account_id}")
def remove_account(account_id: str, principal: dict = Depends(require_admin)):
    """Remove an account registration (admin only)."""
    _require_persistence()
    if not account_repository.delete_account(principal["workspace_id"], account_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"deleted": account_id}


# --- Guided cleanup (mutating — safe by construction) --------------------

# Maps a cleanup result status to an HTTP code.
_CLEANUP_STATUS_CODE = {
    "success": 200,
    "dry_run": 200,
    "confirmation_mismatch": 400,
    "unsupported_action": 400,
    "forbidden": 403,
    "disabled": 403,
    "unknown_account": 404,
    "audit_unavailable": 503,
    "precondition_failed": 409,
    "error": 502,
}

# A cleanup `detail` is rendered verbatim in the dashboard banner, so a status
# whose detail is built *from an exception* must not reach the client. The
# `error` branch of `cleanup_service.execute` stringifies the AWS failure, and
# a botocore ClientError carries the assumed-role ARN and the account id in its
# message. The full text stays in the audit row and the application log, which
# is where an operator looks.
_OPAQUE_CLEANUP_DETAIL = {
    "error": "The cleanup action failed against AWS. Check the audit entry for details.",
}


@app.get("/cleanup/actions")
def cleanup_actions():
    """Catalog of supported cleanup actions + what is intentionally excluded."""
    return {
        "enabled": config.cleanup_enabled(),
        "actions": cleanup_catalog(),
        "not_supported": NOT_SUPPORTED,
    }


@app.get("/cleanup/audit")
def cleanup_audit(limit: int = 50, workspace: str = Depends(get_current_workspace)):
    """Recent cleanup attempts for this workspace (newest first)."""
    _require_persistence()
    return {"entries": audit_repository.list_entries(workspace, limit)}


@app.post("/cleanup/execute")
def cleanup_execute(payload: CleanupRequest, principal: dict = Depends(get_current_principal)):
    """Run one guided cleanup action (admin only).

    Deliberately not `Depends(require_admin)`: every gate — the admin role and
    the `ENABLE_CLEANUP_ACTIONS` flag included — lives in
    `cleanup_service.execute`, so refused attempts are audited like any other
    outcome (D13). This route resolves the principal and maps statuses to HTTP
    codes, nothing more. Requires `confirm_resource_id` to equal `resource_id`.
    Defaults to a dry run; pass `dry_run=false` to mutate. An `account_id` the
    workspace has not registered is refused (404), never run against the
    server's own credentials.
    """
    result = cleanup_service.execute(
        action=payload.action,
        resource_id=payload.resource_id,
        confirm_resource_id=payload.confirm_resource_id,
        region=payload.region,
        account_id=payload.account_id,
        dry_run=payload.dry_run,
        principal=principal,
    )

    code = _CLEANUP_STATUS_CODE.get(result["status"], 400)
    if code >= 400:
        detail = _OPAQUE_CLEANUP_DETAIL.get(result["status"], result["detail"])
        raise HTTPException(status_code=code, detail=detail)
    return result


@app.get("/scan")
def scan_everything(save: bool = True, workspace: str = Depends(get_current_workspace)):
    """Run all scanners and return a combined, summarized result.

    The response includes `alerts` (derived from this scan, and the previous
    saved scan when available). When persistence is configured, the result is
    also saved to DynamoDB and its `scan_id` is returned. Pass `?save=false`
    to skip saving.

    If the workspace has registered AWS accounts, every account is scanned
    (assume-role) and each resource is tagged with its account; otherwise the
    server's own credentials are used.
    """
    result = scan_accounts(workspace)

    # Compare against the most recent saved scan (the "previous" one) for
    # change-aware alerts. Fetch it before saving the new scan.
    previous_resources = None
    if scan_repository.is_enabled():
        recent = scan_repository.list_scans_full(1, workspace_id=workspace)
        if recent:
            previous_resources = recent[0]["resources"]

    alerts = evaluate_alerts(result["resources"], previous_resources)

    scan_id = None
    if save and scan_repository.is_enabled():
        scan_id = scan_repository.save_scan(result, workspace_id=workspace)

    response = {**result, "alerts": alerts, "scan_id": scan_id, "persisted": scan_id is not None}

    # Optionally push alerts to email/Slack on every scan.
    if config.notify_on_scan():
        response["notifications"] = notify(alerts)

    return response


@app.post("/notify")
def notify_alerts(workspace: str = Depends(get_current_workspace)):
    """Deliver the latest saved scan's alerts to configured channels.

    Requires persistence. Returns a per-channel result summary. Channels are
    configured via env (SLACK_WEBHOOK_URL, SMTP_*); with none configured this
    is a no-op that reports zero channels.
    """
    if not scan_repository.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Persistence is required. Use NOTIFY_ON_SCAN for inline delivery instead.",
        )
    recent = scan_repository.list_scans_full(2, workspace_id=workspace)
    if not recent:
        return {"sent_count": 0, "channels": [], "based_on": None}
    current = recent[0]
    previous_resources = recent[1]["resources"] if len(recent) > 1 else None
    alerts = evaluate_alerts(current["resources"], previous_resources)
    return {**notify(alerts), "based_on": current["scan_id"]}


@app.get("/alerts")
def get_alerts(workspace: str = Depends(get_current_workspace)):
    """Alerts derived from the latest saved scan (vs the one before it).

    Requires persistence. Without it, alerts are still returned inline by
    `GET /scan`.
    """
    if not scan_repository.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Persistence is disabled. Alerts are included inline in GET /scan.",
        )
    recent = scan_repository.list_scans_full(2, workspace_id=workspace)
    if not recent:
        return {"alerts": [], "based_on": None}
    current = recent[0]
    previous_resources = recent[1]["resources"] if len(recent) > 1 else None
    alerts = evaluate_alerts(current["resources"], previous_resources)
    return {"alerts": alerts, "based_on": current["scan_id"]}


@app.get("/scans")
def list_scans(limit: int = 20, workspace: str = Depends(get_current_workspace)):
    """List recent saved scans (newest first), each with a `vs_previous` delta.

    503 if persistence is disabled.
    """
    if not scan_repository.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Persistence is disabled. Set DYNAMODB_TABLE_NAME to enable scan history.",
        )
    return {"scans": list_with_deltas(limit=limit, workspace_id=workspace)}


# NOTE: declared before "/scans/{scan_id}" so the fixed "diff" path matches first.
@app.get("/scans/diff")
def diff(from_id: str, to_id: str, workspace: str = Depends(get_current_workspace)):
    """Compare two saved scans (older `from_id` vs newer `to_id`).

    503 if persistence is disabled, 404 if either scan id is missing.
    """
    if not scan_repository.is_enabled():
        raise HTTPException(status_code=503, detail="Persistence is disabled.")
    try:
        return diff_scans(from_id, to_id, workspace_id=workspace)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=f"Scan not found: {exc}") from exc


@app.get("/scans/{scan_id}")
def get_scan(scan_id: str, workspace: str = Depends(get_current_workspace)):
    """Fetch one saved scan by id. 503 if disabled, 404 if not found."""
    if not scan_repository.is_enabled():
        raise HTTPException(status_code=503, detail="Persistence is disabled.")
    record = scan_repository.get_scan(scan_id, workspace_id=workspace)
    if record is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return record
