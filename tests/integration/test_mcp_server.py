"""The MCP adapter must add a surface without adding a judgement.

Two claims are load-bearing here, and each has a way of quietly becoming false.

**The adapter knows no biology.** Every domain name in this file comes from the
registry, never from a literal, so a fourth domain is genuinely covered the day
it is registered rather than the day someone remembers to add it. The strongest
form of that check is the one that registers a domain this repository does not
ship and drives all three tools against it.

**The refusals survive summarisation.** Every safety boundary the platform has
built lives *inside* the report as text, and nothing forces a calling model to
relay it. The mitigation is ordering - status, what was ignored, what is
missing, limitations and risks are declared before the summary - so the test
asserts the order rather than the presence, because presence was never the
thing at risk.
"""

from __future__ import annotations

import ast
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from virtualcell.core.consumption import ConsumptionLedger, ConsumptionStatus
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.mcp import guidance
from virtualcell.mcp.payloads import NO_STATUS_REASON, ToolRefusal
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import (
    DecisionSupport,
    QueryProvenance,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.platform.description import (
    AxisDescription,
    AxisKind,
    DomainDescription,
    TaskDescription,
    ValueType,
    probe_value,
)
from virtualcell.platform.domains import DomainRegistry, QueryValidationError
from virtualcell.platform.service import ReasoningService

mcp_server = pytest.importorskip(
    "virtualcell.mcp.server",
    reason="the MCP adapter needs the optional 'mcp' extra",
)
sdk_errors = pytest.importorskip("mcp.server.mcpserver.exceptions")

MCP_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "virtualcell" / "mcp"

REGISTRY = default_registry()
DOMAINS = REGISTRY.domains()
DESCRIPTIONS = {domain: REGISTRY.describe(domain) for domain in DOMAINS}
TOOL_NAMES = ("list_domains", "describe_domain", "reason")


# --------------------------------------------------------------------------- #
# helpers - nothing below names a vertical
# --------------------------------------------------------------------------- #


def _server(**kwargs):
    return mcp_server.build_server(**kwargs)


def _call(server, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a tool the way a client would, and return its structured payload."""
    result = asyncio.run(server.call_tool(tool, arguments or {}))
    assert not result.is_error, result.content
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _tools(server) -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def _refusal(server, tool: str, arguments: dict[str, Any]) -> ToolRefusal:
    """Call a tool expected to refuse, and recover the typed refusal it carries."""
    with pytest.raises(sdk_errors.ToolError) as caught:
        asyncio.run(server.call_tool(tool, arguments))
    return ToolRefusal.parse(str(caught.value))


def _reading_task(domain: str) -> str:
    """The task that reads measurements, chosen without naming one."""
    description = DESCRIPTIONS[domain]
    reading = [t for t in description.tasks if t.reads_measurements and t.required_axes]
    return (reading or list(description.tasks))[0].name


def _full_payload(domain: str, task: str) -> dict[str, Any]:
    """A value for every axis this task reads, built from the domain's own declaration."""
    description = DESCRIPTIONS[domain]
    wanted = set(description.tasks[0].required_axes)
    for candidate in description.tasks:
        if candidate.name == task:
            wanted = set(candidate.required_axes) | set(candidate.reads_axes)
    payload: dict[str, Any] = {}
    for axis in description.axes:
        if axis.name not in wanted:
            continue
        value = probe_value(axis)
        if value is not None:
            payload[axis.name] = value
    return payload


def _service_response(domain: str, task: str, experiment: Mapping[str, Any]) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    service = ReasoningService(store, REGISTRY)
    query = ReasoningQuery(domain=domain, task=task, experiment=dict(experiment))
    return asyncio.run(service.query(query))


# --------------------------------------------------------------------------- #
# the boundary: if the adapter knows a vertical's name, that is a failure
# --------------------------------------------------------------------------- #


def _mcp_sources() -> list[Path]:
    sources = sorted(MCP_PACKAGE.rglob("*.py"))
    assert sources, "the MCP package has no modules to check"
    return sources


def test_no_mcp_module_imports_a_vertical() -> None:
    """Mirrors the guard already standing over the kernel and the interfaces."""
    offenders: list[str] = []
    for path in _mcp_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "virtualcell.agents"
            ):
                offenders.append(f"{path.name}: from {node.module} import ...")
            if isinstance(node, ast.Import):
                offenders.extend(
                    f"{path.name}: import {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("virtualcell.agents")
                )
    assert not offenders, offenders


def test_no_mcp_module_names_a_registered_domain() -> None:
    """The names come from the registry, so this covers a fourth domain automatically."""
    offenders: list[str] = []
    for path in _mcp_sources():
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.name} contains {domain!r}" for domain in DOMAINS if domain in text)
    assert not offenders, offenders


# --------------------------------------------------------------------------- #
# the tools exist, and say what they must
# --------------------------------------------------------------------------- #


def test_exactly_the_three_designed_tools_are_registered() -> None:
    assert sorted(_tools(_server())) == sorted(TOOL_NAMES)


@pytest.mark.parametrize(("tool", "phrase"), guidance.REQUIRED_PHRASES)
def test_the_shipped_tool_description_still_carries_each_safety_rule(
    tool: str, phrase: str
) -> None:
    """A tool description is the only text a model is guaranteed to read before acting,
    so a well-meant rewording must not be able to drop a rule silently."""
    description = _tools(_server())[tool].description or ""
    assert phrase in guidance.flatten(description)


def test_the_server_instructions_refuse_a_bare_status() -> None:
    text = guidance.flatten(mcp_server.SERVER_INSTRUCTIONS)
    assert "Never report a status on its own." in text


# --------------------------------------------------------------------------- #
# list -> describe -> reason, for every registered domain
# --------------------------------------------------------------------------- #


def test_list_domains_returns_every_registered_domain() -> None:
    listed = _call(_server(), "list_domains")["domains"]
    assert [entry["domain"] for entry in listed] == list(DOMAINS)
    for entry in listed:
        assert entry["summary"].strip()
        assert entry["tasks"] == [t.name for t in DESCRIPTIONS[entry["domain"]].tasks]


@pytest.mark.parametrize("domain", DOMAINS)
def test_describe_domain_reports_the_packs_own_declaration(domain: str) -> None:
    described = _call(_server(), "describe_domain", {"domain": domain})
    declaration = DESCRIPTIONS[domain]

    assert described["domain"] == domain
    assert [t["name"] for t in described["tasks"]] == [t.name for t in declaration.tasks]
    assert [a["send_as"] for a in described["axes"]] == [a.name for a in declaration.axes]

    for axis, declared in zip(described["axes"], declaration.axes, strict=True):
        # The key a caller sends is the public name, never the display label.
        assert axis["send_as"] == declared.name
        assert axis["kind"] == declared.kind.value
        if declared.vocabulary:
            assert axis["vocabulary"] == list(declared.vocabulary)


@pytest.mark.parametrize("domain", DOMAINS)
def test_a_full_payload_reasons_through_every_task(domain: str) -> None:
    server = _server()
    for task in DESCRIPTIONS[domain].tasks:
        payload = _full_payload(domain, task.name)
        result = _call(
            server, "reason", {"domain": domain, "task": task.name, "experiment": payload}
        )
        assert result["domain"] == domain
        assert result["task"] == task.name
        assert result["summary"].strip()
        # Nothing a caller sent from the domain's own declaration may be unrecognised.
        assert result["unsupported_measurements"] == []


# --------------------------------------------------------------------------- #
# the ordering that mitigates summarisation
# --------------------------------------------------------------------------- #

SAFETY_FIELDS = (
    "status",
    "status_reason",
    "unsupported_measurements",
    "missing_inputs",
    "limitations",
    "overinterpretation_risks",
)


def test_every_safety_field_is_declared_before_the_summary() -> None:
    """Order is the mitigation, not presence: a summary read first gets copied and the
    caveats under it get dropped. The SDK derives both the output schema and the
    serialized object from this declaration order, so it is structural."""
    schema = _tools(_server())["reason"].output_schema or {}
    order = list(schema.get("properties", {}))
    assert "summary" in order
    summary_at = order.index("summary")
    for field in SAFETY_FIELDS:
        assert field in order, field
        assert order.index(field) < summary_at, field


@pytest.mark.parametrize("domain", DOMAINS)
def test_the_serialized_payload_keeps_that_order(domain: str) -> None:
    task = _reading_task(domain)
    result = _call(
        _server(),
        "reason",
        {"domain": domain, "task": task, "experiment": _full_payload(domain, task)},
    )
    order = list(result)
    summary_at = order.index("summary")
    for field in SAFETY_FIELDS:
        assert order.index(field) < summary_at, field


# --------------------------------------------------------------------------- #
# null status is stated, never filled in
# --------------------------------------------------------------------------- #


def test_a_task_that_reaches_no_verdict_says_so_explicitly() -> None:
    """At least one shipped task returns no status. Whichever it is, the caller must be
    told why rather than left to infer a verdict from the summary."""
    server = _server()
    seen = []
    for domain in DOMAINS:
        for task in DESCRIPTIONS[domain].tasks:
            result = _call(
                server,
                "reason",
                {
                    "domain": domain,
                    "task": task.name,
                    "experiment": _full_payload(domain, task.name),
                },
            )
            if result["status"] is None:
                assert result["status_reason"] == NO_STATUS_REASON
                seen.append((domain, task.name))
            else:
                assert result["status"] in DESCRIPTIONS[domain].status_vocabulary
                assert result["status_reason"].strip()
    assert seen, "no shipped task returns a null status; this test has stopped covering it"


# --------------------------------------------------------------------------- #
# the self-correction loop an unattended caller runs
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("domain", DOMAINS)
def test_a_misspelled_key_is_reported_then_fixed_from_the_description(domain: str) -> None:
    """typo -> unsupported -> describe_domain -> corrected resend.

    Without the first step the model gets a confident report that silently ignored the
    marker the user cared about most, and nothing anywhere says so.
    """
    server = _server()
    task = _reading_task(domain)
    good = _full_payload(domain, task)
    if not good:
        pytest.skip(f"{domain}/{task} reads no axes")

    real_key = next(iter(good))
    typo = real_key[:-1] + "_typo"
    broken = {key: value for key, value in good.items() if key != real_key}
    broken[typo] = good[real_key]

    first = _call(server, "reason", {"domain": domain, "task": task, "experiment": broken})
    assert typo in first["unsupported_measurements"]

    # The description is what tells the caller the right key - not a guess, not a fuzzy match.
    described = _call(server, "describe_domain", {"domain": domain})
    keys = {axis["send_as"] for axis in described["axes"]}
    assert real_key in keys and typo not in keys

    second = _call(server, "reason", {"domain": domain, "task": task, "experiment": good})
    assert second["unsupported_measurements"] == []


@pytest.mark.parametrize("domain", DOMAINS)
def test_a_missing_input_can_be_measured_and_sent_back_under_the_name_given(domain: str) -> None:
    """The whole point of `send_as`: the platform must accept back the name it handed out."""
    server = _server()
    task = _reading_task(domain)
    empty = _call(server, "reason", {"domain": domain, "task": task, "experiment": {}})
    if not empty["missing_inputs"]:
        pytest.skip(f"{domain}/{task} reports no missing inputs on an empty payload")

    by_name = {axis.name: axis for axis in DESCRIPTIONS[domain].axes}
    payload: dict[str, Any] = {}
    for requirement in empty["missing_inputs"]:
        key = requirement["send_as"]
        assert key in by_name, f"{key!r} is not an axis this domain declares"
        assert requirement["id"] == f"{domain}.axis.{key}"
        payload[key] = probe_value(by_name[key])

    answered = _call(server, "reason", {"domain": domain, "task": task, "experiment": payload})
    assert answered["unsupported_measurements"] == []
    closed = {item["send_as"] for item in answered["missing_inputs"]}
    assert not closed & set(payload), f"still missing after being supplied: {closed & set(payload)}"


def test_advice_never_appears_as_something_to_send() -> None:
    """`recommended_validation` is lab work. Synthesising a value for it is the exact
    failure this platform exists to prevent, so it must not be reachable as a key."""
    server = _server()
    for domain in DOMAINS:
        task = _reading_task(domain)
        result = _call(server, "reason", {"domain": domain, "task": task, "experiment": {}})
        sendable = {item["send_as"] for item in result["missing_inputs"]}
        advice = set(result["recommended_validation"]) | set(result["recommended_next_experiments"])
        assert not sendable & advice
        declared = {axis.name for axis in DESCRIPTIONS[domain].axes}
        assert sendable <= declared


# --------------------------------------------------------------------------- #
# the adapter re-derives nothing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("domain", DOMAINS)
def test_the_mcp_payload_is_the_services_answer_reordered(domain: str) -> None:
    """Every scientific value must be the service's, byte for byte. If the adapter ever
    computes one, this is where it shows up."""
    task = _reading_task(domain)
    experiment = _full_payload(domain, task)
    direct = _service_response(domain, task, experiment)
    through_mcp = _call(
        _server(), "reason", {"domain": domain, "task": task, "experiment": experiment}
    )

    assert through_mcp["summary"] == direct.summary
    assert through_mcp["status"] == direct.decision_support.status
    assert through_mcp["flags"] == list(direct.decision_support.flags)
    assert through_mcp["limitations"] == list(direct.limitations)
    assert through_mcp["overinterpretation_risks"] == list(direct.overinterpretation_risks)
    assert through_mcp["recommended_validation"] == list(direct.recommended_validation)
    assert through_mcp["recommended_next_experiments"] == list(direct.recommended_next_experiments)
    assert through_mcp["missing_information"] == list(direct.missing_information)
    assert [c["statement"] for c in through_mcp["supporting_evidence"]] == [
        c.statement for c in direct.supporting_evidence
    ]
    assert [c["statement"] for c in through_mcp["contradicting_evidence"]] == [
        c.statement for c in direct.contradicting_evidence
    ]
    assert [link["path"] for link in through_mcp["mechanistic_links"]] == [
        list(link.path) for link in direct.mechanistic_links
    ]
    assert [item["send_as"] for item in through_mcp["missing_inputs"]] == [
        item.canonical_axis for item in direct.missing_inputs
    ]
    assert [e["submitted_as"] for e in through_mcp["measurement_consumption"]] == [
        e.submitted_as for e in direct.measurement_consumption.entries
    ]


# --------------------------------------------------------------------------- #
# a malformed call is refused with something a caller can act on
# --------------------------------------------------------------------------- #


def test_an_unknown_domain_is_a_typed_refusal_not_a_crash() -> None:
    """A stack trace tells a model nothing it can act on. Every refusal names the tool
    that fixes it, and parses back into a stable machine-readable kind."""
    server = _server()
    for tool, arguments in (
        ("describe_domain", {"domain": "not-a-registered-domain"}),
        ("reason", {"domain": "not-a-registered-domain", "task": "assess_state"}),
    ):
        refusal = _refusal(server, tool, arguments)
        assert refusal.error == "unknown_domain"
        assert "list_domains" in refusal.remedy


@pytest.mark.parametrize("domain", DOMAINS)
def test_an_unsupported_task_names_the_tool_that_lists_the_real_ones(domain: str) -> None:
    refusal = _refusal(_server(), "reason", {"domain": domain, "task": "not-a-supported-task"})
    assert refusal.error == "unsupported_task"
    assert "describe_domain" in refusal.remedy


@pytest.mark.parametrize("domain", DOMAINS)
def test_an_off_vocabulary_value_is_refused_with_a_remedy(domain: str) -> None:
    """PR18 made categorical axes strict. The refusal must reach the caller as guidance,
    not as an opaque tool failure - and it must not invite them to invent a value."""
    task = _reading_task(domain)
    payload = _full_payload(domain, task)
    categorical = [
        axis
        for axis in DESCRIPTIONS[domain].axes
        if axis.value_type is ValueType.CATEGORICAL and axis.name in payload
    ]
    if not categorical:
        pytest.skip(f"{domain} has no categorical axis in this task's payload")

    payload[categorical[0].name] = "definitely-not-a-value"
    refusal = _refusal(_server(), "reason", {"domain": domain, "task": task, "experiment": payload})
    assert refusal.error == "invalid_experiment"
    assert "describe_domain" in refusal.remedy
    # The remedy must not read as an invitation to make a value up.
    assert "unmeasured_value" in refusal.remedy


# --------------------------------------------------------------------------- #
# the real test of the boundary: a domain this repository does not ship
# --------------------------------------------------------------------------- #

_FOURTH = "a-domain-this-repository-does-not-ship"
_AXIS = "fictional_readout"
_VOCAB = ("present", "absent", "unknown")


def _fourth_description() -> DomainDescription:
    return DomainDescription(
        domain=_FOURTH,
        summary="A fictional domain that exists only inside this test.",
        tasks=(
            TaskDescription(
                name="assess_state",
                purpose="judges a fictional state",
                reads_measurements=True,
                required_axes=(_AXIS,),
                reads_axes=(_AXIS,),
            ),
        ),
        axes=(
            AxisDescription(
                name=_AXIS,
                display_label="Fictional Readout",
                description="a fictional readout",
                value_type=ValueType.CATEGORICAL,
                vocabulary=_VOCAB,
                kind=AxisKind.STATUS,
                unmeasured_value="unknown",
                used_for=("fictional_status",),
            ),
        ),
        status_vocabulary=("fictional_status", "insufficient_evidence"),
        flags=("fictional_flag",),
        unsupported_policy="Anything this domain does not declare is reported as unsupported.",
    )


class _FourthPack:
    """A pack the MCP package has never heard of, exercised through all three tools."""

    domain = _FOURTH
    supported_tasks = ("assess_state",)

    def __init__(self) -> None:
        self._description = _fourth_description()

    def describe(self) -> DomainDescription:
        return self._description

    def validate_experiment(self, task: str, experiment: Mapping[str, Any]) -> None:
        value = experiment.get(_AXIS)
        if value is not None and value not in _VOCAB:
            raise QueryValidationError(f"{_AXIS} must be one of {_VOCAB}, got {value!r}")

    def execute(self, query: ReasoningQuery, store) -> ReasoningResponse:
        value = query.experiment.get(_AXIS, "unknown")
        answered = value in _VOCAB and value != "unknown"
        ledger = ConsumptionLedger()
        for key in query.experiment:
            if key == _AXIS:
                ledger.record(
                    key,
                    ConsumptionStatus.USED_FOR_STATUS,
                    canonical_name=_AXIS,
                    used_for=["fictional_status"],
                )
            else:
                ledger.record(
                    key,
                    ConsumptionStatus.UNSUPPORTED,
                    reason="this domain declares no such axis",
                )
        missing = [] if answered else [self._description.axes[0]]
        return ReasoningResponse(
            domain=_FOURTH,
            task=query.task,
            summary="A fictional summary that establishes nothing.",
            decision_support=DecisionSupport(
                status="fictional_status" if answered else "insufficient_evidence",
                flags=["fictional_flag"] if answered else [],
            ),
            missing_information=[axis.label for axis in missing],
            missing_inputs=[
                item
                for item in _resolve(
                    self._description, query.task, [axis.label for axis in missing]
                )
            ],
            limitations=["This domain is fictional and establishes nothing."],
            overinterpretation_risks=["Do not treat a fictional readout as a real one."],
            recommended_validation=["A fictional validation a person would perform"],
            recommended_next_experiments=["A fictional next experiment"],
            measurement_consumption=ledger.report(),
            provenance=QueryProvenance(
                domain=_FOURTH,
                task=query.task,
                pack=type(self).__name__,
                engine="a fictional engine",
                explanation_level=query.explanation_level,
                literature_requested=query.allow_literature,
            ),
        )


def _resolve(description: DomainDescription, task: str, missing: list[str]):
    from virtualcell.platform.description import resolve_missing_inputs

    return resolve_missing_inputs(description, task=task, missing=missing)


def _fourth_registry() -> DomainRegistry:
    registry = DomainRegistry()
    for name in DOMAINS:
        registry.register(type(REGISTRY.get(name))())
    registry.register(_FourthPack())
    return registry


def test_a_fourth_domain_is_reachable_through_all_three_tools_unchanged() -> None:
    """If this needs a change under src/virtualcell/mcp/, the boundary has leaked."""
    registry = _fourth_registry()
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    server = _server(registry=registry, store=store)

    listed = [entry["domain"] for entry in _call(server, "list_domains")["domains"]]
    assert _FOURTH in listed

    described = _call(server, "describe_domain", {"domain": _FOURTH})
    assert [axis["send_as"] for axis in described["axes"]] == [_AXIS]
    assert described["axes"][0]["vocabulary"] == list(_VOCAB)

    # The display label is prose; only `send_as` is a key.
    empty = _call(server, "reason", {"domain": _FOURTH, "task": "assess_state", "experiment": {}})
    assert empty["status"] == "insufficient_evidence"
    assert empty["missing_information"] == ["Fictional Readout"]
    assert [item["send_as"] for item in empty["missing_inputs"]] == [_AXIS]

    answered = _call(
        server,
        "reason",
        {"domain": _FOURTH, "task": "assess_state", "experiment": {_AXIS: "present"}},
    )
    assert answered["status"] == "fictional_status"
    assert answered["missing_inputs"] == []
    assert answered["unsupported_measurements"] == []

    typo = _call(
        server,
        "reason",
        {"domain": _FOURTH, "task": "assess_state", "experiment": {"fictional_readut": "present"}},
    )
    assert typo["unsupported_measurements"] == ["fictional_readut"]
