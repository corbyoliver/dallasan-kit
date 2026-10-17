"""Send one email over SMTP with verified STARTTLS and a timeout.

Every app on the box used to open its own `smtplib.SMTP(...)` and call
`starttls()` with no context. With no context the stdlib does NOT verify the
server certificate (vps-infra#69, #72), so the Gmail app password went out over a
connection anyone between Hetzner and Google could have sat in the middle of. And
with no `timeout`, a stalled server hangs the job until notify-fail's 2h kill.

Both were one-line fixes, needed in eleven places, in nine repos. This module is
the one place they live now.

It RAISES on failure. Whether a failed send is fatal is the caller's decision, and
a sender that swallows its own errors is how an alert that never arrived looks
exactly like an alert that was never needed. Callers that must be best-effort
(the cap alerter) catch around it explicitly.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

DEFAULT_TIMEOUT_S = 30


def tls_context() -> ssl.SSLContext:
    """A context that verifies the certificate chain AND the hostname."""
    return ssl.create_default_context()


def send(
    msg: EmailMessage,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> None:
    """Send `msg`. Raises on any failure, including a certificate that does not verify.

    Missing settings are the caller's to refuse at startup; an empty host, user or
    password is rejected here too, so an unset variable cannot quietly become an
    unauthenticated or nowhere-bound send.
    """
    for name, value in (("host", host), ("username", username), ("password", password)):
        if not value:
            raise ValueError(f"mail.send: {name} is empty")
    with smtplib.SMTP(host, int(port), timeout=timeout) as s:
        s.starttls(context=tls_context())
        s.login(username, password)
        s.send_message(msg)


def load_env_file(path: str) -> dict[str, str]:
    """Parse a KEY=VALUE file such as /srv/notify.env. Raises if it is missing."""
    env: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def send_alert(subject: str, body: str, *, env_path: str = "/srv/notify.env") -> None:
    """Send an operator alert using the box's shared notify.env credentials.

    Uses the same keys notify-fail.py does: ALERT_FROM, ALERT_TO,
    ALERT_SMTP_PASSWORD, and optionally ALERT_SMTP_HOST / ALERT_SMTP_PORT.
    Raises on failure, like `send`.
    """
    env = load_env_file(env_path)
    msg = EmailMessage()
    msg["From"] = env["ALERT_FROM"]
    msg["To"] = env["ALERT_TO"]
    msg["Subject"] = subject
    msg.set_content(body)
    send(
        msg,
        host=env.get("ALERT_SMTP_HOST", "smtp.gmail.com"),
        port=int(env.get("ALERT_SMTP_PORT", 587)),
        username=env["ALERT_FROM"],
        password=env["ALERT_SMTP_PASSWORD"],
    )
