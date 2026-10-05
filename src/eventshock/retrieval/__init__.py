"""Historical analogue retrieval (Stage 8): find past reports that look like a new one and what the market did after them.

Everything here is a read-only evidence layer. It never feeds the severity score unless the pre-registered test in
``configs/evidence_v3.yaml`` (``retrieval.outcome_value.enter_score_if``) says so, and a retrieved outcome is always labelled as hindsight.
See ``docs/ANALOGUES.md``.
"""
