from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class UtcDateTime(TypeDecorator):
    """Always UTC-aware on the Python side.

    SQLite has no timezone-aware datetime type: it silently drops tzinfo on
    write and returns naive datetimes on read. Serialized to JSON, a naive
    value has no offset and browsers parse it as LOCAL time — every
    timestamp in the UI would be shifted by the viewer's UTC offset. Store
    as naive UTC on SQLite, re-attach UTC on read.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        value = value.astimezone(dt.timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # e.g. "XAUUSD"
    name: Mapped[str] = mapped_column(String(64))
    pillar_config: Mapped[dict] = mapped_column(JSON)  # {pillar_name: weight}
    active: Mapped[bool] = mapped_column(default=True)


class MacroSeries(Base):
    __tablename__ = "macro_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # "fred", "bls", "bea", "eia"
    external_id: Mapped[str] = mapped_column(String(64))  # e.g. "CPIAUCSL"
    label: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(32))
    frequency: Mapped[str] = mapped_column(String(16))  # "M", "W", "D", "Q"
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_macro_series_source_external_id"),)


class MacroObservation(Base):
    __tablename__ = "macro_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("macro_series.id"), index=True)
    period: Mapped[str] = mapped_column(String(16))  # e.g. "2026-08" for monthly
    actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous: Mapped[float | None] = mapped_column(Float, nullable=True)
    consensus: Mapped[float | None] = mapped_column(Float, nullable=True)  # nullable — see DECISIONS.md
    surprise: Mapped[float | None] = mapped_column(Float, nullable=True)  # actual - previous (no paid consensus feed)
    fetched_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    source_url: Mapped[str] = mapped_column(String(256))

    series: Mapped[MacroSeries] = relationship()

    __table_args__ = (UniqueConstraint("series_id", "period", name="uq_macro_obs_series_period"),)


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64))  # e.g. "federalreserve.gov", "ecb.europa.eu"
    dedup_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(512))
    published_at: Mapped[dt.datetime] = mapped_column(UtcDateTime())
    fetched_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    raw_snippet: Mapped[str] = mapped_column(Text)
    instrument_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1
    sentiment: Mapped[str] = mapped_column(String(16), default="neutral")  # bullish/bearish/neutral (coarse, per whole item)
    sentiment_scores: Mapped[dict] = mapped_column(JSON, default=dict)  # {factor_tag: -1..1} — precise, per factor
    factor_tags: Mapped[list[str]] = mapped_column(JSON, default=list)  # e.g. ["fed", "geopolitics"]
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("news_items.id"), nullable=True)
    classifier_version: Mapped[int] = mapped_column(default=0)
    language: Mapped[str] = mapped_column(String(4), default="en", server_default="en")
    title_cs: Mapped[str | None] = mapped_column(String(512), nullable=True)  # Czech headline (original or machine translation)


class CentralBankEvent(Base):
    __tablename__ = "central_bank_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank: Mapped[str] = mapped_column(String(16))  # "Fed", "ECB", "BoE", "BoJ"
    event_type: Mapped[str] = mapped_column(String(32))  # "rate_decision", "minutes", "speech"
    scheduled_at: Mapped[dt.datetime] = mapped_column(UtcDateTime())
    outcome_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    outcome_url: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    computed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    horizon: Mapped[str] = mapped_column(String(16))  # "intraday","1-3d","1-10d","1-4w","1-3m","long_term"
    bias: Mapped[str] = mapped_column(String(16))  # LONG/NEUTRAL/SHORT
    score: Mapped[float] = mapped_column(Float)
    pillar_breakdown: Mapped[dict] = mapped_column(JSON)
    drivers: Mapped[list[str]] = mapped_column(JSON, default=list)
    contrarian: Mapped[list[str]] = mapped_column(JSON, default=list)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    scenarios: Mapped[dict] = mapped_column(JSON, default=dict)  # {"base":..., "bull":..., "bear":...}
    invalidation: Mapped[list[str]] = mapped_column(JSON, default=list)
    direction: Mapped[str] = mapped_column(String(16), default="NEUTRAL")  # BULLISH/NEUTRAL/BEARISH

    instrument: Mapped[Instrument] = relationship()


class ScoreHistoryEntry(Base):
    __tablename__ = "score_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    horizon: Mapped[str] = mapped_column(String(16))
    changed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    old_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_score: Mapped[float] = mapped_column(Float)
    old_bias: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_bias: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(512))
    related_news_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    related_observation_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    pillar_deltas: Mapped[dict] = mapped_column(JSON, default=dict)  # {pillar_name: {old_points, new_points, old_impact, new_impact}}


class AnalysisSnapshot(Base):
    """Trend + technicals + correlations + combined verdict, one per ingestion
    cycle (see app/market/service.py). New table, so existing DBs just gain it."""

    __tablename__ = "analysis_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    computed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON)


class TraScorePoint(Base):
    """History of the fundamental score (app/market/tra.py).
    "live" points are stored while the app runs (on change, at least hourly);
    "backfill" points were rebuilt from historical data (lag-aware) so the
    score-momentum chart is useful from day one."""

    __tablename__ = "tra_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument: Mapped[str] = mapped_column(String(10), index=True)  # "XAUUSD" | "USD"
    computed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), index=True)
    total: Mapped[int] = mapped_column()
    components: Mapped[dict] = mapped_column(JSON, default=dict)  # {category key: score}
    source: Mapped[str] = mapped_column(String(10), default="live")


# --- FTI platform tables (2026-11-01). New tables only, so existing databases just gain them. ---


class SeriesCache(Base):
    """Last good answer of every external source (JSON). When the source fails, the app shows
    this copy with its real date and a STALE/DELAYED label instead of silently going blank."""

    __tablename__ = "series_cache"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    source: Mapped[str] = mapped_column(String(80), default="")
    payload: Mapped[dict] = mapped_column(JSON)


class SourceHealth(Base):
    """Monitoring of one data source: last attempt, last success, error, response time, records."""

    __tablename__ = "source_health"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    last_attempt: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    last_ok: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    last_error_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ok_count: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)
    last_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_records: Mapped[int | None] = mapped_column(nullable=True)
    data_as_of: Mapped[str | None] = mapped_column(String(40), nullable=True)


class PriceBar(Base):
    """OHLCV history per instrument and timeframe, kept so the history grows beyond what a
    source returns at once (Kraken: 720 candles). Needed for backtests and correlations."""

    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("code", "tf", "t", name="uq_price_bar"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    tf: Mapped[str] = mapped_column(String(4), index=True)
    t: Mapped[int] = mapped_column(index=True)  # bar open, unix seconds UTC
    o: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    l: Mapped[float] = mapped_column(Float)  # noqa: E741 (OHLC naming)
    c: Mapped[float] = mapped_column(Float)
    v: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="")


class MarketScoreRecord(Base):
    """Unified -100..+100 score of every instrument, stored each cycle (archive, score history)."""

    __tablename__ = "market_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    computed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow, index=True)
    overall: Mapped[float | None] = mapped_column(Float, nullable=True)
    intraday: Mapped[float | None] = mapped_column(Float, nullable=True)
    swing: Mapped[float | None] = mapped_column(Float, nullable=True)
    technical: Mapped[float | None] = mapped_column(Float, nullable=True)
    fundamental: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    label: Mapped[str] = mapped_column(String(20), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class AnalysisRecord(Base):
    """One analysis (AI advisor, zone analysis, briefing). Never overwritten: an update is a new
    row whose parent_id points at the previous version."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # advisor | zone | briefing
    code: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    tf: Mapped[str | None] = mapped_column(String(4), nullable=True)
    zone_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow, index=True)
    data_as_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred: Mapped[str | None] = mapped_column(String(12), nullable=True)  # LONG | SHORT | NO TRADE
    confidence: Mapped[str | None] = mapped_column(String(12), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class UserZone(Base):
    """A price zone the user drew on the chart. Private: never exported to the public site."""

    __tablename__ = "user_zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    tf: Mapped[str] = mapped_column(String(4))
    lo: Mapped[float] = mapped_column(Float)
    hi: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(20), default="custom")
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)  # long | short | None
    name: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    t_from: Mapped[int | None] = mapped_column(nullable=True)  # where the rectangle starts on the chart
    state: Mapped[str] = mapped_column(String(16), default="active")  # active | archived
    status: Mapped[dict] = mapped_column(JSON, default=dict)  # last monitoring result


class ZoneEvent(Base):
    __tablename__ = "zone_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(index=True)
    at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    event: Mapped[str] = mapped_column(String(20))
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")


class WatchItem(Base):
    """A watchlist entry or an alert rule (kind decides which)."""

    __tablename__ = "watch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # instrument | price | zone | bos | fvg | trend | scenario | event | volatility
    code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    tf: Mapped[str | None] = mapped_column(String(4), nullable=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    state: Mapped[dict] = mapped_column(JSON, default=dict)  # last seen values, so a rule fires once per change


class AlertRecord(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow, index=True)
    code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(default=False)


class AiUsage(Base):
    """Every AI call: tokens and cost, for the monthly budget and the cost overview."""

    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow, index=True)
    task: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    ok: Mapped[bool] = mapped_column(default=True)
    note: Mapped[str] = mapped_column(Text, default="")


class BacktestRecord(Base):
    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    strategy: Mapped[str] = mapped_column(String(60))
    code: Mapped[str] = mapped_column(String(16))
    tf: Mapped[str] = mapped_column(String(4))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
