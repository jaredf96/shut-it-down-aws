"""Slack notifier — posts to an Incoming Webhook URL."""

from __future__ import annotations

import json
import urllib.request

from app.models import Alert
from app.notifiers.base import Notifier

_ICON = {"CRITICAL": "🔴", "WARNING": "🟠", "INFO": "🔵"}


class SlackNotifier(Notifier):
    name = "slack"

    def __init__(self, webhook_url: str, *, timeout: int = 10):
        self.webhook_url = webhook_url
        self.timeout = timeout

    def format(self, alerts: list[Alert]) -> dict:
        """Build the Slack webhook payload ({"text": ...})."""
        lines = [f"*{len(alerts)} AWS cleanup alert(s)*"]
        for a in alerts:
            icon = _ICON.get(a.severity.value, "")
            lines.append(f"{icon} *{a.severity.value}* — {a.title} (`{a.resource_id}`, {a.region})")
        return {"text": "\n".join(lines)}

    def send(self, alerts: list[Alert]) -> None:
        if not alerts:
            return
        data = json.dumps(self.format(alerts)).encode()
        request = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(request, timeout=self.timeout)
