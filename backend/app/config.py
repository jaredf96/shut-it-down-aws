"""Runtime configuration, read from environment variables.

Persistence is **optional**. If `DYNAMODB_TABLE_NAME` is not set, the app runs
fully in-memory and the history endpoints report that persistence is disabled.

These are functions (not module constants) so tests can monkeypatch the
environment and pick up the change without re-importing.
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def get_table_name() -> str | None:
    """Name of the DynamoDB table for scan history, or None if unset."""
    return os.environ.get("DYNAMODB_TABLE_NAME") or None


def get_dynamodb_endpoint_url() -> str | None:
    """Custom endpoint for local DynamoDB (e.g. dynamodb-local), or None."""
    return os.environ.get("DYNAMODB_ENDPOINT_URL") or None


def persistence_enabled() -> bool:
    """True when a table name is configured."""
    return get_table_name() is not None


def auto_create_enabled() -> bool:
    """When true, create the table on startup if it does not exist.

    Handy for local dev; leave off in production where the table is managed
    by infrastructure-as-code (Terraform / CDK).
    """
    return os.environ.get("DYNAMODB_AUTO_CREATE", "").lower() in _TRUTHY


# --- Tenancy / auth ------------------------------------------------------


def default_tenant_id() -> str:
    """Tenant used when no API key is presented (local / single-tenant mode)."""
    return os.environ.get("DEFAULT_TENANT_ID") or "default"


def auth_required() -> bool:
    """When true, every data request must carry a valid API key.

    Off by default so local dev needs no credentials. Turn on for SaaS mode.
    """
    return os.environ.get("AUTH_REQUIRED", "").lower() in _TRUTHY


def admin_token() -> str | None:
    """If set, creating tenants requires this token in the X-Admin-Token header."""
    return os.environ.get("ADMIN_TOKEN") or None


# --- Cleanup actions (mutating!) -----------------------------------------


def cleanup_enabled() -> bool:
    """Master safety switch for mutating cleanup actions.

    OFF by default. Cleanup endpoints refuse to act unless this is true.
    """
    return os.environ.get("ENABLE_CLEANUP_ACTIONS", "").lower() in _TRUTHY


# --- Pricing -------------------------------------------------------------


def live_pricing_enabled() -> bool:
    """Use the live AWS Pricing API to refine estimates (falls back to static)."""
    return os.environ.get("ENABLE_LIVE_PRICING", "").lower() in _TRUTHY


# --- Billing (Stripe) ----------------------------------------------------


def stripe_secret_key() -> str | None:
    return os.environ.get("STRIPE_SECRET_KEY") or None


def stripe_webhook_secret() -> str | None:
    return os.environ.get("STRIPE_WEBHOOK_SECRET") or None


def stripe_price_id() -> str | None:
    """Stripe Price id for the paid (Pro) subscription."""
    return os.environ.get("STRIPE_PRICE_ID") or None


def billing_success_url() -> str:
    return os.environ.get("BILLING_SUCCESS_URL", "http://localhost:5173/?billing=success")


def billing_cancel_url() -> str:
    return os.environ.get("BILLING_CANCEL_URL", "http://localhost:5173/?billing=cancel")


# --- Notifications -------------------------------------------------------

_VALID_SEVERITIES = {"INFO", "WARNING", "CRITICAL"}


def slack_webhook_url() -> str | None:
    """Slack Incoming Webhook URL for alert delivery, or None."""
    return os.environ.get("SLACK_WEBHOOK_URL") or None


def alert_email_recipients() -> list[str]:
    """Comma-separated ALERT_EMAIL_TO -> list of recipients (possibly empty)."""
    raw = os.environ.get("ALERT_EMAIL_TO", "")
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def smtp_settings() -> dict | None:
    """SMTP config for the email notifier, or None if SMTP_HOST is unset."""
    host = os.environ.get("SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "sender": os.environ.get("ALERT_EMAIL_FROM", "alerts@cloud-lab-cleanup.local"),
        "username": os.environ.get("SMTP_USERNAME") or None,
        "password": os.environ.get("SMTP_PASSWORD") or None,
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() in _TRUTHY,
    }


def notify_on_scan() -> bool:
    """When true, GET /scan delivers alerts to configured channels automatically."""
    return os.environ.get("NOTIFY_ON_SCAN", "").lower() in _TRUTHY


def notify_min_severity() -> str:
    """Only alerts at or above this severity are delivered (default WARNING)."""
    value = os.environ.get("NOTIFY_MIN_SEVERITY", "WARNING").upper()
    return value if value in _VALID_SEVERITIES else "WARNING"
