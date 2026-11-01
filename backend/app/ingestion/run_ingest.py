"""Orchestrates one ingestion cycle for XAUUSD: fetch -> classify -> store -> score -> diff.

Kept intentionally sequential and readable over "efficient" — this runs at
most every few minutes (RSS/GDELT) or once a week (CFTC) / day (FRED),
performance is not the constraint here.

One cycle fetches all raw data ONCE, then computes a separate ScoreSnapshot
for every horizon in xauusd.SUPPORTED_HORIZONS from that same data (see
scoring/xauusd.py module docstring for why the horizons differ) — no
redundant network calls per horizon.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.connectors import cot, fred, gdelt, portals, rss_news
from app.connectors.cot import CotUnavailableError
from app.connectors.fred import FredUnavailableError
from app.ingestion.transforms import InsufficientHistoryError, SeriesSpec, derive
from app.instruments import PRIMARY_HORIZON
from app.market import markets, momentum, tra
from app.market import service as market_service
from app.market.service import compute_market_analysis
from app.models import (
    AnalysisSnapshot,
    CentralBankEvent,  # noqa: F401 — reserved for Modul 2 calendar wiring
    Instrument,
    MacroObservation,
    MacroSeries,
    NewsItem,
    ScoreHistoryEntry,
    ScoreSnapshot,
    TraScorePoint,
)
from app.news.classifier import CLASSIFIER_VERSION, classify, dedup_hash
from app.news import translate
from app.news.dedupe import find_duplicate
from app.scoring.base import cz, cz_date
from app.scoring.xauusd import (
    BIAS_CZ,
    PILLAR_DISPLAY,
    PILLAR_WEIGHTS,
    SUPPORTED_HORIZONS,
    MacroPoint,
    NewsDataPoint,
    NewsSignal,
    XauInputs,
    _next_fomc_date,
    compute_xauusd_score,
)

logger = logging.getLogger(__name__)

# One ingestion cycle at a time: the background scheduler and a manual
# "Refresh" click must not interleave writes on the same SQLite file.
_cycle_lock = threading.Lock()
_current_warnings: list[str] = []
LAST_CYCLE: dict = {"started_at": None, "finished_at": None, "warnings": [], "running": False, "error": None}
LAST_MARKET_REFRESH: dict = {"at": None, "error": None}
# Macro readings of the last full cycle — the 5-minute market refresh reuses them
_LAST_MACRO: dict = {}
KEEP_ANALYSIS_SNAPSHOTS = 30  # the UI only reads the newest; 5-minute refreshes would otherwise pile up


def _warn(message: str) -> None:
    logger.warning(message)
    _current_warnings.append(message)

FRED_SERIES: list[SeriesSpec] = [
    # daily market series: compare with ~1 month (20 trading days) earlier;
    # Fed funds with ~3 months (90 daily obs) so the last decision is in view
    SeriesSpec("real_yield_10y", "DFII10", "D", "level", "%", lookback=20),
    SeriesSpec("usd_index", "DTWEXBGS", "D", "level", "index", lookback=20),
    SeriesSpec("fed_funds_target", "DFEDTARU", "D", "level", "%", lookback=90),
    SeriesSpec("core_cpi", "CPILFESL", "M", "yoy", "% YoY"),
    SeriesSpec("core_pce", "PCEPILFE", "M", "yoy", "% YoY"),
    SeriesSpec("gdp", "GDPC1", "Q", "qoq_ann", "% q/q ann."),
    SeriesSpec("unemployment", "UNRATE", "M", "level", "%", lookback=1),
    SeriesSpec("nfp", "PAYEMS", "M", "mom_diff", "k jobs m/m"),
]
FRED_SERIES_KEYS = [s.key for s in FRED_SERIES]

COT_SOURCE = "cftc"
COT_EXTERNAL_ID = "GOLD_COMEX_NONCOMM_NET"

# Wide enough to feed the slowest-decaying horizon (1-3m); decay itself
# (see scoring/xauusd.py) is what makes old items matter less, not this cutoff.
NEWS_LOOKBACK_DAYS = 60
PILLAR_DELTA_EPSILON = 1.0  # points change smaller than this isn't worth reporting as "what changed"


def ensure_xauusd_instrument(session: Session) -> Instrument:
    instrument = session.scalar(select(Instrument).where(Instrument.code == "XAUUSD"))
    if instrument is None:
        instrument = Instrument(code="XAUUSD", name="Gold Spot", pillar_config=PILLAR_WEIGHTS, active=True)
        session.add(instrument)
        session.commit()
        session.refresh(instrument)
    return instrument


def _ensure_series(session: Session, source: str, external_id: str, label: str) -> MacroSeries:
    series = session.scalar(
        select(MacroSeries).where(MacroSeries.source == source, MacroSeries.external_id == external_id)
    )
    if series is None:
        series = MacroSeries(source=source, external_id=external_id, label=label, unit="", frequency="")
        session.add(series)
        session.commit()
        session.refresh(series)
    return series


def _upsert_observation(
    session: Session, series: MacroSeries, period: str, actual: float | None, previous: float | None, source_url: str
) -> MacroObservation:
    existing = session.scalar(
        select(MacroObservation).where(MacroObservation.series_id == series.id, MacroObservation.period == period)
    )
    if existing is not None:
        return existing
    surprise = (actual - previous) if (actual is not None and previous is not None) else None
    obs = MacroObservation(
        series_id=series.id,
        period=period,
        actual=actual,
        previous=previous,
        consensus=None,  # see docs/DECISIONS.md — no free legal consensus source
        surprise=surprise,
        source_url=source_url,
    )
    session.add(obs)
    series.last_synced_at = dt.datetime.now(dt.timezone.utc)
    session.commit()
    session.refresh(obs)
    return obs


def sync_fred_series(session: Session) -> dict[str, MacroPoint]:
    """Fetch, transform (see transforms.py) and upsert every configured FRED series.

    A failure on one series marks only that series unavailable — the rest
    of the cycle continues. Nothing is ever filled in with a guess.
    """
    points: dict[str, MacroPoint] = {}
    for spec in FRED_SERIES:
        series = _ensure_series(session, "fred", spec.external_id, spec.key)
        series.unit = spec.unit
        series.frequency = spec.frequency
        try:
            observations = fred.fetch_observations(spec.external_id)
            derived = derive(observations, spec)
        except (FredUnavailableError, InsufficientHistoryError) as exc:
            _warn(f"FRED {spec.external_id} nedostupné: {exc}")
            points[spec.key] = MacroPoint(actual=None, previous=None, frequency=spec.frequency)
            continue
        obs = _upsert_observation(
            session, series, derived.period, derived.actual, derived.previous,
            f"https://fred.stlouisfed.org/series/{spec.external_id}",
        )
        points[spec.key] = MacroPoint(
            actual=derived.actual,
            previous=derived.previous,
            period=derived.period,
            previous_period=derived.previous_period,
            frequency=spec.frequency,
            observation_id=obs.id,
        )
    return points


def sync_cftc_positioning(session: Session) -> MacroPoint:
    """Fetch the latest two weekly CFTC COT gold reports and upsert them.

    Returns a neutral, explicitly-unavailable MacroPoint (actual=None) on
    any failure — the positioning pillar then reports "unavailable" rather
    than a fabricated number (see app/scoring/xauusd.py _pillar_positioning).
    """
    series = _ensure_series(session, COT_SOURCE, COT_EXTERNAL_ID, "CFTC COMEX Gold net non-commercial long")
    try:
        reports = cot.fetch_latest_two_gold_reports()
    except CotUnavailableError as exc:
        _warn(f"CFTC COT nedostupné: {exc}")
        return MacroPoint(actual=None, previous=None)

    previous_report, latest_report = reports[-2], reports[-1]
    obs = _upsert_observation(
        session, series, latest_report["date"],
        latest_report["net_noncommercial_long"], previous_report["net_noncommercial_long"],
        "https://publicreporting.cftc.gov/Market-Reports/Commitments-of-Traders",
    )
    return MacroPoint(
        actual=latest_report["net_noncommercial_long"],
        previous=previous_report["net_noncommercial_long"],
        period=latest_report["date"],
        previous_period=previous_report["date"],
        frequency="W",
        observation_id=obs.id,
    )


def _source_cz(source: str) -> str:
    return f"{source[6:]} přes GDELT" if source.startswith("gdelt:") else source


def _coarse_sentiment_label(sentiment_scores: dict[str, float]) -> str:
    if any(v > 0.2 for v in sentiment_scores.values()):
        return "bullish"
    if any(v < -0.2 for v in sentiment_scores.values()):
        return "bearish"
    return "neutral"


def _store_news_entries(session: Session, entries: list) -> None:
    # The session has autoflush off, so an item added earlier in THIS batch is
    # invisible to the DB lookups below. GDELT returns the same article for
    # several queries (seen live 2026-09-29): without the in-batch set the
    # second copy hit the UNIQUE constraint and failed the whole cycle.
    seen_in_batch: set[str] = set()
    for entry in entries:
        h = dedup_hash(entry.source, entry.title, entry.url)
        if h in seen_in_batch or session.scalar(select(NewsItem).where(NewsItem.dedup_hash == h)) is not None:
            continue  # byte-identical — already stored
        seen_in_batch.add(h)

        classified = classify(entry.title, entry.snippet)
        duplicate_of = find_duplicate(
            session, entry.title, entry.published_at, classified.factor_tags, classified.instrument_tags
        )

        session.add(
            NewsItem(
                source=entry.source,
                dedup_hash=h,
                title=entry.title,
                url=entry.url,
                published_at=entry.published_at,
                raw_snippet=entry.snippet,
                instrument_tags=classified.instrument_tags,
                relevance_score=classified.relevance_score,
                sentiment=_coarse_sentiment_label(classified.sentiment_by_tag),
                sentiment_scores=classified.sentiment_by_tag,
                factor_tags=classified.factor_tags,
                duplicate_of_id=duplicate_of.id if duplicate_of else None,
                classifier_version=CLASSIFIER_VERSION,
                language=getattr(entry, "language", "en"),
                title_cs=entry.title if getattr(entry, "language", "en") == "cs" else None,
            )
        )
        # flush so find_duplicate() sees this item when a near-duplicate of
        # it arrives later in the same batch
        session.flush()
    session.commit()


def reclassify_stale_news(session: Session) -> int:
    """Re-run the current classifier over items tagged by an older version,
    so a lexicon fix also corrects news that is already stored."""
    stale = list(session.scalars(select(NewsItem).where(NewsItem.classifier_version < CLASSIFIER_VERSION)))
    for item in stale:
        classified = classify(item.title, item.raw_snippet)
        item.instrument_tags = classified.instrument_tags
        item.factor_tags = classified.factor_tags
        item.sentiment_scores = classified.sentiment_by_tag
        item.sentiment = _coarse_sentiment_label(classified.sentiment_by_tag)
        item.relevance_score = classified.relevance_score
        item.classifier_version = CLASSIFIER_VERSION
    session.commit()
    return len(stale)


def sync_news(session: Session) -> list[str]:
    """Pull RSS + GDELT, classify, dedup, store. Returns a list of warnings
    (e.g. GDELT rate-limited) — never raises, ingestion continues either way.
    """
    warnings: list[str] = []

    try:
        rss_entries = rss_news.fetch_all_feeds()
    except Exception as exc:  # noqa: BLE001 — external feed, must not kill the cycle
        warnings.append(f"RSS nedostupné: {exc}")
        rss_entries = []

    gdelt_entries, gdelt_errors = gdelt.fetch_all_queries()
    warnings.extend(gdelt_errors)

    portal_entries, portal_errors = portals.fetch_all()
    warnings.extend(portal_errors)
    _last_portal_sync["at"] = dt.datetime.now(dt.timezone.utc)

    reclassify_stale_news(session)
    _store_news_entries(session, portal_entries)  # portals first: the Czech original wins over a GDELT copy
    _store_news_entries(session, rss_entries)
    _store_news_entries(session, gdelt_entries)
    translate_pending_headlines(session)
    return warnings


NEWS_REFRESH_MINUTES = 10
_last_portal_sync: dict = {"at": None}


def sync_portals(session: Session) -> list[str]:
    """The news portals only (fxstreet.cz, FXStreet, Investing.com, CNBC,
    MarketWatch) — run between full cycles so headlines are at most ~10
    minutes old. Central-bank RSS and GDELT stay in the 30-minute cycle."""
    entries, errors = portals.fetch_all()
    _store_news_entries(session, entries)
    translate_pending_headlines(session, limit=15)
    _last_portal_sync["at"] = dt.datetime.now(dt.timezone.utc)
    return errors


TRANSLATE_PER_CYCLE = 60
TRANSLATE_LOOKBACK_DAYS = 7


def translate_pending_headlines(session: Session, limit: int = TRANSLATE_PER_CYCLE) -> int:
    """Machine-translate relevant English headlines into Czech (local, free).
    Newest first, capped per cycle so a refresh stays quick; the rest follow
    in the next cycles. Irrelevant headlines are never translated."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=TRANSLATE_LOOKBACK_DAYS)
    candidates = session.scalars(
        select(NewsItem)
        .where(NewsItem.language == "en", NewsItem.title_cs.is_(None), NewsItem.published_at >= cutoff)
        .order_by(NewsItem.published_at.desc())
    )
    done = 0
    for item in candidates:
        if done >= limit:
            break
        if not item.factor_tags and "XAUUSD" not in item.instrument_tags and not markets.ANY_MARKET.search(item.title):
            continue
        cz_title = translate.translate(item.title)
        if cz_title is None:
            reason = translate.unavailable_reason()
            if reason:
                _warn(reason)
            break
        item.title_cs = cz_title
        done += 1
    session.commit()
    return done


def _news_signal(session: Session, factor_tag: str, require_instrument: str | None = None) -> NewsSignal:
    """Build the raw (undecayed) NewsSignal for one factor tag — decay is
    applied later, per horizon, inside the scoring engine (see
    scoring/xauusd.py). Duplicates are excluded here so the same real-world
    event reported by RSS and GDELT is never counted twice.
    """
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=NEWS_LOOKBACK_DAYS)
    stmt = select(NewsItem).where(NewsItem.published_at >= cutoff)
    items = [
        n for n in session.scalars(stmt)
        if factor_tag in n.factor_tags and n.duplicate_of_id is None
    ]
    if require_instrument:
        items = [n for n in items if require_instrument in n.instrument_tags]

    points = [
        NewsDataPoint(
            sentiment=n.sentiment_scores.get(factor_tag, 1.0 if n.sentiment == "bullish" else -1.0 if n.sentiment == "bearish" else 0.0),
            published_at=n.published_at,
            item_id=n.id,
            description=f'„{n.title}“ ({_source_cz(n.source)}, {cz_date(n.published_at.date().isoformat())})',
        )
        for n in items
    ]
    return NewsSignal(factor_tag=factor_tag, points=points)


def _compute_pillar_deltas(old_breakdown: dict, new_breakdown: dict) -> dict:
    deltas = {}
    for name, new_pillar in new_breakdown.items():
        old_pillar = old_breakdown.get(name)
        old_points = old_pillar["points"] if old_pillar else 0.0
        new_points = new_pillar["points"]
        if abs(new_points - old_points) < PILLAR_DELTA_EPSILON:
            continue
        deltas[name] = {
            "old_points": old_points,
            "new_points": new_points,
            "old_impact": old_pillar["impact"] if old_pillar else "neutral",
            "new_impact": new_pillar["impact"],
        }
    return deltas


def compute_and_store_score(session: Session, horizon: str | None = None) -> ScoreSnapshot:
    """Run one full ingestion cycle and compute+store a ScoreSnapshot for
    every supported horizon. Returns the snapshot for `horizon` (default:
    the first supported horizon) for convenience — all others are stored
    too and reachable via the API/history endpoints.
    """
    with _cycle_lock:
        _current_warnings.clear()
        LAST_CYCLE.update(started_at=dt.datetime.now(dt.timezone.utc), running=True, error=None)
        try:
            return _run_cycle(session, horizon)
        except Exception as exc:
            session.rollback()
            logger.exception("Ingestion cycle failed")
            # Shown in the UI: first line only (raw DB errors carry whole SQL statements).
            first_line = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
            LAST_CYCLE["error"] = f"{type(exc).__name__}: {first_line[:200]}"
            raise
        finally:
            LAST_CYCLE.update(finished_at=dt.datetime.now(dt.timezone.utc), running=False, warnings=list(_current_warnings))


def _run_cycle(session: Session, horizon: str | None) -> ScoreSnapshot:
    instrument = ensure_xauusd_instrument(session)

    macro = sync_fred_series(session)
    _LAST_MACRO.clear()
    _LAST_MACRO.update(macro)
    positioning = sync_cftc_positioning(session)
    for w in sync_news(session):
        _warn(w)

    fed_tone = _news_signal(session, "fed_tone")
    geopolitics = _news_signal(session, "geopolitics")
    cb_buying = _news_signal(session, "cb_gold_buying", require_instrument="XAUUSD")

    inputs = XauInputs(
        real_yield_10y=macro["real_yield_10y"],
        usd_index=macro["usd_index"],
        fed_funds_target=macro["fed_funds_target"],
        core_cpi=macro["core_cpi"],
        core_pce=macro["core_pce"],
        gdp=macro["gdp"],
        unemployment=macro["unemployment"],
        nfp=macro["nfp"],
        fed_tone_news=fed_tone,
        geopolitics_news=geopolitics,
        central_bank_buying_news=cb_buying,
        positioning=positioning if positioning.actual is not None else None,
    )

    now = dt.datetime.now(dt.timezone.utc)
    related_observation_ids = [p.observation_id for p in macro.values() if p.observation_id is not None]
    if positioning.observation_id is not None:
        related_observation_ids.append(positioning.observation_id)
    related_news_ids = list({*fed_tone.item_ids, *geopolitics.item_ids, *cb_buying.item_ids})

    snapshots_by_horizon: dict[str, ScoreSnapshot] = {}

    for h in SUPPORTED_HORIZONS:
        result = compute_xauusd_score(inputs, horizon=h, now=now)

        previous_snapshot = session.scalar(
            select(ScoreSnapshot)
            .where(ScoreSnapshot.instrument_id == instrument.id, ScoreSnapshot.horizon == h)
            .order_by(ScoreSnapshot.computed_at.desc())
        )

        snapshot = ScoreSnapshot(
            instrument_id=instrument.id,
            computed_at=result.computed_at,
            horizon=h,
            bias=result.bias,
            direction=result.direction,
            score=result.score,
            pillar_breakdown=result.pillar_breakdown_json(),
            drivers=result.drivers,
            contrarian=result.contrarian,
            risks=result.risks,
            scenarios=result.scenarios_json(),
            invalidation=result.invalidation,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        snapshots_by_horizon[h] = snapshot

        score_changed = previous_snapshot is None or previous_snapshot.bias != snapshot.bias or abs(previous_snapshot.score - snapshot.score) >= 5
        if score_changed:
            pillar_deltas = _compute_pillar_deltas(
                previous_snapshot.pillar_breakdown if previous_snapshot else {}, snapshot.pillar_breakdown
            )
            changed_pillar_names = ", ".join(PILLAR_DISPLAY[n] for n in pillar_deltas) or "žádný pilíř se výrazně nezměnil"
            old_bias = BIAS_CZ[previous_snapshot.bias] if previous_snapshot else "—"
            old_score = cz(previous_snapshot.score) if previous_snapshot else "—"
            reason = (
                f"[{h}] Výhled {old_bias} → {BIAS_CZ[snapshot.bias]}, skóre {old_score} → {cz(snapshot.score)}. "
                f"Změněné pilíře: {changed_pillar_names}. "
                f"Hlavní faktor: {result.drivers[0] if result.drivers else 'beze změny'}."
            )
            session.add(
                ScoreHistoryEntry(
                    instrument_id=instrument.id,
                    horizon=h,
                    old_score=previous_snapshot.score if previous_snapshot else None,
                    new_score=snapshot.score,
                    old_bias=previous_snapshot.bias if previous_snapshot else None,
                    new_bias=snapshot.bias,
                    reason=reason,
                    related_news_ids=related_news_ids,
                    related_observation_ids=related_observation_ids,
                    pillar_deltas=pillar_deltas,
                )
            )
            session.commit()

    _store_market_analysis(session, instrument, snapshots_by_horizon[PRIMARY_HORIZON], now, macro)
    return snapshots_by_horizon[horizon or SUPPORTED_HORIZONS[0]]


NEWS_MOOD_HOURS = 72
GOLD_FACTORS = ("fed_tone", "geopolitics", "cb_gold_buying")


def news_mood(session: Session, now: dt.datetime, hours: int = NEWS_MOOD_HOURS) -> dict:
    """What the last few days of news say for gold: average impact of every
    (non-duplicate) article that carries a gold-relevant factor, from all
    sources — portals, central-bank RSS and GDELT."""
    cutoff = now - dt.timedelta(hours=hours)
    items = [
        n for n in session.scalars(select(NewsItem).where(NewsItem.published_at >= cutoff))
        if n.duplicate_of_id is None and any(f in n.factor_tags for f in GOLD_FACTORS)
    ]
    scored = []
    for n in items:
        vals = [n.sentiment_scores.get(f, 0.0) for f in GOLD_FACTORS if f in n.factor_tags]
        scored.append((sum(vals) / len(vals), n))
    scored.sort(key=lambda x: x[1].published_at, reverse=True)
    score = sum(s for s, _ in scored) / len(scored) if scored else None
    return {
        "hours": hours,
        "count": len(scored),
        "bullish": sum(1 for s, _ in scored if s > 0.1),
        "bearish": sum(1 for s, _ in scored if s < -0.1),
        "score": round(score, 3) if score is not None else None,
        "top": [
            {"title": n.title_cs or n.title, "translated": n.language == "en" and n.title_cs is not None,
             "source": _source_cz(n.source), "url": n.url, "published_at": n.published_at.isoformat(),
             "impact": "bullish" if s > 0.1 else "bearish" if s < -0.1 else "neutral"}
            for s, n in scored[:5]
        ],
        "key": _key_news(scored, now),
        "headline": _headline_candidates(session, now),
    }


HEADLINE_HOURS = 48  # headline risk reads the last 12 h, the oil supply risk 48 h


def _headline_candidates(session: Session, now: dt.datetime) -> list[dict]:
    """All fresh, non-duplicate headlines (any topic) for the headline-risk scan."""
    cutoff = now - dt.timedelta(hours=HEADLINE_HOURS)
    rows = session.scalars(select(NewsItem).where(NewsItem.published_at >= cutoff).order_by(NewsItem.published_at.desc()).limit(600))
    return [
        {"title": n.title_cs or n.title, "title_en": n.title, "translated": n.language == "en" and n.title_cs is not None,
         "source": _source_cz(n.source), "url": n.url, "published_at": n.published_at.isoformat()}
        for n in rows if n.duplicate_of_id is None
    ]


FACTOR_CZ = {"fed_tone": "Fed a sazby", "geopolitics": "Geopolitika", "cb_gold_buying": "Nákupy centrálních bank"}


def _key_news(scored: list, now: dt.datetime, limit: int = 5) -> list[dict]:
    """The news that matter most for gold: strong signal × relevance, fading
    with age (half-life 24 h). Context-only items (no direction) rank last."""
    def weight(item) -> float:
        s, n = item
        age_h = max(0.0, (now - n.published_at).total_seconds() / 3600)
        about_gold = 2.0 if "XAUUSD" in (n.instrument_tags or []) else 1.0
        return about_gold * (n.relevance_score or 0.0) * max(abs(s), 0.15) * 0.5 ** (age_h / 24)

    ranked = sorted(scored, key=weight, reverse=True)[:limit]
    return [
        {"title": n.title_cs or n.title, "translated": n.language == "en" and n.title_cs is not None,
         "source": _source_cz(n.source), "url": n.url, "published_at": n.published_at.isoformat(),
         "impact": "bullish" if s > 0.1 else "bearish" if s < -0.1 else "neutral",
         "factors": [FACTOR_CZ[f] for f in GOLD_FACTORS if f in n.factor_tags],
         "gold": "XAUUSD" in (n.instrument_tags or [])}
        for s, n in ranked
    ]


# --- fundamental score history and its momentum
TRA_STORE_MINUTES = 60  # a live point at least hourly, and on every change
TRA_BACKFILL_DAYS = 365
TRA_GAP_HOURS = 36  # the app was closed longer than this → rebuild the missing days
TRA_MOMENTUM_DAYS = 40
TRA_SIDES = (("XAUUSD", "xau"), ("USD", "usd"))


def _tra_components(pack: dict) -> dict:
    return {**{c["key"]: c["score"] for c in pack["components"]}, "_v": tra.MODEL_VERSION}


def _model_outdated(session: Session) -> bool:
    last = session.scalar(select(TraScorePoint).order_by(TraScorePoint.computed_at.desc()).limit(1))
    return last is not None and (last.components or {}).get("_v") != tra.MODEL_VERSION


def backfill_tra(session: Session, inputs: tra.TraInputs, now: dt.datetime) -> int:
    """Rebuild missing score history from historical data (lag-aware, see tra.py): a whole
    year on the first run, afterwards only gaps when the app was not running."""
    newest = session.scalar(select(func.max(TraScorePoint.computed_at)))
    if newest is None:
        days = TRA_BACKFILL_DAYS
    elif now - newest > dt.timedelta(hours=TRA_GAP_HOURS):
        days = min(TRA_BACKFILL_DAYS, (now - newest).days + 1)
    else:
        return 0
    points = [p for p in tra.backfill(inputs, days, now) if newest is None or p["t"] > newest]
    for p in points:
        for inst, side in TRA_SIDES:
            session.add(TraScorePoint(instrument=inst, computed_at=p["t"], total=p[side]["total"],
                                      components=_tra_components(p[side]), source="backfill"))
    session.commit()
    return len(points)


def store_tra_points(session: Session, tra_block: dict, now: dt.datetime) -> None:
    for inst, side in TRA_SIDES:
        pack = tra_block.get(side)
        if not pack:
            continue
        comps = _tra_components(pack)
        last = session.scalar(select(TraScorePoint).where(TraScorePoint.instrument == inst)
                              .order_by(TraScorePoint.computed_at.desc()).limit(1))
        if (last is None or last.total != pack["total"] or last.components != comps
                or now - last.computed_at >= dt.timedelta(minutes=TRA_STORE_MINUTES)):
            session.add(TraScorePoint(instrument=inst, computed_at=now, total=pack["total"], components=comps, source="live"))
    session.commit()


def tra_momentum(session: Session, inputs: tra.TraInputs | None, now: dt.datetime) -> dict:
    out = {}
    for inst, side in TRA_SIDES:
        rows = session.execute(
            select(TraScorePoint.computed_at, TraScorePoint.total)
            .where(TraScorePoint.instrument == inst, TraScorePoint.computed_at >= now - dt.timedelta(days=TRA_MOMENTUM_DAYS))
            .order_by(TraScorePoint.computed_at)
        ).all()
        candles = (inputs.gold_d1 if side == "xau" else inputs.dxy_d1) if inputs else []
        out[side] = momentum.analyze([(t, v) for t, v in rows], [(c.time, c.close) for c in candles[-60:]], now, inst)
    return out


def _tra_history(session: Session, payload: dict, now: dt.datetime) -> None:
    tra_block = payload.get("tra")
    if not tra_block:
        return
    try:
        inputs = market_service.LAST_TRA.get("inputs")
        # never write a year of history from incomplete inputs (e.g. FRED was down this time)
        if inputs is not None and len(tra_block["xau"]["missing"]) <= 1:
            if _model_outdated(session):  # rules changed: rebuild the whole history with the new ones
                session.execute(delete(TraScorePoint))
                session.commit()
            backfill_tra(session, inputs, now)
        store_tra_points(session, tra_block, now)
        tra_block["momentum"] = tra_momentum(session, inputs, now)
    except Exception:  # noqa: BLE001 — the score history must never cost us the analysis
        session.rollback()
        logger.exception("Score history failed")


def _store_market_analysis(session: Session, instrument: Instrument, primary: ScoreSnapshot, now: dt.datetime, macro: dict | None = None) -> None:
    """Trend, technicals, correlations and the combined verdict. A failure
    here must never cost us the fundamental scores computed above."""
    try:
        fundamental = {"score": primary.score, "bias": primary.bias, "pillar_breakdown": primary.pillar_breakdown}
        payload, warnings = compute_market_analysis(fundamental, _next_fomc_date(now), news_mood(session, now), macro=macro or {}, now=now)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Market analysis failed")
        _warn(f"Trend/korelace se nepodařilo spočítat: {exc}")
        return
    for w in warnings:
        _warn(w)
    _tra_history(session, payload, now)
    session.add(AnalysisSnapshot(instrument_id=instrument.id, computed_at=now, payload=payload))
    session.commit()
    old_ids = list(session.scalars(
        select(AnalysisSnapshot.id).where(AnalysisSnapshot.instrument_id == instrument.id)
        .order_by(AnalysisSnapshot.computed_at.desc()).offset(KEEP_ANALYSIS_SNAPSHOTS)
    ))
    if old_ids:
        session.execute(delete(AnalysisSnapshot).where(AnalysisSnapshot.id.in_(old_ids)))
        session.commit()


def refresh_market(session: Session) -> bool:
    """Every few minutes: prices, technicals, trends, DXY, levels and the verdict.
    Slow inputs (macro, COT, calendar, news) come from the last full cycle and
    the service's caches. Skipped while a full cycle runs or before the first one."""
    if not _LAST_MACRO or not _cycle_lock.acquire(blocking=False):
        return False
    try:
        instrument = session.scalar(select(Instrument).where(Instrument.code == "XAUUSD"))
        primary = session.scalar(
            select(ScoreSnapshot).where(ScoreSnapshot.instrument_id == instrument.id, ScoreSnapshot.horizon == PRIMARY_HORIZON)
            .order_by(ScoreSnapshot.computed_at.desc())
        ) if instrument else None
        if primary is None:
            return False
        now = dt.datetime.now(dt.timezone.utc)
        last = _last_portal_sync["at"]
        if last is None or now - last >= dt.timedelta(minutes=NEWS_REFRESH_MINUTES):
            try:
                sync_portals(session)
            except Exception:  # noqa: BLE001 — news must never block the price refresh
                session.rollback()
                logger.exception("Portal news refresh failed")
        _store_market_analysis(session, instrument, primary, now, dict(_LAST_MACRO))
        LAST_MARKET_REFRESH.update(at=now, error=None)
        return True
    except Exception as exc:  # noqa: BLE001 — a failed refresh must not break anything
        session.rollback()
        logger.exception("Market refresh failed")
        LAST_MARKET_REFRESH["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return False
    finally:
        _cycle_lock.release()
