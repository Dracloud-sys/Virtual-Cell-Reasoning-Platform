"""What the platform says is missing must be something the platform will accept back.

The loop an automated caller runs is short and obvious:

    read what is missing  ->  measure it  ->  send it back under the name you were given

Immortalization broke it. `missing_information` reported `SA-b-Gal`, the axis is `SA_b_gal`,
and a caller that echoed the platform's own string was told its correct measurement was an
unrecognised key. PR17's ledger reported that faithfully after the fact, which is the right
behaviour for a caller mistake and the wrong one here — the platform handed them the string.

`missing_inputs` is deliberately **only** inputs. Validation goals, next experiments,
limitations and risks each keep their own response field; a caller reads those directly. An
earlier draft copied them in here under a `kind` discriminator, which made a list named
"missing inputs" something you had to filter before you could use, and gave advisory entries
ids derived from their position in a list rather than from any identity.

These tests walk the loop for real, through the shipped service, for **every registered
domain**. Nothing here names a vertical, so a fourth domain is covered the day it registers.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from virtualcell.api.main import app
from virtualcell.cli import main as cli_main
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.description import (
    AxisKind,
    MissingInput,
    UnknownRequirementError,
    ValueType,
    resolve_missing_inputs,
)
from virtualcell.platform.service import ReasoningService

REGISTRY = default_registry()
DOMAINS = REGISTRY.domains()
DESCRIPTIONS = {d: REGISTRY.describe(d) for d in DOMAINS}


def _service(domain: str, task: str, experiment: dict) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    service = ReasoningService(store, REGISTRY)
    return asyncio.run(
        service.query(
            ReasoningQuery.model_validate(
                {"domain": domain, "task": task, "experiment": experiment}
            )
        )
    )


def _assess_task(domain: str) -> str:
    """The task that reads measurements, chosen without naming one."""
    description = DESCRIPTIONS[domain]
    reading = [t for t in description.tasks if t.reads_measurements and t.required_axes]
    return (reading or list(description.tasks))[0].name


def _minimal_payload(domain: str, task: str) -> dict:
    """The smallest payload a task accepts, taken from its own declaration.

    Not always `{}`: immortalization's mechanism task refuses a request with no construct,
    which is a legitimate refusal and not this milestone's business. `TaskDescription.example`
    exists precisely so a caller does not have to know that per domain.
    """
    described = DESCRIPTIONS[domain].task(task)
    return dict(described.example or {}) if described else {}


def _a_real_value(domain: str, axis_name: str):
    """A value the domain accepts, taken from its own declaration.

    Deliberately *not* the unmeasured spelling: submitting `unknown` would close the loop on
    paper while leaving the axis exactly as unmeasured as before.
    """
    axis = DESCRIPTIONS[domain].axis(axis_name)
    assert axis is not None, f"{domain} reported an axis it does not declare: {axis_name}"
    real = [v for v in axis.vocabulary if v != axis.unmeasured_value]
    if real:
        return real[0]
    return 1 if axis.value_type is ValueType.INTEGER else "x"


# --- the round trip, for every domain -----------------------------------------


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_missing_input_actually_round_trips(domain: str) -> None:
    """The whole point, walked end to end and one axis at a time.

    Each requirement is measured, sent back under the key the platform supplied, and the
    response is checked for the one thing that must not happen: the key coming back as
    `unsupported`. Then the gap must actually close — a loop that accepts the value and keeps
    asking for it has not closed either.
    """
    task = _assess_task(domain)
    first = _service(domain, task, {})
    assert first.missing_inputs, f"{domain}.{task} reports nothing a caller could supply"

    for requirement in first.missing_inputs:
        axis = requirement.canonical_axis
        second = _service(domain, task, {axis: _a_real_value(domain, axis)})

        assert axis not in second.measurement_consumption.unsupported, (
            f"{domain}: the platform asked for {requirement.label!r}, a caller sent the key it "
            f"was given ({axis!r}), and the platform called it unrecognised"
        )
        entry = next(e for e in second.measurement_consumption.entries if e.submitted_as == axis)
        assert entry.status.value in ("used_for_status", "used_for_guidance"), entry.status.value
        assert axis not in {m.canonical_axis for m in second.missing_inputs}, (
            f"{domain}: {axis} was supplied and is still requested"
        )


@pytest.mark.parametrize("domain", DOMAINS)
def test_supplying_everything_asked_for_closes_the_gap(domain: str) -> None:
    """The loop terminates rather than producing a new axis each round."""
    task = _assess_task(domain)
    experiment: dict = {}
    for _ in range(10):  # bounded: an unbounded loop would hang rather than fail
        outstanding = _service(domain, task, experiment).missing_inputs
        if not outstanding:
            break
        for requirement in outstanding:
            experiment[requirement.canonical_axis] = _a_real_value(
                domain, requirement.canonical_axis
            )
    else:
        pytest.fail(f"{domain}: requirements never ran out after 10 rounds")

    final = _service(domain, task, experiment)
    assert not final.missing_inputs
    assert not final.measurement_consumption.unsupported


# --- the specific failure this milestone existed to fix ------------------------


def test_the_display_label_is_still_refused_and_the_canonical_key_is_supplied() -> None:
    """Both halves of the fix, stated together.

    `SA-b-Gal` remains an unrecognised key — it never was one, and making it one would paper
    over the confusion instead of removing it. What changed is that the typed contract now
    hands the caller `SA_b_gal` instead of leaving them to guess.
    """
    response = _service("immortalization", "assess_state", {})
    assert "SA-b-Gal" in response.missing_information  # the human-facing string is unchanged

    echoed = _service("immortalization", "assess_state", {"SA-b-Gal": "high"})
    assert "SA-b-Gal" in echoed.measurement_consumption.unsupported

    requirement = next(m for m in response.missing_inputs if m.label == "SA-b-Gal")
    assert requirement.canonical_axis == "SA_b_gal"

    corrected = _service("immortalization", "assess_state", {"SA_b_gal": "high"})
    assert not corrected.measurement_consumption.unsupported


# --- every entry is a real, declared, acceptable key ---------------------------


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_entry_names_a_declared_axis_the_domain_accepts(domain: str) -> None:
    """Three claims at once, because a key that fails any of them is unusable: the entry has
    a canonical axis, the description declares it, and the domain's own validation takes it."""
    pack = REGISTRY.get(domain)
    for task in REGISTRY.tasks(domain):
        for requirement in _service(domain, task, _minimal_payload(domain, task)).missing_inputs:
            assert requirement.canonical_axis
            axis = DESCRIPTIONS[domain].axis(requirement.canonical_axis)
            assert axis is not None, f"{domain}: {requirement.canonical_axis} is undeclared"
            assert requirement.canonical_axis == axis.name  # never the display label
            assert axis.kind is not AxisKind.CONTEXT
            pack.validate_experiment(
                task, {requirement.canonical_axis: _a_real_value(domain, axis.name)}
            )


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_entry_is_resubmittable_by_construction(domain: str) -> None:
    """The narrowing, stated as behaviour: there is nothing here to filter out."""
    for task in REGISTRY.tasks(domain):
        for requirement in _service(domain, task, _minimal_payload(domain, task)).missing_inputs:
            assert requirement.resubmittable is True


@pytest.mark.parametrize("domain", DOMAINS)
def test_recommendations_never_leak_into_missing_inputs(domain: str) -> None:
    """Advice keeps its own fields. A caller reading `missing_inputs` must not have to tell
    "Karyotype / genomic-stability assay" apart from an axis it can fill in."""
    for task in REGISTRY.tasks(domain):
        response = _service(domain, task, _minimal_payload(domain, task))
        labels = {m.label for m in response.missing_inputs}
        keys = {m.canonical_axis for m in response.missing_inputs}
        advisory = set(response.recommended_validation) | set(response.recommended_next_experiments)
        assert not labels & advisory
        assert not keys & advisory
        # ...and the advisory fields themselves are untouched and still populated.
        if domain == "immortalization" and task == "assess_state":
            assert response.recommended_validation and response.recommended_next_experiments


def test_a_requirement_carries_enough_to_build_a_value_without_asking_again() -> None:
    for requirement in _service("genome_editing", "assess_state", {}).missing_inputs:
        assert requirement.value_type is ValueType.CATEGORICAL
        assert requirement.vocabulary
        assert requirement.unmeasured_value in requirement.vocabulary


# --- identity is stable ---------------------------------------------------------


def test_the_id_is_derived_from_the_axis_not_from_wording_or_order() -> None:
    """The defect that motivated narrowing the contract: an id built from a list position
    changes when the list is reordered, so the same fact gets a new id and a different fact
    inherits the old one."""
    description = DESCRIPTIONS["immortalization"]
    forward = resolve_missing_inputs(
        description, task="assess_state", missing=["gammaH2AX", "SA-b-Gal", "p16"]
    )
    reversed_order = resolve_missing_inputs(
        description, task="assess_state", missing=["p16", "SA-b-Gal", "gammaH2AX"]
    )
    assert {m.id for m in forward} == {m.id for m in reversed_order}

    by_axis = {m.canonical_axis: m.id for m in forward}
    assert by_axis["SA_b_gal"] == "immortalization.axis.SA_b_gal"
    # The label differs from the key, and the id follows the key.
    assert "SA-b-Gal" not in by_axis["SA_b_gal"]


@pytest.mark.parametrize("domain", DOMAINS)
def test_ids_are_unique_and_prefixed_by_their_domain(domain: str) -> None:
    requirements = _service(domain, _assess_task(domain), {}).missing_inputs
    ids = [m.id for m in requirements]
    assert len(ids) == len(set(ids))
    for requirement in requirements:
        assert requirement.id == f"{domain}.axis.{requirement.canonical_axis}"


# --- the contract refuses to express the failure -------------------------------


def test_an_axis_the_domain_does_not_declare_is_refused() -> None:
    with pytest.raises(UnknownRequirementError, match="declares no axis"):
        resolve_missing_inputs(
            DESCRIPTIONS["immortalization"], task="assess_state", missing=["not_an_axis"]
        )


def test_a_context_axis_reported_as_missing_is_refused() -> None:
    """Submittable is not the same as missing. Nothing reads a context field, so its absence
    is not a gap — PR17's `not_applicable` already says what becomes of one."""
    with pytest.raises(UnknownRequirementError, match="no rule reads it"):
        resolve_missing_inputs(
            DESCRIPTIONS["immortalization"], task="assess_state", missing=["species"]
        )


def test_an_entry_without_a_key_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="must name a canonical axis"):
        MissingInput(
            id="immortalization.axis.p16",
            canonical_axis="   ",
            label="p16",
            why="w",
            task="assess_state",
            value_type=ValueType.CATEGORICAL,
            vocabulary=("high",),
        )


def test_resubmittable_is_derived_and_cannot_be_overridden() -> None:
    payload = {
        "id": "immortalization.axis.p16",
        "canonical_axis": "p16",
        "label": "p16",
        "why": "w",
        "task": "assess_state",
        "value_type": "categorical",
        "vocabulary": ["high"],
        "resubmittable": False,
    }
    assert MissingInput.model_validate(payload).resubmittable is True


# --- compatibility and parity ---------------------------------------------------


@pytest.mark.parametrize("domain", DOMAINS)
def test_the_string_contract_is_untouched(domain: str) -> None:
    """`missing_information` keeps its exact values and order; the typed field is additive."""
    expected = {
        "immortalization": ["gammaH2AX", "SA-b-Gal", "p16", "p21"],
        "adipogenesis": ["PPARG", "CEBPA", "FABP4", "ADIPOQ", "PLIN1", "lipid_accumulation"],
        "genome_editing": ["edit_detected", "edit_assay", "parental_control"],
    }
    if domain not in expected:  # pragma: no cover - a fourth domain is checked structurally
        pytest.skip(f"no pinned string list for {domain}")
    assert _service(domain, _assess_task(domain), {}).missing_information == expected[domain]


@pytest.mark.parametrize("domain", DOMAINS)
def test_service_api_and_cli_report_identical_requirements(domain: str, tmp_path, capsys) -> None:
    payload = {"domain": domain, "task": _assess_task(domain), "experiment": {}}
    service = [m.model_dump(mode="json") for m in _service(**payload).missing_inputs]

    with TestClient(app) as client:
        api = client.post("/reasoning/query", json=payload)
    assert api.status_code == 200
    assert api.json()["missing_inputs"] == service

    request_file = tmp_path / "query.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    assert cli_main(["query", "--input", str(request_file), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["missing_inputs"] == service


def test_the_cli_text_view_shows_the_key_beside_the_label(tmp_path, capsys) -> None:
    request_file = tmp_path / "query.json"
    request_file.write_text(
        json.dumps({"domain": "immortalization", "task": "assess_state", "experiment": {}}),
        encoding="utf-8",
    )
    assert cli_main(["query", "--input", str(request_file), "--format", "text"]) == 0
    out = capsys.readouterr().out

    assert "missing inputs:" in out
    assert "- SA-b-Gal (send as: SA_b_gal)" in out
    assert "- p16\n" in out  # a label that *is* the key is not cluttered with a repeat
    # Advice keeps its own blocks and is not counted or summarised in the inputs block.
    assert "recommended validation:" in out
    assert "next experiments:" in out
