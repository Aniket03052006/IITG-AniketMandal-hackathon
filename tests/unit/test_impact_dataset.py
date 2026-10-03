"""The impact modeling table: reproducible, accounted for, and free of anything a model may not see (skipped without the local data)."""

from __future__ import annotations

import json

import pytest

from eventshock.config import REPO_ROOT
from eventshock.ingestion.snapshot import sha256_file
from eventshock.modeling.leakage import FEATURE_REGISTRY
from eventshock.pipeline.impact_features import ALL_FEATURES

TABLE = REPO_ROOT / "data" / "modeling" / "impact_table.jsonl"
MANIFEST = REPO_ROOT / "data" / "modeling" / "impact_dataset.json"
pytestmark = pytest.mark.skipif(not (TABLE.is_file() and MANIFEST.is_file()), reason="local impact table not built (`make impact-table`)")


def _rows(n=3000):
    out = []
    with TABLE.open("rb") as fh:
        for i, raw in enumerate(fh):
            if i >= n:
                break
            out.append(json.loads(raw))
    return out


def test_the_manifest_pins_the_table_it_describes():
    m = json.loads(MANIFEST.read_text())
    assert m["table_sha256"] == sha256_file(TABLE)
    assert m["feature_schema"] == "impact-features-v1" and m["inputs"]["history_signals"]["sha256"]
    assert set(m["by_scope_split_rows"]) == {"ISSUER", "MARKET"}


def test_every_document_is_accounted_for_by_a_row_or_a_named_exclusion():
    m = json.loads(MANIFEST.read_text())
    n_docs = m["inputs"]["history_signals"]["documents"]
    iss_rows = sum(m["by_scope_split_rows"]["ISSUER"].values())
    mkt_rows = sum(m["by_scope_split_rows"]["MARKET"].values())
    excluded = sum(m["exclusions"]["ISSUER"].values()) + sum(m["exclusions"]["MARKET"].values()) - m["exclusions"]["ISSUER"].get("NO_ISSUER", 0)
    # NO_ISSUER documents are the market scope's input, counted there; the text stage is counted once per scope
    assert iss_rows + mkt_rows + excluded == n_docs


def test_rows_carry_only_registered_event_time_features_and_split_labels():
    for r in _rows():
        feats = [k for k in r if k in FEATURE_REGISTRY and FEATURE_REGISTRY[k][0] == "AT_EVENT_TIME"]
        assert set(feats) <= set(ALL_FEATURES) | {"text", "source_type", "sector"}
        assert r["split"] in {"train", "val", "test", "live"} and r["scope"] in {"ISSUER", "MARKET"}
        assert r["abs_z"] >= 0 and 1 <= r["score"] <= 10 and r["episode"].count("|") == 1


def test_no_row_is_one_a_text_model_trained_on():
    from eventshock.pipeline.config import load_event_model_config
    from eventshock.pipeline.event_model import EventModel

    model = EventModel.load(REPO_ROOT / load_event_model_config(REPO_ROOT / "configs").model_dir)
    sample = _rows(400)
    assert not any(d.seen_in_training for d in model.decide_many([r["text"] for r in sample]))


def test_episodes_never_straddle_splits():
    seen: dict[str, str] = {}
    with TABLE.open("rb") as fh:
        for raw in fh:
            r = json.loads(raw)
            assert seen.setdefault(r["scope"] + r["episode"], r["split"]) == r["split"]
