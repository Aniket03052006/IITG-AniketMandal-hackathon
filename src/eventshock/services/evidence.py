"""Build the evidence bundle (``pipeline.evidence_card``) from the loaded cards and the committed evidence files. Pure, deterministic, offline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..domain import ImpactLifecycle
from ..modeling.leakage import AT_EVENT_TIME, FEATURE_REGISTRY, POST_EVENT, SHORTCUT, availability_class
from ..pipeline.event_card import EventModelCard
from ..pipeline.evidence_card import (
    AblationRow,
    BatteryRow,
    CandidateRow,
    CheckRow,
    ContrastRow,
    CostRow,
    DataFoundation,
    EvidenceBundle,
    FeatureRow,
    GoldSummary,
    Increment,
    ProbeRow,
    ProtocolRun,
    RepresentationView,
    SourceFile,
    SourceRow,
    StageStatus,
    StudyView,
    TrackF,
    YearCount,
)
from ..pipeline.impact_card import Estimate, ImpactModelCard
from ..pipeline.impact_features_v2 import RUNGS_V2, feature_group_v2, feature_names_v2, filing_feature_names
from ..pipeline.sentiment_card import SentimentModelCard

STUDY = "docs/evidence/impact_study.json"
BAKEOFF = "docs/evidence/representation_bakeoff.json"
EVENTS = "data/events/manifest.json"
GOLD_V2 = "data/gold_v2/agreement.json"
GOLD_V1 = "data/gold/gold_scores.json"


def _read(root: Path, rel: str) -> tuple[dict[str, Any] | None, SourceFile | None]:
    p = root / rel
    if not p.is_file():
        return None, None
    raw = p.read_bytes()
    return json.loads(raw), SourceFile(file=rel, sha256=hashlib.sha256(raw).hexdigest())


def _est(d: dict[str, Any] | None) -> Estimate:
    return Estimate(value=None) if not d else Estimate(value=d.get("value"), lo=d.get("lo"), hi=d.get("hi"))


def verdict_of(d: dict[str, Any] | None) -> str:
    """Words for a paired error difference (negative = the block helps) from its interval."""
    if not d or d.get("value") is None or d.get("lo") is None:
        return "not evaluable"
    if d["hi"] < 0:
        return "helps"
    if d["lo"] > 0:
        return "hurts"
    return "no measurable effect"


# ------------------------------------------------------------------------------------------------------------ stages
def impact_kind(card: ImpactModelCard | None) -> tuple[str, str, list[str], list[str], list[str]]:
    if card is None:
        return "placeholder", "No impact model artifact is loaded: the labelled heuristic rule scores every signal.", [], [], []
    served = [s for s in card.scopes if s.served]
    if not served:
        return "placeholder", "No scope reached a servable lifecycle: the labelled heuristic keeps serving.", [], [], []
    parts, passed, failed, na = [], set(), set(), set()
    for s in card.scopes:
        parts.append(f"{s.scope.lower()}: {s.lifecycle.value.lower()}")
        for c in s.acceptance.checks:
            (passed if c.passed is True else failed if c.passed is False else na).add(f"{c.id} ({s.scope.lower()})")
    validated = all(s.lifecycle is ImpactLifecycle.PRODUCTION for s in served)
    return ("validated" if validated else "experimental"), "; ".join(parts), sorted(passed), sorted(failed), sorted(na)


def build_stages(sent: SentimentModelCard | None, ev: EventModelCard | None, imp: ImpactModelCard | None) -> list[StageStatus]:
    out: list[StageStatus] = []
    if sent:
        out.append(StageStatus(stage="sentiment", model_id=sent.id, kind="experimental", artifact_sha256=sent.artifact_sha256,
                               summary="Trained TF-IDF logistic regression, calibrated. No pre-registered acceptance bar was written for it, so it is not called validated."))
    else:
        out.append(StageStatus(stage="sentiment", model_id=None, kind="placeholder", summary="Lexicon rules (demo profile)."))
    if ev:
        ok = ev.acceptance.met
        out.append(StageStatus(
            stage="event", model_id=ev.id, kind="validated" if ok else "experimental", artifact_sha256=ev.artifact_sha256,
            summary="Trained 9-way classifier that can abstain. " + _event_verdict(ev),
            passed=[c.name for c in ev.acceptance.checks if c.passed], failed=[c.name for c in ev.acceptance.checks if not c.passed]))
    else:
        out.append(StageStatus(stage="event", model_id=None, kind="placeholder", summary="Keyword rules (demo profile)."))
    kind, summary, passed, failed, na = impact_kind(imp)
    out.append(StageStatus(stage="impact", model_id=imp.id if imp else None, kind=kind, summary=summary, passed=passed, failed=failed, not_evaluable=na,
                           artifact_sha256=imp.artifact_sha256 if imp else None))
    return out


# ------------------------------------------------------------------------------------------------------------ features
def build_features() -> list[FeatureRow]:
    used: dict[str, list[str]] = {}
    for scope in ("ISSUER", "MARKET"):
        for rung in RUNGS_V2:
            for n in feature_names_v2(scope, rung):
                used.setdefault(n, [])
                tag = f"{scope.lower()}:{rung}"
                if tag not in used[n]:
                    used[n].append(tag)
    for rung in ("F0", "F1", "F2"):
        for n in filing_feature_names(rung):
            used.setdefault(n, [])
            if f"filing:{rung}" not in used[n]:
                used[n].append(f"filing:{rung}")
    rows = []
    for name, (kind, why) in sorted(FEATURE_REGISTRY.items()):
        cls = availability_class(name)
        if name.startswith("item_"):
            cls = "b"
        if kind == AT_EVENT_TIME:
            avail = cls or "t"   # t: from the report's own text/timestamp or from prices before it
        elif kind == POST_EVENT:
            avail = "c"
        elif kind == SHORTCUT:
            avail = "shortcut"
        else:
            avail = kind.lower()
        rows.append(FeatureRow(name=name, group=feature_group_v2(name), availability=avail, allowed=kind == AT_EVENT_TIME, used_by=sorted(used.get(name, [])), why=why))
    return rows


# ------------------------------------------------------------------------------------------------------------ data foundation
SOURCES = [
    ("Twitter: top companies (Kaggle, 6 issuers)", "social", "2015-2019", "top-tweets", "publisher time", "hash-sampled; CC0"),
    ("Twitter: stock tweets (Kaggle, 25 tickers)", "social", "2021-09..2022-09", "stock-tweets", "publisher time", "CC0"),
    ("Reuters / CNBC / Guardian headlines (Kaggle)", "news", "2017-2020", "headlines", "date only", "CC0; no ticker tags"),
    ("GDELT GKG, 2026 window", "news", "2026-02..2026-09", "gdelt-gkg", "publisher time where valid, else GDELT first-seen", "titles only; free reuse with citation"),
    ("GDELT GKG, 2023-2025 sample (new)", "news", "2023-01..2025-12", "gdelt-gkg-2023-25", "publisher time where valid, else GDELT first-seen",
     "six fixed 15-minute files per UTC day (about 6% of the flow), titles only"),
]


def build_data(root: Path, study: dict[str, Any] | None) -> tuple[DataFoundation, list[SourceFile]]:
    files: list[SourceFile] = []
    events, sf = _read(root, EVENTS)
    if sf:
        files.append(sf)
    g2, sf2 = _read(root, GOLD_V2)
    if sf2:
        files.append(sf2)
    g1, sf1 = _read(root, GOLD_V1)
    if sf1:
        files.append(sf1)
    if study is None and events is None:
        return DataFoundation(available=False, command="make impact-study events-calendar"), files
    ds = (study or {}).get("dataset", {})
    by_source = ds.get("by_scope_source", {}).get("ISSUER", {}) if ds else {}
    rows = []
    for name, kind, period, key, ts, note in SOURCES:
        rows.append(SourceRow(name=name, kind=kind, period=period, records=by_source.get(key), timestamps=ts, note=note))
    if events:
        filings = events["sources"]["sec_filings"]["rows"]
        rows.append(SourceRow(name="SEC EDGAR filings (8-K items, 10-K, 10-Q, 6-K, 20-F)", kind="filing", period="2014-2026", records=filings,
                              timestamps="exact SEC acceptance time (UTC)", note="public domain; 8-K item codes are the official event type"))
        rows.append(SourceRow(name="FOMC decision dates", kind="calendar", period="2014-2026", records=events["sources"]["fomc"]["meetings"],
                              timestamps="scheduled date (announced ahead); unscheduled meetings flagged and not used", note="federalreserve.gov, public domain"))
    rows.append(SourceRow(name="Daily prices, 34 issuers + S&P 500, VIX, 10y yield", kind="prices", period="2014-2026", records=None, timestamps="session close",
                          note="Yahoo chart endpoint, research use, not redistributed (only derived statistics are frozen for serving)"))
    year: dict[str, YearCount] = {}
    if study:
        for scope, d in (study.get("dataset", {}).get("episodes_by_year") or {}).items():
            for y, n in d.items():
                yc = year.setdefault(y, YearCount(year=y))
                setattr(yc, "issuer" if scope == "ISSUER" else "market", n)
        for y, n in (study.get("track_f", {}).get("events_by_year") or {}).items():
            year.setdefault(y, YearCount(year=y)).filing_events = n
    gold = []
    n1 = int((g1 or {}).get("labelled") or 400)
    gold.append(GoldSummary(name="Gold v1 (frozen)", rows=n1, labelled_by="one AI annotator (ai:claude), blind", human_reviewed=int((g1 or {}).get("overridden_by_human") or 0),
                            note="evaluation only; EARNINGS 14 rows, CREDIT_FUNDING 10; no independent annotator"))
    if g2:
        gold.append(GoldSummary(name="Gold v2 (2023-2025)", rows=g2["rows"], labelled_by="two independent blind AI passes with different prompts and orderings",
                                agreement=g2["overall"]["agreement"], kappa=g2["overall"]["kappa"], agreed_rows=g2["agreed_rows"], human_reviewed=0,
                                note="same-family agreement (bounds label noise, not human kappa); disagreements are queued for human adjudication"))
    gaps = list((events or {}).get("known_gaps", []))
    gaps += ["News for 2023-2025 is a deterministic 6%-of-the-flow sample of GDELT GKG titles, not a complete archive.",
             "Only 34 large issuers; severity does not transfer to small or distressed companies."]
    held = (study or {}).get("dataset", {}).get("by_scope_protocol_split_episodes", {})
    return DataFoundation(available=True, sources=rows, episodes_by_year=[year[k] for k in sorted(year)],
                          held_out={sc: {f"{p}/{sp}": n for p, d in v.items() for sp, n in d.items()} for sc, v in held.items()},
                          calendar_filings=events["sources"]["sec_filings"]["rows"] if events else None, calendar_fomc=events["sources"]["fomc"]["meetings"] if events else None,
                          gold=gold, exclusions=(study or {}).get("dataset", {}).get("exclusions", {}), known_gaps=gaps,
                          command="make fetch-gkg-2023 history-v2 ingest-history-v2 impact-table-v2 events-calendar"), files


# ------------------------------------------------------------------------------------------------------------ the study
def _inc_rows(inc: dict[str, Any], limit_where: tuple[str, ...] = ("oof", "test", "live")) -> list[Increment]:
    names = {"calendar": "calendar block (earnings dates, 8-K recency, FOMC)", "text_given_calendar": "text-model outputs, given the calendar",
             "text_alone": "text-model outputs (event type, sentiment)", "calendar_and_text": "calendar and text together"}
    out = []
    for fam, blocks in inc.items():
        for block, wheres in blocks.items():
            for where in limit_where:
                d = wheres.get(where)
                if d:
                    out.append(Increment(block=names.get(block, block), family=fam, where=where, delta_mae=_est(d), verdict=verdict_of(d)))
    return out


def _run_view(key: str, run: dict[str, Any]) -> ProtocolRun:
    proto, scope = key.split("/")
    view = ProtocolRun(protocol=proto, scope=scope, status=run.get("status", ""), episodes=run.get("episodes", {}), selected=run.get("selected"),
                       best_state=run.get("best_state_model"), best_block=run.get("best_block_model"))
    if run.get("status") != "ok":
        view.verdict = run.get("status", "not run")
        return view
    view.checks = [CheckRow(**c) for c in run.get("checks", [])]
    view.increments = _inc_rows(run.get("increments", {}))
    h = run.get("by_year", {}).get("helpful", {})
    if h.get("periods"):
        view.years_helpful = f"{h['helpful']} of {h['periods']} years"
    bat = run.get("battery", {})
    sets = run.get("sets", {})
    for role in ("selected", "best_state", "best_block"):
        e = bat.get(role)
        if not e:
            continue
        for name in ("test", "live"):
            ns = e.get(f"neutral_skill_{name}")
            if not ns:
                continue
            m = sets.get(name, {}).get("models", {}).get(e["model"], {})
            gap = None
            if m.get("spearman", {}).get("value") is not None and m.get("placebo_spearman") is not None:
                gap = round(m["spearman"]["value"] - m["placebo_spearman"], 4)
            wi = e.get(f"within_issuer_skill_{name}") or {}
            view.battery.append(BatteryRow(model=e["model"], role=role, set=name, neutral_skill=Estimate(value=ns["value"], lo=ns["lo"], hi=ns["hi"]),
                                           within_issuer_skill=wi.get("value"), placebo_gap=gap))
    for block, d in bat.get("ablation", {}).get("blocks", {}).items():
        p = d["permutation_within_issuer_month"]
        view.ablation.append(AblationRow(block=f"{block} ({d['model']})", method="shuffled among the same issuer and month", spearman_lost=round(p["spearman_lost"], 4),
                                         mae_added=round(p["mae_added"], 4), mae_added_lo=round(p["mae_added_lo"], 4), mae_added_hi=round(p["mae_added_hi"], 4)))
        v = d["leave_block_out"]
        view.ablation.append(AblationRow(block=f"{block} ({d['model']})", method="replaced by its training median", spearman_lost=round(v["spearman_lost"], 4), mae_added=round(v["mae_added"], 4)))
    failed = [c.id for c in view.checks if c.passed is False]
    na = [c.id for c in view.checks if c.passed is None]
    view.verdict = ("Every evaluable check passed" if not failed and not na else f"failed {', '.join(failed) or 'none'}; not evaluable {', '.join(na) or 'none'}")
    return view


def _contrast(label: str, d: dict[str, Any] | None) -> ContrastRow | None:
    if not d:
        return None
    return ContrastRow(label=label, pairs=d["n_pairs"], lift=Estimate(value=d["lift"], lo=d["lo"], hi=d["hi"]), auc=d.get("auc"))


def _track_f(tf: dict[str, Any] | None) -> TrackF:
    if not tf:
        return TrackF(available=False)
    names = {"item_earnings": "earnings (item 2.02)", "item_deal": "deals (1.01, 1.02, 2.01, 5.01)", "item_distress": "distress (1.03, 2.04, 3.01, 4.02, 2.06)",
             "item_financing": "financing (2.03, 3.02)", "item_leadership": "officer changes (5.02)", "item_other": "other items (7.01, 8.01, 5.07, ...)"}
    by_item = [r for g, d in tf.get("by_item_group", {}).items() if (r := _contrast(names.get(g, g), d))]
    ey = [r for y, d in tf.get("earnings_by_year", {}).items() if (r := _contrast(y, d))]
    ny = [r for y, d in tf.get("non_earnings_by_year", {}).items() if (r := _contrast(y, d))]
    inc: list[Increment] = []
    m = tf.get("models", {}).get("P2_extended", {})
    for where, sd in (m.get("sets") or {}).items():
        if where not in ("test", "val+test", "live"):
            continue
        for k, d in sd.get("increments", {}).items():
            if k.startswith(("F2_vs_F1", "F2_vs_F0", "F1_vs_F0")):
                a, b = k.split("-")[0].split("_vs_")
                inc.append(Increment(block={"F1": "calendar", "F2": "filing's own item codes"}[a] + f" over {b}", family=k.split("-")[1], where=where,
                                     delta_mae=_est(d), verdict=verdict_of(d)))
    return TrackF(available=True, pairs=tf.get("pairs", 0), headline=_contrast("all filing events vs matched quiet sessions (excluding in-session filings)",
                                                                                 tf.get("excluding_in_session_filings")),
                  by_item=by_item, earnings_by_year=ey, non_earnings_by_year=ny, item_code_increment=inc, note=tf.get("note", ""))


def build_study(study: dict[str, Any] | None, sf: SourceFile | None) -> StudyView:
    if not study:
        return StudyView(available=False, command="make impact-table-v2 filing-events impact-study")
    p1 = study.get("p1_regression", {})
    return StudyView(available=True, preregistration=SourceFile(file=study["preregistration"]["file"], sha256=study["preregistration"]["sha256"]),
                     p1_regression=p1.get("statement", p1.get("status", "")), runs=[_run_view(k, v) for k, v in sorted(study.get("runs", {}).items(), key=lambda kv: (not kv[0].startswith("P2"), "ISSUER" not in kv[0]))],
                     track_f=_track_f(study.get("track_f")), command="make impact-study")


# ------------------------------------------------------------------------------------------------------------ representation
def build_representation(b: dict[str, Any] | None) -> RepresentationView:
    if not b:
        return RepresentationView(available=False, command="make bakeoff-texts bakeoff-embed bakeoff")
    cands = []
    for cid, c in sorted(b["candidates"].items()):
        checks = c.get("adoption_checks", {})
        pd = checks.get("served_macro_f1_delta", {})
        ci = pd.get("ci95") or [None, None]
        detail = c["params"].get("dense") or ", ".join(f"{k}={v}" for k, v in c["params"].items() if k not in ("affect_models", "dense"))
        cands.append(CandidateRow(id=cid, family=c["family"], detail=str(detail), pooled_delta_f1=Estimate(value=pd.get("value"), lo=ci[0], hi=ci[1]),
                                  checks_passed=[k for k, v in checks.items() if v["passed"]], checks_failed=[k for k, v in checks.items() if not v["passed"]],
                                  adopt=bool(c.get("adopt"))))
    cost = [CostRow(model=m, kind=c["kind"], parameters_m=c.get("parameters_m"), ms_per_text_batch1=c.get("ms_per_text_batch1"),
                    ms_per_text_batch32=c.get("ms_per_text_batch32"), peak_rss_mb=c.get("peak_rss_mb"), controlled=bool(c.get("controlled")),
                    deterministic=c.get("deterministic_double_run")) for m, c in sorted(b.get("cost", {}).items())]
    probe = [ProbeRow(channel=k, pairs=v["pairs"], share_correct=v["share_correct"], lo=v["ci95"][0], hi=v["ci95"][1]) for k, v in b.get("polarity_probe", {}).items()]
    base_f1 = b.get("baseline", {}).get("sets", {}).get("pooled", {}).get("served_macro_f1")
    return RepresentationView(available=True, decision=b["decision"]["statement"], baseline=b["baseline"]["id"], sets={k: v["n"] for k, v in b["sets"].items()},
                              baseline_pooled_f1=base_f1, candidates=cands, cost=cost, probe=probe, command="make bakeoff")


LIMITS = [
    "Evidence is chronological and pre-registered, but still small: the held-out windows are one or two calendar years and a few hundred to a few thousand episodes per scope.",
    "The target is a coincident market-response proxy: coverage is partly a reaction to a move, so the model measures how large a response tends to be around a report, not a forecast made before anyone knew.",
    "All labels are AI-annotated; agreement between two passes of the same annotator family bounds label noise but is not human inter-annotator agreement.",
    "34 large current issuers: survivorship bias; severity does not transfer to small or distressed companies.",
    "Realised earnings surprise needs consensus estimates (not free data): never used, never a feature.",
]


def _event_verdict(ev: EventModelCard) -> str:
    """One honest sentence from the card's own checks: all met, none met, or (the hybrid) the scored bars met but no independent set exists."""
    if ev.acceptance.met:
        return "It met its pre-registered bar."
    checks = ev.acceptance.checks
    failed = [c for c in checks if not c.passed]
    if checks and len(failed) < len(checks):
        return (f"It passed {len(checks) - len(failed)} of {len(checks)} checks, but not all of them, so it is not called validated "
                f"(missing: {'; '.join(c.name for c in failed)}).")
    return "It did NOT meet its pre-registered bar on the gold set."


def build_evidence(root: Path, sentiment: SentimentModelCard | None, event: EventModelCard | None, impact: ImpactModelCard | None) -> EvidenceBundle:
    study, sf_study = _read(root, STUDY)
    bake, sf_bake = _read(root, BAKEOFF)
    data, data_files = build_data(root, study)
    files = [f for f in (sf_study, sf_bake) if f] + data_files
    return EvidenceBundle(generated_from=files, stages=build_stages(sentiment, event, impact), data=data, features=build_features(), study=build_study(study, sf_study),
                          representation=build_representation(bake), limitations=LIMITS)
