import smtplib
import ssl

import pytest

from app.models import Alert, AlertSeverity
from app.notifiers import EmailNotifier
from app.services import notify


def _alert(severity, rid):
    return Alert(
        id=f"r:{rid}",
        severity=severity,
        rule="x",
        title="t",
        message="m",
        resource_type="EC2 Instance",
        resource_id=rid,
        region="us-east-1",
        risk_level="HIGH",
    )


class _RecordingNotifier:
    def __init__(self, name="rec", fail=False):
        self.name = name
        self.fail = fail
        self.received = None

    def send(self, alerts):
        if self.fail:
            raise RuntimeError("channel down")
        self.received = alerts


def test_filters_below_min_severity():
    rec = _RecordingNotifier()
    alerts = [_alert(AlertSeverity.INFO, "a"), _alert(AlertSeverity.WARNING, "b")]
    result = notify(alerts, notifiers=[rec], min_severity="WARNING")

    assert result["sent_count"] == 1
    assert [a.resource_id for a in rec.received] == ["b"]
    assert result["channels"][0]["status"] == "sent"


def test_skips_when_no_alerts_at_threshold():
    rec = _RecordingNotifier()
    result = notify([_alert(AlertSeverity.INFO, "a")], notifiers=[rec], min_severity="CRITICAL")
    assert result["channels"][0]["status"] == "skipped"
    assert rec.received is None


def test_one_failing_channel_does_not_break_others():
    good = _RecordingNotifier(name="good")
    bad = _RecordingNotifier(name="bad", fail=True)
    alerts = [_alert(AlertSeverity.CRITICAL, "a")]
    result = notify(alerts, notifiers=[good, bad], min_severity="INFO")

    by_channel = {c["channel"]: c["status"] for c in result["channels"]}
    assert by_channel == {"good": "sent", "bad": "error"}


def test_no_notifiers_configured_is_noop():
    result = notify([_alert(AlertSeverity.CRITICAL, "a")], notifiers=[])
    assert result["channels"] == []
    assert result["sent_count"] == 0


def test_all_channels_failing_reports_nothing_delivered():
    """sent_count must reflect delivery, not intent.

    Every channel is down, so nothing reached anyone. Reporting the alert
    count here would tell a caller their alerts went out when none did.
    """
    down = [_RecordingNotifier(name="a", fail=True), _RecordingNotifier(name="b", fail=True)]
    alerts = [_alert(AlertSeverity.CRITICAL, "x"), _alert(AlertSeverity.CRITICAL, "y")]

    result = notify(alerts, notifiers=down, min_severity="INFO")

    assert result["sent_count"] == 0
    assert [c["status"] for c in result["channels"]] == ["error", "error"]


# --- Invariant 4: a transport failure is one channel's problem -----------


class _FailingSMTP:
    """A relay whose certificate no longer verifies."""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, *, context=None):
        raise ssl.SSLCertVerificationError("certificate verify failed: self signed certificate")

    def send_message(self, message):
        raise AssertionError("must not be reached")


@pytest.mark.parametrize(
    "notifier_kwargs",
    [{}, {"security": "none", "username": "u", "password": "p"}],
    ids=["certificate-verification", "credentials-over-plaintext"],
)
def test_email_transport_failure_is_reported_per_channel(monkeypatch, notifier_kwargs):
    """Both ways verified TLS can fail an operator — a relay whose certificate
    no longer verifies, and a config that would have sent a password in the
    clear — surface as a channel error, never as a broken scan."""
    monkeypatch.setattr(smtplib, "SMTP", _FailingSMTP)

    notifier = EmailNotifier("relay.internal", 587, "a@x", ["b@x"], **notifier_kwargs)
    result = notify(
        [_alert(AlertSeverity.CRITICAL, "a")], notifiers=[notifier], min_severity="INFO"
    )

    assert result["sent_count"] == 0
    channel = result["channels"][0]
    assert channel["channel"] == "email"
    assert channel["status"] == "error"
    assert channel["detail"]
