from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from ...config import REPO_ROOT
from ...domain.base import ContractModel
from ...store import CHANNEL_REPLAY
from ..deps import Container, get_container

router = APIRouter(tags=["scope"])


class TierResult(ContractModel):
    predicted: int
    correct: int
    precision: float | None


class SectorResult(ContractModel):
    documents: int
    recall: float | None
    precision: float | None


class ScopeEvaluation(ContractModel):
    snapshot_id: str
    single_issuer_documents: int
    vocabulary_fired: int
    coverage: float | None
    by_strength: dict[str, TierResult]
    per_sector: dict[str, SectorResult]
    limits: list[str]


class ScopeInfo(ContractModel):
    version: str
    rules: list[str] = Field(description="the ordered decision table, in words")
    sectors: dict[str, int] = Field(description="sector -> number of vocabulary terms")
    themes: dict[str, int]
    regions: list[str]
    replay_mix: dict[str, int] = Field(description="the replay signals by scope level")
    live_mix: dict[str, int] = Field(description="live and pasted signals by scope level")
    evaluation: ScopeEvaluation | None = Field(description="the sector vocabulary measured on documents whose company resolved")


RULES = [
    "A resolved company is the scope (COMPANY); its sector and country come from the entity master.",
    "Text the event model judges not to be a market event gets no subject (UNRESOLVED).",
    "One sector with two or more distinct vocabulary terms and no tie is a SECTOR scope (STRONG).",
    "Otherwise a macro or geopolitical event (event model) or any market-wide vocabulary is a MARKET scope, with its themes.",
    "One sector with exactly one distinct term is a SECTOR scope (WEAK).",
    "Everything else stays UNRESOLVED, with the reason stated. Nothing is guessed.",
]


@router.get("/scope", response_model=ScopeInfo)
def scope_info(c: Container = Depends(get_container)) -> ScopeInfo:
    """How the scope of a signal is decided, how well the sector vocabulary was measured to work, and what the data looks like."""
    if c.scope_config is None:
        raise HTTPException(status_code=404, detail="scope resolution exists only in the replay profile")
    cfg = c.scope_config
    replay = Counter(s.scope.level.value for s in c.signals.list(channel=CHANNEL_REPLAY) if s.scope)
    live = Counter(s.scope.level.value for s in c.signals.list() if s.scope and c.signals.channel_of(s.id) != CHANNEL_REPLAY)
    path = REPO_ROOT / "docs" / "evidence" / "scope_eval.json"
    ev = None
    if path.is_file():
        d = json.loads(path.read_text(encoding="utf-8"))
        ev = ScopeEvaluation(
            snapshot_id=d["snapshot_id"], single_issuer_documents=d["single_issuer_documents"],
            vocabulary_fired=d["vocabulary_fired"], coverage=d["coverage"],
            by_strength={k: TierResult(**v) for k, v in d["by_strength"].items()},
            per_sector={k: SectorResult(documents=v["documents"], recall=v["recall"], precision=v["precision"])
                        for k, v in d["per_sector"].items()},
            limits=d["limits"])
    return ScopeInfo(
        version=cfg.version, rules=RULES, sectors={k: len(v) for k, v in cfg.sectors.items()},
        themes={k: len(v) for k, v in cfg.themes.items()}, regions=sorted(cfg.regions),
        replay_mix=dict(sorted(replay.items())), live_mix=dict(sorted(live.items())), evaluation=ev)
