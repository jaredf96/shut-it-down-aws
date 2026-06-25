"""Request model for a guided cleanup action."""

from __future__ import annotations

from pydantic import BaseModel


class CleanupRequest(BaseModel):
    action: str
    resource_id: str
    # Must equal `resource_id` exactly — the explicit per-resource confirmation.
    confirm_resource_id: str
    region: str
    account_id: str | None = None
    # Safe default: preview only. Set false to actually mutate.
    dry_run: bool = True
