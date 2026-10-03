"""Train, calibrate, evaluate and write ``impact-v2``: the impact model of the Stage 4 protocol (``models/impact/impact-v2/``).

The evidence study (``impact_study``) answered, at the episode level, whether the structured calendar block adds anything beyond market state. This module turns that answer into a
served artifact *the way it will serve*: document-level rows (like impact-v1), the same nested chain and adoption rule, the extended chronological protocol (train through 2023, val 2024, test 2025,
live 2026 news, five-session embargo), rank calibration from out-of-fold predictions, and the acceptance checks of ``configs/impact_model.yaml`` (C1-C8) evaluated by the artifact.
C9-C11 (added in ``configs/evidence_v2.yaml``) are taken from the study for the same scope, because they need the episode-level quantities it computes; their source is stated on each check.

Whether it replaces impact-v1 is not assumed: the card carries a paired comparison against impact-v1 on the same held-out episodes, and the config chooses which artifact serves.

    python -m eventshock.modeling.impact_train_v2 [--dev-only OUT_DIR]
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import sys
from pathlib import Path

import joblib
import numpy as np

from ..config import REPO_ROOT, ConfigError
from ..domain import ImpactLifecycle
from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..pipeline.config import load_impact_model_config
from ..pipeline.event_context import EventCalendar
from ..pipeline.impact_card import (
    ARTIFACT_FILE,
    CARD_FILE,
    AcceptanceCheck,
    ImpactModelCard,
    PreviousComparison,
)
from ..pipeline.impact_features import ISSUER, SCOPES
from ..pipeline.impact_features_v2 import FEATURE_SCHEMA_V2, feature_names_v2
from ..pipeline.impact_model import PAYLOAD_SCHEMA, ImpactModel
from .config import load_modeling_config
from .impact_dataset import load_table
from .impact_stats import boot_indices, delta_mae_estimate, make_view, spearman_estimate
from .impact_study import make_steps, study_cfg
from .impact_train import ScopeRun, Variant, run_scope
from .study_config import load_study_config

MODEL_ID = "impact-v2"
TITLES = {"val": "2024, GKG news (checkpoint)", "test": "2025, GKG news (read once)", "val+test": "2024-2025 pooled",
          "live": "2026 news, all timestamps (read once)", "live_reliable": "2026 news, publisher timestamps outside trading hours"}

LIMITATIONS = [
    "Held-out evidence is two calendar years of GDELT news titles (2024 val, 2025 test) plus 2026 news, a deterministic six-slots-a-day sample of GDELT (about 6% of the flow), titles only. "
    "Far larger than impact-v1's 2022 hold-out, but still one regime; it says nothing about a crisis year it never saw.",
    "Most of what the model predicts is the volatility regime: it predicts the window BEFORE the event better than the window after it (check C7). The event-specific part is the structured calendar "
    "(mainly: an earnings release is expected, or an earnings 8-K was just filed), worth about two percent of the error; the text-model outputs add nothing measurable once the calendar is known.",
    "The target is a coincident market-response proxy: coverage is partly a reaction to a move, so this is not a clean forecast.",
    "34 current large caps: severity is calibrated for them and does not transfer to small or distressed issuers (survivorship).",
    "The calendar is read from SEC EDGAR acceptance times and the Federal Reserve's published meeting dates: scheduled-meeting dates are announced ahead, but they were read from a 2026 snapshot. "
    "An earnings date is inferred from the issuer's own earlier filings, not from an announced date.",
    "Consensus earnings estimates are not free data, so the realised earnings surprise is never an input; only whether and when earnings are expected.",
    "Checks C9-C11 are computed at the episode level by the evidence study; the other checks are computed here at the level the model serves. A scope that fails any check is experimental.",
]


def calendar_pins(cal: EventCalendar) -> dict[str, str]:
    return dict(cal.digests)


def study_checks_for(root: Path):
    """C9-C11 from the committed study (same scope, extended protocol), labelled with their source and the model the study selected."""
    p = root / "docs/evidence/impact_study.json"
    study = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def fn(scope: str, chosen: str, results) -> list[AcceptanceCheck]:
        run = (study or {}).get("runs", {}).get(f"P2_extended/{scope}")
        out = []
        for cid in ("C9", "C10", "C11"):
            c = next((x for x in (run or {}).get("checks", []) if x["id"] == cid), None)
            if c is None:
                out.append(AcceptanceCheck(id=cid, label=f"{cid} (evidence study)", passed=None, value="n/a", detail="docs/evidence/impact_study.json is absent: run `make impact-study`"))
                continue
            out.append(AcceptanceCheck(id=cid, label=c["label"], passed=c["passed"], value=c["value"],
                                       detail=f"from the episode-level evidence study (docs/evidence/impact_study.json; its selected model {run['selected']}, "
                                              f"this artifact's {chosen}): {c['detail']}"))
        return out

    return fn


def compare_with_v1(runs: dict[str, ScopeRun], rows: list[dict], v1_dir: Path, cfg, *, resamples: int, seed: int) -> list[PreviousComparison]:
    """Paired comparison on the same held-out episodes: v2's selected model against impact-v1's served model, both scored from the table's own features."""
    p1 = joblib.load(v1_dir / ARTIFACT_FILE)
    out: list[PreviousComparison] = []
    for scope in SCOPES:
        run = runs.get(scope)
        if run is None or run.payload is None or scope not in p1["scopes"]:
            continue
        part = [r for r in rows if r["scope"] == scope]
        for set_id, keep in (("val+test", lambda r: r["split_P2_extended"] in ("val", "test")), ("live", lambda r: r["split_P2_extended"] == "live")):
            sel = [r for r in part if keep(r)]
            if len(sel) < 50:
                continue
            new = run.payload["model"].predict(_matrix(sel, run.payload["features"]))
            old = p1["scopes"][scope]["model"].predict(_matrix(sel, p1["scopes"][scope]["features"]))
            eps = np.array([r["episode"] for r in sel])
            y = np.log1p(np.array([r["abs_z"] for r in sel], dtype=float))
            absz = np.array([r["abs_z"] for r in sel], dtype=float)
            sc = np.array([r["score"] for r in sel], dtype=int)
            pl = np.array([np.nan if r.get("placebo_abs_z") is None else r["placebo_abs_z"] for r in sel], dtype=float)
            view = make_view(eps, y, absz, sc, pl)
            ib = boot_indices(view.n_ep, resamples, seed)
            a, b = view.aggregate(new), view.aggregate(old)
            out.append(PreviousComparison(scope=scope, previous_id="impact-v1", set_id=set_id, n_episodes=view.n_ep, delta_mae=_est(delta_mae_estimate(a, b, view, ib)),
                                          spearman_new=_est(spearman_estimate(a, view.absz, ib)), spearman_previous=_est(spearman_estimate(b, view.absz, ib))))
    return out


def _matrix(rows: list[dict], names: list[str]) -> np.ndarray:
    return np.array([[np.nan if r.get(n) is None else float(r[n]) for n in names] for r in rows], dtype=float)


def _est(e):
    return e


def run(root: Path = REPO_ROOT, dev_only: Path | None = None, log=print) -> int:
    config_dir = root / "configs"
    scfg, study_sha = load_study_config(config_dir)
    base = load_impact_model_config(config_dir)
    mcfg = load_modeling_config(config_dir)
    cfg = study_cfg(base, scfg)
    table, manifest_path = root / "data/modeling/impact_table_v2.jsonl", root / "data/modeling/impact_dataset_v2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    table_sha = sha256_file(table)
    if manifest["table_sha256"] != table_sha or manifest["preregistration"]["sha256"] != study_sha:
        raise ConfigError("the v2 table does not match its manifest or the current pre-registration: rebuild it with `make impact-table-v2`")
    rows = load_table(table)
    log(f"v2 table: {len(rows)} document rows, sha256 {table_sha[:12]}")
    calendar = EventCalendar.load(root / scfg.data["calendar_dir"], root / scfg.data["sec_items"], recent_hours=float(scfg.structured_features["recent_filing_hours"]),
                                  earnings_lookback_years=int(scfg.structured_features["earnings_lookback_years"]))
    var = Variant(names_fn=feature_names_v2, all_names=lambda sc: feature_names_v2(sc, "R3s"), rungs=("R2", "R2s", "R3", "R3s"), split_key="split_P2_extended",
                  ladder=make_steps(scfg.impact.chain), titles=TITLES, limitations=LIMITATIONS, extra_checks=study_checks_for(root), feature_schema=FEATURE_SCHEMA_V2)
    cfg_sha = sha256_file(config_dir / "evidence_v2.yaml")
    cut = list(mcfg.impact.score_cutpoints)
    runs: dict[str, ScopeRun] = {}
    for scope in SCOPES:
        log(f"scope {scope}")
        runs[scope] = run_scope(scope, rows, cfg, cut, table_sha, cfg_sha, dev_only is not None, log, var)
        log(f"  [{scope}] {runs[scope].card.lifecycle.value}: {runs[scope].card.summary}")
    if dev_only is not None:
        dev_only.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dev_only / "dev_report.json", json.dumps({s: r.card.model_dump(mode="json") for s, r in runs.items()}, indent=1, sort_keys=True) + "\n")
        log(f"--dev-only: wrote {dev_only / 'dev_report.json'}; test and live were not scored, nothing was promoted")
        return 0
    out = root / "models/impact" / MODEL_ID
    out.mkdir(parents=True, exist_ok=True)
    art = out / ARTIFACT_FILE
    joblib.dump({"schema": PAYLOAD_SCHEMA, "feature_schema": FEATURE_SCHEMA_V2, "scopes": {s: r.payload for s, r in runs.items() if r.payload is not None}}, art, compress=3)
    sha = sha256_file(art)
    cmp_ = compare_with_v1(runs, rows, root / base.model_dir, cfg, resamples=scfg.impact.bootstrap_resamples, seed=scfg.impact.bootstrap_seed)
    card = ImpactModelCard(
        id=MODEL_ID, version=MODEL_ID, feature_schema=FEATURE_SCHEMA_V2,
        output_definition=("Per scope: predicted log1p(|z|) of the two-session market response (z = abnormal return / trailing sigma), rank-calibrated to a 1-10 EventShock score with an empirical "
                           "uncertainty interval. Inputs: market state, timing, the frozen text-model outputs (read from the TF-IDF event model impact was fitted with) and the structured calendar "
                           "(earnings dates, recent 8-K filings, FOMC), each tagged known-before or published-at-event-time."),
        artifact_file=ARTIFACT_FILE, artifact_sha256=sha, artifact_bytes=art.stat().st_size,
        libraries={k: md.version(k) for k in ("scikit-learn", "numpy", "scipy")},
        dataset={"table_sha256": table_sha, "rows": int(manifest["rows"]), "feature_schema": FEATURE_SCHEMA_V2, "history_signals_sha256": manifest["inputs"]["history_signals"]["sha256"],
                 "modeling_config_digest": manifest["inputs"]["modeling_config_digest"], "preregistration_sha256": study_sha, "calendar": calendar_pins(calendar)},
        selection_rule=("rolling-origin out-of-fold log-severity MAE over the pre-registered nested chain (R0, market state, + calendar, + text-model outputs); a more complex rung is adopted only if its "
                        "paired improvement interval is entirely below zero"),
        scopes=[runs[s].card for s in SCOPES], vs_previous=cmp_)
    (out / CARD_FILE).write_text(json.dumps(card.model_dump(mode="json"), indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    model = ImpactModel.load(out, base.min_link_confidence, calendar)  # the artifact must load through the real serving class
    log(f"wrote {out}  sha256 {sha[:12]}  ({art.stat().st_size / 1e6:.2f} MB); reloaded: served scopes {model.served_scopes}, "
        f"lifecycle { {s: v.value for s, v in model.lifecycle.items()} }")
    for c in cmp_:
        log(f"  vs impact-v1 [{c.scope} {c.set_id}, {c.n_episodes} episodes]: delta MAE {c.delta_mae.value:+.4f} [{c.delta_mae.lo:+.4f}, {c.delta_mae.hi:+.4f}]; "
            f"Spearman {c.spearman_new.value:+.3f} vs {c.spearman_previous.value:+.3f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eventshock.modeling.impact_train_v2")
    ap.add_argument("--dev-only", metavar="OUT_DIR", type=Path)
    args = ap.parse_args(argv)
    return run(REPO_ROOT, args.dev_only)


__all__ = ["ISSUER", "ImpactLifecycle", "main", "run"]

if __name__ == "__main__":
    sys.exit(main())
