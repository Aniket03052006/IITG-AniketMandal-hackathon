from __future__ import annotations

import dataclasses
import json
from collections import Counter

import pytest

from eventshock.config import REPO_ROOT
from eventshock.domain import EventCategory
from eventshock.modeling.corpora import (
    HistoryDoc,
    TextExample,
    dedup_examples,
    iter_history_docs,
    prepare_text_pool,
    read_jsonl,
    stratified_group_split,
)
from eventshock.modeling.text import exact_key, has_near_duplicate, near_duplicate_groups, template_key
from eventshock.pipeline.topics import TopicMapping, load_topic_mapping

MAPPING = load_topic_mapping(REPO_ROOT / "configs")


class TestTextKeys:
    def test_template_key_ignores_tickers_numbers_handles_and_links(self):
        a = "$AAPL 190c > 188 | 180p < 185 @someone https://t.co/x1"
        b = "$TSLA 1100c > 1055 | 1000p < 1015 @other https://t.co/y2"
        assert template_key(a) == template_key(b)
        assert template_key("Boeing recalls planes") != template_key("Boeing orders planes")

    def test_exact_key_folds_case_links_and_outlet_suffix(self):
        assert exact_key("Fed holds rates - Reuters") == exact_key("FED HOLDS RATES https://x.co/1")

    def test_near_duplicate_groups_link_variants_and_separate_stories(self):
        texts = ["Tesla recalls 50,000 vehicles over seat belt defect",
                 "Tesla recalls 50,000 vehicles over a seat belt defect, NHTSA says",
                 "Fed holds interest rates steady",
                 "Tesla recalls 50,000 vehicles over seat belt defect"]
        g = near_duplicate_groups(texts, 0.7)
        assert g[0] == g[1] == g[3] and g[2] != g[0]

    def test_group_ids_do_not_depend_on_input_order(self):
        texts = ["Apple unveils new phone with faster chip today", "Apple unveils new phone with a faster chip today", "Oil falls on demand fears"]
        a = near_duplicate_groups(texts, 0.7)
        b = near_duplicate_groups(texts[::-1], 0.7)[::-1]
        assert (a[0] == a[1]) and (b[0] == b[1]) and a[2] != a[0] and b[2] != b[0]

    def test_has_near_duplicate(self):
        ref = ["Tesla recalls 50,000 vehicles over seat belt defect in the United States"]
        assert has_near_duplicate(["Tesla recalls 50,000 vehicles over seat belt defect in the US", "Oil falls"], ref, 0.7) == [True, False]


class TestDedup:
    def ex(self, i, text, label):
        return TextExample(f"e{i}", text, label, "c")

    def test_exact_duplicates_collapse_and_conflicts_are_dropped_not_guessed(self):
        kept, rep = dedup_examples([self.ex(1, "Fed holds rates", "a"), self.ex(2, "FED HOLDS RATES https://t.co/x", "a"),
                                    self.ex(3, "Oil jumps today on supply fears", "a"), self.ex(4, "Oil jumps today on supply fears", "b")])
        assert [e.id for e in kept] == ["e1"] and (rep.exact_duplicates_dropped, rep.conflicting_texts_dropped) == (1, 1)

    def test_no_text_is_lost_silently(self):
        items = [self.ex(i, f"distinct headline number {i} about markets", "a") for i in range(5)]
        kept, rep = dedup_examples(items)
        assert len(kept) == 5 and rep.kept == 5 and rep.input == 5


class TestGroupSplit:
    labels = {g: ("pos" if g % 3 else "neg") for g in range(300)}
    sizes = {g: 1 + (g % 4 == 0) * 5 for g in range(300)}
    fr = {"train": 0.8, "valid": 0.1, "test": 0.1}

    def test_deterministic_and_whole_groups(self):
        a = stratified_group_split(self.labels, self.sizes, self.fr, 1)
        assert a == stratified_group_split(self.labels, self.sizes, self.fr, 1) != stratified_group_split(self.labels, self.sizes, self.fr, 2)
        assert set(a) == set(self.labels)

    def test_stratified_within_tolerance(self):
        a = stratified_group_split(self.labels, self.sizes, self.fr, 1)
        for lab in ("pos", "neg"):
            tot = sum(self.sizes[g] for g in self.labels if self.labels[g] == lab)
            for split, frac in self.fr.items():
                got = sum(self.sizes[g] for g, s in a.items() if s == split and self.labels[g] == lab)
                assert abs(got / tot - frac) < 0.06

    def test_forced_groups_land_in_test(self):
        a = stratified_group_split(self.labels, self.sizes, self.fr, 1, forced_test={1, 2, 3})
        assert {a[1], a[2], a[3]} == {"test"}

    def test_pool_groups_keep_near_duplicates_together(self):
        exs = [TextExample(f"e{i}", t, "x", "c") for i, t in enumerate(
            ["Pfizer vaccine trial results beat expectations in phase three", "Pfizer vaccine trial results beat expectations in phase three study",
             "Mortgage rates climb to the highest level this year"])]
        pool = prepare_text_pool(exs, 0.7)
        assert pool.groups[0] == pool.groups[1] != pool.groups[2] and pool.group_sizes[pool.groups[0]] == 2


class TestTopicTiers:
    def test_real_mapping_is_tiered_and_weak_topics_are_not_trainable(self):
        assert MAPPING.tier(7) == "strong" and MAPPING.trainable(7) is EventCategory.EARNINGS_FINANCIAL_PERFORMANCE
        assert MAPPING.tier(2) == "weak" and MAPPING.trainable(2) is None  # Company | Product News is a grab-bag
        assert MAPPING.trainable(2, "weak") is EventCategory.PRODUCT_OPERATIONS
        assert MAPPING.trainable(6) is None  # unmapped topic
        assert MAPPING.trainable(0, "strong") is None and MAPPING.trainable(0, "medium") is EventCategory.MARKET_VALUATION

    def test_the_gold_review_demoted_earnings_stock_movement_and_ma(self):
        assert [MAPPING.tier(i) for i in (5, 19, 13)] == ["weak", "weak", "medium"]
        assert MAPPING.trainable(5) is None and MAPPING.trainable(19) is None

    def test_the_audit_finding_is_pinned_geopolitical_and_product_ops_have_no_trainable_topic(self):
        trainable = {MAPPING.trainable(i) for i in MAPPING.topics} - {None}
        assert EventCategory.GEOPOLITICAL not in trainable and EventCategory.PRODUCT_OPERATIONS not in trainable
        assert len(trainable) == 6

    def test_tier_is_required_exactly_when_a_class_is_mapped(self):
        with pytest.raises(ValueError, match="tier is required"):
            TopicMapping.model_validate({"version": "1", "dataset": "d", "topics": {0: {"name": "a", "category": "MACROECONOMIC"}}})
        with pytest.raises(ValueError, match="tier is required"):
            TopicMapping.model_validate({"version": "1", "dataset": "d", "topics": {0: {"name": "a", "category": None, "tier": "strong"}}})

    def test_every_mapped_topic_has_a_rationale(self):
        assert all(t.rationale for t in MAPPING.topics.values() if t.category)


def signal(i: int, *, headline="Tesla recalls cars", adapter="stock-tweets", tags=None) -> dict:
    md = {"adapter": adapter, "timestamp_origin": "SOURCE"}
    if tags:
        md["x_ticker"] = tags
    return {"id": f"sig{i}", "document": {"headline": headline, "published_at": "2021-05-04T21:00:00Z", "source_type": "SOCIAL", "raw_metadata": md},
            "entity": {"ticker": "TSLA", "entity_id": "ENT_TSLA", "link_confidence": 0.98},
            "provenance": {"timestamp_origin": "SOURCE", "entity_audit": {"multi_entity": False, "rule": "CASHTAG"}, "dedup": {"cluster_id": f"cl{i}", "member_count": 1}},
            "evidence": {"novelty_score": 0.5}, "event": {"category": "MARKET_VALUATION"}, "sentiment": {"score": 0.0}}


class TestHistoryDocs:
    def test_loader_maps_fields_and_keeps_placeholders_out_of_label_names(self, tmp_path):
        p = tmp_path / "s.jsonl"
        p.write_text(json.dumps(signal(1, tags="TSLA")) + "\n\n", encoding="utf-8")
        (doc,) = list(iter_history_docs(p))
        assert doc.ticker == "TSLA" and doc.dataset_tickers == ("TSLA",) and doc.placeholder_event == "MARKET_VALUATION"

    def test_no_field_looks_like_a_label_or_target(self):
        names = {f.name for f in dataclasses.fields(HistoryDoc)}
        assert not {n for n in names if n in {"label", "target", "y", "truth", "event", "sentiment", "impact"} or n.startswith("label")}
        assert {n for n in names if n.startswith("placeholder_")} == {"placeholder_event", "placeholder_sentiment"}

    def test_a_malformed_signal_fails_loudly_with_its_line_number(self, tmp_path):
        p = tmp_path / "s.jsonl"
        p.write_text(json.dumps(signal(1)) + "\n" + json.dumps({"id": "x"}) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match=r"s\.jsonl:2"):
            list(iter_history_docs(p))

    def test_read_jsonl_does_not_split_on_unicode_line_separators(self, tmp_path):
        p = tmp_path / "t.jsonl"
        p.write_bytes((json.dumps({"text": "a b"}, ensure_ascii=False) + "\n").encode())
        assert read_jsonl(p) == [{"text": "a b"}]

    def test_read_jsonl_fails_loudly(self, tmp_path):
        p = tmp_path / "t.jsonl"
        p.write_bytes(b'{"a": 1}\n{oops\n')
        with pytest.raises(ValueError, match=r"t\.jsonl:2"):
            read_jsonl(p)


def test_label_counts_helper_is_stable():
    from eventshock.modeling.corpora import label_distribution

    assert label_distribution([TextExample("1", "a", "x", "c"), TextExample("2", "b", "x", "c"), TextExample("3", "c", "y", "c")]) == Counter(x=2, y=1)
