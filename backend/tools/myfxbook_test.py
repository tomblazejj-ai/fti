"""One-off measurement of the Myfxbook calendar RSS against Forex Factory (user's request: Tue 10. 11. 2026, 13:30–16:00
Prague time, around the US CPI at 14:30). Myfxbook is NOT an active backup — this only measures whether it could be.

    pythonw tools/myfxbook_test.py              run until END (started by a one-time Windows task at 13:25)
    python  tools/myfxbook_test.py --once       one poll + report, to check the parser (no conclusions from it)

Reads only:  https://www.myfxbook.com/rss/forex-economic-calendar-events (public RSS, no account, no e-mail sent),
             backend/cache/ff_events.json (FTI's Forex Factory copy) and FTI's database READ-ONLY (official actuals).
Writes only: backend/cache/myfxbook-test-<date>/ — raw XML of every poll, polls.jsonl, report.json, report.txt.
Polls: every 5 minutes, every minute 14:25–14:45 (the CPI release) — about 45 requests in 2.5 hours.
Measured: events, time, currency, impact, previous/consensus/actual, when the actual appears (delay after release),
duplicates inside the feed, and a match with Forex Factory (same currency, time ±5 min, similar title).
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

BACKEND = Path(__file__).resolve().parents[1]
URL = "https://www.myfxbook.com/rss/forex-economic-calendar-events"
PRAGUE = ZoneInfo("Europe/Prague")
DAY = dt.date(2026, 11, 10)
START = dt.datetime(2026, 11, 10, 13, 30, tzinfo=PRAGUE)
END = dt.datetime(2026, 11, 10, 16, 0, tzinfo=PRAGUE)
DENSE = (dt.datetime(2026, 11, 10, 14, 25, tzinfo=PRAGUE), dt.datetime(2026, 11, 10, 14, 45, tzinfo=PRAGUE))
OUT = BACKEND / "cache" / f"myfxbook-test-{DAY.isoformat()}"
UA = "FTI/1.0 (personal analysis)"
COUNTRY_CCY = {"united-states": "USD", "euro-area": "EUR", "eurozone": "EUR", "germany": "EUR", "france": "EUR", "italy": "EUR",
               "spain": "EUR", "united-kingdom": "GBP", "japan": "JPY", "canada": "CAD", "australia": "AUD",
               "new-zealand": "NZD", "switzerland": "CHF", "china": "CNY"}
IMPACT = {"high": 3, "medium": 2, "low": 1, "no": 0}


def parse(xml: str) -> list[dict]:
    items = []
    for raw in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def tag(name):
            m = re.search(rf"<{name}>(.*?)</{name}>", raw, re.S)
            return html.unescape(m.group(1).strip()) if m else None
        desc = html.unescape(tag("description") or "")
        cells = [re.sub(r"<[^>]+>", " ", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", desc, re.S)]
        imp = re.search(r"sprite-(high|medium|low|no)-impact", desc)
        link = tag("link") or ""
        country = (re.search(r"forex-economic-calendar/([^/]+)/", link) or [None, None])[1]
        try:
            when = dt.datetime.strptime(tag("pubDate") or "", "%a, %d %b %Y %H:%M %Z").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            when = None
        vals = [re.sub(r"\s+", " ", c) for c in cells]
        items.append({"title": tag("title"), "link": link, "country": country, "currency": COUNTRY_CCY.get(country or ""),
                      "time_utc": when.isoformat() if when else None, "impact": IMPACT.get(imp.group(1)) if imp else None,
                      "time_left": vals[0] if len(vals) > 0 else None, "previous": vals[2] or None if len(vals) > 2 else None,
                      "consensus": vals[3] or None if len(vals) > 3 else None, "actual": vals[4] or None if len(vals) > 4 else None})
    return items


def poll(client: httpx.Client) -> dict:
    t0 = time.monotonic()
    sent = dt.datetime.now(dt.timezone.utc)
    try:
        r = client.get(URL)
        status, text = r.status_code, r.text
    except httpx.HTTPError as exc:
        status, text = None, f"{type(exc).__name__}"
    rec = {"at": sent.isoformat(), "status": status, "ms": round((time.monotonic() - t0) * 1000)}
    if status == 200:
        (OUT / f"poll-{sent.strftime('%H%M%S')}.xml").write_text(text, encoding="utf-8")
        rec["items"] = parse(text)
    else:
        rec["error"] = text[:200]
    with (OUT / "polls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (title or "").lower()) if w not in {"m", "y", "q", "s", "the", "of", "and", "yoy", "mom"}}


def report() -> dict:
    polls = [json.loads(x) for x in (OUT / "polls.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    ok = [p for p in polls if p.get("status") == 200]
    seen: dict[tuple, dict] = {}
    first_actual: dict[tuple, str] = {}
    dup = []
    for p in ok:
        keys = [(i["title"], i["time_utc"]) for i in p["items"]]
        dup += [k for k in set(keys) if keys.count(k) > 1]
        for i in p["items"]:
            k = (i["title"], i["time_utc"])
            seen[k] = i
            if i.get("actual") and k not in first_actual:
                first_actual[k] = p["at"]
    day_items = [i for i in seen.values() if i["time_utc"] and dt.datetime.fromisoformat(i["time_utc"]).astimezone(PRAGUE).date() == DAY]
    ff_all = json.loads((BACKEND / "cache" / "ff_events.json").read_text(encoding="utf-8"))["events"]
    ff = [e for e in ff_all if dt.datetime.fromisoformat(e["datetime"]).astimezone(PRAGUE).date() == DAY]
    matched, only_mfb = [], []
    used = set()
    for i in day_items:
        t = dt.datetime.fromisoformat(i["time_utc"])
        best = None
        for j, e in enumerate(ff):
            if j in used or e["currency"] != i["currency"]:
                continue
            gap = abs((dt.datetime.fromisoformat(e["datetime"]) - t).total_seconds())
            score = len(_words(i["title"]) & _words(e["title_en"]))
            if gap <= 300 and score >= 1 and (best is None or score > best[1]):
                best = (j, score, gap)
        if best:
            used.add(best[0])
            e = ff[best[0]]
            k = (i["title"], i["time_utc"])
            delay = None
            if k in first_actual:
                delay = round((dt.datetime.fromisoformat(first_actual[k]) - dt.datetime.fromisoformat(e["datetime"])).total_seconds() / 60, 1)
            matched.append({"myfxbook": i["title"], "ff": e["title_en"], "currency": i["currency"], "time_mfb": i["time_utc"],
                            "time_ff": e["datetime"], "time_gap_s": best[2], "impact_mfb": i["impact"], "impact_ff": e["impact"],
                            "previous_mfb": i["previous"], "previous_ff": e.get("previous"), "consensus_mfb": i["consensus"],
                            "forecast_ff": e.get("forecast"), "actual_mfb": i["actual"], "actual_first_seen": first_actual.get(k),
                            "actual_delay_min": delay})
        else:
            only_mfb.append(i)
    only_ff = [e for j, e in enumerate(ff) if j not in used]
    official = {}
    try:  # FTI's official actuals (ALFRED/BLS), the live DB opened READ-ONLY
        db = sqlite3.connect(f"file:{(BACKEND / 'fti.db').as_posix()}?mode=ro", uri=True)
        for k, p in db.execute("select key, payload from series_cache where key like ?", (f"actual:%:{DAY.isoformat()}%",)):
            rec = json.loads(p)
            official[k.split(":")[1]] = {"actual": rec.get("actual"), "status": (rec.get("verification") or {}).get("status")}
    except sqlite3.Error as exc:
        official = {"error": str(exc)}
    for m in matched:
        o = official.get(m["ff"]) if isinstance(official, dict) else None
        if o:
            m["actual_official"] = o["actual"]
            m["actual_official_status"] = o["status"]
            m["actual_agrees"] = (re.sub(r"[^\d.\-]", "", m["actual_mfb"] or "") == re.sub(r"[^\d.\-]", "", o["actual"] or "")) if m["actual_mfb"] else None
    out = {"day": DAY.isoformat(), "window_prague": [START.isoformat(), END.isoformat()], "polls": len(polls), "polls_ok": len(ok),
           "failed": [{"at": p["at"], "status": p.get("status"), "error": p.get("error")} for p in polls if p.get("status") != 200],
           "items_in_feed_last_poll": len(ok[-1]["items"]) if ok else 0, "events_on_day_mfb": len(day_items), "events_on_day_ff": len(ff),
           "matched": matched, "only_myfxbook": only_mfb, "only_ff": [{"title": e["title_en"], "currency": e["currency"],
                                                                       "time": e["datetime"], "impact": e["impact"]} for e in only_ff],
           "duplicates_in_feed": sorted({f"{a} @ {b}" for a, b in dup}), "official_actuals": official}
    (OUT / "report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"Myfxbook RSS × Forex Factory — {DAY:%d. %m. %Y}, {START:%H:%M}–{END:%H:%M} (Praha). Myfxbook NENÍ aktivní záloha.",
             f"Dotazů {len(polls)}, úspěšných {len(ok)}. Událostí dne: Myfxbook {len(day_items)}, Forex Factory {len(ff)}, "
             f"spárováno {len(matched)}, jen Myfxbook {len(only_mfb)}, jen FF {len(only_ff)}, duplicit ve feedu {len(out['duplicates_in_feed'])}."]
    for m in matched:
        if m["impact_ff"] >= 2 or m["actual_mfb"]:
            lines.append(f"- {m['ff']} ({m['currency']}): čas Δ {m['time_gap_s']:.0f} s, dopad MFB {m['impact_mfb']} / FF {m['impact_ff']}, "
                         f"actual MFB {m['actual_mfb']} (za {m['actual_delay_min']} min) / oficiálně {m.get('actual_official')} "
                         f"({m.get('actual_official_status')}), prognóza FF {m['forecast_ff']} / MFB {m['consensus_mfb']}")
    (OUT / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    global OUT
    if "--once" in argv:  # a parser check never mixes into the real measurement's folder
        OUT = BACKEND / "cache" / "myfxbook-test-zkouska"
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30.0, headers={"User-Agent": UA}, follow_redirects=True) as client:
        if "--once" in argv:
            poll(client)
        else:
            while dt.datetime.now(PRAGUE) < END:
                now = dt.datetime.now(PRAGUE)
                if now >= START - dt.timedelta(minutes=5):
                    poll(client)
                step = 60 if DENSE[0] <= now < DENSE[1] else 300
                time.sleep(step)
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
