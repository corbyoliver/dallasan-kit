"""api_cap: one alert per outage, never raises, and watch() re-raises the original."""
from __future__ import annotations

import json
import sys
import types

import pytest

from dallasan_kit import api_cap, mail

CAP_MSG = ("Error code: 400 - You have reached your specified API usage limits. "
           "You will regain access on 2026-11-01 at 00:00 UTC.")


class BadRequestError(Exception):
    pass


@pytest.fixture
def fake_anthropic(monkeypatch):
    mod = types.ModuleType("anthropic")
    mod.BadRequestError = BadRequestError
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return mod


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(mail, "send_alert", lambda subject, body, env_path: calls.append(subject))
    return calls


@pytest.fixture
def state(tmp_path):
    return str(tmp_path / "state.json")


def test_a_cap_error_alerts_once_per_reset_date(fake_anthropic, sent, state):
    exc = BadRequestError(CAP_MSG)
    assert api_cap.alert_if_api_cap_hit(exc, "job-a", state_file=state) is True
    assert api_cap.alert_if_api_cap_hit(exc, "job-b", state_file=state) is False
    assert len(sent) == 1 and "2026-11-01 at 00:00 UTC" in sent[0]
    assert json.load(open(state))["first_seen_by"] == "job-a"


def test_a_new_reset_date_alerts_again(fake_anthropic, sent, state):
    api_cap.alert_if_api_cap_hit(BadRequestError(CAP_MSG), "j", state_file=state)
    api_cap.alert_if_api_cap_hit(
        BadRequestError(CAP_MSG.replace("2026-11-01", "2026-12-01")), "j", state_file=state)
    assert len(sent) == 2


@pytest.mark.parametrize("exc", [
    BadRequestError("Error code: 400 - prompt is too long"),  # right type, wrong cause
    RuntimeError(CAP_MSG),                                     # right text, wrong type
])
def test_anything_else_is_ignored(fake_anthropic, sent, state, exc):
    assert api_cap.alert_if_api_cap_hit(exc, "j", state_file=state) is False
    assert sent == []


def test_a_broken_anthropic_install_does_not_raise(monkeypatch, sent, state):
    """The inbox-to-boards incident: the alerter's own import raised inside an except."""
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` raise
    assert api_cap.alert_if_api_cap_hit(RuntimeError("x"), "j", state_file=state) is False


def test_a_failed_send_does_not_raise_and_still_records_the_outage(
        fake_anthropic, monkeypatch, state):
    def boom(*a, **k):
        raise OSError("smtp down")
    monkeypatch.setattr(mail, "send_alert", boom)
    assert api_cap.alert_if_api_cap_hit(BadRequestError(CAP_MSG), "j", state_file=state) is False
    # Recorded before the send, so the rest of this outage does not retry-storm.
    assert json.load(open(state))["reset_at"] == "2026-11-01 at 00:00 UTC"


def test_an_unwritable_state_file_does_not_raise(fake_anthropic, sent, tmp_path):
    bad = str(tmp_path / "no-such-dir" / "state.json")
    assert api_cap.alert_if_api_cap_hit(BadRequestError(CAP_MSG), "j", state_file=bad) is True


def test_watch_reraises_the_original_exception(fake_anthropic, sent, state):
    exc = BadRequestError(CAP_MSG)
    with pytest.raises(BadRequestError) as info:
        with api_cap.watch("j", state_file=state):
            raise exc
    assert info.value is exc
    assert len(sent) == 1


def test_watch_reraises_even_when_the_alerter_breaks(monkeypatch, state):
    def boom(*a, **k):
        raise RuntimeError("alerter exploded")
    monkeypatch.setattr(api_cap, "is_cap_error", boom)
    with pytest.raises(ValueError, match="the real error"):
        with api_cap.watch("j", state_file=state):
            raise ValueError("the real error")


def test_watch_is_silent_on_success(sent, state):
    with api_cap.watch("j", state_file=state):
        pass
    assert sent == []
