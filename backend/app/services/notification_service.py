"""Deliver alerts to configured notification channels.

Builds notifiers from environment config, filters alerts by a minimum severity
(so INFO noise does not page anyone), and dispatches. One failing channel never
breaks the others — each result is reported independently.
"""

from __future__ import annotations

from app import config
from app.models import Alert
from app.notifiers import EmailNotifier, Notifier, SlackNotifier

_SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


def notifiers_from_env() -> list[Notifier]:
    """Construct the notifiers that are configured via environment variables."""
    notifiers: list[Notifier] = []

    webhook = config.slack_webhook_url()
    if webhook:
        notifiers.append(SlackNotifier(webhook))

    smtp = config.smtp_settings()
    recipients = config.alert_email_recipients()
    if smtp and recipients:
        notifiers.append(EmailNotifier(recipients=recipients, **smtp))

    return notifiers


def _at_or_above(alerts: list[Alert], min_severity: str) -> list[Alert]:
    threshold = _SEVERITY_RANK[min_severity]
    return [a for a in alerts if _SEVERITY_RANK[a.severity.value] >= threshold]


def notify(
    alerts: list[Alert],
    *,
    notifiers: list[Notifier] | None = None,
    min_severity: str | None = None,
) -> dict:
    """Send alerts (at/above `min_severity`) to each notifier.

    Returns a per-channel result summary; channels that fail are reported with
    status "error" rather than raising.

    `sent_count` counts alerts that actually reached at least one channel. If
    every channel fails it is 0, not the number of alerts we tried to send —
    the per-channel statuses were always accurate, but this field previously
    reported attempts as if they were deliveries.
    """
    notifiers = notifiers if notifiers is not None else notifiers_from_env()
    min_severity = min_severity or config.notify_min_severity()
    relevant = _at_or_above(alerts, min_severity)

    channels = []
    for notifier in notifiers:
        if not relevant:
            channels.append(
                {"channel": notifier.name, "status": "skipped", "detail": "no alerts at threshold"}
            )
            continue
        try:
            notifier.send(relevant)
            channels.append(
                {"channel": notifier.name, "status": "sent", "detail": f"{len(relevant)} alert(s)"}
            )
        except Exception as exc:  # one channel failing must not break the rest
            channels.append({"channel": notifier.name, "status": "error", "detail": str(exc)})

    delivered = any(c["status"] == "sent" for c in channels)

    return {
        "sent_count": len(relevant) if delivered else 0,
        "min_severity": min_severity,
        "channels": channels,
    }
