"""Canonical Experiment Schema v1 (PR12): versioning, compatibility, conformance.

The schema is the convergence point — literature evidence, domain packs and (from PR13)
raw-assay ingestion all produce or consume it — so these tests pin the version contract
itself and prove the *real* producers and consumers honour it.

Four properties carry the weight:

* a declared version is **mandatory** on the normal wire contract, with one explicit
  legacy path for payloads written before the version existed;
* accepting a newer minor **preserves** the fields this reader does not understand,
  rather than silently dropping them while still claiming the newer version;
* run identity is namespaced, so two minting systems cannot collide;
* a measurement's value type is explicit, so a numeric assay cannot hold a string.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from virtualcell.core.experiment import (
    LEGACY_SCHEMA_VERSION,
    SCHEMA_MAJOR,
    SCHEMA_MINOR,
    SCHEMA_VERSION,
    AcquisitionMode,
    ExperimentRun,
    Measurement,
    MeasurementQuality,
    MeasurementTypeError,
    MeasurementValueType,
    Observation,
    OriginKind,
    PassageTimePoint,
    Provenance,
    RunIdError,
    SchemaVersionError,
    is_compatible,
    load_legacy_run,
    make_run_id,
    migrate_legacy_payload,
    parse_run_id,
    parse_schema_version,
    validate_schema_version,
)

NEWER_MINOR = f"{SCHEMA_MAJOR}.{SCHEMA_MINOR + 999}"
OTHER_MAJOR = f"{SCHEMA_MAJOR + 1}.0"


def _run(**over) -> ExperimentRun:
    fields = {
        "schema_version": SCHEMA_VERSION,
        "run_id": "test:1",
        "provenance": Provenance(
            origin_kind=OriginKind.EXPERIMENT, acquisition_mode=AcquisitionMode.IMPORTED
        ),
        "observations": [
            Observation(
                time_point=PassageTimePoint(value=12),
                measurements=[Measurement(name="PDL", value=24.0)],
            )
        ],
    }
    fields.update(over)
    return ExperimentRun(**fields)


# --- the version contract -----------------------------------------------------


def test_schema_version_is_the_leading_serialized_key() -> None:
    # A reader should be able to see what it is looking at before interpreting anything.
    assert list(_run().model_dump(mode="json"))[0] == "schema_version"
    assert SCHEMA_VERSION.startswith(f"{SCHEMA_MAJOR}.")


def test_parse_schema_version_splits_major_and_minor() -> None:
    assert parse_schema_version("1.0") == (1, 0)
    assert parse_schema_version("2.17") == (2, 17)


@pytest.mark.parametrize("bad", ["", "1", "1.", ".1", "1.0.0", "v1.0", "one.zero", "1.x"])
def test_malformed_versions_are_rejected(bad: str) -> None:
    with pytest.raises(SchemaVersionError):
        parse_schema_version(bad)
    assert not is_compatible(bad)


def test_a_newer_minor_is_accepted() -> None:
    """Minors are additive, so the fields this reader knows are still present and
    correctly typed. Refusing structurally valid data would be the worse failure."""
    assert is_compatible(NEWER_MINOR)
    validate_schema_version(NEWER_MINOR)  # must not raise


def test_a_different_major_is_refused() -> None:
    # Silently reading a v2 payload as v1 would corrupt the meaning of the data.
    assert not is_compatible(OTHER_MAJOR)
    with pytest.raises(SchemaVersionError, match="incompatible"):
        validate_schema_version(OTHER_MAJOR)


def test_construction_rejects_a_malformed_version_but_allows_a_foreign_one() -> None:
    with pytest.raises(ValueError):
        _run(schema_version="not-a-version")
    # A run may legitimately be *built* for another reader; only the shape is enforced.
    foreign = _run(schema_version=OTHER_MAJOR)
    assert not foreign.schema_is_compatible
    with pytest.raises(SchemaVersionError):
        foreign.require_compatible_schema()


def test_round_trip_preserves_the_version_and_content() -> None:
    original = _run()
    restored = ExperimentRun.model_validate(original.model_dump(mode="json"))
    assert restored == original
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.observations[0].measurements[0].value == 24.0


# --- a version is mandatory; legacy payloads take an explicit path -------------


def test_normal_validation_refuses_an_unversioned_payload() -> None:
    """An external payload with no version must not be assumed to be v1 forever — that
    is exactly how an unrelated shape gets read as this one."""
    payload = _run().model_dump(mode="json")
    del payload["schema_version"]
    with pytest.raises(ValueError, match="schema_version"):
        ExperimentRun.model_validate(payload)


def test_legacy_migration_loads_a_pre_versioning_payload_as_v1() -> None:
    payload = _run().model_dump(mode="json")
    del payload["schema_version"]
    migrated = load_legacy_run(payload)
    assert migrated.schema_version == LEGACY_SCHEMA_VERSION
    assert migrated.schema_is_compatible
    assert migrated.observations[0].measurements[0].value == 24.0


def test_legacy_migration_refuses_a_payload_that_already_declares_a_version() -> None:
    """Migration must never be usable to overwrite a version that failed a check."""
    payload = _run(schema_version=OTHER_MAJOR).model_dump(mode="json")
    with pytest.raises(SchemaVersionError, match="already declares"):
        migrate_legacy_payload(payload)


def test_legacy_migration_namespaces_a_pre_convention_run_id_only_when_asked() -> None:
    payload = _run().model_dump(mode="json")
    del payload["schema_version"]
    payload["run_id"] = "RUN-1"  # minted before the identity convention existed

    # Not guessed: silently renaming a stored identifier is worse than refusing it.
    with pytest.raises(ValueError, match="not namespaced"):
        load_legacy_run(payload)

    qualified = load_legacy_run(payload, namespace="legacy")
    assert qualified.run_id == "legacy:RUN-1"
    assert qualified.run_local_id == "RUN-1"


# --- accepting a newer minor means preserving what it added -------------------


def _newer_minor_payload() -> dict:
    """A v1.(n+999) payload carrying additive fields this reader knows nothing about."""
    payload = _run(schema_version=NEWER_MINOR).model_dump(mode="json")
    payload["operator_id"] = "tech-7"
    payload["provenance"]["instrument_serial"] = "XYZ-1"
    observation = payload["observations"][0]
    observation["incubator_zone"] = "B2"
    observation["time_point"]["calendar_week"] = 14
    observation["measurements"][0]["replicate_index"] = 3
    return payload


def test_a_newer_minor_payload_is_accepted_and_its_unknown_fields_survive() -> None:
    """The defect this pins: a v1.0 reader that accepts v1.1, drops the v1.1 fields, and
    reserializes the damaged object while still declaring schema_version='1.1'."""
    payload = _newer_minor_payload()
    run = ExperimentRun.model_validate(payload)

    assert run.schema_version == NEWER_MINOR
    assert run.schema_is_compatible
    # Preserved on the model, at the run level and at every nested level.
    assert run.model_extra == {"operator_id": "tech-7"}
    assert run.provenance.model_extra == {"instrument_serial": "XYZ-1"}
    observation = run.observations[0]
    assert observation.model_extra == {"incubator_zone": "B2"}
    assert observation.time_point.model_extra == {"calendar_week": 14}
    assert observation.measurements[0].model_extra == {"replicate_index": 3}


def test_unknown_fields_survive_a_json_round_trip_with_the_version_unchanged() -> None:
    payload = _newer_minor_payload()
    dumped = ExperimentRun.model_validate(payload).model_dump(mode="json")

    assert dumped["schema_version"] == NEWER_MINOR
    assert dumped["operator_id"] == "tech-7"
    assert dumped["provenance"]["instrument_serial"] == "XYZ-1"
    assert dumped["observations"][0]["incubator_zone"] == "B2"
    assert dumped["observations"][0]["time_point"]["calendar_week"] == 14
    assert dumped["observations"][0]["measurements"][0]["replicate_index"] == 3
    # ...and re-validating the dump is a fixed point.
    assert ExperimentRun.model_validate(dumped) == ExperimentRun.model_validate(payload)


def test_unknown_fields_survive_the_store_and_transmit_boundary() -> None:
    """validate -> bundle -> serialize -> re-read is the path that actually loses data."""
    from virtualcell.literature.contracts import (
        LiteratureEvidenceBundle,
        LiteratureQuery,
        ProviderProvenance,
    )

    run = ExperimentRun.model_validate(_newer_minor_payload())
    bundle = LiteratureEvidenceBundle(
        query=LiteratureQuery(query_text="TERT"),
        provider_provenance=ProviderProvenance(
            provider="p", query_sent="q", retrieved_at=datetime(2024, 1, 1, tzinfo=UTC)
        ),
        canonical_runs=[run],
    )
    restored = LiteratureEvidenceBundle.model_validate(bundle.model_dump(mode="json"))
    survivor = restored.canonical_runs[0]

    assert survivor.schema_version == NEWER_MINOR
    assert survivor.model_extra == {"operator_id": "tech-7"}
    assert survivor.observations[0].measurements[0].model_extra == {"replicate_index": 3}
    assert survivor == run


def test_a_fully_known_version_still_refuses_unknown_fields() -> None:
    """Preservation is for forward compatibility, not a general escape hatch: at a version
    this reader implements there are no additive fields left to carry, so an unknown key
    is a typo. ``metadata`` is the field for arbitrary keys."""
    payload = _run().model_dump(mode="json")
    payload["metdata"] = {"note": "typo for 'metadata'"}
    with pytest.raises(ValueError, match="unknown fields"):
        ExperimentRun.model_validate(payload)


def test_a_different_major_is_still_refused_by_consumers_despite_its_extras() -> None:
    """Preservation must not become tolerance: a v2 payload is refused at the read
    boundary even though its unknown fields were carried intact."""
    from virtualcell.agents.immortalization.adapters import run_to_passage_series
    from virtualcell.literature.contracts import (
        LiteratureEvidenceBundle,
        LiteratureQuery,
        ProviderProvenance,
    )

    payload = _newer_minor_payload()
    payload["schema_version"] = OTHER_MAJOR
    foreign = ExperimentRun.model_validate(payload)
    assert foreign.model_extra == {"operator_id": "tech-7"}  # carried...

    with pytest.raises(SchemaVersionError):  # ...but never read
        run_to_passage_series(foreign)
    with pytest.raises(ValueError, match="incompatible canonical experiment schema"):
        LiteratureEvidenceBundle(
            query=LiteratureQuery(query_text="TERT"),
            provider_provenance=ProviderProvenance(
                provider="p", query_sent="q", retrieved_at=datetime(2024, 1, 1, tzinfo=UTC)
            ),
            canonical_runs=[foreign],
        )


def test_a_bundle_may_hold_runs_at_mixed_minors() -> None:
    """A version is a property of a run, not of its container. Older stored runs and newly
    produced ones legitimately travel together; requiring one uniform minor would reject
    readable data."""
    from virtualcell.literature.contracts import (
        LiteratureEvidenceBundle,
        LiteratureQuery,
        ProviderProvenance,
    )

    bundle = LiteratureEvidenceBundle(
        query=LiteratureQuery(query_text="TERT"),
        provider_provenance=ProviderProvenance(
            provider="p", query_sent="q", retrieved_at=datetime(2024, 1, 1, tzinfo=UTC)
        ),
        canonical_runs=[
            _run(run_id="test:old"),
            ExperimentRun.model_validate(_newer_minor_payload()),
        ],
    )
    assert [run.schema_version for run in bundle.canonical_runs] == [SCHEMA_VERSION, NEWER_MINOR]


# --- run identity is namespaced ----------------------------------------------


def test_run_ids_are_namespaced_and_round_trip() -> None:
    assert make_run_id("literature", "cand-1") == "literature:cand-1"
    assert parse_run_id("literature:cand-1") == ("literature", "cand-1")
    # Only the first separator delimits: a DOI-keyed local id keeps its own colons.
    assert parse_run_id("lit:10.1/x:groupA") == ("lit", "10.1/x:groupA")


@pytest.mark.parametrize("namespace", ["", "Literature", "1lit", "lit-erature", "lit ", "lit:x"])
def test_non_canonical_namespaces_are_rejected(namespace: str) -> None:
    with pytest.raises(RunIdError):
        make_run_id(namespace, "x")


@pytest.mark.parametrize("local", ["", "   ", "has space"])
def test_non_canonical_local_ids_are_rejected(local: str) -> None:
    with pytest.raises(RunIdError):
        make_run_id("lit", local)


def test_an_unnamespaced_run_id_is_refused_by_the_schema() -> None:
    """Once ingestion and a second domain pack both mint runs, an unqualified id makes
    collisions possible with no rule preventing them."""
    with pytest.raises(ValueError, match="not namespaced"):
        _run(run_id="RUN-1")


def test_a_run_exposes_its_identity_parts() -> None:
    run = _run(run_id="ingestion:plate-7")
    assert (run.run_namespace, run.run_local_id) == ("ingestion", "plate-7")


# --- measurement values are typed --------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (24.0, MeasurementValueType.NUMERIC),
        (7, MeasurementValueType.NUMERIC),
        ("high", MeasurementValueType.CATEGORICAL),
        ("24.0", MeasurementValueType.CATEGORICAL),
        (True, MeasurementValueType.BOOLEAN),
    ],
)
def test_a_value_type_is_inferred_when_not_declared(value, expected) -> None:
    # bool before int: a flag is not a quantity, so True must never classify as numeric.
    assert Measurement(name="x", value=value).value_type is expected


def test_a_declared_numeric_measurement_refuses_a_string_value() -> None:
    """The point of the type: a numeric assay cannot silently contain a string."""
    with pytest.raises(ValueError, match="does not coerce"):
        Measurement(name="PDL", value="24.0", value_type=MeasurementValueType.NUMERIC)


def test_numeric_value_is_the_single_typed_reader() -> None:
    assert Measurement(name="PDL", value=24).numeric_value() == 24.0

    # A numeric-looking string is refused rather than parsed...
    with pytest.raises(MeasurementTypeError, match="categorical"):
        Measurement(name="PDL", value="24.0").numeric_value()
    # ...and a boolean is refused rather than promoted to 1/0.
    with pytest.raises(MeasurementTypeError, match="boolean"):
        Measurement(name="contaminated", value=True).numeric_value()


def test_a_missing_measurement_keeps_its_declared_type() -> None:
    missing = Measurement(
        name="PDL",
        quality=MeasurementQuality.MISSING,
        value_type=MeasurementValueType.NUMERIC,
    )
    assert missing.value_type is MeasurementValueType.NUMERIC
    assert not missing.is_numeric  # typed numeric, but nothing to read
    with pytest.raises(MeasurementTypeError):
        missing.numeric_value()


def test_the_immortalization_consumer_refuses_a_string_valued_assay() -> None:
    from virtualcell.agents.immortalization.adapters import (
        CanonicalAdapterError,
        canonical_to_passage_observation,
    )

    observation = Observation(
        time_point=PassageTimePoint(value=25),
        measurements=[Measurement(name="cumulative_PDL", value="22.0")],
    )
    with pytest.raises(CanonicalAdapterError, match="not numeric"):
        canonical_to_passage_observation(observation)


# --- condition precedence -----------------------------------------------------


def test_observation_conditions_override_run_conditions() -> None:
    """One canonical resolver: two readers disagreeing about precedence would silently
    disagree about what the experiment measured."""
    observation = Observation(
        time_point=PassageTimePoint(value=12),
        conditions={"oxygen_pct": 5, "note": "switched"},
    )
    run = _run(
        conditions={"medium": "DMEM", "oxygen_pct": 21},
        observations=[observation],
    )
    assert run.effective_conditions(observation) == {
        "medium": "DMEM",  # run-level default carried through
        "oxygen_pct": 5,  # observation wins
        "note": "switched",
    }
    # The stored values are untouched; precedence is resolved on read.
    assert run.conditions["oxygen_pct"] == 21


def test_effective_conditions_of_an_observation_without_overrides() -> None:
    observation = Observation(time_point=PassageTimePoint(value=12))
    run = _run(conditions={"medium": "DMEM"}, observations=[observation])
    assert run.effective_conditions(observation) == {"medium": "DMEM"}


# --- real producers emit v1 ---------------------------------------------------


def test_literature_canonical_conversion_emits_v1(jats_xml, article_identifier) -> None:
    from virtualcell.literature.canonical import RUN_NAMESPACE, experiment_runs_from_verified
    from virtualcell.literature.documents import parse_jats
    from virtualcell.literature.extraction import ExtractionTask, extract_deterministic
    from virtualcell.literature.verification import verify_candidates

    document = parse_jats(jats_xml, article=article_identifier, provider="europe_pmc")
    task = ExtractionTask(target_measurements=["TERT"])
    result = extract_deterministic(document, task)
    decisions = verify_candidates(
        document, result, task, verified_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    )
    runs = experiment_runs_from_verified(result.measurements, decisions)

    assert runs
    assert all(run.schema_version == SCHEMA_VERSION for run in runs)
    assert all(run.schema_is_compatible for run in runs)
    assert all(run.run_namespace == RUN_NAMESPACE for run in runs)


def test_immortalization_adapter_emits_v1() -> None:
    from virtualcell.agents.immortalization.adapters import passage_series_to_run
    from virtualcell.agents.immortalization.models import PassageObservation

    run = passage_series_to_run(
        [PassageObservation(passage=12, cumulative_PDL=24.0, DT_hours=40.0)],
        run_id="immortalization:passages",
    )
    assert run.schema_version == SCHEMA_VERSION
    assert run.run_namespace == "immortalization"


# --- real consumers validate before trusting the shape ------------------------


def test_passage_extraction_refuses_an_incompatible_run() -> None:
    """The consumer reads field *meanings* out of a structure it did not build; an
    incompatible major could yield a plausible but wrong trajectory."""
    from virtualcell.agents.immortalization.adapters import run_to_passage_series

    with pytest.raises(SchemaVersionError):
        run_to_passage_series(_run(schema_version=OTHER_MAJOR))


def test_passage_extraction_accepts_a_compatible_run() -> None:
    from virtualcell.agents.immortalization.adapters import (
        passage_series_to_run,
        run_to_passage_series,
    )
    from virtualcell.agents.immortalization.models import PassageObservation

    original = [PassageObservation(passage=12, cumulative_PDL=24.0, DT_hours=40.0)]
    run = passage_series_to_run(original, run_id="immortalization:passages")
    assert run_to_passage_series(run)[0].passage == 12


def test_ingestion_skips_an_incompatible_run_and_ingests_the_rest() -> None:
    """One unreadable run must not abort ingestion of the others, and the skip must be
    reported rather than silent."""
    from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
    from virtualcell.literature.ingestion import ingest_runs

    readable = _run(run_id="literature:ok")
    foreign = _run(run_id="literature:foreign", schema_version=OTHER_MAJOR)

    store = InMemoryKnowledgeStore()
    report = ingest_runs(store, [foreign, readable])

    assert report.runs_ingested == 1
    assert any("literature:foreign" in skip and "incompatible" in skip for skip in report.skipped)


def test_evidence_bundle_refuses_an_incompatible_canonical_run() -> None:
    """A bundle is what gets stored, transmitted and re-read, so it is the right boundary
    to refuse a run whose field meanings this reader cannot trust."""
    from virtualcell.literature.contracts import (
        LiteratureEvidenceBundle,
        LiteratureQuery,
        ProviderProvenance,
    )

    provenance = ProviderProvenance(
        provider="p", query_sent="q", retrieved_at=datetime(2024, 1, 1, tzinfo=UTC)
    )
    query = LiteratureQuery(query_text="TERT")

    # A compatible run is accepted...
    LiteratureEvidenceBundle(query=query, provider_provenance=provenance, canonical_runs=[_run()])
    # ...an incompatible one is refused at the bundle boundary.
    with pytest.raises(ValueError, match="incompatible canonical experiment schema"):
        LiteratureEvidenceBundle(
            query=query,
            provider_provenance=provenance,
            canonical_runs=[_run(schema_version=OTHER_MAJOR)],
        )
