import smtplib

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
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        self.user = user

    def send_message(self, message):
        self.sent.append(message)


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
