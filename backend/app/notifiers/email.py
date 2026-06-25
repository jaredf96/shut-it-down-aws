"""Email notifier — sends a plain-text summary over SMTP."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.models import Alert
from app.notifiers.base import Notifier


class EmailNotifier(Notifier):
    name = "email"

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        recipients: list[str],
        *,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        timeout: int = 10,
    ):
        self.host = host
        self.port = port
        self.sender = sender
        self.recipients = recipients
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.timeout = timeout

    def format(self, alerts: list[Alert]) -> tuple[str, str]:
        """Build (subject, plain-text body)."""
        critical = sum(1 for a in alerts if a.severity.value == "CRITICAL")
        subject = f"Cloud Lab Cleanup: {len(alerts)} alert(s)"
        if critical:
            subject += f" ({critical} critical)"

        blocks = [
            f"[{a.severity.value}] {a.title}\n"
            f"  {a.resource_type} {a.resource_id} in {a.region}\n"
            f"  {a.message}"
            for a in alerts
        ]
        return subject, "\n\n".join(blocks)

    def send(self, alerts: list[Alert]) -> None:
        if not alerts:
            return
        subject, body = self.format(alerts)

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(body)

        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
            if self.use_tls:
                server.starttls()
            if self.username:
                server.login(self.username, self.password)
            server.send_message(message)
