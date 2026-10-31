from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class ScoreSnapshotOut(BaseModel):
    instrument: str
    horizon: str
    computed_at: dt.datetime
    bias: str
    direction: str
    score: float
    pillar_breakdown: dict
    drivers: list[str]
    contrarian: list[str]
    risks: list[str]
    scenarios: dict
    invalidation: list[str]

    model_config = {"from_attributes": True}


class ScoreHistoryOut(BaseModel):
    id: int
    changed_at: dt.datetime
    horizon: str
    old_score: float | None
    new_score: float
    old_bias: str | None
    new_bias: str
    reason: str
    related_news_ids: list[int]
    related_observation_ids: list[int]
    pillar_deltas: dict

    model_config = {"from_attributes": True}
