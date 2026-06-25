"""Scan one or many AWS accounts for a tenant.

If the tenant has registered accounts, each is scanned with assumed-role
credentials and every resource is tagged with its account. Otherwise we fall
back to a single scan using the server's own credentials (local / default).

A failure assuming one account's role never breaks the others — it is collected
in `account_errors`.
"""

from __future__ import annotations

from app.aws.session import session_for_account
from app.models import Resource
from app.repositories import account_repository
from app.services.scan_service import scan_all, summarize


def _tag(resource: Resource, account: dict) -> Resource:
    label = account.get("name") or account["account_id"]
    return resource.model_copy(update={"account_id": account["account_id"], "account_label": label})


def scan_accounts(tenant_id: str | None = None) -> dict:
    """Scan all of a tenant's registered accounts (or default creds if none)."""
    accounts = account_repository.list_accounts(tenant_id) if tenant_id else []

    if not accounts:
        # Single-account / local mode — unchanged behavior.
        return scan_all()

    all_resources: list[Resource] = []
    scanned: list[dict] = []
    errors: list[dict] = []

    for account in accounts:
        try:
            session = session_for_account(account)
            result = scan_all(regions=account.get("regions"), session=session)
            all_resources.extend(_tag(r, account) for r in result["resources"])
            scanned.append({"account_id": account["account_id"], "name": account.get("name")})
        except Exception as exc:  # one bad account must not break the rest
            errors.append(
                {
                    "account_id": account["account_id"],
                    "name": account.get("name"),
                    "error": str(exc),
                }
            )

    return {
        "summary": summarize(all_resources),
        "resources": all_resources,
        "accounts_scanned": scanned,
        "account_errors": errors,
    }
