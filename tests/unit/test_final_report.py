"""docs/notes/FINAL_MODEL_REPORT.md quotes numbers from the committed cards; each must still match its source."""
from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal

from eventshock.config import REPO_ROOT

REPORT = (REPO_ROOT / "docs/notes/FINAL_MODEL_REPORT.md").read_text(encoding="utf-8")


def card(rel: str) -> dict:
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def f(x: float, n: int = 3) -> str:
    """Round half up on the card's own decimal digits (the cards hold 4 decimals): 0.4175 -> 0.418, as the report prints it."""
    return str(Decimal(repr(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def evals(c: dict) -> dict:
    return {e["id"]: e["model"] for e in c["evaluations"]}


def quoted(*values: str) -> None:
    missing = [v for v in values if v not in REPORT]
    assert not missing, f"not in docs/notes/FINAL_MODEL_REPORT.md (card changed?): {missing}"


def test_sentiment_numbers():
    c = card("models/sentiment/tfidf-lr-v1/model_card.json")
    e = evals(c)
    lo, hi = e["tfn_test"]["macro_f1_ci95"]
    base = next(x for x in c["evaluations"] if x["id"] == "tfn_test")["baselines"]["placeholder_lexicon"]["macro_f1"]
    quoted(f(e["tfn_test"]["macro_f1"]), f"[{f(lo)}, {f(hi)}]", f(base), f(e["phrasebank"]["macro_f1"]), f(e["gold_history"]["macro_f1"], 2),
           f(e["gold_history"]["ece"], 2), f"{e['tfn_test']['n']:,}", f"{c['training']['rows']['train']:,}")


def test_event_numbers():
    c = card("models/event/hybrid-event-v2/model_card.json")
    e = evals(c)
    for k in ("gold_history", "gold_v2", "replay_check"):
        lo, hi = e[k]["served_f1_ci95"]
        quoted(f(e[k]["served"]["macro_f1"]), f"[{f(lo)}, {f(hi)}]")
    assert c["acceptance"]["met"] is False
    train = c["training"]["rows"]
    quoted(f"{train['train/annotated']:,}", str(train["dev"]))
    d = c["training"]["label_distribution_train"]
    rare = [d[k] for k in ("CREDIT_FUNDING", "EARNINGS_FINANCIAL_PERFORMANCE", "GEOPOLITICAL", "MACROECONOMIC", "MA_CORPORATE_ACTION")]
    quoted(f"{min(rare)}-{max(rare)}")
    ece = [e[k]["ece"] for k in ("gold_history", "gold_tfn", "gold_v2", "replay_check")]
    quoted(f"{min(ece):.2f}-{max(ece):.2f}")


def test_impact_numbers():
    c = card("models/impact/impact-v2/model_card.json")
    sc = {s["scope"]: s for s in c["scopes"]}
    iss = {x["id"]: x for x in sc["ISSUER"]["acceptance"]["checks"]}
    assert iss["C1"]["value"].startswith("+0.168 [+0.148, +0.187]") and "+0.084 [+0.013, +0.156]" in iss["C8"]["value"]
    assert "placebo +0.236" in iss["C7"]["value"] and iss["C5"]["value"].startswith("0.93 (nominal 0.80)")
    quoted("+0.168", "[+0.148, +0.187]", "+0.084", "[+0.013, +0.156]", "+0.236", "0.93 vs nominal 0.80")
    ep = sc["ISSUER"]["training"]["episodes"]
    quoted(f"{ep['train']:,}", f"{sc['MARKET']['training']['episodes']['train']:,}")
    quoted(f"{next(e for e in sc['ISSUER']['evaluations'] if e['id'] == 'val+test')['n_episodes']:,}")
    passed = {k: sum(x["passed"] is True for x in s["acceptance"]["checks"]) for k, s in sc.items()}
    assert passed == {"ISSUER": 9, "MARKET": 6}
    quoted("passes 9 of 11", "passes 6 of 11")


def test_stress_book_numbers():
    p = json.loads((REPO_ROOT / "data/replay/portfolio.json").read_text(encoding="utf-8"))["assets"]
    quoted(str(len(p)), f"${sum(a['market_value'] for a in p) / 1e6:.1f}M")
    kinds = {k: sum(a["asset_type"] == k for a in p) for k in ("BOND", "EQUITY", "LOAN", "DERIVATIVE")}
    quoted(f"{kinds['BOND']} bonds", f"{kinds['EQUITY']} equities", f"{kinds['LOAN']} loans", f"{kinds['DERIVATIVE']} derivatives")
