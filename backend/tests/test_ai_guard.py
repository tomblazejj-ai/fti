"""The AI guard (app/ai/guard.py): FTI's own caps on top of Groq Free, pauses after 429 and outages,
blocks after a rejected key or a payment demand, and state that survives a restart."""

import datetime as dt
import threading
import time

import pytest

from app.ai import groq, guard
from app.data import secrets, settings_store, store
from app.models import AiUsage

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
KEY = "gsk_" + "G4rd" * 10
M120, M20 = "openai/gpt-oss-120b", "openai/gpt-oss-20b"


@pytest.fixture()
def ai(monkeypatch):
    cfg = {"provider": "groq", "daily_request_cap": 80, "daily_token_cap": 100000, "per_minute_cap": 6}
    keys = {"GROQ_API_KEY": KEY}
    saved: dict = {}
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: cfg if path == "ai" else default)
    monkeypatch.setattr(secrets, "get", lambda name: keys.get(name, ""))
    monkeypatch.setattr(store, "cache_get", lambda key, session=None: (saved.get(key), None))
    monkeypatch.setattr(store, "cache_put", lambda key, payload, source="", session=None: saved.__setitem__(key, payload))
    guard.reset_memory()
    yield {"cfg": cfg, "keys": keys, "saved": saved}
    guard.reset_memory()


def _rows(session, n, at=NOW, tokens=0, ok=True):
    for _ in range(n):
        session.add(AiUsage(at=at, task="t", provider="groq", model=M120, input_tokens=tokens, output_tokens=0, ok=ok))
    session.commit()


def _err(kind, **kw):
    return groq.GroqError(kind, "x", **kw)


def test_ai_off_or_without_key_sends_nothing(db_session, ai):
    ai["cfg"]["provider"] = "none"
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M120, 100, now=NOW)
    assert e.value.code == "off"
    ai["cfg"]["provider"] = "groq"
    ai["keys"].clear()
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M120, 100, now=NOW)
    assert e.value.code == "no_key"


def test_daily_cap_of_80_counts_failed_requests_too(db_session, ai):
    _rows(db_session, 70)
    _rows(db_session, 10, ok=False)
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M120, 100, "high", now=NOW)
    assert e.value.code == "daily_cap" and e.value.until == dt.datetime(2026, 11, 3, tzinfo=UTC)


def test_yesterday_does_not_count(db_session, ai):
    _rows(db_session, 80, at=NOW - dt.timedelta(days=1))
    guard.check(db_session, M120, 100, now=NOW)


def test_settings_can_lower_the_cap_but_never_raise_it(ai):
    ai["cfg"]["daily_request_cap"] = 500
    assert guard.caps()["requests"] == 80
    ai["cfg"]["daily_request_cap"] = 10
    assert guard.caps()["requests"] == 10
    ai["cfg"]["daily_request_cap"] = "nesmysl"
    assert guard.caps()["requests"] == 80


def test_last_fifth_is_reserved_for_important_events(db_session, ai):
    _rows(db_session, 64, at=NOW - dt.timedelta(hours=1))
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M120, 100, "normal", now=NOW)
    assert e.value.code == "reserve"
    guard.check(db_session, M120, 100, "high", now=NOW)


def test_daily_token_cap(db_session, ai):
    _rows(db_session, 1, tokens=99_900, at=NOW - dt.timedelta(hours=2))
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M120, 200, now=NOW)
    assert e.value.code == "token_cap"


def test_per_minute_cap_and_groq_tokens_per_minute(db_session, ai):
    _rows(db_session, 6, at=NOW - dt.timedelta(seconds=30))
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M120, 100, now=NOW)
    assert e.value.code == "minute"
    guard.check(db_session, M120, 100, now=NOW + dt.timedelta(seconds=40))  # the burst left the window
    ok = groq.GroqReply(M120, {}, 1.0, 10, 10, {"tokens_per_minute": 8000})
    guard.record_success(db_session, "t", M120, ok, now=NOW + dt.timedelta(minutes=5))
    _rows(db_session, 1, tokens=6000, at=NOW + dt.timedelta(minutes=5, seconds=10))
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M120, 1500, now=NOW + dt.timedelta(minutes=5, seconds=20))  # 6 020 + 1 500 > 90 % of 8 000
    assert e.value.code == "minute"


def test_429_pauses_only_that_model_until_retry_after(db_session, ai):
    guard.record_failure(db_session, "t", M120, _err("rate_limit", retry_after=37), now=NOW)
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M120, 100, now=NOW + dt.timedelta(seconds=30))
    assert e.value.code == "model_paused" and e.value.until == NOW + dt.timedelta(seconds=37)
    guard.check(db_session, M20, 100, now=NOW + dt.timedelta(seconds=30))  # the other free model still works
    guard.check(db_session, M120, 100, now=NOW + dt.timedelta(seconds=38))


def test_429_with_daily_limit_gone_waits_for_the_daily_reset(db_session, ai):
    err = _err("rate_limit", retry_after=5, limits={"requests_left_today": 0, "requests_reset_s": 3600})
    guard.record_failure(db_session, "t", M120, err, now=NOW)
    with pytest.raises(guard.Blocked):
        guard.check(db_session, M120, 100, now=NOW + dt.timedelta(minutes=30))
    guard.check(db_session, M120, 100, now=NOW + dt.timedelta(minutes=61))


def test_outage_opens_the_breaker_1_5_15_60_minutes_and_success_closes_it(db_session, ai):
    t = NOW
    for minutes in (1, 5, 15, 60, 60):
        guard.record_failure(db_session, "t", M120, _err("unavailable"), now=t)
        with pytest.raises(guard.Blocked) as e:
            guard.check(db_session, M120, 100, "high", now=t + dt.timedelta(seconds=30))
        assert e.value.code == "paused" and e.value.until == t + dt.timedelta(minutes=minutes)
        t = t + dt.timedelta(minutes=minutes, seconds=1)
    guard.record_success(db_session, "t", M120, groq.GroqReply(M120, {}, 1.0), now=t)
    assert guard._load()["fail_streak"] == 0
    guard.check(db_session, M120, 100, "high", now=t + dt.timedelta(seconds=1))


def test_rejected_key_blocks_until_a_new_key_is_saved(db_session, ai):
    guard.record_failure(db_session, "t", M120, _err("auth"), now=NOW)
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M120, 100, now=NOW + dt.timedelta(days=2))
    assert e.value.code == "auth"
    ai["keys"]["GROQ_API_KEY"] = "gsk_" + "N3wK" * 10
    guard.check(db_session, M120, 100, now=NOW + dt.timedelta(days=2))


def test_payment_demand_stops_ai_until_the_user_resumes(db_session, ai):
    guard.record_failure(db_session, "t", M120, _err("billing"), now=NOW)
    with pytest.raises(guard.Blocked) as e:
        guard.check(db_session, M20, 100, "high", now=NOW + dt.timedelta(days=30))
    assert e.value.code == "billing"
    guard.resume()
    guard.check(db_session, M20, 100, now=NOW + dt.timedelta(days=30))


def test_pause_survives_a_restart(db_session, ai):
    guard.record_failure(db_session, "t", M120, _err("rate_limit", retry_after=600), now=NOW)
    guard.reset_memory()  # = the app restarted; the state comes back from the database
    with pytest.raises(guard.Blocked):
        guard.check(db_session, M120, 100, now=NOW + dt.timedelta(minutes=5))


def test_a_change_of_groq_limits_is_flagged(db_session, ai):
    guard.record_success(db_session, "t", M120, groq.GroqReply(M120, {}, 1.0, limits={"requests_per_day": 1000}), now=NOW)
    guard.record_success(db_session, "t", M120, groq.GroqReply(M120, {}, 1.0, limits={"requests_per_day": 500}), now=NOW)
    changed = guard.status(db_session, now=NOW)["limits_changed"]
    assert changed["old"] == 1000 and changed["new"] == 500


def test_identical_requests_at_the_same_time_run_one_after_another(ai):
    inside, overlap = [0], [False]

    def work():
        with guard.single_flight("same"):
            inside[0] += 1
            overlap[0] |= inside[0] > 1
            time.sleep(0.05)
            inside[0] -= 1

    threads = [threading.Thread(target=work) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlap[0] is False


def test_status_shows_usage_and_state_without_the_key(db_session, ai):
    _rows(db_session, 3, tokens=500)
    s = guard.status(db_session, now=NOW)
    assert s["state"] == "ready" and s["usage"]["requests"] == 3 and s["usage"]["tokens"] == 1500 and s["usage"]["cap"] == 80
    assert KEY not in str(s) and s["cost"].startswith("0 Kč")
