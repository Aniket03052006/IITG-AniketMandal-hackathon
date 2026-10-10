"""The severity benchmark: pre-registration integrity, reproducibility, and guards against the compression the previous formula showed.

These are *guards*, deliberately looser than the pre-registered acceptance criteria (which are reported, pass or fail, in docs/evidence/severity_benchmark.json).
They fail if the architecture regresses to a compressed scale; they do not assert that the pre-registered criteria are met.
"""

from __future__ import annotations

import json

import pytest

from eventshock.assessment import benchmark as bm
from eventshock.config import REPO_ROOT

EVIDENCE = REPO_ROOT / "docs" / "evidence" / "severity_benchmark.json"


@pytest.fixture(scope="module")
def rig() -> bm.Rig:
    return bm.Rig.build()


# ------------------------------------------------------------------------------------------------------------------ pre-registration
def test_the_benchmark_files_are_what_was_pre_registered() -> None:
    ev = json.loads(EVIDENCE.read_text())
    for name, ds in bm.DATASETS.items():
        assert ev["datasets"][name]["sha256"] == bm.file_sha256(ds.path), f"{ds.path.name} changed after its results were recorded"


def test_the_benchmarks_cover_every_group_and_band_and_are_skewed_like_a_real_corpus() -> None:
    for ds in bm.DATASETS.values():
        rows = bm.load_rows(ds.path)
        assert {r["group"][0] for r in rows} == set("ABCDEFGH")
        assert {r["expected_band"] for r in rows} == set(bm.BANDS)
        assert len({r["text"] for r in rows}) == len(rows), "no duplicate headlines"
        counts = [sum(r["expected_band"] == b for r in rows) for b in bm.BANDS]
        assert max(counts) / len(rows) < 0.5 and min(counts) >= 3  # not uniform, but every band is present
    dev, held = (bm.load_rows(d.path) for d in bm.DATASETS.values())
    assert not ({r["text"] for r in dev} & {r["text"] for r in held}), "the held-out set must not repeat a development headline"


# ----------------------------------------------------------------------------------------------------------------- the guards (rules mode)
def test_rule_mode_does_not_compress_the_scale_on_the_development_set(rig: bm.Rig) -> None:
    r = bm.evaluate_rules(rig, bm.DATASETS["dev"])
    assert r["min"] <= 2 and r["max"] >= 9, "the scale must reach both ends"
    assert sum(1 for b in bm.BANDS if r["band_counts"][b] >= 2) >= 4, "at least four of the five bands must be occupied"
    assert r["spearman"] >= 0.70, "the score must rank the pre-registered bands"
    assert r["within_one_band"] >= 0.85
    # the previous formula put 30 of 64 items in one band and reached at most 7 in rule mode; no band may hold a majority now
    assert max(r["band_counts"].values()) / r["n"] < 0.5


def test_the_rules_fallback_is_measured_on_the_heldout_set_and_does_not_generalise() -> None:
    """The rule vocabulary was written by an author who had seen the development set, so the dev numbers above are optimistic. The held-out set was never used to
    write or tune a cue, and it shows what the crude fallback really does on unseen wording: it under-scores (many real events read as routine) and ranks the bands
    only weakly. That is a documented limitation, not something to be tuned away against the held-out set (that would end its independence), so this test pins the
    honest finding instead of asserting a quality bar: the committed evidence must report it, and the fallback must at least rank above chance."""
    ev = json.loads(EVIDENCE.read_text())["datasets"]["heldout"]["rules"]
    assert ev["n"] == 32 and ev["spearman"] > 0.2, "the fallback should still rank better than chance"
    assert ev["spearman"] < 0.70, (
        "if the held-out rules result now meets the dev bar, check that the held-out set did not leak into the vocabulary (data/benchmarks/README.md) "
        "before celebrating, then update this test and docs/notes/RISK_ASSESSMENT.md"
    )


def test_a_systemic_text_scores_far_above_a_routine_one_in_rule_mode(rig: bm.Rig) -> None:
    routine = bm.score_text(rig, "Company to present at investor conference next month", None, use_llm=False)
    systemic = bm.score_text(rig, "Bank run spreads as the lender collapses and funding freezes across markets", None, use_llm=False)
    assert (routine["score"] or 1) <= 2 and systemic["score"] >= 9


def test_evaluation_is_reproducible_run_to_run(rig: bm.Rig) -> None:
    a, b = bm.evaluate_rules(rig), bm.evaluate_rules(rig)
    assert [i["score"] for i in a["items"]] == [i["score"] for i in b["items"]]


# ------------------------------------------------------------------------------------------------------- recorded real-model outputs (no calls)
@pytest.mark.parametrize("name", ["dev", "heldout"])
def test_recorded_outputs_replay_with_zero_provider_calls(rig: bm.Rig, name: str) -> None:
    ds = bm.DATASETS[name]
    if not ds.recorded.exists():
        pytest.skip(f"no recording for {name}")
    r = bm.evaluate_recorded(rig, ds)  # raises if any recorded answer fails to replay as an LLM answer
    assert r["fallbacks"] == 0 and r["n"] > 0, "every recorded text must replay from the recording with no provider call"
    assert r["recorded_for_sha256"] == bm.file_sha256(ds.path), "the recording was made for a different benchmark file"


@pytest.mark.parametrize("name", ["dev", "heldout"])
def test_a_current_recording_does_not_compress_the_scale(rig: bm.Rig, name: str) -> None:
    """Guards the LLM path on real model answers. Active only for a recording made with the CURRENT prompt: a recording from an earlier prompt documents history
    (the v4 recording is why the level 3 / 4 definitions were rewritten) and is not asserted against."""
    from eventshock.llm.prompt import PROMPT_VERSION

    ds = bm.DATASETS[name]
    if not ds.recorded.exists():
        pytest.skip(f"no recording for {name}")
    if bm.recording_meta(ds.recorded)["prompt_version"] != PROMPT_VERSION:
        pytest.skip(f"the {name} recording is from an earlier prompt; re-record it: python scripts/severity_benchmark.py record {name} --fresh")
    r = bm.evaluate_recorded(rig, ds)
    assert r["min"] <= 2 and r["max"] >= 9
    assert r["spearman"] >= 0.75 and r["within_one_band"] >= 0.85
    assert max(r["band_counts"].values()) / r["n"] < 0.5, "compression: one band holds half of the items"


def test_the_committed_evidence_matches_a_fresh_evaluation(rig: bm.Rig) -> None:
    """The numbers quoted in docs and reports are the numbers the code produces now."""
    ev = json.loads(EVIDENCE.read_text())
    for name, ds in bm.DATASETS.items():
        d = ev["datasets"][name]
        fresh = bm.evaluate_rules(rig, ds)
        assert (fresh["spearman"], fresh["band_counts"]) == (d["rules"]["spearman"], d["rules"]["band_counts"]), f"{name}: rerun scripts/severity_benchmark.py evaluate"
        if ds.recorded.exists() and "llm_recorded" in d:
            r = bm.evaluate_recorded(rig, ds)
            assert (r["spearman"], r["band_counts"]) == (d["llm_recorded"]["spearman"], d["llm_recorded"]["band_counts"])
