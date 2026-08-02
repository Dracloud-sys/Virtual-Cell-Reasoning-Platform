"""Reviewed ingestion of canonical literature evidence into the knowledge graph (PR8e).

The tail of the literature pipeline: a canonical ``ExperimentRun`` built from a
``MACHINE_VERIFIED`` measurement (PR8d-2) is written into a :class:`KnowledgeStore` as
**weak, provenance-tagged, review-flagged** evidence — never as established biological
fact. The discipline mirrors the curated seed graph but is deliberately more cautious,
because a single machine-verified number is not a mechanism:

* every ingested node and edge is namespaced under ``lit:`` and tagged
  ``review_status = "pending_review"``, so literature evidence is never silently merged
  into curated truth and a human can always find and re-review it;
* the only relation emitted is the **weak, symmetric** ``ASSOCIATED_WITH`` linking a
  measurement to the marker it measured — no ``PROMOTES``/``INHIBITS``/``REGULATES`` or
  any other causal/established edge is ever created here;
* full provenance (article ids, exact locator, source-text hash, the verification
  decision, the raw value with comparator/uncertainty) travels onto the node and edge;
* ingestion is deterministic and idempotent — re-ingesting the same run upserts the same
  nodes and does not duplicate the edge.

No reasoning, entity-resolution against curated nodes, or evidence-tier computation
happens here; connecting literature markers to the curated ontology is later work.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from virtualcell.core.experiment import ExperimentRun, SchemaVersionError
from virtualcell.knowledge.schema import (
    AssayResult,
    Interaction,
    Marker,
    RelationType,
)
from virtualcell.knowledge.store import KnowledgeStore

# Provenance/labels for everything this module writes.
INGESTION_SOURCE = "literature_ingestion"
REVIEW_STATUS = "pending_review"
EVIDENCE_KIND = "literature_machine_verified"
# A fixed, conservative weight — NOT an extraction confidence and NOT a biological
# strength. A single machine-verified literature number is weak evidence by construction.
LITERATURE_EVIDENCE_CONFIDENCE = 0.3
# The one relation literature ingestion is allowed to assert (weak, symmetric).
LITERATURE_RELATION = RelationType.ASSOCIATED_WITH


class IngestionReport(BaseModel):
    """A deterministic summary of what one ingestion wrote (for reporting/tests)."""

    runs_ingested: int = 0
    markers: list[str] = Field(default_factory=list)
    assay_results: list[str] = Field(default_factory=list)
    interactions_added: int = 0
    skipped: list[str] = Field(default_factory=list)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _str(value: object) -> str:
    return value if isinstance(value, str) else str(value)


def ingest_runs(store: KnowledgeStore, runs: list[ExperimentRun]) -> IngestionReport:
    """Ingest canonical literature runs as weak, reviewable evidence.

    Deterministic and idempotent: nodes have content-derived ids and are upserted; the
    ``ASSOCIATED_WITH`` edge from a measurement to its marker is added only if not already
    present, so re-ingesting the same run is a no-op on the edge set. Returns a summary;
    the graph mutation is the side effect.
    """
    report = IngestionReport()
    seen_markers: set[str] = set()
    seen_assays: set[str] = set()
    for run in runs:
        # A consumer that reads field *meanings* out of a run it did not build. An
        # incompatible major is skipped rather than raised: one unreadable run must not
        # abort ingestion of the rest, and the skip is reported so it is never silent.
        try:
            run.require_compatible_schema()
        except SchemaVersionError as exc:
            report.skipped.append(f"{run.run_id}: {exc}")
            continue
        measurement, meta = _single_measurement(run)
        if measurement is None:
            report.skipped.append(f"{run.run_id}: no measurement to ingest")
            continue
        candidate_id = _str(meta.get("candidate_id") or run.run_id)
        marker_id = f"lit:marker:{_slug(measurement.name)}"
        assay_id = f"lit:assay:{candidate_id}"

        store.upsert(_marker(marker_id, measurement.name))
        store.upsert(_assay_result(assay_id, run, measurement, meta))
        if marker_id not in seen_markers:
            seen_markers.add(marker_id)
            report.markers.append(marker_id)
        if assay_id not in seen_assays:
            seen_assays.add(assay_id)
            report.assay_results.append(assay_id)

        if _add_association(store, assay_id, marker_id, run, meta):
            report.interactions_added += 1
        report.runs_ingested += 1
    return report


def _single_measurement(run: ExperimentRun):
    """The one canonical measurement of a literature run, with its run provenance."""
    for observation in run.observations:
        for measurement in observation.measurements:
            return measurement, run.provenance.metadata
    return None, run.provenance.metadata


def _marker(marker_id: str, name: str) -> Marker:
    return Marker(
        id=marker_id,
        name=name,
        properties={
            "source": INGESTION_SOURCE,
            "review_status": REVIEW_STATUS,
        },
    )


def _assay_result(assay_id: str, run: ExperimentRun, measurement, meta: dict) -> AssayResult:
    # Carry the full canonical provenance verbatim (stringified), plus the review flag,
    # so the node is self-describing and auditable.
    properties: dict[str, str] = {
        "source": INGESTION_SOURCE,
        "review_status": REVIEW_STATUS,
        "evidence_kind": EVIDENCE_KIND,
        "run_id": run.run_id,
        "measurement_name": measurement.name,
    }
    for key, value in meta.items():
        if value is not None:
            properties[key] = _str(value)
    return AssayResult(
        id=assay_id,
        name=f"{measurement.name} = {measurement.value}"
        + (f" {measurement.unit}" if measurement.unit else ""),
        assay=_opt(meta.get("assay")),
        value=None if measurement.value is None else _str(measurement.value),
        unit=measurement.unit,
        timepoint=_opt(run.conditions.get("time_point")),
        properties=properties,
    )


def _opt(value: object) -> str | None:
    return None if value is None else _str(value)


def _add_association(
    store: KnowledgeStore, assay_id: str, marker_id: str, run: ExperimentRun, meta: dict
) -> bool:
    """Add the weak measurement↔marker edge unless it already exists (idempotent)."""
    existing = store.edges(assay_id, relation=LITERATURE_RELATION.value, direction="any")
    if any(edge.target_id == marker_id for edge in existing):
        return False
    store.add_interaction(
        Interaction(
            source_id=assay_id,
            target_id=marker_id,
            relation=LITERATURE_RELATION,
            confidence=LITERATURE_EVIDENCE_CONFIDENCE,
            evidence=_evidence(run, meta),
        )
    )
    return True


def _evidence(run: ExperimentRun, meta: dict) -> list[str]:
    parts = [
        f"review_status:{REVIEW_STATUS}",
        f"run:{run.run_id}",
    ]
    if meta.get("article_key"):
        parts.append(f"article:{_str(meta['article_key'])}")
    if meta.get("source_text_hash"):
        parts.append(f"source_hash:{_str(meta['source_text_hash'])}")
    if meta.get("verified_at"):
        verifier = _str(meta.get("verifier", "?"))
        method = _str(meta.get("verification_method", "?"))
        parts.append(f"verified:{_str(meta['verified_at'])} by {verifier}/{method}")
    return parts
