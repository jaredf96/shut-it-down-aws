import logging
import smtplib
import ssl

import pytest

from app import config
from app.models import Alert, AlertSeverity
from app.notifiers import EmailNotifier, SlackNotifier


def _alert(severity, rid="i-1", title="High-risk resource"):
    return Alert(
        id=f"r:{rid}",
        severity=severity,
        rule="high_risk_resource",
        title=title,
        message="costs money",
        resource_type="NAT Gateway",
        resource_id=rid,
        region="us-east-1",
        risk_level="HIGH",
    )


# --- Slack ---------------------------------------------------------------


def test_slack_format_includes_severity_and_resource():
    payload = SlackNotifier("http://hook").format([_alert(AlertSeverity.CRITICAL)])
    text = payload["text"]
    assert "CRITICAL" in text
    assert "i-1" in text


def test_slack_send_posts_to_webhook(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["method"] = request.get_method()

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    monkeypatch.setattr("app.notifiers.slack.urllib.request.urlopen", fake_urlopen)

    SlackNotifier("http://hook.example/abc").send([_alert(AlertSeverity.WARNING)])
    assert captured["url"] == "http://hook.example/abc"
    assert captured["method"] == "POST"
    assert b"WARNING" in captured["body"]


def test_slack_send_noop_on_empty(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not send for empty alerts")

    monkeypatch.setattr("app.notifiers.slack.urllib.request.urlopen", boom)
    SlackNotifier("http://hook").send([])  # must not raise


# --- Email ---------------------------------------------------------------


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.sent = []
        self.tls = False
        self.tls_context = None
        self.credentials = None
        self.tls_before_login = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, *, context=None):
        self.tls = True
        self.tls_context = context

    def login(self, user, password):
        self.user = user
        self.credentials = (user, password)
        # Ordering matters more than the call itself: a password must not go
        # out before the transport is encrypted.
        self.tls_before_login = self.tls

    def send_message(self, message):
        self.sent.append(message)


class _FakeSMTPSSL:
    """Matches the real `smtplib.SMTP_SSL` signature: timeout and context are
    keyword-only, and the handshake happens in the constructor."""

    instances = []

    def __init__(self, host, port, *, timeout=None, context=None):
        self.host = host
        self.port = port
        self.context = context
        self.sent = []
        self.credentials = None
        _FakeSMTPSSL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.credentials = (user, password)

    def send_message(self, message):
        self.sent.append(message)


class _RefusingSMTP:
    """Constructing this is the failure. Used where the point of the test is
    that no socket is opened at all."""

    def __init__(self, *a, **k):
        raise AssertionError("no connection should be attempted")


def _verifying(context):
    return (
        isinstance(context, ssl.SSLContext)
        and context.verify_mode is ssl.CERT_REQUIRED
        and context.check_hostname is True
    )


def test_email_format_subject_counts_critical():
    notifier = EmailNotifier("smtp", 587, "from@x", ["to@x"])
    subject, body = notifier.format([_alert(AlertSeverity.CRITICAL), _alert(AlertSeverity.WARNING)])
    assert "2 alert(s)" in subject
    assert "(1 critical)" in subject
    assert "NAT Gateway" in body


def test_email_send_uses_smtp(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    notifier = EmailNotifier("smtp.example", 587, "from@x", ["a@x", "b@x"])
    notifier.send([_alert(AlertSeverity.WARNING)])

    assert len(_FakeSMTP.instances) == 1
    server = _FakeSMTP.instances[0]
    assert server.tls is True
    assert len(server.sent) == 1
    assert server.sent[0]["To"] == "a@x, b@x"


# --- Email transport security --------------------------------------------


def test_email_starttls_uses_a_verifying_context(monkeypatch):
    """`starttls()` called bare builds ssl._create_stdlib_context(): CERT_NONE,
    check_hostname False. The chain is never validated and the name never
    matched, and login() then sends the password over it."""
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    EmailNotifier("smtp.example", 587, "from@x", ["to@x"]).send([_alert(AlertSeverity.WARNING)])

    server = _FakeSMTP.instances[0]
    assert _verifying(server.tls_context)


def test_email_ssl_mode_uses_smtps_and_never_starttls(monkeypatch):
    """Port 465 speaks TLS from the first byte. The old boolean could not
    express it, so a 465 relay was unreachable."""
    _FakeSMTPSSL.instances = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    monkeypatch.setattr(smtplib, "SMTP", _RefusingSMTP)

    EmailNotifier("smtp.example", 465, "from@x", ["to@x"], security="ssl").send(
        [_alert(AlertSeverity.WARNING)]
    )

    assert len(_FakeSMTPSSL.instances) == 1
    server = _FakeSMTPSSL.instances[0]
    assert _verifying(server.context)
    assert len(server.sent) == 1


@pytest.mark.parametrize("mode", ["tls", "TLS1.2", "", "STARTTLS ", "None"])
def test_unknown_security_mode_falls_back_to_verified_starttls(monkeypatch, mode):
    """The constructor is a way in that does not go through config. An
    unrecognised mode must not match no branch and land in the clear."""
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    notifier = EmailNotifier("h", 25, "a@x", ["b@x"], security=mode, username="u", password="p")
    assert notifier.security == "starttls"

    notifier.send([_alert(AlertSeverity.WARNING)])
    server = _FakeSMTP.instances[0]
    assert _verifying(server.tls_context)
    assert server.tls_before_login is True


def test_email_refuses_credentials_over_plaintext(monkeypatch):
    """The refusal has to happen before the socket, or the password is already
    on the wire by the time anything objects."""
    monkeypatch.setattr(smtplib, "SMTP", _RefusingSMTP)

    notifier = EmailNotifier("h", 25, "a@x", ["b@x"], security="none", username="u", password="p")
    with pytest.raises(ValueError) as excinfo:
        notifier.send([_alert(AlertSeverity.WARNING)])
    assert "SMTP_SECURITY" in str(excinfo.value)


def test_email_plaintext_without_credentials_still_sends(monkeypatch):
    """The loopback/sidecar relay case stays available — it just cannot
    authenticate."""
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    EmailNotifier("localhost", 25, "a@x", ["b@x"], security="none").send(
        [_alert(AlertSeverity.WARNING)]
    )

    server = _FakeSMTP.instances[0]
    assert server.tls is False
    assert server.tls_context is None
    assert len(server.sent) == 1


def test_email_bad_ca_bundle_raises_before_any_connection(monkeypatch):
    """Building the context lazily is what keeps invariant 4: constructed in
    __init__ it would escape notifiers_from_env() and break the scan. Built in
    send(), it is one channel's error — and it happens before DNS or TCP, so
    this test needs no network."""
    monkeypatch.setattr(smtplib, "SMTP", _RefusingSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _RefusingSMTP)

    notifier = EmailNotifier("relay.invalid", 587, "a@x", ["b@x"], ca_bundle="/nonexistent/ca.pem")

    with pytest.raises(FileNotFoundError):
        notifier.send([_alert(AlertSeverity.WARNING)])


def test_smtp_security_env_precedence_and_legacy_warning(monkeypatch, caplog):
    config._warn_legacy_smtp_tls_env.cache_clear()

    monkeypatch.delenv("SMTP_SECURITY", raising=False)
    monkeypatch.delenv("SMTP_USE_TLS", raising=False)
    assert config.smtp_security() == "starttls"

    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    assert config.smtp_security() == "ssl"  # canonical wins

    monkeypatch.setenv("SMTP_SECURITY", "bogus")
    assert config.smtp_security() == "starttls"
    assert config.smtp_security() != "none"  # a typo must not drop the transport

    # `configure_logging` stops the `app` tree propagating so nothing
    # double-logs through uvicorn's handlers, which also hides these records
    # from caplog's root handler. Let them through for this test only.
    monkeypatch.setattr(logging.getLogger("app"), "propagate", True)

    monkeypatch.delenv("SMTP_SECURITY")
    with caplog.at_level(logging.WARNING, logger="app.config"):
        for _ in range(5):
            assert config.smtp_security() == "none"
    warnings = [r for r in caplog.records if "SMTP_SECURITY" in r.getMessage()]
    assert len(warnings) == 1
    assert "SMTP_USE_TLS is deprecated" in warnings[0].getMessage()


def test_smtp_settings_keys_match_the_notifier_kwargs(monkeypatch):
    """`notifiers_from_env` splats this dict into EmailNotifier, so a key that
    drifts from a parameter is a TypeError raised outside the per-channel try."""
    import inspect

    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    settings = config.smtp_settings()

    assert "use_tls" not in settings
    assert settings["security"] == "starttls"
    assert settings["ca_bundle"] is None

    params = set(inspect.signature(EmailNotifier.__init__).parameters) - {"self", "recipients"}
    assert set(settings) <= params
