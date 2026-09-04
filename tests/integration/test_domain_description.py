"""A domain's self-description must be true of the domain.

The description exists so a caller — soon an MCP client, today a human reading JSON — can ask
what the axes are instead of guessing. That only helps if it cannot drift from what the domain
actually accepts.

Every test here runs over **whatever the registry holds**, and reaches a domain's real input
contract through `DomainPack.validate_experiment` rather than by importing its Pydantic model.
Nothing in this file names a vertical, so a fourth domain is genuinely covered the day it is
registered — an earlier draft claimed that while mapping three domain names to three model
classes, which made the claim false.

The vocabulary check runs in **both** directions. A description that omits an accepted value
leaves a caller unable to use it; a description that lists a rejected one sends the caller into
an error. Only checking acceptance would have missed the case this hardening fixed.
"""

from __future__ import annotations

import asyncio

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.description import AxisKind, ValueType, probe_value
from virtualcell.platform.domains import DomainError, UnknownDomainError, validate_pack
from virtualcell.platform.service import ReasoningService

REGISTRY = default_registry()
DOMAINS = REGISTRY.domains()
DESCRIPTIONS = {domain: REGISTRY.describe(domain) for domain in DOMAINS}
AXES = [(d, axis) for d in DOMAINS for axis in DESCRIPTIONS[d].axes]
CATEGORICAL = [(d, a) for d, a in AXES if a.value_type is ValueType.CATEGORICAL]

# Strings a caller could plausibly send and no domain should accept. Typos of real values, so
# the check is not satisfied by rejecting obvious nonsense.
OFF_VOCABULARY = ("hgih", "presnt", "definitely-not-a-value", "")


def _service(payload: dict) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    service = ReasoningService(store, REGISTRY)
    return asyncio.run(service.query(ReasoningQuery.model_validate(payload)))


def _assess_task(domain: str) -> str:
    """The task that reads measurements, chosen without naming one."""
    description = DESCRIPTIONS[domain]
    reading = [t for t in description.tasks if t.reads_measurements and t.required_axes]
    return (reading or list(description.tasks))[0].name


# --- every domain describes itself --------------------------------------------


def test_every_registered_domain_describes_itself() -> None:
    """Required rather than optional: a domain a caller cannot introspect is one they will
    send invented axis names to, and PR17 showed those are accepted and read by nothing."""
    assert DESCRIPTIONS and set(DESCRIPTIONS) == set(DOMAINS)
    for domain, description in DESCRIPTIONS.items():
        assert description.domain == domain
        assert description.summary.strip()
        assert description.tasks


def test_a_description_can_only_be_read_for_a_queryable_domain() -> None:
    """The stand-in name is deliberately one no vertical could ever claim. An earlier draft
    used "myogenesis", which is a plausible fourth domain - and a test that starts failing
    the day someone registers it is testing the wrong thing."""
    with pytest.raises(UnknownDomainError):
        REGISTRY.describe("not-a-registered-domain")


def test_described_tasks_are_the_tasks_the_registry_will_dispatch() -> None:
    for domain, description in DESCRIPTIONS.items():
        assert sorted(t.name for t in description.tasks) == REGISTRY.tasks(domain)


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_registered_pack_passes_the_full_contract_check(domain: str) -> None:
    """The expensive check the registry cannot afford at construction: every declared axis is
    a payload the pack's own validation accepts, on every task."""
    validate_pack(REGISTRY.get(domain))


# --- the description agrees with what the domain accepts ----------------------


@pytest.mark.parametrize(("domain", "axis"), AXES, ids=lambda v: getattr(v, "name", v))
def test_every_described_axis_is_one_the_domain_will_accept(domain: str, axis) -> None:
    """A described axis a caller cannot actually send would be worse than no description.

    Checked through the pack's own validation, so this asks the domain rather than a model
    this test had to know how to import.
    """
    REGISTRY.get(domain).validate_experiment(_assess_task(domain), {axis.name: probe_value(axis)})


@pytest.mark.parametrize(("domain", "axis"), CATEGORICAL, ids=lambda v: getattr(v, "name", v))
def test_every_declared_vocabulary_value_is_accepted(domain: str, axis) -> None:
    """Direction one: everything the description offers, the domain takes."""
    pack = REGISTRY.get(domain)
    task = _assess_task(domain)
    for value in axis.vocabulary:
        pack.validate_experiment(task, {axis.name: value})


@pytest.mark.parametrize(("domain", "axis"), CATEGORICAL, ids=lambda v: getattr(v, "name", v))
def test_a_value_outside_the_declared_vocabulary_is_refused(domain: str, axis) -> None:
    """Direction two, and the one the hardening added.

    Adipogenesis used to accept any string on a marker axis, so `PPARG: "hgih"` passed
    validation and — matching neither the present set nor the absent set — was then treated
    exactly like `unknown`. A typo became "we did not look", silently, in the vertical whose
    entire purpose is keeping those two apart.
    """
    pack = REGISTRY.get(domain)
    task = _assess_task(domain)
    for value in OFF_VOCABULARY:
        if value in axis.vocabulary:  # pragma: no cover - no domain declares these
            continue
        with pytest.raises(DomainError):
            pack.validate_experiment(task, {axis.name: value})


@pytest.mark.parametrize(("domain", "axis"), CATEGORICAL, ids=lambda v: getattr(v, "name", v))
def test_a_rejected_value_never_reaches_the_reasoning_as_a_gap(domain: str, axis) -> None:
    """The failure mode behind the vocabulary check, stated as behaviour: an invalid value
    must produce an error, not a report that quietly says the axis was unmeasured."""
    with pytest.raises(DomainError):
        _service(
            {"domain": domain, "task": _assess_task(domain), "experiment": {axis.name: "hgih"}}
        )


def _loose(name: str) -> str:
    """Compare axis names ignoring separators and case, so a display label still matches."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


@pytest.mark.parametrize("domain", DOMAINS)
def test_required_axes_are_the_ones_reported_missing_when_nothing_is_sent(domain: str) -> None:
    """The description's `required_axes` and the report's `missing_information` are two
    statements of the same fact, produced by different code.

    Matched loosely on purpose: immortalization reports a *display label* rather than the axis
    name, which is a real gap and is pinned separately below. Matching strictly here would
    conflate "the wrong axes are reported" with "the right axes are spelled for a human".
    """
    task = _assess_task(domain)
    required = {_loose(a) for a in DESCRIPTIONS[domain].task(task).required_axes}
    if not required:
        pytest.skip(f"{domain}.{task} declares no required axes")
    reported = {
        _loose(a)
        for a in _service({"domain": domain, "task": task, "experiment": {}}).missing_information
    }
    assert required <= reported, (
        f"declared required but not reported missing: {required - reported}"
    )


def test_missing_information_is_not_always_round_trippable_as_an_axis_name() -> None:
    """Closed by PR19 on the *envelope*, and this test is why it stayed open here.

    Immortalization reports its unmeasured senescence axes under display labels - `SA-b-Gal`
    for the axis a caller must send as `SA_b_gal`. A caller that echoes `missing_information`
    back as an experiment key therefore gets `unsupported`, which is precisely the loop an MCP
    client would run: read what is missing, measure it, send it under the name it was given.

    `missing_information` still reports the display label, deliberately: it is prose for a
    person, the same label appears inside an existing evidence claim, and changing either
    would break a compatibility surface to fix a machine-readability problem. The fix went
    where the problem was - `ReasoningResponse.missing_inputs` now carries the canonical key,
    proved end to end in `test_missing_input_round_trip.py`.

    So this test still passes, and now means the opposite of what it once did: the string
    field is *allowed* to be human-facing precisely because a typed field is authoritative.
    """
    missing = _service(
        {"domain": "immortalization", "task": "assess_state", "experiment": {}}
    ).missing_information
    described = {a.name for a in DESCRIPTIONS["immortalization"].axes}

    assert "SA-b-Gal" in missing  # the label a human reads...
    assert "SA-b-Gal" not in described  # ...is not the name a caller can send
    assert "SA_b_gal" in described

    echoed = _service(
        {
            "domain": "immortalization",
            "task": "assess_state",
            "experiment": {name: "high" for name in missing},
        }
    )
    assert "SA-b-Gal" in echoed.measurement_consumption.unsupported


# --- the description agrees with the consumption ledger ------------------------


@pytest.mark.parametrize(("domain", "axis"), AXES, ids=lambda v: getattr(v, "name", v))
def test_an_axis_is_consumed_as_the_kind_it_was_declared(domain: str, axis) -> None:
    """The claim that makes the single declaration real: PR17's ledger is now *derived* from
    `AxisKind`, so what a caller is told up front and what they are told afterwards cannot
    disagree."""
    task = _assess_task(domain)
    if not DESCRIPTIONS[domain].task(task).reads(axis.name):
        pytest.skip(f"{domain}.{task} does not read {axis.name}")
    if axis.value_type is ValueType.SERIES:
        pytest.skip("a series needs a structured value, covered by the domain's own tests")

    value = next((v for v in axis.vocabulary if v != axis.unmeasured_value), None)
    if value is None:
        value = 1 if axis.value_type is ValueType.INTEGER else "x"

    response = _service({"domain": domain, "task": task, "experiment": {axis.name: value}})
    entry = next(e for e in response.measurement_consumption.entries if e.submitted_as == axis.name)
    expected = {
        AxisKind.STATUS: "used_for_status",
        AxisKind.GUIDANCE: "used_for_guidance",
        AxisKind.CONTEXT: "not_applicable",
    }[axis.kind]
    assert entry.status.value == expected
    assert entry.canonical_name == axis.resolved_name
    if axis.kind is not AxisKind.CONTEXT:
        assert tuple(entry.used_for) == axis.used_for


@pytest.mark.parametrize("domain", DOMAINS)
def test_the_unsupported_policy_is_what_actually_happens(domain: str) -> None:
    """The description promises an unrecognised key is preserved, unread and reported. Every
    clause of that is checked rather than taken on trust."""
    response = _service(
        {
            "domain": domain,
            "task": _assess_task(domain),
            "experiment": {"definitely_not_an_axis": "value"},
        }
    )
    assert response.measurement_consumption.unsupported == ["definitely_not_an_axis"]
    entry = response.measurement_consumption.entries[0]
    assert entry.canonical_name is None
    assert entry.reason == DESCRIPTIONS[domain].unsupported_policy


@pytest.mark.parametrize("domain", DOMAINS)
def test_a_context_axis_really_is_read_by_nothing(domain: str) -> None:
    """Declaring an axis as context is a promise that it changes no answer. Checked by
    sending it and comparing the whole report against not sending it."""
    task = _assess_task(domain)
    context = [a for a in DESCRIPTIONS[domain].axes if a.kind is AxisKind.CONTEXT]
    if not context:
        pytest.skip(f"{domain} declares no context axes")

    def answer(experiment: dict) -> tuple[dict, object]:
        """What must not move, and what is allowed to.

        Two things legitimately differ when a context value is sent, and neither is an
        answer: the consumption ledger reports the submitted key, and ``domain_details``
        preserves the validated input verbatim - the losslessness the packs exist to have.
        Everything else on the envelope *is* the answer and must be identical.

        The native report is compared too when a pack publishes one, but by presence rather
        than by assumption: a fourth domain that structures `domain_details` differently is
        checked on the envelope alone instead of erroring on a missing key.
        """
        response = _service({"domain": domain, "task": task, "experiment": experiment})
        envelope = response.model_dump(mode="json")
        envelope.pop("measurement_consumption", None)
        envelope.pop("domain_details", None)
        return envelope, response.domain_details.get("decision_report")

    baseline_envelope, baseline_report = answer({})
    for axis in context:
        envelope, report = answer({axis.name: "something"})
        assert envelope == baseline_envelope, (
            f"{domain}.{axis.name} is declared context but changed the answer"
        )
        assert report == baseline_report, (
            f"{domain}.{axis.name} is declared context but changed the domain report"
        )
