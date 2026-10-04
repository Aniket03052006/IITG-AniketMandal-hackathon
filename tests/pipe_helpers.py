"""Builders for ingestion-pipeline tests (small entity master, documents, pipeline runner)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from eventshock.config import REPO_ROOT
from eventshock.domain import Entity, RawDocument, SourceType
from eventshock.pipeline.config import load_enrichment_config, load_pipeline_config
from eventshock.pipeline.run import run_documents

AS_OF = datetime(2026, 10, 1, 12, tzinfo=UTC)
W0 = datetime(2026, 9, 17, tzinfo=UTC)
W1 = AS_OF  # the real pack's window ends earlier than its clock; see test_normalize_validate
CFG = load_pipeline_config(REPO_ROOT / "configs")
ENRICH = load_enrichment_config(REPO_ROOT / "configs")

ENTITIES = [
    Entity(entity_id="ENT_AAPL", name="Apple Inc.", ticker="AAPL", sector="Technology", country="US",
           aliases=["Apple", "iPhone", "Apple Music"]),
    Entity(entity_id="ENT_MSFT", name="Microsoft Corporation", ticker="MSFT", sector="Technology", country="US",
           aliases=["Microsoft"]),
    Entity(entity_id="ENT_JPM", name="JPMorgan Chase & Co.", ticker="JPM", sector="Financials", country="US",
           aliases=["JPMorgan", "J.P. Morgan"]),
    Entity(entity_id="ENT_V", name="Visa Inc.", ticker="V", sector="Financials", country="US", aliases=["Visa"]),
    Entity(entity_id="ENT_TGT", name="Target Corporation", ticker="TGT", sector="Consumer", country="US",
           aliases=["Target"]),
    Entity(entity_id="ENT_SHEL", name="Shell plc", ticker="SHEL", sector="Energy", country="GB", aliases=["Shell"]),
    Entity(entity_id="ENT_GS", name="The Goldman Sachs Group, Inc.", ticker="GS", sector="Financials",
           country="US", aliases=["Goldman Sachs", "Goldman"]),
]


def doc(did: str, headline: str, *, source: str = "wire.example.com", hours: float = 10.0,
        url: str | None = "auto", stype: SourceType = SourceType.NEWS, origin: str = "GDELT_FIRST_SEEN",
        language: str = "en", label: str | None = None, body: str = "") -> RawDocument:
    meta = {"adapter": "gdelt-doc" if stype is SourceType.NEWS else "tfn-replay", "record_ref": f"t.jsonl:{did}",
            "content_sha256": "0" * 64, "timestamp_origin": origin, "domain": source if url else None}
    if label:
        meta["source_label"] = label
    return RawDocument(
        id=did, source=source, source_type=stype, published_at=AS_OF - timedelta(hours=hours), ingested_at=max(AS_OF, AS_OF - timedelta(hours=hours)),
        headline=headline, body=body, url=(f"https://{source}/{did}" if url == "auto" else url),
        language=language, raw_metadata=meta)


def run(records, entities=None):
    return run_documents(records, snapshot_id="t", as_of=AS_OF, window_start=W0, window_end=W1,
                         entities=entities or ENTITIES, cfg=CFG, enrich_cfg=ENRICH)


def jsonl_path(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def digest_without_stage6(signals) -> str:
    """The pipeline's output digest with the two fields Stage 6 added (`scope`, `evidence.novelty_measured`) removed.

    The golden digests of earlier stages were taken before those fields existed; this reproduces them, which is the proof that adding
    the fields moved no pre-existing value.
    """
    import hashlib
    import json

    payload = []
    for s in sorted(signals, key=lambda s: s.id):
        d = s.model_dump(mode="json")
        d.pop("scope", None)
        d["evidence"].pop("novelty_measured", None)
        payload.append(d)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
