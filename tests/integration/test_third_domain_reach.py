"""A third domain reaches every interface, and the kernel never learned it exists.

The second domain could not settle this. It was written by people who had just read the first,
so any abstraction the two shared might have been shared by imitation rather than by being
right. This file is the actual generality check: a domain whose *decision shape* differs from
both — it judges a molecular claim about a construct, and it has to know how a value was
measured before it can say what the value means — reaching the shipped service, API and CLI,
with zero kernel changes and one line in the composition root.

PR17's transparency contract is re-checked here rather than assumed, because it was written
before this vertical existed. A contract that only holds for the domains it was written
against is not a platform contract.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from virtualcell.api.main import app
from virtualcell.cli import main as cli_main
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.service import ReasoningService

CLONAL = {
    "domain": "genome_editing",
    "task": "assess_state",
    "experiment": {
        "species": "bovine",
        "target_gene": "MSTN",
        "edit_detected": "present",
        "edit_assay": "ngs",
        "allele_pattern": "homozygous",
        "parental_control": "matched",
    },
}
BAND_ONLY = {
    "domain": "genome_editing",
    "task": "assess_state",
    "experiment": {"edit_detected": "present", "edit_assay": "pcr", "parental_control": "matched"},
}
MECHANISM = {
    "domain": "genome_editing",
    "task": "explain_mechanism",
    "experiment": {"edit_type": "knockout"},
}


def _service(payload: dict) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    service = ReasoningService(store, default_registry())
    return asyncio.run(service.query(ReasoningQuery.model_validate(payload)))


def _states(payload: dict) -> dict[str, str]:
    return {
        entry.submitted_as: entry.status.value
        for entry in _service(payload).measurement_consumption.entries
    }


# --- registration and reach ---------------------------------------------------


def test_the_third_domain_is_registered_and_shadows_nothing() -> None:
    registry = default_registry()
    assert registry.domains() == ["adipogenesis", "genome_editing", "immortalization"]
    assert registry.tasks("genome_editing") == ["assess_state", "explain_mechanism"]


def test_adding_the_third_domain_touched_no_interface() -> None:
    """The PR11 claim, checked structurally for a third time: no interface names any vertical."""
    for path in (
        "src/virtualcell/platform/service.py",
        "src/virtualcell/platform/domains.py",
        "src/virtualcell/platform/description.py",
        "src/virtualcell/api/main.py",
        "src/virtualcell/cli.py",
    ):
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not any("genome_editing" in name for name in imported), path


def test_the_vertical_was_not_written_by_copying_either_predecessor() -> None:
    """Any similarity between the three verticals has to be evidence, not inheritance."""
    for path in pathlib.Path("src/virtualcell/agents/genome_editing").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        leaked = [
            name
            for name in imported
            if "agents.immortalization" in name or "agents.adipogenesis" in name
        ]
        assert not leaked, f"{path.name} imports another vertical: {leaked}"


def test_the_kernel_still_knows_no_domain() -> None:
    """The milestone's headline claim, restated where it can fail."""
    for path in pathlib.Path("src/virtualcell/reasoning/kernel").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        imported |= {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any("virtualcell.agents" in name for name in imported), path.name


@pytest.mark.parametrize("payload", [CLONAL, BAND_ONLY, MECHANISM])
def test_service_api_and_cli_agree(payload: dict, tmp_path, capsys) -> None:
    def semantics(response: ReasoningResponse) -> dict:
        return {
            "summary": response.summary,
            "status": response.decision_support.status,
            "flags": sorted(response.decision_support.flags),
            "supporting": [(c.statement, c.tier.value) for c in response.supporting_evidence],
            "links": [(link.target_id, tuple(link.path)) for link in response.mechanistic_links],
            "missing": response.missing_information,
            "consumption": response.measurement_consumption.model_dump(mode="json"),
        }

    service = semantics(_service(payload))

    with TestClient(app) as client:
        api = client.post("/reasoning/query", json=payload)
    assert api.status_code == 200

    request_file = tmp_path / "query.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    assert cli_main(["query", "--input", str(request_file), "--format", "json"]) == 0
    cli = json.loads(capsys.readouterr().out)

    assert semantics(ReasoningResponse.model_validate(api.json())) == service
    assert semantics(ReasoningResponse.model_validate(cli)) == service


def test_the_answer_is_the_vertical_s_own() -> None:
    response = _service(CLONAL)
    assert response.domain == "genome_editing"
    assert response.provenance.pack == "genome_editing.v1"
    assert response.decision_support.status == "edited_clonal"
    assert "edited clone" in response.summary


def test_the_third_domain_grounds_because_its_graph_is_seeded_too() -> None:
    response = _service(MECHANISM)
    assert response.mechanistic_links
    steps = [step for link in response.mechanistic_links for step in link.path]
    assert any("double-strand break" in step for step in steps)
    assert any("end joining" in step for step in steps)  # the repair arm, not only the cut


def test_the_domain_status_travels_on_the_envelope_not_the_report() -> None:
    """A third domain hits the same wall the second did: `DecisionReport.candidate_status` is
    typed to immortalization's vocabulary, so `edited_clonal` cannot be stated there. Recorded
    a third time because three callers is the evidence that would justify migrating it."""
    response = _service(CLONAL)
    assert response.decision_support.status == "edited_clonal"
    assert response.domain_details["decision_report"]["candidate_status"] is None


# --- the science, through the product path ------------------------------------


def test_a_band_is_not_a_genotype() -> None:
    """The domain's headline rule, and the reason it tests the kernel: the verdict turns on
    *how* the value was measured, not on the value."""
    band = _service(BAND_ONLY)
    assert band.decision_support.status == "insufficient_evidence"
    assert "weak_assay" in band.decision_support.flags

    sequenced = _service(
        {
            **CLONAL,
            "experiment": {
                **BAND_ONLY["experiment"],
                "edit_assay": "ngs",
                "allele_pattern": "homozygous",
            },
        }
    )
    # Same locus reading, same control, a different instrument - and a different answer.
    assert sequenced.decision_support.status == "edited_clonal"
    assert "weak_assay" not in sequenced.decision_support.flags


def test_a_weak_negative_is_not_an_absence_call_either() -> None:
    """The asymmetry that is easy to get half-right: PCR-negative is as uninformative as
    PCR-positive, and only a sequence-level assay makes 'unedited' a finding."""
    weak = {"edit_detected": "absent", "edit_assay": "pcr", "parental_control": "matched"}
    assert _service({**CLONAL, "experiment": weak}).decision_support.status == (
        "insufficient_evidence"
    )
    strong = {**weak, "edit_assay": "ngs"}
    assert _service({**CLONAL, "experiment": strong}).decision_support.status == "unedited"


def test_a_positive_call_never_claims_function_or_a_clean_genome() -> None:
    response = _service(CLONAL)
    assert {"off_target_unassessed", "function_unverified"} <= set(response.decision_support.flags)
    asserted = " ".join(
        [
            response.summary,
            *(c.statement for c in response.supporting_evidence),
            *(c.statement for c in response.contradicting_evidence),
        ]
    ).lower()
    for phrase in ("knockout confirmed", "no off-target effects", "clean genome", "safe to use"):
        assert phrase not in asserted


def test_predicted_site_screening_does_not_clear_the_genome() -> None:
    """Real work that answers a narrower question than the flag asks."""
    partial = _service(
        {**CLONAL, "experiment": {**CLONAL["experiment"], "off_target_screened": "predicted_sites"}}
    )
    assert "off_target_unassessed" in partial.decision_support.flags
    full = _service(
        {**CLONAL, "experiment": {**CLONAL["experiment"], "off_target_screened": "genome_wide"}}
    )
    assert "off_target_unassessed" not in full.decision_support.flags


# --- PR17 transparency, on a vertical that did not exist when it was written ---


def test_status_axes_guidance_axes_and_context_are_reported_apart() -> None:
    states = _states(
        {
            **CLONAL,
            "experiment": {
                **CLONAL["experiment"],
                "off_target_screened": "genome_wide",
                "allele_pattern": "unknown",
                "crispr_efficiency": "40%",
            },
        }
    )
    assert states["edit_detected"] == states["edit_assay"] == "used_for_status"
    assert states["off_target_screened"] == "used_for_guidance"
    assert states["allele_pattern"] == "not_applicable"  # explicit unknown
    assert states["species"] == states["target_gene"] == "not_applicable"  # context
    assert states["crispr_efficiency"] == "unsupported"


def test_a_guidance_axis_changes_the_plan_and_not_the_verdict() -> None:
    base = _service(CLONAL)
    refined = _service(
        {
            **CLONAL,
            "experiment": {
                **CLONAL["experiment"],
                "off_target_screened": "genome_wide",
                "protein_expression": "confirmed",
            },
        }
    )
    assert base.decision_support.status == refined.decision_support.status == "edited_clonal"
    assert base.recommended_next_experiments != refined.recommended_next_experiments
    assert not any(
        e.affected_status
        for e in refined.measurement_consumption.entries
        if e.submitted_as in ("off_target_screened", "protein_expression")
    )


def test_an_unsupported_key_does_not_change_the_domain_report() -> None:
    """The whole reason transparency is an envelope concern: a key nothing consumed must not
    alter a verdict, and must not therefore be invisible either."""
    with_typo = _service(
        {**CLONAL, "experiment": {**CLONAL["experiment"], "allele_patern": "homozygous"}}
    )
    assert with_typo.measurement_consumption.unsupported == ["allele_patern"]
    assert (
        with_typo.domain_details["decision_report"]
        == _service(CLONAL).domain_details["decision_report"]
    )


def test_the_mechanism_task_reports_the_marker_axes_as_unread() -> None:
    states = _states(
        {**MECHANISM, "experiment": {"edit_type": "knockout", "edit_detected": "present"}}
    )
    assert states["edit_type"] == "used_for_guidance"
    assert states["edit_detected"] == "not_applicable"


def test_the_cli_text_view_names_the_unrecognised_axis(tmp_path, capsys) -> None:
    payload = {**CLONAL, "experiment": {**CLONAL["experiment"], "sanger_seq": "confirmed"}}
    request_file = tmp_path / "query.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    assert cli_main(["query", "--input", str(request_file), "--format", "text"]) == 0
    out = capsys.readouterr().out

    assert "not recognised (ignored): sanger_seq" in out
    assert "used for the status:" in out
