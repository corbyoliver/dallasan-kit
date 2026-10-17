"""mail.send: verified STARTTLS, a timeout, and loud failure (vps-infra#69, #72)."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import pytest

from dallasan_kit import mail


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.context = "NOT CALLED"
        self.logged_in = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.context = context

    def login(self, user, pw):
        self.logged_in = (user, pw)

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP.instances


def _msg():
    m = EmailMessage()
    m["Subject"] = "s"
    m.set_content("b")
    return m


def test_starttls_verifies_the_certificate_and_hostname(fake_smtp):
    mail.send(_msg(), host="smtp.example.com", port=587, username="u", password="p")
    ctx = fake_smtp[0].context
    # A bare starttls() passes context=None, which the stdlib treats as CERT_NONE.
    assert isinstance(ctx, ssl.SSLContext), "starttls() was called without a context"
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_a_timeout_is_always_set(fake_smtp):
    mail.send(_msg(), host="h", port=587, username="u", password="p")
    assert fake_smtp[0].timeout == mail.DEFAULT_TIMEOUT_S


def test_it_logs_in_and_sends(fake_smtp):
    m = _msg()
    mail.send(m, host="h", port="587", username="u", password="p")
    s = fake_smtp[0]
    assert (s.host, s.port) == ("h", 587)
    assert s.logged_in == ("u", "p")
    assert s.sent == [m]


@pytest.mark.parametrize("field", ["host", "username", "password"])
def test_an_empty_setting_is_refused_not_sent(fake_smtp, field):
    kw = dict(host="h", port=587, username="u", password="p")
    kw[field] = ""
    with pytest.raises(ValueError, match=field):
        mail.send(_msg(), **kw)
    assert fake_smtp == [], "nothing may be attempted with an empty setting"


def test_a_send_failure_raises(monkeypatch, fake_smtp):
    def boom(self, msg):
        raise smtplib.SMTPException("relay refused")
    monkeypatch.setattr(FakeSMTP, "send_message", boom)
    with pytest.raises(smtplib.SMTPException):
        mail.send(_msg(), host="h", port=587, username="u", password="p")


def test_send_alert_uses_notify_env(tmp_path, fake_smtp):
    env = tmp_path / "notify.env"
    env.write_text("# comment\nALERT_FROM=a@x.com\nALERT_TO=b@x.com\nALERT_SMTP_PASSWORD=pw\n")
    mail.send_alert("subj", "body", env_path=str(env))
    s = fake_smtp[0]
    assert (s.host, s.port) == ("smtp.gmail.com", 587)
    assert s.logged_in == ("a@x.com", "pw")
    assert s.sent[0]["To"] == "b@x.com"
    assert s.sent[0]["Subject"] == "subj"


def test_send_alert_raises_when_notify_env_is_missing(tmp_path, fake_smtp):
    with pytest.raises(FileNotFoundError):
        mail.send_alert("s", "b", env_path=str(tmp_path / "nope.env"))
