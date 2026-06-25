"""Alert model.

An Alert is a notification-ready signal derived from a scan (and, when
available, the previous scan). The same shape is what email/Slack integrations
will deliver later — so it is intentionally self-contained and plain.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class AlertSeverity(str, Enum):
    """Severity is distinct from a resource's risk level.

    CRITICAL - something changed for the worse (new billable resource, risk rose)
    WARNING  - a standing, ongoing cost risk worth attention
    INFO     - worth a glance (e.g. a new bucket to review)
    """

    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class Alert(BaseModel):
    """A single alert about one resource."""

    id: str
    severity: AlertSeverity
    rule: str  # machine-readable reason, e.g. "new_billable_resource"
    title: str
    message: str
    resource_type: str
    resource_id: str
    region: str
    risk_level: str
    estimated_monthly_cost: float | None = None
