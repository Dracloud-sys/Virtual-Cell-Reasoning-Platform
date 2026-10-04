"""What the plan analysis must answer, written before the analysis.

The host writes the objectives, hypotheses, mechanism candidates, predictions and readings of
the evidence. Code answers only what follows from what was written:

* does every objective reach an experiment, or has the design quietly narrowed the goal?
* how many independent studies stand behind a claim, when several spans come from one paper?
* which candidate mechanism links carry no evidence, no conditions, or are absent from the
  knowledge graph — without writing anything to that graph?
* given each hypothesis's predicted direction per readout, which pairs does each experiment
  separate, which does no experiment separate, and where does coexistence blur a readout?

None of it grades the biology, and none of it produces a score.
"""

from __future__ import annotations

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.literature.contracts import ArticleIdentifier, SourceKind, SourceLocator
from virtualcell.platform.bootstrap import seed_registered_domains
from virtualcell.research.contracts import (
    DecisionBranch,
    EvidenceItem,
    EvidenceKind,
    EvidenceLink,
    Hypothesis,
    HypothesisSupport,
    MechanismLink,
    Objective,
    Prediction,
    ProposedExperiment,
    ResearchProvenance,
    ResearchReport,
    SubQuestion,
)
from virtualcell.research.plan import analyze_plan


def _span(ident: str, doi: str, text: str) -> EvidenceItem:
    return EvidenceItem(
        id=ident,
        kind=EvidenceKind.RETRIEVED_SOURCE,
        statement="a paper",
        locator=SourceLocator(
            article=ArticleIdentifier(doi=doi), source_kind=SourceKind.SECTION, source_text=text
        ),
    )


def _prior(ident: str) -> EvidenceItem:
    return EvidenceItem(id=ident, kind=EvidenceKind.MODEL_PRIOR, statement="host prior")


def _h(ident: str, **kw) -> Hypothesis:
    return Hypothesis(
        id=ident,
        statement=f"hypothesis {ident}",
        support=kw.pop("support", HypothesisSupport.UNVERIFIED_CANDIDATE),
        **kw,
    )


def _p(h: str, readout: str, expected: str, note: str | None = None) -> Prediction:
    return Prediction(hypothesis_id=h, readout=readout, expected=expected, note=note)


def _report(**kw) -> ResearchReport:
    return ResearchReport(
        question="q",
        restated_question="rq",
        provenance=ResearchProvenance(
            backend="host_llm", prompt_version="t", model_calls=0, evidence_offered=0
        ),
        **kw,
    )


# --- A1: the goal is kept, and a goal no experiment reaches is named --------------------------


def test_an_objective_no_experiment_reaches_is_reported() -> None:
    report = _report(
        objectives=[
            Objective(id="O1", statement="bridge the gap", stated_by="user"),
            Objective(id="O2", statement="limit scarring", stated_by="user"),
        ],
        sub_questions=[SubQuestion(id="Q1", question="does it hold?", objective_ids=["O1"])],
        hypotheses=[_h("H1", sub_question_ids=["Q1"]), _h("H2", sub_question_ids=["Q1"])],
        experiments=[
            ProposedExperiment(
                id="E1",
                design="d",
                discriminates=["H1", "H2"],
                controls=["c"],
                measurements=["load"],
                predictions=[_p("H1", "load", "increase"), _p("H2", "load", "no_change")],
            )
        ],
    )

    analysis = analyze_plan(report, [])

    trace = {t.objective_id: t for t in analysis.goal_trace}
    assert trace["O1"].experiment_ids == ["E1"]
    assert trace["O2"].experiment_ids == []
    assert analysis.unreached_objectives == ["O2"]


def test_user_goals_confirmed_and_open_conditions_and_host_assumptions_stay_apart() -> None:
    report = _report(
        objectives=[Objective(id="O1", statement="g", stated_by="user")],
        confirmed_conditions=["in vitro only"],
        open_conditions=["cell type"],
        assumptions=["cell type: dermal fibroblast (candidate)"],
    )

    analysis = analyze_plan(report, [])

    assert analysis.conditions.confirmed == ["in vitro only"]
    assert analysis.conditions.open == ["cell type"]
    assert analysis.conditions.host_assumptions == ["cell type: dermal fibroblast (candidate)"]
    assert analysis.goal_trace[0].stated_by == "user"


def test_a_condition_both_confirmed_and_open_is_flagged() -> None:
    analysis = analyze_plan(
        _report(confirmed_conditions=["Cell type"], open_conditions=["cell  type"]), []
    )

    assert any(f.code == "condition_both_confirmed_and_open" for f in analysis.findings)


def test_a_hypothesis_no_experiment_tests_is_reported() -> None:
    report = _report(hypotheses=[_h("H1"), _h("H9")], experiments=[])

    assert set(analyze_plan(report, []).untested_hypotheses) == {"H1", "H9"}


# --- A2: evidence is counted by study, and the reading stays the host's ----------------------


def test_three_spans_from_one_paper_are_one_study_not_three() -> None:
    evidence = [
        _span("s1", "10.1/a", "first"),
        _span("s2", "10.1/a", "second"),
        _span("s3", "10.1/a", "third"),
        _span("s4", "10.1/b", "other paper"),
    ]
    report = _report(
        hypotheses=[_h("H1", supporting_evidence_ids=["s1", "s2", "s3", "s4"])],
    )

    analysis = analyze_plan(report, evidence)

    (row,) = [r for r in analysis.evidence if r.target_id == "H1" and r.role == "supports"]
    assert row.span_count == 4
    assert row.independent_studies == 2
    assert any(d.evidence_ids == ["s1", "s2", "s3"] for d in analysis.same_study_spans)


def test_roles_are_kept_apart_and_the_reading_is_labelled_the_hosts() -> None:
    evidence = [_span("s1", "10.1/a", "method text"), _span("s2", "10.1/b", "scope text")]
    report = _report(
        hypotheses=[_h("H1")],
        evidence_links=[
            EvidenceLink(evidence_id="s1", target_id="H1", role="method", reading="how"),
            EvidenceLink(evidence_id="s2", target_id="H1", role="scope_limit", reading="where"),
        ],
    )

    rows = {r.role: r for r in analyze_plan(report, evidence).evidence if r.target_id == "H1"}

    assert set(rows) == {"method", "scope_limit"}
    assert rows["method"].host_readings == ["how"]
    assert rows["method"].interpretation_by == "host"


def test_support_resting_only_on_priors_is_not_counted_as_a_study() -> None:
    report = _report(hypotheses=[_h("H1", supporting_evidence_ids=["p1"])])

    (row,) = analyze_plan(report, [_prior("p1")]).evidence

    assert row.independent_studies == 0
    assert row.ungrounded_ids == ["p1"]


def test_a_link_to_an_unknown_evidence_id_or_target_is_a_finding() -> None:
    report = _report(
        hypotheses=[_h("H1")],
        evidence_links=[
            EvidenceLink(evidence_id="ghost", target_id="H1", role="supports"),
            EvidenceLink(evidence_id="s1", target_id="H404", role="supports"),
        ],
    )

    codes = {f.code for f in analyze_plan(report, [_span("s1", "10.1/a", "t")]).findings}

    assert {"unknown_evidence_id", "unknown_link_target"} <= codes


# --- A3: candidate mechanisms, what they lose, and the graph read-only ------------------------


def test_a_case_link_with_no_evidence_or_conditions_says_so() -> None:
    report = _report(
        hypotheses=[_h("H1")],
        mechanism_links=[
            MechanismLink(
                id="M1", source="X", relation="increases", target="Y", hypothesis_ids=["H1"]
            )
        ],
    )

    (link,) = analyze_plan(report, []).mechanism_links

    assert {"no_evidence", "no_conditions"} <= set(link.gaps)


def test_a_link_backed_only_by_a_prior_is_marked_ungrounded() -> None:
    report = _report(
        mechanism_links=[
            MechanismLink(
                id="M1", source="X", relation="r", target="Y", evidence_ids=["p1"], conditions=["c"]
            )
        ]
    )

    (link,) = analyze_plan(report, [_prior("p1")]).mechanism_links

    assert "only_ungrounded_evidence" in link.gaps


def _seeded() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    return store


class _WriteRecordingStore(InMemoryKnowledgeStore):
    """A seeded store that records any write made after seeding."""

    def __init__(self) -> None:
        self.writes: list[str] = []
        super().__init__()
        seed_registered_domains(self)

    def upsert(self, entity) -> None:
        self.writes.append(f"upsert {entity.id}")
        super().upsert(entity)

    def add_interaction(self, interaction) -> None:
        self.writes.append("add_interaction")
        super().add_interaction(interaction)


def test_the_graph_is_consulted_for_a_case_link_and_nothing_is_written() -> None:
    store = _WriteRecordingStore()
    store.writes.clear()
    report = _report(
        mechanism_links=[
            MechanismLink(
                id="M1",
                source="PPARGC1A",
                relation="promotes",
                target="Mitochondrial function",
                conditions=["c"],
            ),
            MechanismLink(
                id="M2",
                source="an entity nobody seeded",
                relation="r",
                target="Viability",
                conditions=["c"],
            ),
        ]
    )

    links = {m.id: m for m in analyze_plan(report, [], store=store).mechanism_links}

    assert links["M1"].graph.status == "path_found"
    assert links["M1"].graph.path
    assert links["M2"].graph.status == "endpoint_not_in_graph"
    assert "not_in_graph" in links["M2"].gaps
    assert store.writes == []


def test_without_a_graph_links_are_still_represented() -> None:
    report = _report(mechanism_links=[MechanismLink(id="M1", source="A", relation="r", target="B")])

    (link,) = analyze_plan(report, [], store=None).mechanism_links

    assert link.graph.status == "not_checked"


def test_a_graph_path_does_not_carry_the_cases_conditions() -> None:
    report = _report(
        mechanism_links=[
            MechanismLink(
                id="M1",
                source="PPARGC1A",
                relation="promotes",
                target="Mitochondrial function",
                conditions=["human dermal fibroblasts"],
            )
        ]
    )

    (link,) = analyze_plan(report, [], store=_seeded()).mechanism_links

    assert "graph_path_without_case_conditions" in link.gaps


# --- A4: discrimination, from predicted values only ------------------------------------------


def _discrimination_report(**exp_kw) -> ResearchReport:
    return _report(
        hypotheses=[_h("H1"), _h("H2"), _h("H3")],
        experiments=[
            ProposedExperiment(
                id="E1",
                design="per-cell normalisation",
                discriminates=["H1", "H2"],
                controls=["vehicle"],
                measurements=["signal per cell", "cell count"],
                predictions=[
                    _p("H1", "signal per cell", "no_change"),
                    _p("H2", "signal per cell", "decrease"),
                    _p("H3", "signal per cell", "decrease"),
                    _p("H1", "cell count", "decrease"),
                    _p("H2", "cell count", "no_change"),
                    _p("H3", "cell count", "no_change"),
                ],
                branches=[DecisionBranch(outcome="per-cell falls", implication="H2 or H3")],
            ),
            ProposedExperiment(
                id="E2",
                design="cell-free assay",
                discriminates=["H3"],
                controls=["medium only"],
                measurements=["cell-free signal"],
                predictions=[
                    _p("H1", "cell-free signal", "no_change"),
                    _p("H2", "cell-free signal", "no_change"),
                    _p("H3", "cell-free signal", "decrease"),
                ],
            ),
            ProposedExperiment(
                **{
                    "id": "E3",
                    "design": "total signal only",
                    "controls": ["vehicle"],
                    "measurements": ["total signal"],
                    "predictions": [
                        _p("H1", "total signal", "decrease", note="fewer cells"),
                        _p("H2", "total signal", "decrease", note="less activity per cell"),
                        _p("H3", "total signal", "decrease", note="interference"),
                    ],
                    **exp_kw,
                }
            ),
        ],
    )


def _exp(analysis, ident):
    return next(e for e in analysis.experiments if e.experiment_id == ident)


def test_pairs_separated_by_each_experiment_are_computed_from_values() -> None:
    analysis = analyze_plan(_discrimination_report(), [])

    e1 = _exp(analysis, "E1")
    assert {tuple(p.pair) for p in e1.separated_pairs} == {("H1", "H2"), ("H1", "H3")}
    assert {tuple(p.pair) for p in e1.unseparated_pairs} == {("H2", "H3")}
    e2 = _exp(analysis, "E2")
    assert {tuple(p.pair) for p in e2.separated_pairs} == {("H1", "H3"), ("H2", "H3")}


def test_different_wording_with_the_same_prediction_separates_nothing() -> None:
    e3 = _exp(analyze_plan(_discrimination_report(), []), "E3")

    assert e3.separated_pairs == []
    assert len(e3.unseparated_pairs) == 3
    assert all(p.reason == "same_prediction_on_every_shared_readout" for p in e3.unseparated_pairs)


def test_a_pair_no_candidate_experiment_separates_is_named_across_the_plan() -> None:
    report = _discrimination_report()
    report.experiments = [e for e in report.experiments if e.id != "E2"]

    assert [tuple(p) for p in analyze_plan(report, []).pairs_never_separated] == [("H2", "H3")]


def test_coexistence_is_allowed_and_its_blur_is_stated() -> None:
    """H1 predicts no change per cell, H2 a decrease. Seeing a decrease says H2 (or H3) holds;
    it does not say H1 is absent, because H1 and H2 can both be true."""
    e1 = _exp(analyze_plan(_discrimination_report(), []), "E1")

    notes = " ".join(n for p in e1.separated_pairs for n in p.coexistence_notes)
    assert "cannot rule out" in notes


def test_opposing_predictions_that_can_coexist_warn_of_offsetting() -> None:
    report = _report(
        hypotheses=[_h("A"), _h("B")],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                controls=["c"],
                measurements=["r"],
                predictions=[_p("A", "r", "increase"), _p("B", "r", "decrease")],
            )
        ],
    )

    (pair,) = _exp(analyze_plan(report, []), "E").separated_pairs

    assert any("offset" in n for n in pair.coexistence_notes)


def test_declared_exclusivity_removes_the_coexistence_caveat() -> None:
    report = _report(
        hypotheses=[_h("A", mutually_exclusive_with=["B"]), _h("B")],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                controls=["c"],
                measurements=["r"],
                predictions=[_p("A", "r", "increase"), _p("B", "r", "decrease")],
            )
        ],
    )

    (pair,) = _exp(analyze_plan(report, []), "E").separated_pairs

    assert pair.coexistence_notes == []


def test_one_experiment_covering_anothers_pairs_is_stated_as_a_set_relation() -> None:
    report = _discrimination_report()
    report.experiments.append(
        ProposedExperiment(
            id="E4",
            design="count only, two hypotheses",
            controls=["vehicle"],
            measurements=["cell count"],
            predictions=[_p("H1", "cell count", "decrease"), _p("H2", "cell count", "no_change")],
        )
    )

    covers = {
        (c.experiment_id, c.covers_experiment_id, c.relation)
        for c in analyze_plan(report, []).coverage
    }

    assert ("E1", "E4", "strict_superset") in covers
    assert not any({a, b} == {"E1", "E2"} for a, b, _ in covers)
    assert not any("E3" in (a, b) for a, b, _ in covers), "separating nothing covers nothing"


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_no_score_or_probability_is_produced() -> None:
    keys = _keys(analyze_plan(_discrimination_report(), []).model_dump())

    for word in ("score", "probability", "information_gain", "rank", "priority"):
        assert not any(word in key for key in keys), word


def test_readouts_only_one_hypothesis_predicts_are_listed_not_compared() -> None:
    report = _report(
        hypotheses=[_h("A"), _h("B")],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                controls=["c"],
                measurements=["r1", "r2"],
                predictions=[_p("A", "r1", "increase"), _p("B", "r2", "decrease")],
            )
        ],
    )

    e = _exp(analyze_plan(report, []), "E")

    assert [p.reason for p in e.unseparated_pairs] == ["no_shared_predicted_readout"]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"controls": []}, "predictions_without_controls"),
        ({"measurements": []}, "readout_not_measured"),
    ],
)
def test_missing_controls_and_unmeasured_readouts_are_findings(change, code) -> None:
    report = _discrimination_report(**change)

    assert any(f.code == code and "E3" in f.where for f in analyze_plan(report, []).findings)


def test_a_claimed_discrimination_missing_a_prediction_is_a_finding() -> None:
    report = _report(
        hypotheses=[_h("H1"), _h("H2")],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                discriminates=["H1", "H2"],
                controls=["c"],
                measurements=["r"],
                predictions=[_p("H1", "r", "increase")],
            )
        ],
    )

    codes = {f.code for f in analyze_plan(report, []).findings}
    assert "discrimination_claimed_without_predictions" in codes


def test_an_experiment_without_any_prediction_is_listed_not_faulted() -> None:
    """Predictions are optional; a draft that does not use them is not a defective draft."""
    report = _report(
        hypotheses=[_h("H1"), _h("H2")],
        experiments=[
            ProposedExperiment(id="E", design="d", discriminates=["H1", "H2"], controls=["c"])
        ],
    )

    analysis = analyze_plan(report, [])

    assert analysis.experiments_without_predictions == ["E"]
    assert analysis.findings == []


def test_the_hosts_next_decisions_are_returned_as_the_hosts() -> None:
    e1 = _exp(analyze_plan(_discrimination_report(), []), "E1")

    assert e1.next_decisions_by == "host"
    assert e1.next_decisions[0].outcome == "per-cell falls"


# --- found by the development cases -----------------------------------------------------------


def test_present_against_absent_is_not_an_offsetting_pair() -> None:
    """`absent` is a null, like `no_change`: seeing the effect says A holds and cannot rule B
    out. Found on case 2, where a cell-free interference control was reported as two effects
    that 'may offset'."""
    report = _report(
        hypotheses=[_h("A"), _h("B")],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                controls=["c"],
                measurements=["r"],
                predictions=[_p("A", "r", "present"), _p("B", "r", "absent")],
            )
        ],
    )

    (pair,) = _exp(analyze_plan(report, []), "E").separated_pairs

    assert not any("offset" in n for n in pair.coexistence_notes)
    assert any("cannot rule out B" in n for n in pair.coexistence_notes)


def test_hypotheses_answering_different_questions_are_not_compared() -> None:
    """Found on case 1: a degradation-route hypothesis and a handover hypothesis were listed as
    'never separated'. They answer different sub-questions; they are not alternatives."""
    report = _report(
        sub_questions=[
            SubQuestion(id="Q1", question="route?"),
            SubQuestion(id="Q2", question="handover?"),
        ],
        hypotheses=[
            _h("R1", sub_question_ids=["Q1"]),
            _h("R2", sub_question_ids=["Q1"]),
            _h("K1", sub_question_ids=["Q2"]),
        ],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                controls=["c"],
                measurements=["r"],
                predictions=[
                    _p("R1", "r", "increase"),
                    _p("R2", "r", "no_change"),
                    _p("K1", "r", "increase"),
                ],
            )
        ],
    )

    analysis = analyze_plan(report, [])
    pairs = {tuple(p.pair) for p in _exp(analysis, "E").separated_pairs} | {
        tuple(p.pair) for p in _exp(analysis, "E").unseparated_pairs
    }

    assert pairs == {("R1", "R2")}
    assert analysis.pairs_never_separated == []
