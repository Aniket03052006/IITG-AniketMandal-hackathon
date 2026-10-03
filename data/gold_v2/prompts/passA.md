# Gold v2, pass A: annotator brief

You are labelling short financial news headlines (title text only) for the **type of event** each one reports. You are blind: you see only
`label_id, source, ticker, published_at, text`. Do not look for any other file in this repository.

Follow `docs/GOLD_LABELING_GUIDE.md` exactly (the eight classes, `NONE`, the tie-breakers; label the cause, not the price move; when genuinely unsure between a
class and `NONE` choose `NONE`).

Write one JSON object per input row to the output file, one per line:
`{"label_id": "...", "event_class": "<one of the 8 classes or NONE>", "secondary_class": "<a class or empty>", "notes": "<one line for NONE or ambiguous rows>"}`
Label every row, in the order given, and no others. Output nothing else.
