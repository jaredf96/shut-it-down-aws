"""Billing: plans, plan-limit enforcement, and Stripe integration.

Plans are intentionally simple — Free and Pro — with per-tenant limits on the
number of registered AWS accounts and team members. Stripe is **optional**: when
`STRIPE_SECRET_KEY` is unset, billing runs in a local/dev mode where an admin can
set the plan directly (so paid features can be tried without Stripe). With Stripe
configured, plan changes flow through Checkout + webhooks instead.
"""

from __future__ import annotations

from app import config
from app.repositories import account_repository, billing_repository, user_repository

try:  # Stripe is optional; the app runs fine without it.
    import stripe
except ImportError:  # pragma: no cover
    stripe = None

PLANS: dict[str, dict] = {
    "free": {"label": "Free", "max_accounts": 1, "max_users": 3},
    "pro": {"label": "Pro", "max_accounts": 25, "max_users": 50},
}


def billing_enabled() -> bool:
    """True when Stripe is installed and configured."""
    return stripe is not None and config.stripe_secret_key() is not None


def _limits(plan: str) -> dict:
    return PLANS.get(plan, PLANS["free"])


def get_billing(tenant_id: str) -> dict:
    """Current plan, its limits, status, and live usage counts."""
    billing = billing_repository.get_billing(tenant_id)
    plan = billing["plan"]
    usage = {
        "accounts": len(account_repository.list_accounts(tenant_id)),
        "users": len(user_repository.list_users(tenant_id)),
    }
    return {
        **billing,
        "limits": _limits(plan),
        "usage": usage,
        "billing_managed_by_stripe": billing_enabled(),
        "plans": PLANS,
    }


def set_plan(
    tenant_id: str, plan: str, *, status: str | None = None, customer_id: str | None = None
) -> dict:
    """Set a tenant's plan. Raises ValueError for an unknown plan."""
    if plan not in PLANS:
        raise ValueError(f"Unknown plan: {plan}")
    billing_repository.set_billing(
        tenant_id, plan=plan, subscription_status=status, stripe_customer_id=customer_id
    )
    return get_billing(tenant_id)


def account_limit_reached(tenant_id: str) -> bool:
    billing = billing_repository.get_billing(tenant_id)
    limit = _limits(billing["plan"])["max_accounts"]
    return len(account_repository.list_accounts(tenant_id)) >= limit


def user_limit_reached(tenant_id: str) -> bool:
    billing = billing_repository.get_billing(tenant_id)
    limit = _limits(billing["plan"])["max_users"]
    return len(user_repository.list_users(tenant_id)) >= limit


# --- Stripe -------------------------------------------------------------


def create_checkout_session(tenant_id: str) -> dict:
    """Create a Stripe Checkout session for the Pro subscription."""
    if not billing_enabled():
        raise RuntimeError("Billing is not configured.")
    stripe.api_key = config.stripe_secret_key()
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": config.stripe_price_id(), "quantity": 1}],
        success_url=config.billing_success_url(),
        cancel_url=config.billing_cancel_url(),
        client_reference_id=tenant_id,
        subscription_data={"metadata": {"tenant_id": tenant_id}},
    )
    return {"url": session.url, "id": session.id}


def handle_webhook(payload: bytes, signature: str | None) -> dict:
    """Verify a Stripe webhook and apply its effect to the tenant's plan."""
    if not billing_enabled():
        raise RuntimeError("Billing is not configured.")
    event = stripe.Webhook.construct_event(payload, signature, config.stripe_webhook_secret())
    return apply_event(event)


def apply_event(event: dict) -> dict:
    """Map a Stripe event to a plan change (separated out so it is unit-testable)."""
    obj = event["data"]["object"]
    etype = event["type"]
    tenant_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("tenant_id")
    if not tenant_id:
        return {"handled": False, "reason": "no tenant reference"}

    if etype == "checkout.session.completed":
        set_plan(tenant_id, "pro", status="active", customer_id=obj.get("customer"))
        return {"handled": True, "tenant_id": tenant_id, "plan": "pro"}

    if etype == "customer.subscription.deleted":
        set_plan(tenant_id, "free", status="canceled")
        return {"handled": True, "tenant_id": tenant_id, "plan": "free"}

    return {"handled": False, "reason": f"ignored event {etype}"}
