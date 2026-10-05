"""Stage 8: the committed evidence files, pinned. A silent change of method, data or pre-registration shows up here.

These read only committed files (``docs/evidence``, ``configs``); they need neither prices nor an encoder.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.retrieval.config import RetrievalConfig, load_retrieval_config, resolve_floor
from eventshock.services.outcome_check import build_outcome_check

EVID = REPO_ROOT / "docs" / "evidence"
PRE_SHA = hashlib.sha256((REPO_ROOT / "configs" / "evidence_v3.yaml").read_bytes()).hexdigest()
FILES = ["outcome_audit", "severity_validity", "analogue_relevance", "analogue_floor", "analogue_outcome_value"]


def load(name):
    return json.loads((EVID / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", FILES)
def test_every_evidence_file_was_produced_under_the_current_preregistration(name):
    assert load(name)["preregistration_sha256"] == PRE_SHA, f"{name}.json was produced under a different configs/evidence_v3.yaml: the pre-registration was edited after a result"


def test_the_audit_decision_and_its_inputs():
    a = load("outcome_audit")
    assert a["decision"]["outcome_version"] == "outcome-v3" and all(a["decision"]["checks"].values())
    assert a["identity_check"]["max_abs_diff_z"] < 1e-9 and a["identity_check"]["max_abs_diff_sigma"] < 1e-6
    assert a["null_sample"]["n"] == 60000
    e = a["event_vs_quiet"]
    assert 0.50 < e["stratified_auc"]["auc"] < 0.55 and e["auc_ci95"][0] < e["stratified_auc"]["auc"] < e["auc_ci95"][1]   # news is barely distinguishable from a quiet day
    assert a["posthoc_ex_earnings"]["news_with_earnings_in_window_vs_all_quiet"]["auc"] > 0.7                              # earnings is the exception
    assert a["clustering"]["design_effect"] > 1.5 and a["clustering"]["effective_n"] < a["clustering"]["n"]                  # why intervals are clustered


def test_the_severity_scale_is_labelled_heuristic_and_the_label_follows_from_the_numbers():
    v = load("severity_validity")
    assert v["label"]["label"] == "HEURISTIC_UNCALIBRATED" and v["outcome_version"] == "outcome-v3"
    for split in ("test", "live"):
        m1 = v["by_split"][split]["metrics"]["M1_overall_rank"]
        assert m1["lo"] < 0 < m1["hi"], f"{split}: the interval no longer contains zero, so the label must be revisited"
    assert not any(v["label"]["outcome_validated_conditions"].values()) and not any(v["label"]["monotone_bands"].values())
    assert v["inputs"]["episodes"] == 19638 and v["posthoc_market_scope"]["note"].startswith("POST-HOC")


def test_retrieval_relevance_decision():
    r = load("analogue_relevance")
    assert r["decision"]["adopt_e5"] is True and r["decision"]["served_retriever"] == "e5-large"
    assert r["metrics"]["all_queries"]["delta_p_at_5_e5_minus_tfidf"]["lo"] > 0
    assert r["inputs"]["queries"] == 280 and r["inputs"]["labelled_corpus"] == 3270


def test_the_floor_is_the_pre_registered_rule_and_the_served_floor_follows_it():
    f = load("analogue_floor")
    assert f["viable"] and f["chosen"] == 0.78
    ok = [row["floor"] for row in f["curve"] if row["ok"]]
    assert f["chosen"] == min(ok)
    cfg = load_retrieval_config(REPO_ROOT / "configs")
    assert cfg.similarity_floor == "rule" and resolve_floor(cfg, REPO_ROOT) == (0.78, None)


def test_retrieval_does_not_enter_the_score_and_the_ui_says_so():
    v = load("analogue_outcome_value")
    assert not any(x["may_enter_score"] for x in v["enter_score"].values())
    assert v["decision"].startswith("No analogue-derived quantity enters the severity score")
    o = build_outcome_check(REPO_ROOT)
    assert o.label == "HEURISTIC_UNCALIBRATED" and not o.missing and o.retrieval and o.retrieval.decision == v["decision"]


class TestRetrievalConfig:
    def test_floor_can_be_overridden_only_with_a_number(self):
        assert resolve_floor(RetrievalConfig(version="x", similarity_floor=0.9), REPO_ROOT) == (0.9, None)
        with pytest.raises(Exception):  # noqa: B017
            RetrievalConfig(version="x", similarity_floor=1.5)

    def test_missing_floor_evidence_or_a_non_viable_rule_is_a_reason_not_a_guess(self, tmp_path):
        cfg = RetrievalConfig(version="x")
        floor, why = resolve_floor(cfg, tmp_path)
        assert floor is None and "analogue-floor" in why
        (tmp_path / "docs" / "evidence").mkdir(parents=True)
        (tmp_path / "docs" / "evidence" / "analogue_floor.json").write_text(json.dumps({"chosen": None}))
        floor, why = resolve_floor(cfg, tmp_path)
        assert floor is None and "no viable floor" in why

    def test_unknown_keys_and_missing_file_stop_start_up(self, tmp_path):
        with pytest.raises(ConfigError, match="missing"):
            load_retrieval_config(tmp_path)
        (tmp_path / "retrieval.yaml").write_text('version: "x"\nsimilarity_floor: rule\nsurprise: 1\n')
        with pytest.raises(ConfigError):
            load_retrieval_config(tmp_path)


def test_the_committed_analogue_pack_is_consistent_with_the_corpus_manifest_and_stays_derived_only():
    m = json.loads((REPO_ROOT / "data" / "replay" / "analogues" / "analogues.json").read_text())
    assert m["trusted_only"] is True and m["dims"] == 1024 and m["encoder"] == "intfloat/multilingual-e5-large" and m["preregistration_sha256"] == PRE_SHA
    assert m["bytes"]["vectors"] + m["bytes"]["rows"] < 17_000_000
    first = (REPO_ROOT / "data" / "replay" / "analogues" / "analogues.jsonl").read_text().splitlines()[0]
    assert not {"open", "high", "low", "close", "adj_close", "volume"} & set(json.loads(first))   # outcomes only, never prices
