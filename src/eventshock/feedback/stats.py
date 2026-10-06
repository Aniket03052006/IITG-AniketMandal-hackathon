"""Aggregate statistics of analyst feedback. Counts and shares only: no model reads them."""

from __future__ import annotations

from .models import NEGATIVE, Feedback, FeedbackStats, FeedbackType, FeedbackValue, TypeStats

NOTE = ("These are counts of what analysts said. They are analyst feedback, not ground truth: they are not a validated label set, they do not change any model, score, threshold or mapping, "
        "and EventShock does not learn from them. Using them to improve a model would need a separate, validated training dataset.")
LIMITATIONS = [
    "Feedback is self-selected: analysts tend to flag what looks wrong, so agreement shares are not accuracy.",
    "Several analysts, or one analyst over time, can disagree; the latest answer of each analyst per event and type is what 'needs review' and 'disagreements' read.",
    "An event id is the event the monitor groups reports into; if grouping changes, old feedback stays attached to the id it was given for.",
]


def _type_stats(items: list[Feedback], t: FeedbackType) -> TypeStats:
    rows = [f for f in items if f.type is t]
    by: dict[str, int] = {}
    for f in rows:
        by[f.value.value] = by.get(f.value.value, 0) + 1
    n = len(rows)
    if t is FeedbackType.RELEVANCE:
        rel, part = by.get(FeedbackValue.RELEVANT.value, 0), by.get(FeedbackValue.PARTIALLY_RELEVANT.value, 0)
        return TypeStats(type=t, total=n, by_value=dict(sorted(by.items())), agreement=(rel / n if n else None), at_least_partly_relevant=((rel + part) / n if n else None))
    return TypeStats(type=t, total=n, by_value=dict(sorted(by.items())), agreement=(by.get(FeedbackValue.CORRECT.value, 0) / n if n else None))


def compute(items: list[Feedback]) -> FeedbackStats:
    latest: dict[tuple[str, str, str], Feedback] = {}          # (event, type, analyst) -> that analyst's latest answer
    for f in sorted(items, key=lambda f: (f.created_at, f.feedback_id)):
        latest[(f.event_id, f.type.value, f.analyst_id)] = f
    pairs: dict[tuple[str, str], list[Feedback]] = {}
    for (eid, t, _), f in latest.items():
        pairs.setdefault((eid, t), []).append(f)
    needs = sum(1 for fs in pairs.values() if any(f.value in NEGATIVE for f in fs))
    disagree = sum(1 for fs in pairs.values() if any(f.value in NEGATIVE for f in fs) and any(f.value not in NEGATIVE for f in fs))
    times = [f.created_at for f in items]
    return FeedbackStats(volume=len(items), events=len({f.event_id for f in items}), analysts=len({f.analyst_id for f in items}), relevance=_type_stats(items, FeedbackType.RELEVANCE),
                         scope=_type_stats(items, FeedbackType.SCOPE), event=_type_stats(items, FeedbackType.EVENT), needs_review=needs, disagreements=disagree,
                         first_at=min(times) if times else None, last_at=max(times) if times else None, note=NOTE, limitations=LIMITATIONS)
