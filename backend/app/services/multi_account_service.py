"""Scan one or many AWS accounts for a workspace.

If the workspace has registered accounts, each is scanned with assumed-role
credentials and every resource is tagged with its account. Otherwise we fall
back to a single scan using the server's own credentials (local / default).

A failure assuming one account's role never breaks the others — it is collected
in `account_errors`. Regions an account was scanned with but could not be read
are collected in `regions_failed`, and whole scanners that could not run in
`scanners_failed`; both are stamped with the account they belong to.
"""

from __future__ import annotations

from app.aws.session import session_for_account
from app.models import Resource
from app.repositories import account_repository
from app.services.scan_service import scan_all, summarize


def _label(account: dict) -> str:
    return account.get("name") or account["account_id"]


def _tag(resource: Resource, account: dict) -> Resource:
    return resource.model_copy(
        update={"account_id": account["account_id"], "account_label": _label(account)}
    )


def _tag_failure(failure: dict, account: dict) -> dict:
    """Attribute a gap in coverage to the account it happened in.

    Shared by region and scanner failures: both carry the same account fields,
    for the same reason resources do — the same gap in two accounts must not
    conflate.
    """
    return {**failure, "account_id": account["account_id"], "account_label": _label(account)}


def scan_accounts(workspace_id: str | None = None, *, principal: dict | None = None) -> dict:
    """Scan all of a workspace's registered accounts (or default creds if none).

    `principal` is attribution only — it names each assumed session so the
    scanned account's own CloudTrail shows who caused the reads. `workspace_id`
    remains the sole authority for *which* accounts are listed; the one
    production caller derives it from the same principal, so the two cannot
    disagree.
    """
    accounts = account_repository.list_accounts(workspace_id) if workspace_id else []

    if not accounts:
        # Single-account / local mode — unchanged behavior.
        return scan_all()

    all_resources: list[Resource] = []
    regions_failed: list[dict] = []
    scanners_failed: list[dict] = []
    scanned: list[dict] = []
    errors: list[dict] = []

    for account in accounts:
        try:
            session = session_for_account(account, principal=principal)
            result = scan_all(regions=account.get("regions"), session=session)
            all_resources.extend(_tag(r, account) for r in result["resources"])
            regions_failed.extend(
                _tag_failure(f, account) for f in result.get("regions_failed", [])
            )
            scanners_failed.extend(
                _tag_failure(f, account) for f in result.get("scanners_failed", [])
            )
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
        "regions_failed": regions_failed,
        "scanners_failed": scanners_failed,
        "accounts_scanned": scanned,
        "account_errors": errors,
    }
