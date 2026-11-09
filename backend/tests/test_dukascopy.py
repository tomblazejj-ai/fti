"""Dukascopy (app/connectors/dukascopy.py): real XAU/USD bid quotes, delayed ~1 h, exact tick times;
gentle — finished files cached forever, a few new files per call, a pause after the first failure."""

import datetime as dt
import lzma
import struct

import httpx
import pytest

from app.connectors import dukascopy
from app.data import bars, market_hours, prices, quality

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 3, 15, 30, tzinfo=UTC)  # Tuesday afternoon


def _minutes(day: dt.date, price=3870.0):
    recs = b"".join(struct.pack(">5i1f", m * 60, int(price * 1000), int((price + 0.1) * 1000), int((price - 0.5) * 1000),
                                int((price + 0.5) * 1000), 1.0) for m in range(0, 1440, 30))
    return lzma.compress(recs, format=lzma.FORMAT_ALONE)


def _ticks(price=3875.0):
    recs = b"".join(struct.pack(">3i2f", ms, int((price + 0.3) * 1000), int(price * 1000), 1.0, 1.0) for ms in (1000, 1_800_000, 3_599_000))
    return lzma.compress(recs, format=lzma.FORMAT_ALONE)


@pytest.fixture()
def feed(monkeypatch, tmp_path):
    monkeypatch.setattr(dukascopy, "bars", REAL_BARS)  # the autouse conftest stub replaced it; the real one here
    monkeypatch.setattr(dukascopy, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(dukascopy, "MIN_INTERVAL", 0.0)
    dukascopy.reset()
    state = {"seen": [], "fail": None, "no_ticks_from": 99}

    def handler(request):
        state["seen"].append(request.url.path)
        if state["fail"]:
            return httpx.Response(state["fail"], content=b"<html>503</html>")
        if request.url.path.endswith("BID_candles_min_1.bi5"):
            return httpx.Response(200, content=_minutes(NOW.date()))
        if int(request.url.path.rsplit("/", 1)[1][:2]) >= state["no_ticks_from"]:
            return httpx.Response(404)  # the source stopped delivering
        return httpx.Response(200, content=_ticks())

    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(handler))
    return state


REAL_BARS = dukascopy.bars


def test_bars_and_the_exact_last_tick(feed):
    h1, meta = dukascopy.h1_bars("XAUUSD", 2, now=NOW)
    assert h1 and meta["missing_files"] > 0  # only NEW_FILES_PER_CALL files per call — the rest comes later
    assert all(p.startswith("/datafeed/XAUUSD/2026/10/") for p in feed["seen"])  # 0-based month: November = 10
    for _ in range(10):
        h1, meta = dukascopy.h1_bars("XAUUSD", 2, now=NOW)
    t, bid, ask, precision = dukascopy.last_tick("XAUUSD")
    assert precision == "tick" and bid == pytest.approx(3875.0) and ask == pytest.approx(3875.3)
    assert dt.datetime.fromtimestamp(t, UTC) == dt.datetime(2026, 11, 3, 14, 59, 59, tzinfo=UTC)


def test_finished_files_are_never_downloaded_twice(feed):
    for _ in range(12):
        dukascopy.h1_bars("XAUUSD", 2, now=NOW)
    n = len(feed["seen"])
    dukascopy.h1_bars("XAUUSD", 2, now=NOW)
    assert len(feed["seen"]) == n  # all finished periods come from the disk cache now


def test_first_failure_pauses_the_feed(feed):
    feed["fail"] = 503
    with pytest.raises(dukascopy.DukascopyUnavailable):
        dukascopy.h1_bars("XAUUSD", 2, now=NOW)
    feed["fail"] = None
    n = len(feed["seen"])
    with pytest.raises(dukascopy.DukascopyUnavailable):
        dukascopy.h1_bars("XAUUSD", 2, now=NOW)
    assert len(feed["seen"]) == n == 1  # paused: no second request


def test_unverified_instruments_are_refused(feed):
    with pytest.raises(dukascopy.DukascopyUnavailable):
        dukascopy.h1_bars("GBPUSD", 2, now=NOW)  # EURUSD & co. were verified on 8. 11. 2026, GBPUSD not yet
    with pytest.raises(dukascopy.DukascopyUnavailable):
        dukascopy.month_hours("GBPUSD", 2026, 9, now=NOW)
    assert feed["seen"] == []
    assert {"EURUSD", "USDJPY", "USA500IDXUSD", "DOLLARIDXUSD", "VOLIDXUSD"} <= set(dukascopy.POINT)


def test_xauusd_quote_is_delayed_with_exact_time_never_live(feed, monkeypatch):
    for _ in range(12):
        dukascopy.h1_bars("XAUUSD", 14, now=NOW)
    monkeypatch.setattr(market_hours, "state", lambda inst, now, crypto_status_fn=None: {"state": market_hours.OPEN, "label": "trh otevřen"})
    bs = bars.get_bars("XAUUSD", "H1", now=NOW, store=False)
    assert bs.ok and bs.provider == "dukascopy" and bs.proxy is False
    assert bs.quality["status"] == quality.DELAYED and "zpožděním" in bs.quality["text"]
    lq = bs.last_quote
    assert lq["time_verified"] is True and lq["tradable_now"] is False and lq["price"] == pytest.approx(3875.0)
    q = prices.quote("XAUUSD", now=NOW)
    assert q["provider"] == "dukascopy" and "PAXG" not in q["source"]


def test_open_market_without_new_quotes_is_stale(feed, monkeypatch):
    feed["no_ticks_from"] = 15
    for _ in range(12):
        dukascopy.h1_bars("XAUUSD", 14, now=NOW)
    monkeypatch.setattr(market_hours, "state", lambda inst, now, crypto_status_fn=None: {"state": market_hours.OPEN, "label": "trh otevřen"})
    bs = bars.get_bars("XAUUSD", "H1", now=NOW + dt.timedelta(hours=5), store=False)
    assert bs.quality["status"] == quality.STALE


def test_m15_bars_from_minutes_and_no_fake_volume(feed):
    for _ in range(6):
        m15, meta = dukascopy.bars("XAUUSD", 900, 2, now=NOW)
    assert m15 and all(b[0] % 900 == 0 for b in m15) and all(b[5] == 0.0 for b in m15)
    assert "OTC" in meta["volume_note"]


def test_growing_pause_after_consecutive_failures(feed, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(dukascopy.time, "monotonic", lambda: clock[0])
    feed["fail"] = 503
    pauses = []
    for _ in range(4):
        with pytest.raises(dukascopy.DukascopyUnavailable) as e:
            dukascopy.bars("XAUUSD", 3600, 2, now=NOW)
        pauses.append(e.value.args[0])
        clock[0] += 3600  # wait out the pause
    assert [p.split("za ")[1] for p in pauses] == ["2 min.", "5 min.", "15 min.", "30 min."]


def test_completeness_is_measured_and_gaps_are_never_filled(feed):
    day = dt.date(2026, 11, 2)  # a Monday
    minutes = [(t, 1.0, 1.0, 1.0, 1.0) for t in sorted(dukascopy.expected_minutes("XAUUSD", day))]
    gap = minutes[100:105]
    kept = minutes[:100] + minutes[105:]
    cov = dukascopy.coverage("XAUUSD", day, kept)
    assert cov["missing"] == 5 and cov["gaps"] == [(dt.datetime.fromtimestamp(gap[0][0], UTC).isoformat(), 5)]
    assert cov["present"] == cov["expected"] - 5
    assert len(dukascopy._aggregate(kept, 60)) == len(kept)  # nothing invented for the gap


def test_download_success_is_counted(feed):
    for _ in range(3):
        dukascopy.bars("XAUUSD", 3600, 2, now=NOW)
    st = dukascopy.stats()
    assert st["requests"] > 0 and st["errors"] == 0 and st["success_pct"] == 100.0 and st["from_cache"] > 0
