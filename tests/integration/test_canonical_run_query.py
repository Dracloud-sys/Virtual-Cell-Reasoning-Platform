"""The rules the canonical-run entry has to enforce before it is safe to open.

A second way into `ReasoningService.query` is a second way to get a verdict, so each rule
here exists because the alternative is a wrong answer rather than an inconvenience:

* **Two sources for one value is a conflict, not a merge.** A run and a dict may both be
  supplied - a passage export carries the series, and the markers come from other assays -
  but where they overlap, silently preferring one would let a caller's correction be
  ignored, or their export be overwritten, with nothing in the answer saying which.
* **A pack owns its own biology mapping.** The platform never guesses that a measurement
  named `X` is the axis `Y`; it asks the pack, and refuses a domain that has no answer
  rather than inventing one.
* **Literature runs do not enter here.** A paper's number reaching a status through the
  same door as a bench measurement would undo the weak-evidence policy the literature
  layer is built on, and it would do it silently, because a literature run declares
  `OriginKind.EXPERIMENT` exactly like a real one - a paper does report a real experiment.
  What separates them is the namespace PR12 gave run identity.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from virtualcell.agents.immortalization.adapters import passage_series_to_run
from virtualcell.agents.immortalization.models import PassageObservation
from virtualcell.core.experiment import (
    SCHEMA_VERSION,
    AcquisitionMode,
    ExperimentRun,
    Measurement,
    MeasurementValueType,
    Observation,
    OriginKind,
    PassageTimePoint,
    Provenance,
    make_run_id,
)
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.literature.canonical import RUN_NAMESPACE as LITERATURE_NAMESPACE
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery
from virtualcell.platform.domains import QueryValidationError
from virtualcell.platform.service import ReasoningService

REGISTRY = default_registry()
DOMAIN = "immortalization"
TASK = "assess_state"

SERIES = [
    PassageObservation(passage=10, cumulative_PDL=12.0, DT_hours=24.0),
    PassageObservation(passage=20, cumulative_PDL=20.0, DT_hours=30.0),
    PassageObservation(passage=30, cumulative_PDL=25.0, DT_hours=40.0),
]


def _service() -> ReasoningService:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    return ReasoningService(store, REGISTRY)


def _run(**overrides: Any) -> ExperimentRun:
    run = passage_series_to_run(SERIES, run_id=make_run_id("bench", "series-1"))
    return run.model_copy(update=overrides) if overrides else run


def _ask(domain: str = DOMAIN, task: str = TASK, **fields: Any):
    query = ReasoningQuery(domain=domain, task=task, **fields)
    return asyncio.run(_service().query(query))


# --- the run path answers at all ----------------------------------------------


def test_a_canonical_run_alone_produces_an_answer() -> None:
    response = _ask(experiment_run=_run())
    assert response.summary
    assert response.decision_support.status


def test_the_dict_path_is_untouched() -> None:
    """Additive means additive: the existing entry must behave exactly as before."""
    response = _ask(experiment={"p16": "high", "p21": "high"})
    assert response.summary
    assert response.provenance.experiment_run is None


# --- a run and a dict together ------------------------------------------------


def test_a_run_and_a_dict_that_do_not_overlap_are_both_read() -> None:
    """The real workflow. A passage export carries the series; the senescence markers come
    from stains that were never in that file."""
    response = _ask(experiment_run=_run(), experiment={"p16": "high", "p21": "high"})

    submitted = {entry.submitted_as for entry in response.measurement_consumption.entries}
    assert {"cumulative_PDL", "DT_hours"} <= submitted, "the run's readings are missing"
    assert {"p16", "p21"} <= submitted, "the dict's markers are missing"


def test_a_run_and_a_dict_that_collide_are_refused() -> None:
    """Whichever one won, the answer could not say so. Refusing is the only outcome that
    cannot quietly discard a measurement."""
    with pytest.raises(QueryValidationError) as caught:
        _ask(experiment_run=_run(), experiment={"observations": [], "p16": "high"})

    message = str(caught.value)
    assert "observations" in message
    assert "p16" not in message, "only the colliding key belongs in the refusal"


def test_every_consumption_entry_names_something_the_caller_actually_sent() -> None:
    """The PR17/PR19 invariant, extended to this path. A ledger that reports on keys the
    platform synthesised from a run describes a submission nobody made."""
    response = _ask(experiment_run=_run(), experiment={"p16": "high"})

    sent = {"cumulative_PDL", "DT_hours", "p16"}
    reported = {entry.submitted_as for entry in response.measurement_consumption.entries}
    assert reported <= sent, f"the ledger invented {reported - sent}"


# --- what the platform refuses ------------------------------------------------


def test_a_domain_that_does_not_accept_runs_says_so_and_says_what_it_takes() -> None:
    other = [d for d in REGISTRY.domains() if d != DOMAIN]
    assert other, "this test needs a second registered domain"

    for domain in other:
        task = REGISTRY.tasks(domain)[0]
        with pytest.raises(QueryValidationError) as caught:
            _ask(domain=domain, task=task, experiment_run=_run())
        message = str(caught.value)
        assert domain in message
        assert "experiment" in message, "the refusal must name the entry that does work"


def test_an_unreadable_schema_version_is_refused_rather_than_guessed() -> None:
    """The run's field meanings are read out of a structure this process did not build. A
    different major version could yield a plausible-looking and wrong trajectory."""
    major = int(SCHEMA_VERSION.split(".")[0]) + 1
    with pytest.raises(QueryValidationError) as caught:
        _ask(experiment_run=_run(schema_version=f"{major}.0", checksum=None))
    assert "schema" in str(caught.value).lower()


def test_a_run_edited_after_sealing_cannot_be_submitted_at_all() -> None:
    """Integrity is enforced by the contract, so a tampered run is refused before any
    surface sees it - there is no code path where an edited run is reasoned over."""
    sealed = _run().sealed()
    with pytest.raises(ValueError, match="checksum"):
        sealed.model_copy(update={"run_id": make_run_id("bench", "other")}).model_validate(
            sealed.model_dump(mode="json") | {"run_id": make_run_id("bench", "other")}
        )


def test_an_unsealed_run_is_reported_as_unsealed_rather_than_refused() -> None:
    """A missing checksum is a missing claim, not a failed one. Refusing would block every
    run built in memory; pretending would be worse."""
    response = _ask(experiment_run=_run(checksum=None))
    assert response.provenance.experiment_run.sealed is False


# --- the weak-evidence boundary -----------------------------------------------


def _literature_run() -> ExperimentRun:
    """Shaped exactly as `virtualcell.literature.canonical` produces one."""
    return ExperimentRun(
        schema_version=SCHEMA_VERSION,
        run_id=make_run_id(LITERATURE_NAMESPACE, "candidate-1"),
        provenance=Provenance(
            origin_kind=OriginKind.EXPERIMENT,
            acquisition_mode=AcquisitionMode.IMPORTED,
            source_system="literature",
        ),
        observations=[
            Observation(
                time_point=PassageTimePoint(value=30),
                measurements=[
                    Measurement(
                        name="cumulative_PDL",
                        value=25.0,
                        value_type=MeasurementValueType.NUMERIC,
                    )
                ],
            )
        ],
    )


def test_a_literature_run_cannot_be_submitted_as_a_measurement() -> None:
    """The failure this rule prevents is not loud. A literature run declares
    `OriginKind.EXPERIMENT` like any other - a paper does report a real experiment - so
    nothing in its shape stops it driving a candidate status at full weight, and every
    safeguard the literature layer built would be bypassed through a different door."""
    with pytest.raises(QueryValidationError) as caught:
        _ask(experiment_run=_literature_run())

    message = str(caught.value)
    assert "literature" in message.lower()
    assert "allow_literature" in message, "the refusal must name the entry that does work"


def test_the_literature_check_reads_identity_not_origin_kind() -> None:
    """Pinned because the tempting check is the wrong one: filtering on `origin_kind` would
    admit every literature run and reject nothing."""
    assert _literature_run().provenance.origin_kind is OriginKind.EXPERIMENT
    assert _run().provenance.origin_kind is OriginKind.EXPERIMENT
    assert _literature_run().run_namespace == LITERATURE_NAMESPACE
    assert _run().run_namespace != LITERATURE_NAMESPACE


# --- the surfaces reach it without a change of their own -----------------------


def test_the_http_api_and_the_cli_accept_a_run_without_their_own_change() -> None:
    """Both take a `ReasoningQuery` as their payload, so the new entry is theirs the moment
    the contract has it. Asserted rather than assumed: "additive" is a claim about the
    surfaces, not about the model."""
    import json

    from fastapi.testclient import TestClient

    from virtualcell.api.main import app
    from virtualcell.cli import main as cli_main

    body = {
        "domain": DOMAIN,
        "task": TASK,
        "experiment_run": _run().model_dump(mode="json"),
    }

    with TestClient(app) as client:
        payload = client.post("/reasoning/query", json=body).json()
    assert payload["decision_support"]["status"]
    assert payload["provenance"]["experiment_run"]["run_id"] == _run().run_id

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "query.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        assert cli_main(["query", "--input", str(path), "--format", "json"]) == 0


def test_the_cli_counts_repeated_readings_instead_of_listing_them(capsys) -> None:
    """A run reports one entry per measurement *per observation* - right, because a quality
    exclusion must be traceable to its passage, but a 50-passage import would otherwise
    print the same two names a hundred times and bury the rest of the block."""
    import json
    import tempfile
    from pathlib import Path

    from virtualcell.cli import main as cli_main

    body = {"domain": DOMAIN, "task": TASK, "experiment_run": _run().model_dump(mode="json")}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "query.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        assert cli_main(["query", "--input", str(path), "--format", "text"]) == 0

    line = next(
        line for line in capsys.readouterr().out.splitlines() if "used for the status" in line
    )
    assert "cumulative_PDL (x3)" in line
    assert line.count("cumulative_PDL") == 1
