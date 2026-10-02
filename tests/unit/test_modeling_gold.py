from __future__ import annotations

import json
from collections import Counter

import pytest

from eventshock.config import REPO_ROOT
from eventshock.modeling.config import GoldConfig
from eventshock.modeling.corpora import TextExample, prepare_text_pool
from eventshock.modeling.gold import (
    ADJ_COLUMNS,
    SHEET_COLUMNS,
    NaiveBayes,
    adjudication_rows,
    build_sample,
    cohens_kappa,
    consistency_rows,
    effective_labels,
    read_sheet,
    score_gold,
    validate_sheet,
    weighted_scores,
    wilson,
    write_sheet,
)
from eventshock.pipeline.config import load_enrichment_config
from eventshock.pipeline.topics import load_topic_mapping
from tests.modeling_helpers import base_config, make_doc

MAPPING = load_topic_mapping(REPO_ROOT / "configs")
ENR = load_enrichment_config(REPO_ROOT / "configs")
WORDS = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango".split()


def _letters(i: int) -> str:
    out = ""
    for _ in range(4):
        out += "bcdfghjklmnpqrstvwxz"[i % 20] + "aeiou"[(i // 20) % 5]
        i //= 100
    return out


def sentence(i: int, topic: str = "story") -> str:
    """Distinct words per i (digits would be masked by the template key), so no two sentences are near-duplicates."""
    return f"{topic} {_letters(i)} {_letters(i * 7 + 3)} {_letters(i * 13 + 5)} {_letters(i * 31 + 11)} reported"


def tfn_pool(n_per_topic: int = 12) -> list[TextExample]:
    out = []
    for t in MAPPING.topics:
        cat = MAPPING.category(t)
        for k in range(n_per_topic):
            out.append(TextExample(f"tfn-topic-train-{t * 100 + k}", sentence(t * 100 + k, f"topic{t}"), cat.value if cat else "UNMAPPED",
                                   "tfn-topic", "train", topic=t, topic_name=MAPPING.topics[t].name, tier=MAPPING.tier(t)))
    return out


def sentiment_pool() -> list[TextExample]:
    labs = ["negative", "neutral", "positive"]
    return [TextExample(f"s{i}", sentence(i, ["loses", "flat", "beats"][i % 3]), labs[i % 3], "tfn-sentiment") for i in range(60)]


def history(n: int = 400):
    adapters = ["stock-tweets", "top-tweets", "headlines", "gdelt-gkg"]
    events = ["MARKET_VALUATION"] * 6 + ["GEOPOLITICAL", "CREDIT_FUNDING", "EARNINGS_FINANCIAL_PERFORMANCE", "REGULATORY_LEGAL"]
    docs = []
    for i in range(n):
        docs.append(make_doc(i, text=sentence(1000 + i, "hist"), adapter=adapters[i % 4], ticker=["AAA", "BBB", "CCC", "DDD"][i % 4],
                             multi=(i % 17 == 0), rule="WEAK_ALIAS" if i % 19 == 0 else "CASHTAG",
                             origin="SOURCE_DATE_ONLY" if i % 23 == 0 else "SOURCE", placeholder=events[i % 10],
                             sentiment=[-0.4, 0.0, 0.4][i % 3]))
    return docs


SMALL = GoldConfig.model_validate({**base_config().gold.model_dump(mode="json"),
                                   "tfn_topic_per_topic": 2, "disagreement_event": 4, "disagreement_sentiment": 4, "hard_multi_entity": 3,
                                   "hard_weak_entity_rule": 3, "hard_date_only": 3, "random_per_source": 5,
                                   "rare_class_per_class": {"GEOPOLITICAL": 3, "MACROECONOMIC": 3, "CREDIT_FUNDING": 3, "MA_CORPORATE_ACTION": 3,
                                                            "REGULATORY_LEGAL": 3, "PRODUCT_OPERATIONS": 3, "EARNINGS_FINANCIAL_PERFORMANCE": 3},
                                   "adjudication_rows": 12, "consistency_rows": 6})


def sample(docs=None, **kw):
    t = prepare_text_pool(tfn_pool(), 0.7)
    s = prepare_text_pool(sentiment_pool(), 0.7)
    return build_sample(SMALL, history=docs if docs is not None else history(), topic_pool=t, sentiment_pool=s, enrichment_cfg=ENR, **kw)


class TestSample:
    def test_deterministic(self):
        a, b = sample(), sample()
        assert a[0] == b[0] and json.dumps(a[1], sort_keys=True) == json.dumps(b[1], sort_keys=True)

    def test_quotas_and_ids(self):
        rows, man = sample()
        assert [r["gold_id"] for r in rows] == [f"G{i:03d}" for i in range(1, len(rows) + 1)]
        assert all(s["sampled"] == min(s["quota"], s["population_size"]) for s in man["strata"].values())
        assert sum(1 for i in man["items"].values() if i["population"] == "tfn") == 40

    def test_sheet_is_blind(self):
        rows, man = sample()
        assert list(rows[0]) == SHEET_COLUMNS
        cells = " ".join(v for r in rows for k, v in r.items() if k != "text")
        assert not any(name in cells for name in man["strata"]) and "placeholder" not in cells
        # weak labels live only in the manifest
        assert all("placeholder_event" in i["weak"] for i in man["items"].values())

    def test_weights_reconstruct_the_population_in_every_stratum(self):
        _, man = sample()
        for name, s in man["strata"].items():
            w = sum(i["weight"] for i in man["items"].values() if i["stratum"] == name)
            assert w == pytest.approx(s["population_size"], rel=1e-4), name

    def test_every_history_doc_lands_in_exactly_one_stratum(self):
        _, man = sample()
        hist = sum(s["population_size"] for n, s in man["strata"].items() if not n.startswith("tfn:"))
        assert hist == len(history())

    def test_near_duplicates_of_tfn_text_are_dropped_from_the_pool(self):
        docs = history()
        docs.append(make_doc(9999, text=tfn_pool()[3].text))  # same text as a TFN training row
        _, man = sample(docs)
        assert sum(s["population_size"] for n, s in man["strata"].items() if not n.startswith("tfn:")) == len(history())
        assert "9999" not in json.dumps(man["items"])

    def test_spam_templates_collapse_to_one_representative(self):
        spam = [make_doc(5000 + i, text=f"FREE option alerts join now $AAPL {100 + i}c > {90 + i} | {80 + i}p < {85 + i}") for i in range(20)]
        _, man = sample([*history(), *spam])
        assert sum(s["population_size"] for n, s in man["strata"].items() if not n.startswith("tfn:")) == len(history()) + 1

    def test_prefix_of_the_sheet_is_a_spread_of_strata(self):
        rows, man = sample()
        first = Counter(man["items"][r["gold_id"]]["stratum"].split(":")[0] for r in rows[: len(rows) // 3])
        assert len(first) >= 4  # not all one stratum

    def test_issuer_cap_applies_to_targeted_strata(self):
        docs = [make_doc(i, text=sentence(2000 + i, "cap"), ticker="AAA", placeholder="GEOPOLITICAL") for i in range(40)]
        docs += [make_doc(100 + i, text=sentence(3000 + i, "cap"), ticker="BBB", placeholder="GEOPOLITICAL") for i in range(40)]
        _, man = sample(docs)
        picked = [i for i in man["items"].values() if i["stratum"] == "rare:GEOPOLITICAL"]
        assert len(picked) == 3  # quota 3 with cap 1 per issuer: two issuers fill 2 slots, the cap relaxes for the third
        assert Counter("AAA" if int(i["origin_id"][1:]) < 100 else "BBB" for i in picked).most_common(1)[0][1] <= 2


class TestProbe:
    def test_naive_bayes_learns_a_trivial_split(self):
        nb = NaiveBayes().fit(["profit surges record", "profit beats estimates", "lawsuit fraud probe", "fraud charges filed"],
                              ["up", "up", "down", "down"])
        assert nb.predict("record profit")[0] == "up" and nb.predict("fraud lawsuit")[0] == "down"
        assert sum(nb.proba("anything").values()) == pytest.approx(1.0)


def labelled(rows, man, *, event="NONE", sentiment="0"):
    out = []
    for r in rows:
        out.append({**r, "ai_sentiment": sentiment, "ai_event_class": event, "ai_secondary_class": "", "ai_entity_ok": "y" if r["ticker"] else "na",
                    "ai_notes": ""})
    return out


class TestValidate:
    rows, man = sample()

    def test_empty_sheet_is_valid_but_incomplete(self):
        rep = validate_sheet(self.rows, self.man)
        assert rep.ok and rep.complete == 0
        assert not validate_sheet(self.rows, self.man, require_complete=True).ok

    def test_complete_sheet_passes(self):
        rep = validate_sheet(labelled(self.rows, self.man), self.man, require_complete=True)
        assert rep.ok and rep.complete == len(self.rows)

    @pytest.mark.parametrize("field,value,fragment", [("ai_sentiment", "2", "sentiment"), ("ai_event_class", "BANKRUPTCY", "event_class"),
                                                      ("ai_entity_ok", "maybe", "entity_ok")])
    def test_bad_vocabulary_is_an_error(self, field, value, fragment):
        rows = labelled(self.rows, self.man)
        rows[0][field] = value
        rep = validate_sheet(rows, self.man)
        assert not rep.ok and fragment in rep.errors[0]

    def test_secondary_must_differ_from_primary(self):
        rows = labelled(self.rows, self.man, event="GEOPOLITICAL")
        rows[0]["ai_secondary_class"] = "GEOPOLITICAL"
        assert not validate_sheet(rows, self.man).ok

    def test_rows_without_a_ticker_take_na_and_rows_with_one_take_y_or_n(self):
        rows = labelled(self.rows, self.man)
        tfn = next(r for r in rows if self.man["items"][r["gold_id"]]["population"] == "tfn")
        hist = next(r for r in rows if self.man["items"][r["gold_id"]]["population"] == "history" and r["ticker"])
        tfn["ai_entity_ok"], hist["ai_entity_ok"] = "y", "na"
        assert len(validate_sheet(rows, self.man).errors) == 2

    def test_id_mismatch_with_the_manifest_is_an_error(self):
        assert not validate_sheet(self.rows[1:], self.man).ok

    def test_a_subset_sheet_is_valid_only_when_declared(self):
        assert validate_sheet(self.rows[:5], self.man, subset=True).ok
        extra = [{**self.rows[0], "gold_id": "G999"}]
        assert not validate_sheet(extra, self.man, subset=True).ok


class TestSheetIO:
    def test_round_trip_with_newlines_quotes_and_commas(self, tmp_path):
        rows = [{**{k: "" for k in SHEET_COLUMNS}, "gold_id": "G001", "text": 'line one\nline "two", with comma ⏎ 👍'}]
        write_sheet(tmp_path / "s.csv", rows)
        assert read_sheet(tmp_path / "s.csv") == rows


class TestScoring:
    def man(self):
        def item(pop, w, **weak):
            return {"origin_id": "x", "population": pop, "stratum": "s", "role": "population", "weight": w, "weak": weak}

        return {"annotator": "ai:claude", "items": {
            "G1": item("tfn", 10.0, topic=5, topic_name="Earnings", tier="strong", mapped_class="EARNINGS_FINANCIAL_PERFORMANCE",
                       placeholder_event="EARNINGS_FINANCIAL_PERFORMANCE", placeholder_sentiment=0.5, nb_event="NONE", nb_sentiment="1"),
            "G2": item("tfn", 10.0, topic=5, topic_name="Earnings", tier="strong", mapped_class="EARNINGS_FINANCIAL_PERFORMANCE",
                       placeholder_event="MARKET_VALUATION", placeholder_sentiment=0.0, nb_event="NONE", nb_sentiment="0"),
            "G3": item("history", 3.0, placeholder_event="MARKET_VALUATION", placeholder_sentiment=-0.5, nb_event="NONE", nb_sentiment="-1"),
            "G4": item("history", 1.0, placeholder_event="GEOPOLITICAL", placeholder_sentiment=0.5, nb_event="NONE", nb_sentiment="0")}}

    def sheet(self):
        def r(gid, s, e, ent, sec=""):
            return {"gold_id": gid, "source": "", "published_at": "", "ticker": "", "text": "", "ai_sentiment": s, "ai_event_class": e,
                    "ai_secondary_class": sec, "ai_entity_ok": ent, "ai_notes": ""}

        return [r("G1", "1", "EARNINGS_FINANCIAL_PERFORMANCE", "na"), r("G2", "0", "NONE", "na"), r("G3", "-1", "MARKET_VALUATION", "y"),
                r("G4", "0", "NONE", "n")]

    def test_crosswalk_precision_per_topic(self):
        out = score_gold(self.sheet(), self.man())
        t = out["topic_mapping_precision"]["05 Earnings"]
        assert t["n"] == 2 and t["precision_primary_or_secondary"] == 0.5 and t["share_none"] == 0.5
        assert out["mapping_precision_by_tier"] == {"strong": 0.5}

    def test_weighted_scores_use_inclusion_weights(self):
        out = score_gold(self.sheet(), self.man())["weak_labels_vs_gold"]["population:history"]["placeholder_event"]
        # truth/pred/weight: (MV, MV, 3) hit, (NONE, GEO, 1) miss -> 3/4
        assert out["accuracy"] == 0.75 and out["n"] == 2
        tfn = score_gold(self.sheet(), self.man())["weak_labels_vs_gold"]["population:tfn"]["placeholder_event"]
        assert tfn["accuracy"] == 0.5

    def test_sentiment_baselines_and_history_estimates(self):
        out = score_gold(self.sheet(), self.man())
        assert out["weak_labels_vs_gold"]["population:history"]["placeholder_sentiment"]["accuracy"] == 0.75  # -0.5 -> -1 hit (w=3), 0.5 -> +1 vs gold 0 miss (w=1)
        assert out["history_population_estimates"]["share_none"] == 0.25 and out["history_population_estimates"]["entity_ok_rate_among_resolved"] == 0.75

    def test_human_override_wins_and_agreement_is_reported(self):
        adj = [{c: "" for c in ADJ_COLUMNS} | {"gold_id": "G2", "ai_event_class": "NONE", "ai_sentiment": "0", "human_event_class": "EARNINGS_FINANCIAL_PERFORMANCE"}]
        labs = effective_labels(self.sheet(), adj)
        assert labs["G2"]["event"] == "EARNINGS_FINANCIAL_PERFORMANCE" and labs["G2"]["overridden"] == "yes" and labs["G1"]["overridden"] == "no"
        out = score_gold(self.sheet(), self.man(), adj)
        assert out["ai_vs_human"]["event"] == {"n": 1, "agreement": 0.0, "kappa": 0.0} and out["overridden_by_human"] == 1

    def test_self_consistency_is_labelled_as_not_inter_annotator(self):
        second = [{**r, "ai_event_class": "NONE" if r["gold_id"] == "G1" else r["ai_event_class"]} for r in self.sheet()]
        out = score_gold(self.sheet(), self.man(), (), second)["self_consistency"]
        assert out["event"]["agreement"] == 0.75 and "NOT an independent" in out["note"]

    def test_current_tiers_override_the_frozen_ones(self):
        out = score_gold(self.sheet(), self.man(), tiers={5: "weak"})
        assert out["topic_mapping_precision"]["05 Earnings"]["tier"] == "weak" and out["mapping_precision_by_tier"] == {"weak": 0.5}

    def test_random_strata_report_unweighted_shares_with_a_wilson_interval(self):
        man = self.man()
        for gid in ("G3", "G4"):
            man["items"][gid]["stratum"] = "rand:stock-tweets"
        out = score_gold(self.sheet(), man)["random_strata"]["rand:stock-tweets"]
        assert out["n"] == 2 and out["share_none"] == 0.5 and out["none_ci95"][0] < 0.5 < out["none_ci95"][1]

    def test_wilson_interval(self):
        lo, hi = wilson(50, 100)
        assert 0.40 < lo < 0.41 and 0.59 < hi < 0.60 and wilson(0, 0)[0] != wilson(0, 0)[0]

    def test_metrics_helpers(self):
        assert cohens_kappa(["a", "a", "b", "b"], ["a", "a", "b", "b"]) == 1.0
        assert cohens_kappa(["a", "b"], ["b", "a"]) == -1.0
        s = weighted_scores([("a", "a", 1.0), ("b", "a", 1.0)], ["a", "b"])
        assert s["accuracy"] == 0.5 and s["per_class"]["a"]["precision"] == 0.5 and s["per_class"]["b"]["recall"] == 0.0


class TestWorkflowSheets:
    def test_adjudication_picks_disagreements_plus_random_and_hides_nothing_else(self):
        rows, man = sample()
        lab = labelled(rows, man, event="GEOPOLITICAL")
        adj = adjudication_rows(lab, man, SMALL)
        assert len(adj) == SMALL.adjudication_rows and list(adj[0]) == ADJ_COLUMNS[:7] + ADJ_COLUMNS[7:]
        assert all(r["human_event_class"] == "" for r in adj) and len({r["gold_id"] for r in adj}) == len(adj)

    def test_consistency_sheet_is_blind(self):
        rows, man = sample()
        cons = consistency_rows(labelled(rows, man), SMALL)
        assert len(cons) == SMALL.consistency_rows and all(r["ai_event_class"] == "" and r["ai_sentiment"] == "" for r in cons)
