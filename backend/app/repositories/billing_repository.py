"""Per-tenant billing state, stored on the tenant record.

    pk = "TENANTMETA#<tenant_id>"  sk = "#"
        + plan, subscription_status, stripe_customer_id

Defaults to the free plan when nothing is stored.
"""

from __future__ import annotations

from app.repositories.dynamo import get_table, is_enabled

DEFAULT_PLAN = "free"


def get_billing(tenant_id: str) -> dict:
    """Return {plan, subscription_status, stripe_customer_id} (with defaults)."""
    if not is_enabled():
        return {"plan": DEFAULT_PLAN, "subscription_status": "inactive", "stripe_customer_id": None}

    response = get_table().get_item(Key={"pk": f"TENANTMETA#{tenant_id}", "sk": "#"})
    item = response.get("Item") or {}
    return {
        "plan": item.get("plan", DEFAULT_PLAN),
        "subscription_status": item.get("subscription_status", "inactive"),
        "stripe_customer_id": item.get("stripe_customer_id"),
    }


def set_billing(
    tenant_id: str,
    *,
    plan: str,
    subscription_status: str | None = None,
    stripe_customer_id: str | None = None,
) -> dict:
    """Update the tenant's billing attributes. Returns the new billing state."""
    if not is_enabled():
        raise RuntimeError("Persistence is required for billing")

    names = {"#plan": "plan"}
    values = {":plan": plan}
    sets = ["#plan = :plan"]
    if subscription_status is not None:
        names["#status"] = "subscription_status"
        values[":status"] = subscription_status
        sets.append("#status = :status")
    if stripe_customer_id is not None:
        values[":cust"] = stripe_customer_id
        sets.append("stripe_customer_id = :cust")

    get_table().update_item(
        Key={"pk": f"TENANTMETA#{tenant_id}", "sk": "#"},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    return get_billing(tenant_id)
