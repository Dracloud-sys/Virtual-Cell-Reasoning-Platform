"""P1: an open research question reaches a design without a domain pack.

The strict path resolves a `DomainPack` before anything else, so a question nobody has
written a pack for gets an error where the bare model would have given an answer. These
questions pin the other door: same code path for any subject, evidence kept labelled by
what it actually is, a produced report checked against the request that produced it, and a
missing model provider that reports *nothing ran* rather than an empty success.

**These are behaviour tests, not research-quality tests.** The backend is scripted, so what
they establish is that the path works — never that the designs are any good. That question
needs a real model and an independent reader, and calling a scripted pass "validated
reasoning" is the confusion this file exists to keep out of the record.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from virtualcell.literature.contracts import ArticleIdentifier, SourceKind, SourceLocator
from virtualcell.research import (
    BackendCallFailed,
    BackendUnavailable,
    EvidenceItem,
    EvidenceKind,
    ModelReply,
    ResearchRequest,
    ResearchService,
    build_prompt,
    get_research_backend,
    render_report_text,
)


class ScriptedBackend:
    """Returns a fixed payload. Test-only, and deliberately not shipped in ``src``.

    It exists so the path can be exercised offline. It is not a fallback and nothing in
    the product may select it: a run with no provider must fail, not quietly use this.
    """

    name = "scripted-test"
    model = "scripted"

    def __init__(self, payload: dict | str, **reply_fields) -> None:
        self._payload = payload
        self._reply_fields = reply_fields
        self.prompts: list[str] = []

    def design(self, prompt: str, *, max_output_tokens: int) -> ModelReply:
        self.prompts.append(prompt)
        text = self._payload if isinstance(self._payload, str) else json.dumps(self._payload)
        return ModelReply(text=text, **self._reply_fields)


def _well_formed(**overrides) -> dict:
    payload = {
        "restated_question": "Does X change Y under Z, measured as W?",
        "assumptions": ["the assay reports what it claims to"],
        "hypotheses": [
            {
                "id": "H1",
                "statement": "X drives Y directly",
                "support": "evidence_linked",
                "supporting_evidence_ids": ["obs-1"],
                "contradicting_evidence_ids": [],
                "applicability": "same cell type as the observation",
            },
            {
                "id": "H2",
                "statement": "Y is an artefact of the readout",
                "support": "unverified_candidate",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "applicability": None,
            },
        ],
        "experiments": [
            {
                "id": "E1",
                "design": "vary X with the readout blinded",
                "discriminates": ["H1", "H2"],
                "controls": ["vehicle", "readout-only"],
                "measurements": ["Y"],
                "timepoints": ["day 3", "day 7"],
                "branches": [
                    {"outcome": "Y tracks X", "implication": "H2 drops out"},
                    {"outcome": "Y is flat", "implication": "H1 drops out"},
                    {"outcome": "ambiguous", "implication": "the readout is the problem"},
                ],
                "priority_rationale": "cheapest thing that separates the two",
            }
        ],
        "open_items": ["nobody has measured Z directly"],
        "evidence_used": ["obs-1"],
    }
    payload.update(overrides)
    return payload


def _observation(ident: str = "obs-1") -> EvidenceItem:
    return EvidenceItem(
        id=ident,
        kind=EvidenceKind.USER_OBSERVATION,
        statement="Y rose two-fold when X was added",
        measurement_context="n=3, day 7, plate reader, not independently replicated",
    )


def _read_span(ident: str = "lit-1") -> EvidenceItem:
    return EvidenceItem(
        id=ident,
        kind=EvidenceKind.RETRIEVED_SOURCE,
        statement="X is reported to raise Y in a related system",
        locator=SourceLocator(
            article=ArticleIdentifier(doi="10.1000/example"),
            source_kind=SourceKind.ABSTRACT,
            source_text="X treatment increased Y approximately two-fold.",
        ),
    )


# --- a question with no domain gets through -----------------------------------------------


def test_a_question_with_no_domain_reaches_a_design() -> None:
    """The whole point. No domain, no task, no registry, and an answer comes back."""
    service = ResearchService(backend=ScriptedBackend(_well_formed()))

    report = service.investigate(
        ResearchRequest(question="Why does Y rise when X is added?", evidence=[_observation()])
    )

    assert report.restated_question
    assert [h.id for h in report.hypotheses] == ["H1", "H2"]
    assert report.experiments[0].branches
    assert report.integrity == []


def test_the_request_refuses_a_blank_question() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(question="   ")


# --- the same path for unrelated subjects -------------------------------------------------


def test_two_unrelated_subjects_take_the_same_path() -> None:
    """No branch on subject matter. A biomaterial question and a metabolism question are
    handled identically, because the alternative is the dispatch table this path exists to
    avoid — and because a path that special-cases the topics it was demoed on has not been
    generalized, only decorated.
    """
    ecm = ResearchRequest(
        question="Does scaffold stiffness drive myofibroblast conversion?",
        field_of_study="biomaterials",
        context={"cell_type": "dermal fibroblast"},
        evidence=[_observation()],
    )
    metabolic = ResearchRequest(
        question="Does substrate limitation explain the drop in oxygen consumption?",
        field_of_study="cell metabolism",
        context={"cell_type": "hepatocyte"},
        evidence=[_observation()],
    )

    backend = ScriptedBackend(_well_formed())
    service = ResearchService(backend=backend)
    first = service.investigate(ecm)
    second = service.investigate(metabolic)

    assert first.model_dump(exclude={"question"}) == second.model_dump(exclude={"question"})
    assert len(backend.prompts) == 2


def test_the_field_of_study_reaches_the_prompt_as_context_not_as_a_key() -> None:
    """It is printed for a reader and it steers nothing. Both halves matter."""
    prompt = build_prompt(
        ResearchRequest(question="Q?", field_of_study="biomaterials", evidence=[_observation()])
    )

    assert "biomaterials" in prompt
    assert "does not restrict" in prompt


# --- evidence keeps its label -------------------------------------------------------------


def test_a_retrieved_span_must_say_where_it_was_read() -> None:
    with pytest.raises(ValidationError, match="carries no locator"):
        EvidenceItem(
            id="lit-x",
            kind=EvidenceKind.RETRIEVED_SOURCE,
            statement="a paper says so",
        )


def test_only_a_retrieved_span_may_carry_a_locator() -> None:
    """A model's own guess wearing a citation is the failure this forbids outright."""
    with pytest.raises(ValidationError, match="only a span actually read"):
        EvidenceItem(
            id="prior-x",
            kind=EvidenceKind.MODEL_PRIOR,
            statement="this is probably how it works",
            locator=SourceLocator(
                article=ArticleIdentifier(doi="10.1000/example"),
                source_kind=SourceKind.ABSTRACT,
                source_text="something plausible",
            ),
        )


def test_an_inference_names_what_it_was_inferred_from() -> None:
    with pytest.raises(ValidationError, match="derived from"):
        EvidenceItem(id="inf-x", kind=EvidenceKind.DERIVED_INFERENCE, statement="therefore Z")


def test_the_prompt_shows_each_item_with_its_kind_and_its_measurement_context() -> None:
    prompt = build_prompt(ResearchRequest(question="Q?", evidence=[_observation(), _read_span()]))

    assert "(user_observation)" in prompt
    assert "not independently replicated" in prompt
    assert "(retrieved_source)" in prompt
    assert "doi:10.1000/example" in prompt


# --- the report is checked against the request --------------------------------------------


def test_a_cited_evidence_id_that_was_never_supplied_is_reported() -> None:
    """The report parsed. That is not the same as the report being about this session."""
    payload = _well_formed()
    payload["hypotheses"][0]["supporting_evidence_ids"] = ["obs-1", "obs-does-not-exist"]
    service = ResearchService(backend=ScriptedBackend(payload))

    report = service.investigate(ResearchRequest(question="Q?", evidence=[_observation()]))

    codes = {f.code for f in report.integrity}
    assert "unknown_evidence_id" in codes


def test_a_hypothesis_claiming_support_it_does_not_have_is_reported() -> None:
    """`evidence_linked` while citing only the model's own prior is the confusion that
    makes an exploratory session look like a finding."""
    payload = _well_formed()
    payload["hypotheses"][0]["supporting_evidence_ids"] = ["prior-1"]
    service = ResearchService(backend=ScriptedBackend(payload))

    report = service.investigate(
        ResearchRequest(
            question="Q?",
            evidence=[
                EvidenceItem(
                    id="prior-1",
                    kind=EvidenceKind.MODEL_PRIOR,
                    statement="a mechanism worth checking",
                )
            ],
        )
    )

    codes = {f.code for f in report.integrity}
    assert "unsupported_evidence_link" in codes


def test_an_experiment_that_decides_nothing_is_reported() -> None:
    payload = _well_formed()
    payload["experiments"][0]["branches"] = []
    payload["experiments"][0]["discriminates"] = []
    service = ResearchService(backend=ScriptedBackend(payload))

    report = service.investigate(ResearchRequest(question="Q?", evidence=[_observation()]))

    codes = {f.code for f in report.integrity}
    assert {"no_decision_branches", "discriminates_nothing"} <= codes


def test_integrity_findings_do_not_fail_the_run() -> None:
    """They travel with the report. A reader needs to see both, not one instead of the
    other."""
    payload = _well_formed()
    payload["evidence_used"] = ["nope"]
    service = ResearchService(backend=ScriptedBackend(payload))

    report = service.investigate(ResearchRequest(question="Q?", evidence=[_observation()]))

    assert report.integrity
    assert report.hypotheses


# --- a missing provider is not an empty answer --------------------------------------------


def test_no_provider_raises_rather_than_returning_an_empty_design(monkeypatch) -> None:
    """`reasoning/llm.py` falls back to a template with no API key, which is right there
    and wrong here: there is no honest offline answer to "design me an experiment", so a
    fallback would report a success that never happened."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(BackendUnavailable):
        get_research_backend()

    with pytest.raises(BackendUnavailable):
        ResearchService().investigate(ResearchRequest(question="Q?"))


def test_a_model_that_returns_prose_is_a_failure_not_a_report() -> None:
    service = ResearchService(backend=ScriptedBackend("I think you should try a few things."))

    with pytest.raises(BackendCallFailed, match="parseable JSON"):
        service.investigate(ResearchRequest(question="Q?"))


def test_a_fenced_json_reply_is_accepted() -> None:
    fenced = "```json\n" + json.dumps(_well_formed()) + "\n```"
    service = ResearchService(backend=ScriptedBackend(fenced))

    report = service.investigate(ResearchRequest(question="Q?", evidence=[_observation()]))

    assert report.hypotheses


# --- provenance ---------------------------------------------------------------------------


def test_the_strict_path_still_refuses_what_it_always_refused() -> None:
    """Adding a second door must not quietly open the first one.

    An unknown domain on `ReasoningQuery` is still an error, and `domain`/`task` are still
    required. If this ever starts succeeding, a caller who asked for a verified verdict is
    silently getting exploratory prose instead — which is worse than the refusal.
    """
    from virtualcell.platform.bootstrap import default_registry
    from virtualcell.platform.contracts import ReasoningQuery
    from virtualcell.platform.domains import UnknownDomainError

    with pytest.raises(ValidationError):
        ReasoningQuery(task="assess")  # type: ignore[call-arg]

    with pytest.raises(UnknownDomainError):
        default_registry().resolve("extracellular_matrix_scaffold", "assess")


def test_the_two_paths_do_not_share_a_request_type() -> None:
    """`ResearchRequest` has no domain and no task, and forbids them being smuggled in."""
    assert "domain" not in ResearchRequest.model_fields
    assert "task" not in ResearchRequest.model_fields
    with pytest.raises(ValidationError):
        ResearchRequest(question="Q?", domain="immortalization")  # type: ignore[call-arg]


# --- the one user-facing surface ----------------------------------------------------------


def _write_request(tmp_path, payload: dict):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_cli_reports_a_missing_provider_with_its_own_exit_code(tmp_path, monkeypatch, capsys):
    """Exit 3 is "nothing ran", which a caller must be able to tell from a bad request (1)
    and from a provider that ran and failed (4). Retrying the wrong one wastes a budget."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from virtualcell.cli import main

    path = _write_request(tmp_path, {"question": "Why does Y rise when X is added?"})

    assert main(["research", "--input", str(path)]) == 3
    assert "nothing ran" in capsys.readouterr().out


def test_the_cli_rejects_a_malformed_request(tmp_path, capsys):
    from virtualcell.cli import main

    path = _write_request(tmp_path, {"goal": "no question here"})

    assert main(["research", "--input", str(path)]) == 1
    assert "invalid research request" in capsys.readouterr().out


def test_the_cli_prints_a_report_including_its_integrity_findings(tmp_path, monkeypatch, capsys):
    """The text surface must show the findings, not just the design. A reader who sees only
    the confident half has been told less than the report knows."""
    import virtualcell.research as research_pkg

    payload = _well_formed()
    payload["evidence_used"] = ["never-supplied"]
    backend = ScriptedBackend(payload)
    monkeypatch.setattr(
        research_pkg, "ResearchService", lambda *a, **k: ResearchService(backend=backend)
    )

    from virtualcell.cli import main

    path = _write_request(
        tmp_path,
        {
            "question": "Does scaffold stiffness drive myofibroblast conversion?",
            "evidence": [
                {
                    "id": "obs-1",
                    "kind": "user_observation",
                    "statement": "alpha-SMA rose between day 7 and 14",
                    "measurement_context": "n=2, one operator",
                }
            ],
        },
    )

    # 5, not 0: the report is printed, and a script reading only the exit code is still
    # told that something in it does not check out. See the dedicated test below.
    assert main(["research", "--input", str(path), "--format", "text"]) == 5
    out = capsys.readouterr().out
    assert "H1" in out and "tells apart" in out
    assert "Integrity findings" in out
    assert "never-supplied" in out


# --- P1.1 review: defects found by reading the code against its own claims ---------------


def test_the_model_cannot_manufacture_a_source_record() -> None:
    """Q1. Evidence enters only from the request; the model returns hypotheses and
    experiments and has no channel for an `EvidenceItem`. A payload that tries anyway is
    ignored rather than merged, so a fabricated citation cannot become trusted evidence.
    """
    payload = _well_formed()
    payload["evidence"] = [
        {"id": "forged-1", "kind": "retrieved_source", "statement": "a paper I invented"}
    ]
    service = ResearchService(backend=ScriptedBackend(payload))

    report = service.investigate(ResearchRequest(question="Q?", evidence=[_observation()]))

    assert [item.id for item in report.evidence_snapshot] == ["obs-1"]
    assert "forged-1" not in {item.id for item in report.evidence_snapshot}


def test_the_report_resolves_its_citations_rather_than_only_naming_them() -> None:
    """Q2. A report carrying only ids cannot be audited on its own: a later reader sees
    `obs-1` and has no way to know what it said. The offered evidence travels with it.
    """
    report = ResearchService(backend=ScriptedBackend(_well_formed())).investigate(
        ResearchRequest(question="Q?", evidence=[_observation(), _read_span()])
    )

    snapshot = {item.id: item for item in report.evidence_snapshot}
    assert snapshot["obs-1"].statement == "Y rose two-fold when X was added"
    assert snapshot["obs-1"].measurement_context
    assert snapshot["lit-1"].locator is not None
    assert snapshot["lit-1"].locator.source_text_hash


def test_reusing_an_id_with_changed_content_is_detectable() -> None:
    """Q3. Stable ids across sessions are useful and dangerous: the same `obs-1` with a
    different statement must not silently look like the same evidence. A content digest
    makes the change visible to anyone comparing two reports.
    """
    original = _observation()
    edited = EvidenceItem(
        id="obs-1",
        kind=EvidenceKind.USER_OBSERVATION,
        statement="Y rose ten-fold when X was added",
        measurement_context=original.measurement_context,
    )

    assert original.content_hash != edited.content_hash
    assert original.content_hash == _observation().content_hash


def test_a_supplied_content_hash_that_disagrees_with_the_content_is_rejected() -> None:
    """A stale digest travelling with changed text would be worse than no digest."""
    with pytest.raises(ValidationError, match="content_hash"):
        EvidenceItem(
            id="obs-1",
            kind=EvidenceKind.USER_OBSERVATION,
            statement="Y rose two-fold",
            content_hash="0" * 64,
        )


def test_integrity_findings_are_not_reported_only_as_a_plain_success(tmp_path, monkeypatch, capsys):
    """Q6. The report is still produced and still printed — but a script that checks only
    the exit code must not read "cites evidence that does not exist" as success.
    """
    import virtualcell.research as research_pkg

    payload = _well_formed()
    payload["hypotheses"][0]["supporting_evidence_ids"] = ["obs-1", "never-supplied"]
    backend = ScriptedBackend(payload)
    monkeypatch.setattr(
        research_pkg, "ResearchService", lambda *a, **k: ResearchService(backend=backend)
    )

    from virtualcell.cli import main

    path = _write_request(
        tmp_path,
        {
            "question": "Q?",
            "evidence": [{"id": "obs-1", "kind": "user_observation", "statement": "Y rose"}],
        },
    )

    assert main(["research", "--input", str(path), "--format", "text"]) == 5
    out = capsys.readouterr().out
    assert "H1" in out  # the report is still shown
    assert "never-supplied" in out


def test_a_clean_report_still_exits_zero(tmp_path, monkeypatch, capsys):
    import virtualcell.research as research_pkg

    backend = ScriptedBackend(_well_formed())
    monkeypatch.setattr(
        research_pkg, "ResearchService", lambda *a, **k: ResearchService(backend=backend)
    )

    from virtualcell.cli import main

    path = _write_request(
        tmp_path,
        {
            "question": "Q?",
            "evidence": [{"id": "obs-1", "kind": "user_observation", "statement": "Y rose"}],
        },
    )

    assert main(["research", "--input", str(path), "--format", "text"]) == 0


def test_the_budget_does_not_promise_a_ceiling_nothing_enforces() -> None:
    """Q7. `max_model_calls` was declared, validated, and read by nothing. A budget field
    that cannot be exceeded and cannot be checked is a claim, not a control; the loop that
    will need one is P3's. `max_output_tokens` stays because the provider enforces it.
    """
    from virtualcell.research.contracts import ResearchBudget

    assert "max_model_calls" not in ResearchBudget.model_fields
    assert "max_output_tokens" in ResearchBudget.model_fields


def test_a_truncated_reply_says_the_output_budget_was_too_small() -> None:
    """Q7. Hitting `max_tokens` produces JSON that stops mid-object, and reporting that as
    "the model did not return parseable JSON" sends the caller to debug the wrong thing.
    """
    from virtualcell.research.backend import AnthropicResearchBackend, BackendCallFailed

    class _Block:
        type = "text"
        text = '{"restated_question": "half a repl'

    class _Response:
        stop_reason = "max_tokens"
        content = [_Block()]

    backend = AnthropicResearchBackend(model="test-model")
    with pytest.raises(BackendCallFailed, match="output budget"):
        backend._read_reply(_Response())


def test_the_report_records_what_produced_it() -> None:
    service = ResearchService(backend=ScriptedBackend(_well_formed()))

    report = service.investigate(
        ResearchRequest(question="Q?", evidence=[_observation(), _read_span()])
    )

    assert report.provenance.backend == "scripted-test"
    assert report.provenance.prompt_version
    assert report.provenance.evidence_offered == 2
    assert report.provenance.model_calls == 1


# --- P1.2: what the model returns is checked before a report is built from it -------------
#
# Every question in this block was reproduced against the shipped code first, through
# `ResearchService.investigate` and through the CLI, before anything was changed. They are
# recorded as the behaviour that was actually observed, not as the behaviour that was
# feared.


def _run(payload, **request_kwargs):
    """Investigate `payload` through the product path. Returns the report."""
    return ResearchService(backend=ScriptedBackend(payload)).investigate(
        ResearchRequest(question="Q?", **request_kwargs)
    )


def test_a_reply_containing_no_design_is_not_an_ordinary_success() -> None:
    """Observed before the fix: `{"restated_question": "R?"}` produced a report with zero
    hypotheses, zero experiments, **zero integrity findings and exit 0**. A caller reading
    only the exit code was told a research design had been produced. It had not.
    """
    report = _run({"restated_question": "Does X change Y, measured as W?"})

    assert report.hypotheses == []
    assert report.experiments == []
    assert [f.code for f in report.integrity] == ["no_design_produced"]


def test_a_stated_hold_is_told_apart_from_an_empty_shell() -> None:
    """Declining to design, and saying what is missing, is a legitimate answer — the one
    the prompt asks for when nothing supplied can carry a design. It still must not read
    as a completed design, and it must not read as the same thing as an empty reply: one
    needs the missing material, the other needs the call re-examined.
    """
    report = _run(
        {
            "restated_question": "Does X change Y?",
            "open_items": ["no baseline for Y in this cell type; nothing can be designed yet"],
        }
    )

    assert [f.code for f in report.integrity] == ["design_withheld"]
    assert report.open_items


def test_a_hypothesis_count_is_never_padded_to_reach_a_quota() -> None:
    """The counterpart to the two questions above, and the reason neither of them demands
    a number. A single well-founded hypothesis is a valid answer; a validator that
    required three would be asking the model to invent two.
    """
    payload = _well_formed(
        hypotheses=[
            {
                "id": "H1",
                "statement": "X drives Y directly",
                "support": "evidence_linked",
                "supporting_evidence_ids": ["obs-1"],
                "contradicting_evidence_ids": [],
                "applicability": None,
            }
        ],
        experiments=[],
    )
    report = _run(payload, evidence=[_observation()])

    assert len(report.hypotheses) == 1
    assert report.integrity == []


def test_a_null_where_a_list_belongs_is_a_typed_failure() -> None:
    """Observed before the fix: `"hypotheses": null` escaped as a raw
    ``TypeError: 'NoneType' object is not iterable``, straight past the CLI's typed
    handlers, so a caller saw a traceback instead of a diagnosis.
    """
    with pytest.raises(BackendCallFailed, match="hypotheses"):
        _run(_well_formed(hypotheses=None))


def test_a_null_element_inside_a_list_is_a_typed_failure() -> None:
    """Observed before the fix: a raw
    ``AttributeError: 'NoneType' object has no attribute 'get'``.
    """
    with pytest.raises(BackendCallFailed, match=r"hypotheses\[0\]"):
        _run(_well_formed(hypotheses=[None]))


def test_a_bare_string_is_not_a_list_of_its_own_characters() -> None:
    """The quietest of the lot. `"assumptions": "abc"` produced ``['a', 'b', 'c']`` — three
    assumptions nobody wrote, each one character long, printed in the report as if the
    model had listed them. A string is iterable; that is not the same as being a list.
    """
    with pytest.raises(BackendCallFailed, match="assumptions"):
        _run(_well_formed(assumptions="abc"))


def test_an_evidence_id_that_is_not_a_string_is_refused_rather_than_stringified() -> None:
    """``str(1)`` is ``"1"``, which is a perfectly well-formed evidence id that nobody
    supplied. Coercion here would manufacture the citation the integrity check then goes
    looking for.
    """
    payload = _well_formed()
    payload["hypotheses"][0]["supporting_evidence_ids"] = [1]

    with pytest.raises(BackendCallFailed, match="supporting_evidence_ids"):
        _run(payload)


def test_an_unknown_support_value_is_named_rather_than_raised_raw() -> None:
    """Observed before the fix: `"support": "definitely_true"` raised a bare ``ValueError``
    from inside a list comprehension. The two legal values are now in the message, because
    a model that invented a third needs to be told which two exist.
    """
    payload = _well_formed()
    payload["hypotheses"][0]["support"] = "definitely_true"

    with pytest.raises(BackendCallFailed, match="definitely_true") as exc:
        _run(payload)
    assert "evidence_linked" in str(exc.value)
    assert "unverified_candidate" in str(exc.value)


def test_a_field_nobody_declared_is_reported_rather_than_dropped() -> None:
    """The one that mattered most. Observed before the fix: a hypothesis carrying
    ``"certainty": 0.99`` and ``"citation": "Nature 2020"`` was assembled into a report
    with **both silently discarded and no trace anywhere**. The prompt forbids a numeric
    confidence and forbids inventing a citation; the model did both, and the report said
    the model had complied.

    The value is quoted back, not just the key, because "the model attached a citation"
    and "the model attached *this* citation" are different things to a reader deciding
    whether a fabricated source nearly reached their notes.
    """
    payload = _well_formed()
    payload["hypotheses"][0]["certainty"] = 0.99
    payload["hypotheses"][0]["citation"] = "Nature 2020"

    report = _run(payload, evidence=[_observation()])

    reported = [f for f in report.integrity if f.code == "unexpected_model_field"]
    assert {f.where for f in reported} == {"hypothesis:H1"}
    joined = " ".join(f.detail for f in reported)
    assert "certainty" in joined and "0.99" in joined
    assert "citation" in joined and "Nature 2020" in joined


def test_an_undeclared_key_at_the_top_of_the_reply_is_reported_too() -> None:
    """`evidence_snapshot`, `integrity` and `provenance` are written from the request and
    the call, never from the payload. A reply offering one is trying to author the record
    of its own trustworthiness, and that attempt should be visible.
    """
    report = _run(_well_formed(evidence_snapshot=[{"id": "made-up", "statement": "invented"}]))

    assert any(
        f.code == "unexpected_model_field" and "evidence_snapshot" in f.detail
        for f in report.integrity
    )
    assert report.evidence_snapshot == []


def test_two_hypotheses_sharing_an_id_are_reported() -> None:
    """Observed before the fix: both were accepted, and an experiment saying it
    discriminates ``H1`` named neither in particular — while the integrity check happily
    confirmed that ``H1`` existed.
    """
    payload = _well_formed()
    payload["hypotheses"][1]["id"] = "H1"

    report = _run(payload, evidence=[_observation()])

    assert any(f.code == "duplicate_hypothesis_id" for f in report.integrity)


def test_an_empty_statement_is_reported_without_discarding_the_reply() -> None:
    """A hypothesis with no statement says nothing, but the rest of the reply may still be
    worth reading. It stays, and the gap is named where it is.
    """
    payload = _well_formed()
    payload["hypotheses"][0]["statement"] = "   "

    report = _run(payload, evidence=[_observation()])

    assert len(report.hypotheses) == 2
    assert any(
        f.code == "empty_required_text" and f.where == "hypothesis:H1" for f in report.integrity
    )


def test_the_reply_is_checked_before_any_part_of_a_report_is_built() -> None:
    """Ordering, stated as behaviour rather than as a comment. A payload that is malformed
    in one place and fine everywhere else produces **no report at all** — not a partial one
    with the good half filled in, which is what assembling first produced.
    """
    service = ResearchService(backend=ScriptedBackend(_well_formed(open_items=None)))

    with pytest.raises(BackendCallFailed, match="open_items"):
        service.investigate(ResearchRequest(question="Q?"))


# --- P1.2: the default output does not hide what the reader needs -------------------------


def test_the_text_output_prints_everything_the_report_holds(tmp_path, monkeypatch, capsys):
    """`--format text` is the default, so what it omits is what most readers never see.
    Observed before the fix: it dropped `contradicting_evidence_ids`, `applicability`,
    `controls`, `measurements`, `timepoints` and `priority_rationale`.

    `applicability` is the worst of those to lose. It is where a hypothesis says the
    supporting result came from another species — the species-mismatch warning, printed
    nowhere. And a design without its controls is not a design.
    """
    from virtualcell import cli

    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "question": "Why does Y rise when X is added?",
                "evidence": [
                    {
                        "id": "obs-1",
                        "kind": "user_observation",
                        "statement": "Y rose two-fold when X was added",
                    },
                    {
                        "id": "obs-2",
                        "kind": "user_observation",
                        "statement": "Y did not rise in the second batch",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    payload = _well_formed()
    payload["hypotheses"][0]["contradicting_evidence_ids"] = ["obs-2"]
    payload["hypotheses"][0]["applicability"] = "shown in mouse cortex, asked about human skin"
    monkeypatch.setattr(
        "virtualcell.research.ResearchService",
        lambda: ResearchService(backend=ScriptedBackend(payload)),
    )

    cli.main(["research", "--input", str(request)])
    out = capsys.readouterr().out

    assert "obs-2" in out
    assert "shown in mouse cortex, asked about human skin" in out
    assert "vehicle" in out and "readout-only" in out
    assert "day 3" in out and "day 7" in out
    assert "cheapest thing that separates the two" in out


# --- P1.2: an evidence digest that covers what the evidence actually asserts ---------------


def _span(statement: str, **locator_kwargs) -> EvidenceItem:
    fields = {
        "article": ArticleIdentifier(doi="10.1000/paper-a"),
        "source_kind": SourceKind.ABSTRACT,
        "source_text": "X treatment increased Y approximately two-fold.",
    }
    fields.update(locator_kwargs)
    return EvidenceItem(
        id="lit-1",
        kind=EvidenceKind.RETRIEVED_SOURCE,
        statement=statement,
        locator=SourceLocator(**fields),
    )


def test_the_same_sentence_from_two_different_papers_is_not_the_same_evidence() -> None:
    """Observed before the fix: **identical hashes**. The digest covered the span's text
    and nothing about where it came from, so "this was published in A" and "this was
    published in B" were the same item — and swapping one citation for another left the
    digest that exists to detect exactly that kind of edit completely unmoved.
    """
    from_a = _span("X raises Y", article=ArticleIdentifier(doi="10.1000/paper-a"))
    from_b = _span("X raises Y", article=ArticleIdentifier(doi="10.2000/paper-b"))

    assert from_a.content_hash != from_b.content_hash


def test_the_same_span_read_in_two_places_in_one_paper_is_not_the_same_evidence() -> None:
    """Observed before the fix: **identical hashes**. A sentence in the Results and the
    same sentence in the Discussion are a measurement and a gloss on one, and the locator
    is the only thing that says which was read.
    """
    results = _span("X raises Y", section_title="Results")
    discussion = _span("X raises Y", section_title="Discussion")

    assert results.content_hash != discussion.content_hash


def test_a_joined_list_cannot_impersonate_two_entries() -> None:
    """Observed before the fix: **identical hashes**. The digest joined lists on ``|``, so
    one id containing that character and two separate ids produced the same bytes. A
    digest whose serialisation is not injective cannot say two items differ.
    """
    one = EvidenceItem(
        id="inf-1",
        kind=EvidenceKind.DERIVED_INFERENCE,
        statement="X probably acts through Z",
        derived_from=["a|b"],
    )
    two = one.model_copy(update={"derived_from": ["a", "b"], "content_hash": None})
    two = EvidenceItem(**two.model_dump(exclude={"content_hash"}))

    assert one.content_hash != two.content_hash


def test_the_digest_still_ignores_the_id_it_exists_to_outlive() -> None:
    """The property the digest is for: the same content under two ids agrees, so a later
    reader can tell that `obs-1` in one report and `obs-7` in another are the same claim —
    and that `obs-1` saying "two-fold" and `obs-1` saying "ten-fold" are not.
    """
    first = _observation("obs-1")
    second = _observation("obs-7")
    edited = EvidenceItem(
        id="obs-1",
        kind=EvidenceKind.USER_OBSERVATION,
        statement="Y rose ten-fold when X was added",
        measurement_context="n=3, day 7, plate reader, not independently replicated",
    )

    assert first.content_hash == second.content_hash
    assert first.content_hash != edited.content_hash


# --- P1.2: what a real provider call is allowed to spend, and what it reported -------------


class _Usage:
    input_tokens = 1234
    output_tokens = 567


class _TextBlock:
    type = "text"
    text = '{"restated_question": "R?"}'


class _GoodResponse:
    stop_reason = "end_turn"
    model = "claude-opus-5-dated-id"
    content = [_TextBlock()]
    usage = _Usage()


def test_the_provider_call_sets_its_own_per_request_limits() -> None:
    """The SDK's default is a ten-minute timeout. Both limits are set here instead, so what
    one request is allowed is readable in this repository rather than in a dependency's
    release notes.

    What they are **not** is a deadline, and an earlier version of this test asserted that
    they were: ``timeout_seconds * max_request_attempts <= 600.0``, described as "the figure
    a caller has to budget for". That product is not an upper bound — the SDK sleeps between
    retries with backoff the per-request timeout does not cover — and nothing here cancels
    an operation that exceeds it, so no total deadline is enforced at all. The assertion
    pinned a control that does not exist.
    """
    from virtualcell.research.backend import (
        DEFAULT_MAX_RETRIES,
        DEFAULT_TIMEOUT_SECONDS,
        AnthropicResearchBackend,
    )

    backend = AnthropicResearchBackend(model="test-model")

    assert backend.timeout_seconds == DEFAULT_TIMEOUT_SECONDS < 600.0
    assert backend.max_request_attempts == DEFAULT_MAX_RETRIES + 1


def test_how_long_a_call_took_is_measured_rather_than_predicted() -> None:
    """Since no deadline is enforced, the settings cannot say how long a run took. So the
    call is timed on a monotonic clock and the number travels out with the report, next to
    the limits it ran under and distinguishable from them.
    """
    from virtualcell.research.backend import AnthropicResearchBackend

    reply = AnthropicResearchBackend(model="m")._read_reply(_GoodResponse(), elapsed_seconds=4.25)
    assert reply.elapsed_seconds == 4.25

    report = ResearchService(
        backend=ScriptedBackend(_well_formed(), elapsed_seconds=4.25, timeout_seconds=120.0)
    ).investigate(ResearchRequest(question="Q?", evidence=[_observation()]))

    assert report.provenance.elapsed_seconds == 4.25
    assert report.provenance.timeout_seconds == 120.0


def test_a_backend_that_does_not_time_itself_reports_no_duration() -> None:
    """Nothing is not zero, here as everywhere else in provenance."""
    report = ResearchService(backend=ScriptedBackend(_well_formed())).investigate(
        ResearchRequest(question="Q?")
    )

    assert report.provenance.elapsed_seconds is None


def test_one_run_renders_as_both_text_and_json_without_a_second_call() -> None:
    """Two renderings of one run are not worth two runs. The text form used to live inside
    the CLI command, so seeing a report both ways meant invoking the command twice — two
    model calls, two bills, and two different answers being compared as if they were one.
    """
    backend = ScriptedBackend(_well_formed())
    report = ResearchService(backend=backend).investigate(
        ResearchRequest(question="Q?", evidence=[_observation()])
    )

    text = render_report_text(report)
    as_json = report.model_dump_json(indent=2)

    assert len(backend.prompts) == 1
    assert "cheapest thing that separates the two" in text
    assert "cheapest thing that separates the two" in as_json
    assert render_report_text(report) == text  # and rendering is pure


def test_a_retry_ceiling_is_recorded_as_a_limit_and_never_as_a_count() -> None:
    """The distinction the instruction asks for. One logical design call is one thing; the
    HTTP attempts the SDK made inside it are another, and the SDK does not report the
    second. So the report carries the *ceiling* it ran under, under a name that says so,
    and no field anywhere claims how many attempts were actually made.
    """
    from virtualcell.research.contracts import ResearchProvenance

    backend = ScriptedBackend(_well_formed(), max_request_attempts=3, timeout_seconds=120.0)
    report = ResearchService(backend=backend).investigate(
        ResearchRequest(question="Q?", evidence=[_observation()])
    )

    assert report.provenance.model_calls == 1
    assert report.provenance.max_request_attempts == 3
    assert report.provenance.timeout_seconds == 120.0
    assert not [f for f in ResearchProvenance.model_fields if "attempts_made" in f]


def test_what_the_provider_reported_is_recorded_not_only_what_was_asked_for() -> None:
    """An alias resolves to a dated id, and a deployment can serve something else again. A
    run that logs only the model it requested cannot afterwards be told apart from a
    different run, which is the one job provenance has.
    """
    from virtualcell.research.backend import AnthropicResearchBackend

    reply = AnthropicResearchBackend(model="claude-opus-5")._read_reply(_GoodResponse())

    assert reply.model_served == "claude-opus-5-dated-id"
    assert reply.stop_reason == "end_turn"
    assert reply.input_tokens == 1234
    assert reply.output_tokens == 567

    report = ResearchService(
        backend=ScriptedBackend(
            _well_formed(),
            model_served="claude-opus-5-dated-id",
            stop_reason="end_turn",
            input_tokens=1234,
            output_tokens=567,
        )
    ).investigate(ResearchRequest(question="Q?", evidence=[_observation()]))

    assert report.provenance.model == "scripted"
    assert report.provenance.model_served == "claude-opus-5-dated-id"
    assert report.provenance.input_tokens == 1234
    assert report.provenance.output_tokens == 567
    assert report.provenance.stop_reason == "end_turn"


def test_a_backend_that_reports_no_usage_leaves_it_blank_rather_than_guessing() -> None:
    """A zero would read as a measurement. Nothing is not zero."""
    report = ResearchService(backend=ScriptedBackend(_well_formed())).investigate(
        ResearchRequest(question="Q?", evidence=[_observation()])
    )

    assert report.provenance.input_tokens is None
    assert report.provenance.stop_reason is None


def test_a_refusal_is_not_reported_as_an_empty_reply() -> None:
    """A refusal carries no text, so it used to surface as "the model returned no text" and
    send the caller to debug the transport. The request is what to look at.
    """
    from virtualcell.research.backend import AnthropicResearchBackend

    class _Refusal:
        stop_reason = "refusal"
        model = "claude-opus-5-dated-id"
        content = []

    with pytest.raises(BackendCallFailed, match="declined"):
        AnthropicResearchBackend(model="test-model")._read_reply(_Refusal())
