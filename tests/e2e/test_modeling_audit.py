"""End to end on a synthetic repo layout: prices, TFN files, entities and exported signals -> audit tables."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.modeling.audit import run_audit
from eventshock.modeling.corpora import read_jsonl
from eventshock.modeling.leakage import LeakageError, require_clean
from eventshock.pipeline.topics import load_topic_mapping
from tests.modeling_helpers import SECTORS, base_config, make_store, override, write_prices
from tests.unit.test_modeling_corpora import signal
from tests.unit.test_modeling_gold import _letters


def build_repo(tmp_path):
    cfg = override(base_config(), splits={**base_config().splits.model_dump(mode="json"), "impact": {
        "embargo_sessions": 5, "train_end": "2021-03-31", "val_start": "2021-04-01", "val_end": "2021-06-30",
        "test_start": "2021-07-01", "test_end": "2021-09-30", "live_start": "2021-10-15"}})
    store = make_store(520, cfg=cfg)
    write_prices(tmp_path / "data" / "raw" / "prices", store)
    (tmp_path / "data" / "history").mkdir(parents=True)
    (tmp_path / "data" / "history" / "entities.json").write_text(json.dumps(
        [{"entity_id": f"ENT_{t}", "name": t, "ticker": t, "sector": s, "country": "US", "aliases": []} for t, s in SECTORS.items()]), encoding="utf-8")
    rng = random.Random(3)
    sigs, start = [], datetime(2020, 12, 1, 15)
    for i in range(600):
        s = signal(i, headline=f"{_letters(i)} {_letters(i * 3 + 1)} {_letters(i * 7 + 2)} {_letters(i * 11 + 4)} update")
        t = start + timedelta(hours=rng.randrange(0, 24 * 330))
        s["document"]["published_at"] = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        s["entity"] = {"ticker": list(SECTORS)[i % 4], "entity_id": "ENT_X", "link_confidence": 0.95}
        sigs.append(s)
    out = tmp_path / "data" / "processed" / "history"
    out.mkdir(parents=True)
    (out / "signals.jsonl").write_text("\n".join(json.dumps(s) for s in sigs) + "\n", encoding="utf-8")
    tfn = tmp_path / "data" / "raw" / "tfn"
    tfn.mkdir(parents=True)
    for name, n, labels in (("train", 90, 3), ("valid", 30, 3), ("topic_train", 200, 20), ("topic_valid", 60, 20)):
        rows = [{"label": i % labels, "row": i, "split": name.split("_")[-1], "text": f"{_letters(i + 500)} {_letters(i * 5 + 9)} {_letters(i * 9 + 7)} {_letters(i + 77)} stock news {name}"}
                for i in range(n)]
        (tfn / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return cfg


@pytest.fixture(scope="module")
def audit(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("repo")
    cfg = build_repo(tmp)
    out = tmp / "out"
    res = run_audit(cfg, repo_root=tmp, config_dir=REPO_ROOT / "configs", mapping=load_topic_mapping(REPO_ROOT / "configs"), out_dir=out)
    return tmp, cfg, out, res


def test_audit_runs_clean_and_writes_every_artefact(audit):
    _, _, out, res = audit
    assert res["errors"] == []
    assert {p.name for p in out.iterdir()} >= {"audit.json", "impact_events.jsonl", "sentiment.jsonl", "event_silver.jsonl"}
    assert json.loads((out / "audit.json").read_text())["config_digest"] == res["config_digest"]


def test_impact_table_has_all_splits_targets_and_no_future_columns(audit):
    _, _, out, res = audit
    rows = read_jsonl(out / "impact_events.jsonl")
    assert {r["split"] for r in rows} >= {"train", "val", "test"} and len(rows) == res["impact"]["eligible_rows"]
    assert all(1 <= r["score"] <= 10 and r["abs_z"] >= 0 and r["episode"].startswith(r["ticker"]) for r in rows)
    # the feature registry must accept every f_* column the table ships
    from eventshock.modeling.leakage import check_features

    assert check_features([k for k in rows[0] if k.startswith("f_")])[0].severity == "INFO"


def test_no_episode_or_group_straddles_splits(audit):
    _, _, out, _ = audit
    from eventshock.modeling.leakage import group_straddle

    rows = [r for r in read_jsonl(out / "impact_events.jsonl") if r["split"] in ("train", "val", "test", "live")]
    assert require_clean(group_straddle(rows, "episode"))
    sent = read_jsonl(out / "sentiment.jsonl")
    assert require_clean(group_straddle(sent, "group", splits=("train", "valid", "test")))


def test_text_tables_are_split_stratified_and_deduplicated(audit):
    _, _, out, res = audit
    ev = read_jsonl(out / "event_silver.jsonl")
    assert {r["split"] for r in ev} == {"train", "valid", "test"}
    assert all(r["train_eligible"] == (r["tier"] in ("strong", "medium")) for r in ev)
    assert res["text"]["sentiment"]["rows"] == len(read_jsonl(out / "sentiment.jsonl"))


def test_the_audit_is_reproducible(audit, tmp_path):
    tmp, cfg, out, res = audit
    out2 = tmp_path / "again"
    res2 = run_audit(cfg, repo_root=tmp, config_dir=REPO_ROOT / "configs", mapping=load_topic_mapping(REPO_ROOT / "configs"), out_dir=out2)
    for name in ("impact_events.jsonl", "sentiment.jsonl", "event_silver.jsonl"):
        assert (out / name).read_bytes() == (out2 / name).read_bytes()
    assert res["impact"]["findings"] == res2["impact"]["findings"]


def test_missing_inputs_fail_loudly(tmp_path):
    with pytest.raises(ConfigError, match="missing input"):
        run_audit(base_config(), repo_root=tmp_path, config_dir=REPO_ROOT / "configs", mapping=load_topic_mapping(REPO_ROOT / "configs"),
                  out_dir=tmp_path / "o")


def test_an_injected_leak_is_reported_as_an_error(audit):
    _, _, out, _ = audit
    from eventshock.modeling.leakage import group_straddle

    rows = read_jsonl(out / "impact_events.jsonl")
    leaky = [dict(r) for r in rows if r["split"] == "train"][:1]
    clone = {**leaky[0], "split": "test"}
    with pytest.raises(LeakageError):
        require_clean(group_straddle([*leaky, clone], "episode"))
