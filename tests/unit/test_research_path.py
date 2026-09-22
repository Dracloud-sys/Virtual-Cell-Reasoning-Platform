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
    ResearchRequest,
    ResearchService,
    build_prompt,
    get_research_backend,
)


class ScriptedBackend:
    """Returns a fixed payload. Test-only, and deliberately not shipped in ``src``.

    It exists so the path can be exercised offline. It is not a fallback and nothing in
    the product may select it: a run with no provider must fail, not quietly use this.
    """

    name = "scripted-test"
    model = "scripted"

    def __init__(self, payload: dict | str) -> None:
        self._payload = payload
        self.prompts: list[str] = []

    def design(self, prompt: str, *, max_output_tokens: int) -> str:
        self.prompts.append(prompt)
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)


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

    assert main(["research", "--input", str(path), "--format", "text"]) == 0
    out = capsys.readouterr().out
    assert "H1" in out and "tells apart" in out
    assert "Integrity findings" in out
    assert "never-supplied" in out


def test_the_report_records_what_produced_it() -> None:
    service = ResearchService(backend=ScriptedBackend(_well_formed()))

    report = service.investigate(
        ResearchRequest(question="Q?", evidence=[_observation(), _read_span()])
    )

    assert report.provenance.backend == "scripted-test"
    assert report.provenance.prompt_version
    assert report.provenance.evidence_offered == 2
    assert report.provenance.model_calls == 1
