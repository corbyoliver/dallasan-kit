"""The account-wide Anthropic usage-cap alert (vps-infra#38, #55).

The cap is account-wide: once it is hit, every app sharing the key fails
identically until it resets. This sends ONE high-visibility email the first time
any job on the box sees it, deduped through a state file shared by every app, and
fires again on its own when the reset date in the error changes.

It started life in inbox-to-boards/app/api_cap.py. Two lessons came with it:

- **It must never raise.** It is called from inside an `except` block, and an
  exception there replaces the one being handled. In inbox-to-boards, a broken
  `anthropic` install once made the alerter's own `import anthropic` raise and
  turned a clean fail-closed HOLD into a crash. Every line of `alert_if_api_cap_hit`
  is inside a try.
- **Coverage is a list kept by memory.** On 2026-08-21 a second model caller was
  added without the alerter, and eighteen requests hit the cap in silence (#55).
  `watch()` makes wrapping a call site one line, which is the cheap half of the
  fix; a conformance check is the other half.
"""
from __future__ import annotations

import json
import os
import re
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from . import mail

STATE_FILE = "/srv/.api-cap-alert-state.json"
NOTIFY_ENV = "/srv/notify.env"
_CAP_TEXT = "specified API usage limits"


def is_cap_error(exc: BaseException) -> bool:
    """True when `exc` is Anthropic's account usage-cap 400. Never raises."""
    try:
        import anthropic
    except Exception:
        return False
    try:
        return isinstance(exc, anthropic.BadRequestError) and _CAP_TEXT in str(exc)
    except Exception:
        return False


def alert_if_api_cap_hit(
    exc: BaseException,
    job_name: str,
    *,
    state_file: str = STATE_FILE,
    env_path: str = NOTIFY_ENV,
) -> bool:
    """Email once per outage if `exc` is the usage cap. Returns True if it sent.

    Never raises, whatever goes wrong inside it.
    """
    try:
        if not is_cap_error(exc):
            return False
        m = re.search(r"regain access on ([^.]+)", str(exc))
        reset_at = m.group(1).strip() if m else "unknown"

        try:
            with open(state_file) as f:
                state = json.load(f)
        except Exception:
            state = {}
        if state.get("reset_at") == reset_at:
            return False  # already alerted for this outage

        # Record BEFORE sending: a failed send must not make every later call in
        # the same outage retry and fail the same way.
        try:
            with open(state_file, "w") as f:
                json.dump({"reset_at": reset_at, "first_seen_by": job_name}, f)
            os.chmod(state_file, 0o600)
        except Exception:
            pass

        mail.send_alert(
            f"[VPS ALERT] ANTHROPIC API MONTHLY CAP HIT (resets {reset_at})",
            "Account-wide Anthropic API usage cap reached. EVERY project on "
            "this account sharing this key will fail identically until it "
            "resets. This is not a bug in the job below.\n\n"
            f"First detected by: {job_name}\n"
            f"Host: {socket.gethostname()}\n"
            f"Detected at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Resets: {reset_at}\n\n"
            f"Raw error: {exc}\n",
            env_path=env_path,
        )
        return True
    except Exception:
        return False


@contextmanager
def watch(job_name: str, **kwargs) -> Iterator[None]:
    """Wrap a model call: alert on a cap hit, then re-raise the ORIGINAL exception.

        with api_cap.watch("daily-digest summarize"):
            resp = client.messages.create(...)

    The caller's own error handling is unchanged; this only adds the alert.
    """
    try:
        yield
    except Exception as exc:
        alert_if_api_cap_hit(exc, job_name, **kwargs)
        raise
