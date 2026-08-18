"""FastAPI entrypoint for the Cloud Lab Cleanup Dashboard.

Scanning is read-only. Mutating cleanup actions exist only under `/cleanup/*`
and are OFF by default — they require `ENABLE_CLEANUP_ACTIONS=true`, an admin
role, an exact per-resource confirmation, default to dry-run, and audit every
attempt. See `app/services/cleanup_service.py`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import config
from app.auth import get_current_principal, get_current_tenant, require_admin
from app.logging_setup import configure_logging
from app.models import AccountCreate, CleanupRequest, UserCreate
from app.repositories import (
    account_repository,
    audit_repository,
    scan_repository,
    tenant_repository,
    user_repository,
)
from app.services import (
    billing_service,
    cleanup_service,
    diff_scans,
    evaluate_alerts,
    list_with_deltas,
    notify,
    scan_accounts,
    scan_one,
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
    title="Cloud Lab Cleanup Dashboard",
    description="Read-only scanner that finds AWS resources left over from labs and tutorials.",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow the local Vite dev server to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


class TenantCreate(BaseModel):
    name: str


class PlanUpdate(BaseModel):
    plan: str


@app.get("/health")
def health():
    """Liveness check that does not touch AWS."""
    return {
        "status": "ok",
        "service": "shut-it-down-aws",
        "version": "0.1.0",
        "persistence_enabled": scan_repository.is_enabled(),
        "auth_required": config.auth_required(),
    }


@app.post("/tenants", status_code=201)
def create_tenant(payload: TenantCreate, x_admin_token: str | None = Header(default=None)):
    """Register a tenant and return its API key (shown once).

    Requires persistence. If ADMIN_TOKEN is set, the X-Admin-Token header must
    match it — protect this endpoint before exposing it publicly.
    """
    if not scan_repository.is_enabled():
        raise HTTPException(status_code=503, detail="Persistence is required to create tenants.")
    admin = config.admin_token()
    if admin and x_admin_token != admin:
        raise HTTPException(status_code=401, detail="Invalid admin token.")
    return tenant_repository.create_tenant(payload.name)


def _require_persistence() -> None:
    if not scan_repository.is_enabled():
        raise HTTPException(status_code=503, detail="Persistence is required for this endpoint.")


@app.get("/me")
def whoami(principal: dict = Depends(get_current_principal)):
    """Return the calling principal (tenant, user, role) — handy for the UI."""
    return principal


# --- Users (team members) ------------------------------------------------


@app.get("/users")
def list_users(tenant: str = Depends(get_current_tenant)):
    """List the team members of this tenant."""
    _require_persistence()
    return {"users": user_repository.list_users(tenant)}


@app.post("/users", status_code=201)
def add_user(payload: UserCreate, principal: dict = Depends(require_admin)):
    """Create a team member and return their API key (admin only, shown once)."""
    _require_persistence()
    if billing_service.user_limit_reached(principal["tenant_id"]):
        raise HTTPException(
            status_code=402, detail="Team-member limit reached for your plan. Upgrade to add more."
        )
    return user_repository.create_user(principal["tenant_id"], payload.name, payload.role)


@app.delete("/users/{user_id}")
def remove_user(user_id: str, principal: dict = Depends(require_admin)):
    """Remove a team member and revoke their API key (admin only)."""
    _require_persistence()
    if user_id == principal["user_id"]:
        raise HTTPException(status_code=400, detail="You cannot remove yourself.")
    if not user_repository.delete_user(principal["tenant_id"], user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return {"deleted": user_id}


# --- Accounts (multi-account) --------------------------------------------


@app.get("/accounts")
def list_accounts(tenant: str = Depends(get_current_tenant)):
    """List the AWS accounts registered for this tenant."""
    _require_persistence()
    return {"accounts": account_repository.list_accounts(tenant)}


@app.post("/accounts", status_code=201)
def add_account(payload: AccountCreate, principal: dict = Depends(require_admin)):
    """Register an AWS account (admin only)."""
    _require_persistence()
    if billing_service.account_limit_reached(principal["tenant_id"]):
        raise HTTPException(
            status_code=402, detail="AWS-account limit reached for your plan. Upgrade to add more."
        )
    return account_repository.create_account(principal["tenant_id"], payload.model_dump())


@app.delete("/accounts/{account_id}")
def remove_account(account_id: str, principal: dict = Depends(require_admin)):
    """Remove an account registration (admin only)."""
    _require_persistence()
    if not account_repository.delete_account(principal["tenant_id"], account_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"deleted": account_id}


# --- Guided cleanup (mutating — safe by construction) --------------------

# Maps a cleanup result status to an HTTP code.
_CLEANUP_STATUS_CODE = {
    "success": 200,
    "dry_run": 200,
    "confirmation_mismatch": 400,
    "unsupported_action": 400,
    "precondition_failed": 409,
    "error": 502,
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
def cleanup_audit(limit: int = 50, tenant: str = Depends(get_current_tenant)):
    """Recent cleanup attempts for this tenant (newest first)."""
    _require_persistence()
    return {"entries": audit_repository.list_entries(tenant, limit)}


@app.post("/cleanup/execute")
def cleanup_execute(payload: CleanupRequest, principal: dict = Depends(require_admin)):
    """Run one guided cleanup action (admin only).

    Hard-gated by `ENABLE_CLEANUP_ACTIONS`. Requires `confirm_resource_id` to
    equal `resource_id`. Defaults to a dry run; pass `dry_run=false` to mutate.
    """
    if not config.cleanup_enabled():
        raise HTTPException(
            status_code=403, detail="Cleanup actions are disabled in this environment."
        )

    result = cleanup_service.execute(
        action=payload.action,
        resource_id=payload.resource_id,
        confirm_resource_id=payload.confirm_resource_id,
        region=payload.region,
        account_id=payload.account_id,
        dry_run=payload.dry_run,
        tenant_id=principal["tenant_id"],
        user_id=principal["user_id"],
    )

    code = _CLEANUP_STATUS_CODE.get(result["status"], 400)
    if code >= 400:
        raise HTTPException(status_code=code, detail=result["detail"])
    return result


# --- Billing -------------------------------------------------------------


@app.get("/billing")
def billing(tenant: str = Depends(get_current_tenant)):
    """Current plan, limits, usage, and available plans."""
    _require_persistence()
    return billing_service.get_billing(tenant)


@app.post("/billing/plan")
def set_billing_plan(payload: PlanUpdate, principal: dict = Depends(require_admin)):
    """Manually set the plan (admin). Only when Stripe is NOT configured (dev)."""
    _require_persistence()
    if billing_service.billing_enabled():
        raise HTTPException(
            status_code=409, detail="Plan is managed by Stripe — use checkout instead."
        )
    try:
        return billing_service.set_plan(principal["tenant_id"], payload.plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/billing/checkout")
def billing_checkout(principal: dict = Depends(require_admin)):
    """Create a Stripe Checkout session to upgrade (admin). 503 if not configured."""
    _require_persistence()
    if not billing_service.billing_enabled():
        raise HTTPException(status_code=503, detail="Billing is not configured.")
    return billing_service.create_checkout_session(principal["tenant_id"])


@app.post("/billing/webhook")
async def billing_webhook(request: Request, stripe_signature: str | None = Header(default=None)):
    """Stripe webhook — verified by signature, updates the tenant's plan."""
    if not billing_service.billing_enabled():
        raise HTTPException(status_code=503, detail="Billing is not configured.")
    payload = await request.body()
    try:
        return billing_service.handle_webhook(payload, stripe_signature)
    except Exception as exc:  # signature/verification errors -> 400
        raise HTTPException(status_code=400, detail=f"Webhook error: {exc}") from exc


@app.get("/scan")
def scan_everything(save: bool = True, tenant: str = Depends(get_current_tenant)):
    """Run all scanners and return a combined, summarized result.

    The response includes `alerts` (derived from this scan, and the previous
    saved scan when available). When persistence is configured, the result is
    also saved to DynamoDB and its `scan_id` is returned. Pass `?save=false`
    to skip saving.

    If the tenant has registered AWS accounts, every account is scanned
    (assume-role) and each resource is tagged with its account; otherwise the
    server's own credentials are used.
    """
    result = scan_accounts(tenant)

    # Compare against the most recent saved scan (the "previous" one) for
    # change-aware alerts. Fetch it before saving the new scan.
    previous_resources = None
    if scan_repository.is_enabled():
        recent = scan_repository.list_scans_full(1, tenant_id=tenant)
        if recent:
            previous_resources = recent[0]["resources"]

    alerts = evaluate_alerts(result["resources"], previous_resources)

    scan_id = None
    if save and scan_repository.is_enabled():
        scan_id = scan_repository.save_scan(result, tenant_id=tenant)

    response = {**result, "alerts": alerts, "scan_id": scan_id, "persisted": scan_id is not None}

    # Optionally push alerts to email/Slack on every scan.
    if config.notify_on_scan():
        response["notifications"] = notify(alerts)

    return response


@app.post("/notify")
def notify_alerts(tenant: str = Depends(get_current_tenant)):
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
    recent = scan_repository.list_scans_full(2, tenant_id=tenant)
    if not recent:
        return {"sent_count": 0, "channels": [], "based_on": None}
    current = recent[0]
    previous_resources = recent[1]["resources"] if len(recent) > 1 else None
    alerts = evaluate_alerts(current["resources"], previous_resources)
    return {**notify(alerts), "based_on": current["scan_id"]}


@app.get("/alerts")
def get_alerts(tenant: str = Depends(get_current_tenant)):
    """Alerts derived from the latest saved scan (vs the one before it).

    Requires persistence. Without it, alerts are still returned inline by
    `GET /scan`.
    """
    if not scan_repository.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Persistence is disabled. Alerts are included inline in GET /scan.",
        )
    recent = scan_repository.list_scans_full(2, tenant_id=tenant)
    if not recent:
        return {"alerts": [], "based_on": None}
    current = recent[0]
    previous_resources = recent[1]["resources"] if len(recent) > 1 else None
    alerts = evaluate_alerts(current["resources"], previous_resources)
    return {"alerts": alerts, "based_on": current["scan_id"]}


@app.get("/scans")
def list_scans(limit: int = 20, tenant: str = Depends(get_current_tenant)):
    """List recent saved scans (newest first), each with a `vs_previous` delta.

    503 if persistence is disabled.
    """
    if not scan_repository.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Persistence is disabled. Set DYNAMODB_TABLE_NAME to enable scan history.",
        )
    return {"scans": list_with_deltas(limit=limit, tenant_id=tenant)}


# NOTE: declared before "/scans/{scan_id}" so the fixed "diff" path matches first.
@app.get("/scans/diff")
def diff(from_id: str, to_id: str, tenant: str = Depends(get_current_tenant)):
    """Compare two saved scans (older `from_id` vs newer `to_id`).

    503 if persistence is disabled, 404 if either scan id is missing.
    """
    if not scan_repository.is_enabled():
        raise HTTPException(status_code=503, detail="Persistence is disabled.")
    try:
        return diff_scans(from_id, to_id, tenant_id=tenant)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=f"Scan not found: {exc}") from exc


@app.get("/scans/{scan_id}")
def get_scan(scan_id: str, tenant: str = Depends(get_current_tenant)):
    """Fetch one saved scan by id. 503 if disabled, 404 if not found."""
    if not scan_repository.is_enabled():
        raise HTTPException(status_code=503, detail="Persistence is disabled.")
    record = scan_repository.get_scan(scan_id, tenant_id=tenant)
    if record is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return record


def _scan_route(key: str):
    """Shared handler for the per-service scan endpoints."""
    try:
        resources = scan_one(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown scanner: {key}") from exc
    return {"count": len(resources), "resources": resources}


@app.get("/scan/ec2")
def scan_ec2(tenant: str = Depends(get_current_tenant)):
    return _scan_route("ec2")


@app.get("/scan/ebs")
def scan_ebs(tenant: str = Depends(get_current_tenant)):
    return _scan_route("ebs")


@app.get("/scan/elastic-ips")
def scan_elastic_ips(tenant: str = Depends(get_current_tenant)):
    return _scan_route("elastic-ips")


@app.get("/scan/nat-gateways")
def scan_nat_gateways(tenant: str = Depends(get_current_tenant)):
    return _scan_route("nat-gateways")


@app.get("/scan/load-balancers")
def scan_load_balancers(tenant: str = Depends(get_current_tenant)):
    return _scan_route("load-balancers")


@app.get("/scan/rds")
def scan_rds(tenant: str = Depends(get_current_tenant)):
    return _scan_route("rds")


@app.get("/scan/s3")
def scan_s3(tenant: str = Depends(get_current_tenant)):
    return _scan_route("s3")
