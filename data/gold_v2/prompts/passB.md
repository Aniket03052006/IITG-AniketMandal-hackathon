# Gold v2, pass B: annotator brief (deliberately worded differently from pass A)

Imagine you cover these companies for a risk desk. For each headline below ask: **"Would a risk manager log this as a distinct, new event that
could move this company's (or the market's) risk, and if so what kind?"** You see only `label_id, source, ticker, published_at, text`. Do not open any other file
in this repository except `docs/GOLD_LABELING_GUIDE.md`, which defines the label vocabulary (eight event classes plus `NONE`) and the tie-breakers.

Be strict about `NONE`: opinion pieces, lists, evergreen explainers, promotional or how-to content, scheduling notices and generic price chatter are not events.
When two classes seem plausible, label what *happened* (the cause), not what the stock did afterwards.

Write one JSON object per row, one per line: `{"label_id": "...", "event_class": "...", "secondary_class": "...", "notes": "..."}`, every row in the given order, nothing else.
