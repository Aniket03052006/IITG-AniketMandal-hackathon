"""Ingestion pipeline: validate, normalise, resolve entities, de-duplicate, enrich (placeholder), assemble."""

from .run import PIPELINE_VERSION, PipelineResult, run_documents, run_snapshot

__all__ = ["PIPELINE_VERSION", "PipelineResult", "run_documents", "run_snapshot"]
