from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.ingestion.run_ingest import compute_and_store_score
from app.models import Instrument, ScoreHistoryEntry, ScoreSnapshot
from app.schemas import ScoreHistoryOut, ScoreSnapshotOut
from app.scoring.xauusd import SUPPORTED_HORIZONS

router = APIRouter(prefix="/instruments", tags=["instruments"])


def _require_xauusd(code: str) -> None:
    if code.upper() != "XAUUSD":
        raise HTTPException(status_code=404, detail=f"Instrument {code} zatím není podporován (jen XAUUSD).")


def _require_horizon(horizon: str) -> None:
    if horizon not in SUPPORTED_HORIZONS:
        raise HTTPException(status_code=400, detail=f"Nepodporovaný horizont '{horizon}', povolené: {SUPPORTED_HORIZONS}")


def _to_schema(code: str, snapshot: ScoreSnapshot) -> ScoreSnapshotOut:
    return ScoreSnapshotOut(
        instrument=code.upper(),
        horizon=snapshot.horizon,
        computed_at=snapshot.computed_at,
        bias=snapshot.bias,
        direction=snapshot.direction,
        score=snapshot.score,
        pillar_breakdown=snapshot.pillar_breakdown,
        drivers=snapshot.drivers,
        contrarian=snapshot.contrarian,
        risks=snapshot.risks,
        scenarios=snapshot.scenarios,
        invalidation=snapshot.invalidation,
    )


@router.get("/{code}/score", response_model=ScoreSnapshotOut)
def get_latest_score(code: str, horizon: str = "1-10d", session: Session = Depends(get_session)):
    _require_xauusd(code)
    _require_horizon(horizon)

    instrument = session.scalar(select(Instrument).where(Instrument.code == code.upper()))
    snapshot = None
    if instrument is not None:
        snapshot = session.scalar(
            select(ScoreSnapshot)
            .where(ScoreSnapshot.instrument_id == instrument.id, ScoreSnapshot.horizon == horizon)
            .order_by(ScoreSnapshot.computed_at.desc())
        )
    if snapshot is None:
        snapshot = compute_and_store_score(session, horizon=horizon)

    return _to_schema(code, snapshot)


@router.get("/{code}/scores", response_model=dict[str, ScoreSnapshotOut])
def get_all_horizon_scores(code: str, session: Session = Depends(get_session)):
    """All 5 horizons at once — the "open XAUUSD, see everything" view from
    the brief (section 13), computed from a single shared data fetch.
    """
    _require_xauusd(code)
    instrument = session.scalar(select(Instrument).where(Instrument.code == code.upper()))
    out: dict[str, ScoreSnapshotOut] = {}
    missing_horizons = list(SUPPORTED_HORIZONS)

    if instrument is not None:
        for h in list(missing_horizons):
            snapshot = session.scalar(
                select(ScoreSnapshot)
                .where(ScoreSnapshot.instrument_id == instrument.id, ScoreSnapshot.horizon == h)
                .order_by(ScoreSnapshot.computed_at.desc())
            )
            if snapshot is not None:
                out[h] = _to_schema(code, snapshot)
                missing_horizons.remove(h)

    if missing_horizons:
        compute_and_store_score(session, horizon=missing_horizons[0])
        instrument = session.scalar(select(Instrument).where(Instrument.code == code.upper()))
        for h in missing_horizons:
            snapshot = session.scalar(
                select(ScoreSnapshot)
                .where(ScoreSnapshot.instrument_id == instrument.id, ScoreSnapshot.horizon == h)
                .order_by(ScoreSnapshot.computed_at.desc())
            )
            if snapshot is not None:
                out[h] = _to_schema(code, snapshot)

    return out


@router.post("/{code}/refresh", response_model=ScoreSnapshotOut)
def refresh_score(code: str, horizon: str = "1-10d", session: Session = Depends(get_session)):
    _require_xauusd(code)
    _require_horizon(horizon)
    snapshot = compute_and_store_score(session, horizon=horizon)
    return _to_schema(code, snapshot)


@router.get("/{code}/history", response_model=list[ScoreHistoryOut])
def get_history(code: str, horizon: str = "1-10d", session: Session = Depends(get_session)):
    _require_xauusd(code)
    _require_horizon(horizon)
    instrument = session.scalar(select(Instrument).where(Instrument.code == code.upper()))
    if instrument is None:
        return []
    entries = session.scalars(
        select(ScoreHistoryEntry)
        .where(ScoreHistoryEntry.instrument_id == instrument.id, ScoreHistoryEntry.horizon == horizon)
        .order_by(ScoreHistoryEntry.changed_at.desc())
    ).all()
    return list(entries)
