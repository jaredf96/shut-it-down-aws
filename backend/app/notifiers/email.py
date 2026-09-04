"""Email notifier — sends a plain-text summary over SMTP.

Transport contract: when TLS is used it is always certificate- and
hostname-verified (an explicit `ssl.create_default_context()`), and there is no
option to disable verification. `SMTP_CA_BUNDLE` is the supported path for a
private CA. Plaintext requires the literal mode `none`, and refuses to
authenticate (D15).
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.models import Alert
from app.notifiers.base import Notifier

_SECURITY_MODES = ("starttls", "ssl", "none")


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
        security: str = "starttls",
        ca_bundle: str | None = None,
        timeout: int = 10,
    ):
        self.host = host
        self.port = port
        self.sender = sender
        self.recipients = recipients
        self.username = username
        self.password = password
        # Coerce, never trust. An unrecognised mode becomes the secure default
        # rather than falling through to plaintext: `send()` branches on the
        # complement of "none", so skipping TLS takes the literal word at both
        # layers. Coercing rather than raising because __init__ runs inside
        # notifiers_from_env(), outside notify()'s per-channel try (invariant
        # 4) — and a string assignment cannot raise.
        self.security = security if security in _SECURITY_MODES else "starttls"
        self.ca_bundle = ca_bundle
        self.timeout = timeout

    def format(self, alerts: list[Alert]) -> tuple[str, str]:
        """Build (subject, plain-text body)."""
        critical = sum(1 for a in alerts if a.severity.value == "CRITICAL")
        subject = f"Shut It Down: {len(alerts)} alert(s)"
        if critical:
            subject += f" ({critical} critical)"

        blocks = [
            f"[{a.severity.value}] {a.title}\n"
            f"  {a.resource_type} {a.resource_id} in {a.region}\n"
            f"  {a.message}"
            for a in alerts
        ]
        return subject, "\n\n".join(blocks)

    def _ssl_context(self) -> ssl.SSLContext:
        """A verifying TLS context — chain validation and hostname check, always.

        `smtplib` builds `ssl._create_stdlib_context()` when `starttls()` is
        called bare: CERT_NONE, check_hostname False. Passing this instead is
        the whole fix.

        Built per-send, not in __init__, on purpose. Notifiers are constructed
        by `notifiers_from_env()`, which `notification_service.notify` calls
        *outside* its per-channel try — so a bad `SMTP_CA_BUNDLE` path built
        eagerly would raise FileNotFoundError up through `GET /scan` and break
        the scan (invariant 4). Built here, it is one channel's error.

        A supplied bundle *replaces* the system trust store rather than adding
        to it (`ssl.create_default_context` skips `load_default_certs` when
        cafile is given), so trust becomes exactly this file.
        """
        return ssl.create_default_context(cafile=self.ca_bundle)

    def send(self, alerts: list[Alert]) -> None:
        if not alerts:
            return

        if self.username and self.security == "none":
            raise ValueError(
                "Refusing to send SMTP credentials over an unencrypted "
                "connection. Set SMTP_SECURITY=starttls (or ssl), or unset "
                "SMTP_USERNAME/SMTP_PASSWORD to relay anonymously."
            )

        # Before any socket, and identically for both transports: a bad
        # SMTP_CA_BUNDLE must fail without a connection attempt.
        context = None if self.security == "none" else self._ssl_context()

        subject, body = self.format(alerts)

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(body)

        if self.security == "ssl":
            with smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=context
            ) as server:
                self._deliver(server, message)
            return

        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
            # The complement of "none", not `== "starttls"`: with the mode
            # coerced in __init__ these branches are exhaustive, and plaintext
            # takes the literal word.
            if context is not None:
                server.starttls(context=context)
            self._deliver(server, message)

    def _deliver(self, server, message: EmailMessage) -> None:
        if self.username:
            server.login(self.username, self.password)
        server.send_message(message)
