"""Shared data model for a scanned AWS resource.

Every scanner returns objects of this shape so the API and frontend can
treat all resources uniformly.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class RiskLevel(str, Enum):
    """Risk levels used across all scanners.

    LOW    - unlikely to cost much, or already stopped
    MEDIUM - actively costing money but cheap / easy to stop
    HIGH   - actively costing money and easy to forget about
    REVIEW - needs a human to decide (cost depends on usage)
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    REVIEW = "REVIEW"


class Resource(BaseModel):
    """Consistent JSON shape returned for every scanned resource."""

    resource_type: str
    resource_id: str
    name: str | None = None
    region: str
    status: str
    risk_level: RiskLevel
    monthly_cost_risk: str
    suggested_action: str
    # Populated when scanning multiple AWS accounts; None for single-account/local.
    account_id: str | None = None
    account_label: str | None = None
    # Type-specific inputs used for cost estimation (e.g. instance_type, size_gb).
    details: dict | None = None
    # Rough estimated monthly cost (USD). source: "live" | "static" | "unknown".
    estimated_monthly_cost: float | None = None
    cost_currency: str = "USD"
    cost_source: str | None = None
