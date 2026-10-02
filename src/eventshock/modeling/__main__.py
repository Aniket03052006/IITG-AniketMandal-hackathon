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

    return train_main()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eventshock.modeling", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit", help="profile the data, build the impact and text tables, run every leakage check").set_defaults(fn=_audit)
    sub.add_parser("probe", help="seconds-long classical baselines on the built tables (needs the ml extra)").set_defaults(fn=_probe)
    sub.add_parser("train-sentiment", help="train, select, calibrate and evaluate the sentiment model; write models/sentiment/*").set_defaults(fn=_train_sentiment)
    from . import gold_cli  # noqa: PLC0415

    gold_cli.register(sub)
    args = ap.parse_args(argv)
    try:
        return int(args.fn(args))
    except (ConfigError, LeakageError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
