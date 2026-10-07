"""``python -m eventshock.modeling <command>``: audit, gold set tooling and probes."""

from __future__ import annotations

import argparse
import json
import sys

from ..config import REPO_ROOT, ConfigError
from ..pipeline.topics import load_topic_mapping
from .audit import run_audit
from .config import load_modeling_config
from .leakage import LeakageError

CONFIG_DIR = REPO_ROOT / "configs"
OUT_DIR = REPO_ROOT / "data" / "modeling"


def _audit(args: argparse.Namespace) -> int:
    cfg = load_modeling_config(CONFIG_DIR)
    gold_ids: set[str] = set()
    manifest = REPO_ROOT / "data" / "gold" / "gold_manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text(encoding="utf-8"))
        gold_ids = {r["origin_id"] for r in m["items"].values() if str(r.get("origin_id", "")).startswith("tfn-topic-")}
    res = run_audit(cfg, repo_root=REPO_ROOT, config_dir=CONFIG_DIR, mapping=load_topic_mapping(CONFIG_DIR), out_dir=OUT_DIR,
                    gold_topic_ids=gold_ids)
    imp = res["impact"]
    print(f"config digest {res['config_digest']}  ->  {OUT_DIR / 'audit.json'}")
    print(f"impact: {imp['eligible_rows']} eligible rows in {imp['episodes']} ticker-sessions; drops {imp['drops']}")
    print(f"        split rows {imp['split_rows']}; share score>=7: rows {imp['share_score_ge_7_rows']}, episodes {imp['share_score_ge_7_episodes']}")
    for sec in ("impact", "text"):
        for f in res[sec]["findings"]:
            print(f"  [{f['severity']}] {f['check']}: {f['detail']}")
    if res["errors"]:
        print(f"{len(res['errors'])} leakage ERROR(s)", file=sys.stderr)
        return 1
    return 0


def _probe(args: argparse.Namespace) -> int:
    from ..pipeline.config import load_enrichment_config
    from .gold_cli import probe_gold
    from .probe import run_probe

    res = run_probe(OUT_DIR, load_enrichment_config(CONFIG_DIR), OUT_DIR / "probe.json")
    sent, ev, imp = res["sentiment"], res["event"], res["impact"]
    f = lambda d: f"acc {d['accuracy']:.3f}  macro-F1 {d['macro_f1']:.3f}"  # noqa: E731
    print(f"sentiment (C={sent['chosen_C']}, train {sent['train_rows']}) re-split test:")
    for k, v in sent["test"].items():
        print(f"  {k:20s} {f(v)}")
    print(f"  published-valid tfidf {f(sent['published_valid_tfidf_logreg'])}   <- published split: carries near-duplicate leakage")
    if "phrasebank_eval_only" in sent:
        for k, v in sent["phrasebank_eval_only"].items():
            print(f"  phrasebank {k:20s} {f(v)}")
    print(f"event (trainable tiers, classes {len(ev['classes'])}, train {ev['train_rows']}) re-split test:")
    for k, v in ev["test"].items():
        print(f"  {k:20s} {f(v)}")
    print(f"  published-valid tfidf {f(ev['published_valid_tfidf_logreg'])}   <- published split: carries near-duplicate leakage")
    print("impact (tabular event-time features only, no text):")
    for split, d in imp["splits"].items():
        print(f"  {split:5s} " + "  ".join(f"{t}: rho {v['spearman']:+.3f} lift {v['top_decile_lift']:.2f} (n={v['n']})" for t, v in d.items()))
    probe_gold(res)
    return 0


def _train_sentiment(args: argparse.Namespace) -> int:
    from .sentiment_train import main as train_main

    return train_main(["--config", args.config] if getattr(args, "config", None) else [])


def _train_event(args: argparse.Namespace) -> int:
    from .event_train import main as train_main

    return train_main(["--dev-only", args.dev_only] if args.dev_only else [])


def _impact_table(args: argparse.Namespace) -> int:
    from .impact_dataset import build_dataset

    m = build_dataset(repo_root=REPO_ROOT, config_dir=CONFIG_DIR)
    print(f"impact table: {m['rows']} rows  sha256 {m['table_sha256'][:12]}  ->  {m['table']}")
    for scope in ("ISSUER", "MARKET"):
        print(f"  {scope}: rows {m['by_scope_split_rows'][scope]}  episodes {m['by_scope_split_episodes'][scope]}")
        print(f"          excluded {m['exclusions'][scope]}")
    print(f"  text stage excluded {m['text_stage_exclusions']}")
    return 0


def _impact_table_v2(args: argparse.Namespace) -> int:
    from .impact_dataset_v2 import build_dataset_v2

    m = build_dataset_v2(repo_root=REPO_ROOT, config_dir=CONFIG_DIR, history_signals=REPO_ROOT / "data/processed/history_v2/signals.jsonl",
                         out_table=REPO_ROOT / "data/modeling/impact_table_v2.jsonl", out_manifest=REPO_ROOT / "data/modeling/impact_dataset_v2.json")
    print(f"impact table v2: {m['rows']} rows  sha256 {m['table_sha256'][:12]}  ->  {m['table']}")
    for scope in ("ISSUER", "MARKET"):
        print(f"  {scope}: episodes by protocol {m['by_scope_protocol_split_episodes'][scope]}")
        print(f"          by year {m['by_scope_year'][scope]}")
        print(f"          excluded {m['exclusions'][scope]}")
    print(f"  text stage excluded {m['text_stage_exclusions']}")
    return 0


def _filing_events(args: argparse.Namespace) -> int:
    from .filing_events import build_filing_table

    m = build_filing_table(repo_root=REPO_ROOT, config_dir=CONFIG_DIR, out_table=REPO_ROOT / "data/modeling/filing_events.jsonl",
                           out_manifest=REPO_ROOT / "data/modeling/filing_events.json")
    print(f"filing events: {m['event_episodes']} event episodes, {m['matched_pairs']} matched controls  sha256 {m['table_sha256'][:12]}")
    print(f"  by year {m['events_by_year']}")
    print(f"  by item group {m['events_by_item_group']}  excluded {m['exclusions']}")
    return 0


def _impact_study(args: argparse.Namespace) -> int:
    from .impact_study import main as study_main

    return study_main(["--dev-only"] if args.dev_only else [])


def _train_impact(args: argparse.Namespace) -> int:
    from .impact_train import main as train_main

    return train_main(["--dev-only", args.dev_only] if args.dev_only else [])


def _outcome_audit(args: argparse.Namespace) -> int:
    from .outcome_audit import run_audit

    out = REPO_ROOT / "docs" / "evidence" / "outcome_audit.json"
    res = run_audit(REPO_ROOT, CONFIG_DIR, out)
    d = res["decision"]
    print(f"decision: {d['outcome_version']} (adopt EWMA sigma: {d['adopt_ewma']}); checks {d['checks']}")
    return 0


def _severity_validity(args: argparse.Namespace) -> int:
    from .severity_validity import run_validity

    out = REPO_ROOT / "docs" / "evidence" / ("severity_validity.json" if not args.limit else "severity_validity.smoke.json")
    res = run_validity(REPO_ROOT, CONFIG_DIR, out, limit=args.limit)
    print(f"label: {res['label']['label']}")
    for name in ("dev", "test", "live"):
        m = res["by_split"][name].get("metrics")
        if m:
            print(f"  {name:5s} n={res['by_split'][name]['n']:5d}  " + "  ".join(f"{k.split('_')[0]} {v['estimate']:+.3f} [{v['lo'] if v['lo'] is not None else float('nan'):+.3f},{v['hi'] if v['hi'] is not None else float('nan'):+.3f}]"
                                                                               for k, v in m.items()))
    return 0


def _analogue_corpus(args: argparse.Namespace) -> int:
    from ..retrieval.corpus import build_corpus

    m = build_corpus(REPO_ROOT, CONFIG_DIR, OUT_DIR)
    print(f"  by clock {m['counts']['clock']}\n  by split {m['counts']['split']}")
    return 0


def _analogue_relevance(args: argparse.Namespace) -> int:
    from ..retrieval.relevance_eval import run_relevance

    r = run_relevance(REPO_ROOT, CONFIG_DIR, REPO_ROOT / "docs" / "evidence" / "analogue_relevance.json")
    for name, m in r["metrics"].items():
        d = m["delta_p_at_5_e5_minus_tfidf"]
        print(f"  {name:24s} n={m['queries']:3d} base {m['base_rate']:.3f}  P@5 e5 {m['e5']['p_at_5']:.3f} tfidf {m['tfidf']['p_at_5']:.3f}  "
              f"delta {d['estimate']:+.3f} [{d['lo']:+.3f},{d['hi']:+.3f}]")
    print(f"decision: {r['decision']['served_retriever']}")
    return 0


def _analogue_index(args: argparse.Namespace) -> int:
    from ..retrieval.build import build_index, index_pack_dir

    idx = build_index(REPO_ROOT, CONFIG_DIR)
    m = idx.save(index_pack_dir(REPO_ROOT))
    print(f"analogue index: {m['rows']} trusted episodes/documents, {m['dims']} dims, {m['bytes']['vectors'] / 1e6:.1f} MB vectors + {m['bytes']['rows'] / 1e6:.1f} MB rows")
    return 0


def _analogue_floor(args: argparse.Namespace) -> int:
    from ..retrieval.outcome_value import run_floor

    r = run_floor(REPO_ROOT, CONFIG_DIR, REPO_ROOT / "docs" / "evidence" / "analogue_floor.json")
    print(f"floor rule: chosen {r['chosen']} (viable: {r['viable']})")
    return 0


def _analogue_value(args: argparse.Namespace) -> int:
    from ..retrieval.outcome_value import run_outcome_value

    fl = REPO_ROOT / "docs" / "evidence" / "analogue_floor.json"
    if not fl.is_file():
        print("run `make analogue-floor` first (the floor comes from the pre-registered rule, not from a flag)", file=sys.stderr)
        return 1
    floor = json.loads(fl.read_text(encoding="utf-8"))["chosen"]
    if floor is None:
        print("the floor rule found no viable similarity floor: retrieval is NOT_VIABLE (see docs/evidence/analogue_floor.json)", file=sys.stderr)
        return 1
    r = run_outcome_value(REPO_ROOT, CONFIG_DIR, float(floor), REPO_ROOT / "docs" / "evidence" / "analogue_outcome_value.json")
    print(r["decision"])
    return 0


def _shock_history(args: argparse.Namespace) -> int:
    from ..stress.history_check import PATH, build_shock_history

    out = build_shock_history(REPO_ROOT, CONFIG_DIR, REPO_ROOT / PATH)
    print(f"shock history: {out['first_session']}..{out['last_session']}, series {sorted(out['series'])}, horizons {out['horizons_sessions']}")
    return 0


def _portfolio_betas(args: argparse.Namespace) -> int:
    from ..portfolio.betas import PATH, build_betas
    from ..portfolio.config import load_portfolio_config
    from .outcome_audit import build_store

    store = build_store(REPO_ROOT, CONFIG_DIR)
    rules = load_portfolio_config(CONFIG_DIR).betas
    tickers = [t for t in store.sectors if t in store.ret]
    out = build_betas(store, rules, tickers, REPO_ROOT / PATH)
    print(f"portfolio betas: {len(out['betas'])}/{len(tickers)} issuers, as of {out['as_of']}, window {out['window_sessions']} sessions")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eventshock.modeling", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit", help="profile the data, build the impact and text tables, run every leakage check").set_defaults(fn=_audit)
    sub.add_parser("probe", help="seconds-long classical baselines on the built tables (needs the ml extra)").set_defaults(fn=_probe)
    ts = sub.add_parser("train-sentiment", help="train, select, calibrate and evaluate the sentiment model; write models/sentiment/*")
    ts.add_argument("--config", help="file under configs/ (default sentiment_model.yaml; v2: sentiment_model_v2.yaml)")
    ts.set_defaults(fn=_train_sentiment)
    p = sub.add_parser("train-event", help="train, tune, calibrate and evaluate the event model; write models/event/*")
    p.add_argument("--dev-only", metavar="OUT_DIR", help="iterate on dev rows only, writing to OUT_DIR; never scores the held-out sets")
    p.set_defaults(fn=_train_event)
    sub.add_parser("impact-table", help="build the impact modeling table (both scopes, text features, exclusions) + manifest").set_defaults(fn=_impact_table)
    sub.add_parser("impact-table-v2", help="build the v2 impact table (history v2, calendar features, protocol splits) + manifest").set_defaults(fn=_impact_table_v2)
    sub.add_parser("outcome-audit", help="Stage 8: audit the realised-outcome construction on a quiet-day null -> docs/evidence/outcome_audit.json").set_defaults(fn=_outcome_audit)
    sv = sub.add_parser("severity-validity", help="Stage 8: does the text-only severity scorecard rank realised market moves? -> docs/evidence/severity_validity.json")
    sv.add_argument("--limit", type=int, default=0, help="score every n-th episode only (smoke run; writes severity_validity.smoke.json)")
    sv.set_defaults(fn=_severity_validity)
    sub.add_parser("analogue-corpus", help="Stage 8: build the analogue corpus (past news reports + realised outcome-v3) and the texts to embed -> data/modeling/").set_defaults(fn=_analogue_corpus)
    sub.add_parser("analogue-relevance", help="Stage 8: retrieval relevance (e5 vs TF-IDF) on gold-v2 queries against the labelled corpus -> docs/evidence/analogue_relevance.json").set_defaults(fn=_analogue_relevance)
    sub.add_parser("analogue-index", help="Stage 8: pack the trusted analogue episodes (e5 vectors + outcomes) -> data/replay/analogues/").set_defaults(fn=_analogue_index)
    sub.add_parser("analogue-floor", help="Stage 8: the pre-registered similarity-floor rule on dev data -> docs/evidence/analogue_floor.json").set_defaults(fn=_analogue_floor)
    sub.add_parser("analogue-value", help="Stage 8: does retrieval add information beyond regime + calendar? -> docs/evidence/analogue_outcome_value.json").set_defaults(fn=_analogue_value)
    sub.add_parser("portfolio-betas", help="single-factor trailing beta of each issuer vs the S&P 500 (Blume-adjusted, derived stats only) -> data/replay/market/betas.json").set_defaults(fn=_portfolio_betas)
    sub.add_parser("shock-history", help="Stage 8: empirical k-session move distributions (quantiles + tails, no prices) for the scenario reality check -> data/replay/market/shock_history.json").set_defaults(fn=_shock_history)
    sub.add_parser("filing-events", help="build the filing-anchored event table (8-K events + matched quiet-session controls)").set_defaults(fn=_filing_events)
    st = sub.add_parser("impact-study", help="the Stage 4 study: protocols, incremental value of each block, regime-vs-event battery -> docs/evidence/impact_study.json")
    st.add_argument("--dev-only", action="store_true", help="never score the held-out sets (val/test/live); writes nothing under docs/evidence")
    st.set_defaults(fn=_impact_study)
    q = sub.add_parser("train-impact", help="select, fit, calibrate and evaluate the impact model; write models/impact/*")
    q.add_argument("--dev-only", metavar="OUT_DIR", help="iterate on train + val only, writing to OUT_DIR; never scores test or live")
    q.set_defaults(fn=_train_impact)
    from . import gold_cli  # noqa: PLC0415

    gold_cli.register(sub)
    from . import event_cli  # noqa: PLC0415

    event_cli.register(sub)
    args = ap.parse_args(argv)
    try:
        return int(args.fn(args))
    except (ConfigError, LeakageError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
