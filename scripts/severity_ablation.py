#!/usr/bin/env python
"""Development ablation: how much does each policy for the AI's rubric answers matter? Replays the recorded real-model outputs (zero provider calls).

    python scripts/severity_ablation.py        # writes docs/evidence/severity_ai_bound_ablation.json

Development analysis on the *development* set: the recording was made with an earlier prompt, so this says how the scoring policy treats real model answers, not how good the
final prompt is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eventshock.assessment import benchmark as bm  # noqa: E402

POLICIES = {
    "rules_only": dict(free_steps=0, uninformed_baseline_accepts_quoted_answer=False, ignore_ai=True),
    "ai_strict_1_step": dict(free_steps=1, uninformed_baseline_accepts_quoted_answer=False),
    "ai_1_step_quote_lifts_where_rules_have_no_evidence (shipped)": dict(free_steps=1, uninformed_baseline_accepts_quoted_answer=True),
    "ai_2_steps": dict(free_steps=2, uninformed_baseline_accepts_quoted_answer=False),
    "ai_unbounded": dict(free_steps=4, uninformed_baseline_accepts_quoted_answer=False),
}


def main() -> int:
    rig = bm.Rig.build()
    base = rig.deriver.cfg
    out = {"recording": bm.recording_meta(bm.RECORDED), "policies": {}}
    for name, p in POLICIES.items():
        adj = base.ai_adjustment.model_copy(update={k: v for k, v in p.items() if k != "ignore_ai"})
        cfg = base.model_copy(update={"ai_adjustment": adj})
        rig.deriver.cfg = cfg
        if p.get("ignore_ai"):
            r = bm.evaluate_rules(rig, bm.DEV)
        else:
            r = bm.evaluate_recorded(rig, bm.DEV)
        out["policies"][name] = {k: r[k] for k in ("n", "min", "max", "mean", "p10", "p90", "band_counts", "spearman", "exact_band", "within_one_band", "mean_ai_effect")}
        print(f"{name:32} spearman={r['spearman']} exact={r['exact_band']} within1={r['within_one_band']} min={r['min']} max={r['max']} mean_ai_effect={r['mean_ai_effect']} bands={r['band_counts']}")
    rig.deriver.cfg = base
    (ROOT / "docs" / "evidence" / "severity_ai_bound_ablation.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
