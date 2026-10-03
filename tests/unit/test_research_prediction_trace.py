"""Questions the plan analysis must answer about predictions, written before the change.

Stage A compared predicted values. These pin what it has to say *around* a comparison:

* a state (`present`/`absent`) and a change (`increase`/`decrease`/`no_change`) are different
  claims and are never compared; two changes against different references are not compared;
* which hypothesis pairs were compared and which were left out, with the reason — nothing is
  silently hidden by the sub-question rule;
* whether an objective is measured directly, only through a proxy, or lies outside the
  experiment's reach — as the host's judgement;
* for every prediction, the path from evidence and mechanism to the expected measurement and
  the decision it feeds, and what is affected if evidence is withdrawn or a condition changes.
"""

from __future__ import annotations

from virtualcell.literature.contracts import ArticleIdentifier, SourceKind, SourceLocator
from virtualcell.research.contracts import (
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    HypothesisSupport,
    MechanismLink,
    Objective,
    ObjectiveCoverage,
    Prediction,
    ProposedExperiment,
    ReadoutSpec,
    ResearchProvenance,
    ResearchReport,
    SubQuestion,
)
from virtualcell.research.plan import WhatIf, analyze_plan


def _span(ident: str, doi: str) -> EvidenceItem:
    return EvidenceItem(
        id=ident,
        kind=EvidenceKind.RETRIEVED_SOURCE,
        statement="paper",
        locator=SourceLocator(
            article=ArticleIdentifier(doi=doi), source_kind=SourceKind.SECTION, source_text=ident
        ),
    )


def _h(ident: str, **kw) -> Hypothesis:
    return Hypothesis(
        id=ident, statement=ident, support=HypothesisSupport.UNVERIFIED_CANDIDATE, **kw
    )


def _p(h: str, readout: str, expected: str, **kw) -> Prediction:
    return Prediction(hypothesis_id=h, readout=readout, expected=expected, **kw)


def _report(**kw) -> ResearchReport:
    return ResearchReport(
        question="q",
        restated_question="rq",
        provenance=ResearchProvenance(
            backend="host_llm", prompt_version="t", model_calls=0, evidence_offered=0
        ),
        **kw,
    )


def _one_experiment(predictions, **exp_kw) -> ResearchReport:
    ids = sorted({p.hypothesis_id for p in predictions})
    return _report(
        hypotheses=[_h(i) for i in ids],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                controls=["c"],
                measurements=sorted({p.readout for p in predictions}),
                predictions=predictions,
                **exp_kw,
            )
        ],
    )


def _exp(analysis, ident="E"):
    return next(e for e in analysis.experiments if e.experiment_id == ident)


# --- A. states, changes and references are not interchangeable ------------------------------


def test_a_state_and_a_change_are_not_compared() -> None:
    report = _one_experiment([_p("A", "r", "absent"), _p("B", "r", "decrease", versus="vehicle")])

    e = _exp(analyze_plan(report, []))

    assert e.separated_pairs == []
    (excluded,) = e.readout_exclusions
    assert excluded.reason == "different_prediction_kinds"
    assert excluded.pair == ["A", "B"]


def test_changes_against_different_references_are_not_compared() -> None:
    report = _one_experiment(
        [_p("A", "r", "increase", versus="vehicle"), _p("B", "r", "no_change", versus="baseline")]
    )

    e = _exp(analyze_plan(report, []))

    assert e.separated_pairs == []
    assert e.readout_exclusions[0].reason == "different_reference"


def test_a_change_with_no_stated_reference_is_reported_as_missing() -> None:
    report = _one_experiment([_p("A", "r", "increase"), _p("B", "r", "no_change")])

    analysis = analyze_plan(report, [])

    assert _exp(analysis).separated_pairs, "compared as before, for compatibility"
    traces = [t for t in analysis.prediction_traces if t.hypothesis_id == "A"]
    assert "change_without_reference" in traces[0].gaps


def test_readout_fields_needed_to_compare_observations_are_listed_when_missing() -> None:
    report = _one_experiment(
        [_p("A", "r", "increase", versus="v")],
        readouts=[ReadoutSpec(name="r", assay="fluorescence", unit="RFU")],
    )

    (missing,) = analyze_plan(report, []).readout_specs_missing

    assert missing.readout == "r"
    assert set(missing.missing) == {
        "target",
        "compartment",
        "timepoint",
        "reference",
        "normalization",
    }


# --- B. which pairs were compared, and why others were not ----------------------------------


def test_excluded_pairs_are_listed_with_their_reason_not_hidden() -> None:
    report = _report(
        sub_questions=[SubQuestion(id="Q1", question="a"), SubQuestion(id="Q2", question="b")],
        hypotheses=[
            _h("A", sub_question_ids=["Q1"]),
            _h("B", sub_question_ids=["Q1"]),
            _h("C", sub_question_ids=["Q2"]),
            _h("D", sub_question_ids=["Q2"], alternative_to=["A"]),
        ],
    )

    selection = {tuple(s.pair): s for s in analyze_plan(report, []).pair_selection}

    assert selection[("A", "B")].compared and selection[("A", "B")].reason == "shared_sub_question"
    assert selection[("A", "D")].compared and selection[("A", "D")].reason == "declared_alternative"
    assert not selection[("A", "C")].compared
    assert selection[("A", "C")].reason == "no_shared_sub_question_and_not_declared_alternatives"


def test_differing_predictions_are_not_called_sufficient_discrimination() -> None:
    limits = " ".join(analyze_plan(_report(), []).limits)

    assert "not a measure of how well the experiment would discriminate" in limits


# --- C. how directly an objective is tested ---------------------------------------------------


def test_an_objective_reached_only_through_a_proxy_is_marked_so() -> None:
    report = _report(
        objectives=[
            Objective(id="O1", statement="bridge", stated_by="user"),
            Objective(id="O2", statement="scar", stated_by="user"),
            Objective(id="O3", statement="ingress", stated_by="user"),
        ],
        experiments=[
            ProposedExperiment(
                id="E1",
                design="d",
                objective_coverage=[
                    ObjectiveCoverage(objective_id="O1", level="direct"),
                    ObjectiveCoverage(objective_id="O2", level="proxy"),
                ],
            ),
            ProposedExperiment(
                id="E2",
                design="d",
                objective_coverage=[ObjectiveCoverage(objective_id="O2", level="out_of_scope")],
            ),
        ],
    )

    levels = {lv.objective_id: lv for lv in analyze_plan(report, []).objective_levels}

    assert levels["O1"].directly_measured and levels["O1"].direct == ["E1"]
    assert not levels["O2"].directly_measured
    assert levels["O2"].proxy == ["E1"] and levels["O2"].out_of_scope == ["E2"]
    assert levels["O2"].judged_by == ["host"]
    assert levels["O3"].direct == [] and not levels["O3"].directly_measured


def test_an_experiment_that_separates_nothing_is_not_called_useless() -> None:
    report = _report(
        hypotheses=[_h("A")],
        experiments=[
            ProposedExperiment(
                id="E",
                design="measure ingress",
                controls=["c"],
                measurements=["depth"],
                purposes=["function_check"],
                predictions=[_p("A", "depth", "decrease", versus="uncrosslinked")],
            )
        ],
    )

    (row,) = analyze_plan(report, []).non_discriminating_experiments

    assert row.experiment_id == "E"
    assert row.purposes == ["function_check"]
    assert "not a defect" in row.note


# --- the path from evidence to a prediction, and what depends on what -------------------------


def _traced_report() -> ResearchReport:
    return _report(
        hypotheses=[_h("A"), _h("B")],
        mechanism_links=[
            MechanismLink(
                id="M1",
                source="X",
                relation="reduces",
                target="Y",
                evidence_ids=["m1", "m2"],
                conditions=["renal fibroblasts on collagen gel"],
                hypothesis_ids=["A"],
            )
        ],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                controls=["c"],
                measurements=["r"],
                predictions=[
                    _p(
                        "A",
                        "r",
                        "decrease",
                        versus="vehicle",
                        biological_expectation="less Y",
                        basis="mechanism_derived",
                        evidence_ids=["d1"],
                        mechanism_link_ids=["M1"],
                        assumptions=["assay reads Y linearly"],
                    ),
                    _p("B", "r", "no_change", versus="vehicle", basis="evidence_observed"),
                ],
                branches=[{"outcome": "r falls", "implication": "A holds"}],
            )
        ],
    )


def _traced_evidence() -> list[EvidenceItem]:
    return [_span("d1", "10.1/a"), _span("m1", "10.1/a"), _span("m2", "10.1/b")]


def test_a_prediction_traces_back_to_evidence_mechanism_and_assumption() -> None:
    analysis = analyze_plan(_traced_report(), _traced_evidence())

    trace = next(t for t in analysis.prediction_traces if t.hypothesis_id == "A")
    assert trace.basis == "mechanism_derived"
    assert trace.biological_expectation == "less Y"
    assert trace.direct_evidence_ids == ["d1"]
    assert trace.mechanism_evidence_ids == ["m1", "m2"]
    assert trace.independent_studies == 2, "d1 and m1 are one paper"
    assert trace.mechanism_links[0].id == "M1"
    assert trace.assumptions == ["assay reads Y linearly"]
    assert trace.separates == [["A", "B"]]
    assert trace.decisions[0].outcome == "r falls"


def test_a_basis_the_prediction_does_not_carry_is_a_gap() -> None:
    trace = next(
        t
        for t in analyze_plan(_traced_report(), _traced_evidence()).prediction_traces
        if t.hypothesis_id == "B"
    )

    assert "evidence_observed_without_evidence" in trace.gaps


def test_withdrawing_evidence_names_what_depends_on_it_and_flips_nothing() -> None:
    analysis = analyze_plan(
        _traced_report(), _traced_evidence(), what_if=WhatIf(remove_evidence_ids=["m2"])
    )

    impact = analysis.impact
    assert [(a.experiment_id, a.hypothesis_id, a.readout) for a in impact.affected_predictions] == [
        ("E", "A", "r")
    ]
    assert impact.affected_predictions[0].via == ["mechanism_link:M1"]
    assert impact.affected_hypotheses == ["A"] and impact.affected_experiments == ["E"]
    trace = next(t for t in analysis.prediction_traces if t.hypothesis_id == "A")
    assert trace.expected == "decrease", "a withdrawn source does not reverse a prediction"


def test_changing_a_condition_names_the_links_and_predictions_it_touches() -> None:
    impact = analyze_plan(
        _traced_report(),
        _traced_evidence(),
        what_if=WhatIf(changed_conditions=["Renal fibroblasts on collagen gel"]),
    ).impact

    assert [a.hypothesis_id for a in impact.affected_predictions] == ["A"]
    assert impact.affected_mechanism_links == ["M1"]


def test_without_a_what_if_there_is_no_impact_section() -> None:
    assert analyze_plan(_traced_report(), _traced_evidence()).impact is None


# --- findings, pinned rather than fixed (docs/research_path.md, "Findings from the cases") --------


def test_finding_withdrawing_a_span_does_not_withdraw_its_study() -> None:
    """Case 1: withdrawing one span of the Dupuytren paper left a same-study span in force.

    `what_if` removes evidence ids, not studies. Pinned so a change to study-level withdrawal is
    a deliberate decision, not a side effect.
    """
    report = _one_experiment(
        [
            _p("A", "r", "increase", versus="v", basis="evidence_observed", evidence_ids=["d1"]),
            _p("B", "r", "no_change", versus="v", basis="evidence_observed", evidence_ids=["m1"]),
        ]
    )

    impact = analyze_plan(
        report, _traced_evidence(), what_if=WhatIf(remove_evidence_ids=["d1"])
    ).impact

    assert [a.hypothesis_id for a in impact.affected_predictions] == ["A"], (
        "m1 is the same paper as d1 and is not affected"
    )


def test_finding_there_is_no_value_for_changes_in_an_unknown_direction() -> None:
    """Case 2: H3a (direct chemistry) changes a cell-free reading in a direction it does not fix.

    The vocabulary has no value for that, so the cell is `not_predicted` with the reason in
    `unresolved`, and it separates nothing.
    """
    from virtualcell.research.contracts import Expectation

    assert {e.value for e in Expectation} == {
        "increase",
        "decrease",
        "no_change",
        "present",
        "absent",
        "not_predicted",
    }
