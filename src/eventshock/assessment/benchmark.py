"""Evaluate the severity architecture on the pre-registered benchmark (``data/benchmarks/``): does the score discriminate genuinely different levels of risk?

Text-only on purpose: no trained-model reading, no market data, no issuer: the result depends on the text and the architecture. ``abstained`` items (the text is
not a market event, so nothing is scored) count as score 1 for the metrics and are reported separately. The acceptance criteria are fixed in
``data/benchmarks/README.md`` before the first run; nothing here is tuned to pass them.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT, Settings, load_taxonomy
from ..llm.cache import ExtractionCache, cache_key
from ..llm.client import LLMUnavailable
from ..llm.config import load_llm_config
from ..pipeline.scope import ScopeResolver, load_scope_config
from .config import load_semantics_config, load_severity_config
from .extractor import SemanticExtractor
from .freshness import assess_market
from .reference import Reference
from .rubric import RubricDeriver
from .rules import RuleExtractor
from .severity import SeverityInputs, SeverityScorer
from .vocab import Vocab

BENCH_DIR = REPO_ROOT / "data" / "benchmarks"


@dataclass(frozen=True)
class Dataset:
    """A pre-registered benchmark file and the recorded real-model outputs for it."""

    name: str
    path: Path
    recorded: Path
    min_per_band: int  # the "every band occupied" criterion, scaled to the set's size


DEV = Dataset("dev", BENCH_DIR / "severity_benchmark.jsonl", BENCH_DIR / "llm_outputs.jsonl", 3)
HELDOUT = Dataset("heldout", BENCH_DIR / "severity_heldout.jsonl", BENCH_DIR / "llm_outputs_heldout.jsonl", 2)
DATASETS = {d.name: d for d in (DEV, HELDOUT)}
BENCHMARK, RECORDED = DEV.path, DEV.recorded  # kept for callers that mean the development set
BANDS = ("negligible", "low", "moderate", "high", "extreme")
BAND_RANGE = {"negligible": (1, 2), "low": (3, 4), "moderate": (5, 6), "high": (7, 8), "extreme": (9, 10)}
REPORT_TIME = datetime(2026, 10, 5, 12, tzinfo=UTC)


class NoCallClient:
    """Stands in for the provider when replaying recorded outputs: any call is a bug (a cache miss), not a request to make."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def extract(self, **_: Any) -> dict[str, Any]:
        raise LLMUnavailable("a recorded benchmark replay must not call the provider (cache miss)")


@dataclass
class Rig:
    vocab: Vocab
    rules: RuleExtractor
    deriver: RubricDeriver
    scorer: SeverityScorer
    llm_cfg: Any
    config_dir: Path

    @classmethod
    def build(cls, config_dir: Path | None = None) -> Rig:
        s = Settings(config_dir=config_dir) if config_dir else Settings()
        scope_cfg = load_scope_config(s.config_dir)
        scope = ScopeResolver(scope_cfg)
        vocab = Vocab.build(load_semantics_config(s.config_dir), scope_cfg, {c.id.value: c.label for c in load_taxonomy(s).categories})
        sev = load_severity_config(s.config_dir)
        return cls(vocab, RuleExtractor(vocab, scope), RubricDeriver(vocab, scope, sev), SeverityScorer(sev), load_llm_config(s.config_dir), s.config_dir)

    def extractor(self, client: Any = None, cache: ExtractionCache | None = None, prompt_version: str | None = None) -> SemanticExtractor:
        cfg = self.llm_cfg.model_copy(update={"enabled": client is not None})
        return SemanticExtractor(self.vocab, self.rules, cfg, client=client, cache=cache, prompt_version=prompt_version)


def load_rows(path: Path = BENCHMARK) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def file_sha256(path: Path = BENCHMARK) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recording_meta(recorded: Path) -> dict[str, Any]:
    """The first line of a recording: which model, prompt and vocabulary produced it, and for which benchmark file."""
    return json.loads(recorded.read_text(encoding="utf-8").splitlines()[0])["value"]


def score_text(rig: Rig, text: str, extractor: SemanticExtractor | None, *, use_llm: bool) -> dict[str, Any]:
    """One text through the real pipeline pieces (extraction -> rubric -> scorecard), text-only. ``extractor`` is None for rules mode."""
    if extractor is None or not use_llm:
        reading, info = rig.rules.extract(text, Reference())
        rules_reading = reading
    else:
        reading, info = extractor.extract(text, Reference(), use_llm=True)
        rules_reading = rig.rules.extract(text, Reference())[0]
    rubric = rig.deriver.combine(text, rules_reading, reading.ai_rubric)
    market = assess_market(REPORT_TIME, None, None, rig.scorer.cfg.regime)
    sev = rig.scorer.score(SeverityInputs(reading=reading, rubric=rubric, market=market, novelty=None, source_type="NEWS", corroborating_at_event_time=0))
    return {"mode": info.mode.value, "fallback": info.fallback_reason, "event_type": reading.event_type, "score": sev.score if sev else None,
            "baseline_score": sev.baseline_score if sev else None, "range": [sev.low, sev.high] if sev else None,
            "rubric": {f.id: {"rules": f.baseline, "ai": f.ai, "final": f.final, "adjustment": f.adjustment} for f in rubric} if sev else None,
            "inferred_indicators": sum(1 for h in reading.severity_indicators if h.basis.value == "INFERRED"),
            "quoted_indicators": sum(1 for h in reading.severity_indicators if h.basis.value != "INFERRED")}


def band_of(score: int) -> str:
    return next(b for b, (lo, hi) in BAND_RANGE.items() if lo <= score <= hi)


def _rank(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    out = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = _rank(a), _rank(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True)) / den if den else float("nan")


def percentile(values: list[float], p: float) -> float:
    v = sorted(values)
    k = (len(v) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def summarise(rows: list[dict[str, Any]], results: list[dict[str, Any]], *, spearman_min: float, min_per_band: int = 3) -> dict[str, Any]:
    """The distribution, the agreement with the pre-registered bands and the pre-registered criteria (each reported pass/fail)."""
    scores = [r["score"] if r["score"] is not None else 1 for r in results]
    exp = [BANDS.index(x["expected_band"]) + 1 for x in rows]
    got = [BANDS.index(band_of(s)) + 1 for s in scores]
    n = len(scores)
    rho = spearman([float(x) for x in exp], [float(s) for s in scores])
    exact = sum(a == b for a, b in zip(exp, got, strict=True)) / n
    within1 = sum(abs(a - b) <= 1 for a, b in zip(exp, got, strict=True)) / n
    band_counts = Counter(band_of(s) for s in scores)
    groups: dict[str, list[int]] = {}
    for x, s in zip(rows, scores, strict=True):
        groups.setdefault(x["group"].split()[0], []).append(s)
    med = {g: statistics.median(v) for g, v in groups.items()}
    gross = [x["id"] for x, s in zip(rows, scores, strict=True)
             if (x["expected_band"] == "extreme" and s < 7) or (x["expected_band"] == "negligible" and s > 4)]
    criteria = {
        "1_rank_agreement": {"value": round(rho, 3), "min": spearman_min, "pass": rho >= spearman_min},
        "2a_exact_band": {"value": round(exact, 3), "min": 0.70, "pass": exact >= 0.70},
        "2b_within_one_band": {"value": round(within1, 3), "min": 0.90, "pass": within1 >= 0.90},
        "3_no_gross_misses": {"value": gross, "pass": not gross},
        "4_spread": {"value": {"min": min(scores), "max": max(scores), "p10": percentile(scores, 10), "p90": percentile(scores, 90),
                               "bands_occupied": [b for b in BANDS if band_counts.get(b, 0) >= min_per_band], "min_per_band": min_per_band},
                     "pass": min(scores) <= 2 and max(scores) >= 9 and percentile(scores, 10) <= 3 and percentile(scores, 90) >= 8
                     and all(band_counts.get(b, 0) >= min_per_band for b in BANDS)},
        "5_monotone_groups": {"value": {k: med[k] for k in ("G", "E", "C", "A")}, "pass": med["G"] > med["E"] > med["C"] > med["A"]},
    }
    exp_counts = Counter(x["expected_band"] for x in rows)
    return {
        "n": n, "abstained": sum(1 for r in results if r["score"] is None),
        "min": min(scores), "max": max(scores), "mean": round(statistics.mean(scores), 2), "median": statistics.median(scores),
        "p10": percentile(scores, 10), "p25": percentile(scores, 25), "p75": percentile(scores, 75), "p90": percentile(scores, 90),
        "score_counts": dict(sorted(Counter(scores).items())), "band_counts": {b: band_counts.get(b, 0) for b in BANDS},
        "expected_band_counts": {b: exp_counts.get(b, 0) for b in BANDS}, "group_medians": med,
        "spearman": round(rho, 3), "exact_band": round(exact, 3), "within_one_band": round(within1, 3),
        "criteria": criteria, "all_criteria_pass": all(c["pass"] for c in criteria.values()),
        "mean_ai_effect": round(statistics.mean((r["score"] - r["baseline_score"]) for r in results if r["score"] is not None), 2) if any(r["score"] is not None for r in results) else 0.0,
        "fallbacks": sum(1 for r in results if r["fallback"]),
        "items": [{"id": x["id"], "group": x["group"], "text": x["text"], "expected": x["expected_band"], "score": r["score"], "band": band_of(s),
                   "baseline_score": r["baseline_score"], "range": r["range"], "event_type": r["event_type"], "rubric": r["rubric"],
                   "inferred_indicators": r["inferred_indicators"]} for x, r, s in zip(rows, results, scores, strict=True)],
    }


def evaluate_rules(rig: Rig | None = None, ds: Dataset = DEV) -> dict[str, Any]:
    rig = rig or Rig.build()
    rows = load_rows(ds.path)
    return summarise(rows, [score_text(rig, r["text"], None, use_llm=False) for r in rows], spearman_min=0.80, min_per_band=ds.min_per_band)


def evaluate_recorded(rig: Rig | None = None, ds: Dataset = DEV) -> dict[str, Any]:
    """Replay the recorded real-model outputs from the cache: zero provider calls. A text with no recorded answer would be a cache miss and falls back to the rules
    (reported as ``fallbacks``)."""
    rig = rig or Rig.build()
    all_rows = load_rows(ds.path)
    meta = recording_meta(ds.recorded)
    cache = ExtractionCache(ds.recorded, 100000)
    key = lambda text: cache_key(text[: rig.llm_cfg.max_chars_sent], meta["model"], meta["prompt_version"], rig.vocab.cfg.version)  # noqa: E731
    rows = [r for r in all_rows if cache.get(key(r["text"])) is not None]  # only what was actually recorded: a missing text is reported, never scored by the rules
    missing = [r["id"] for r in all_rows if cache.get(key(r["text"])) is None]
    ex = rig.extractor(NoCallClient(meta["model"]), cache, prompt_version=meta["prompt_version"])
    results = [score_text(rig, r["text"], ex, use_llm=True) for r in rows]
    not_llm = [r["id"] for r, x in zip(rows, results, strict=True) if x["mode"] != "LLM"]
    if not_llm:  # a recorded answer that did not replay would silently turn this into a rules evaluation: refuse
        raise RuntimeError(f"recorded outputs did not replay as LLM answers for {not_llm}: the recording and the code disagree (prompt, vocabulary or model)")
    out = summarise(rows, results, spearman_min=0.85, min_per_band=ds.min_per_band)
    out.update(model=meta["model"], prompt_version=meta["prompt_version"], recorded_for_sha256=meta["benchmark_sha256"], n_total=len(all_rows),
               missing_ids=missing, complete=not missing)
    return out
