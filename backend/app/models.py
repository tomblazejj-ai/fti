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
    """History of the Funded Mind / Trading Analyzer style score (app/market/tra.py).
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
