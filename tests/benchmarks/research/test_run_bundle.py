"""The run bundle must stay runnable and honest without a provider.

It is the deliverable for an environment that has no credential: someone else will run it,
once, and spend money doing so. So the things that would waste that run are checked here —
that the dry run calls nothing, that B and C are actually matched, that the committed
prompts are the prompts that would be sent, and that the excluded case stays excluded.

No model is called by any of this.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from virtualcell.research import ResearchRequest

RUN_DIR = Path(__file__).parent / "run"
PROMPTS_DIR = RUN_DIR / "prompts"

sys.path.insert(0, str(RUN_DIR))
from run_comparison import COMPARISON_CASES, EXCLUDED_CASES, main  # noqa: E402


def test_the_comparison_cases_exist_and_validate() -> None:
    for name in COMPARISON_CASES:
        path = Path(__file__).parent / "cases" / name
        assert path.exists(), name
        ResearchRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_the_placeholder_case_is_excluded_from_the_comparison() -> None:
    """Scoring a design built on an invented paper measures how well a model reasons from a
    fabrication. It is excluded by name, and it is not quietly in the run list either.
    """
    assert "species_mismatch.json" in EXCLUDED_CASES
    assert not set(COMPARISON_CASES) & set(EXCLUDED_CASES)


def test_a_dry_run_calls_no_provider_and_writes_the_prompts(tmp_path, monkeypatch, capsys):
    """The default has to be free. A runner that spends on invocation would spend the first
    time someone ran it to see what it did.

    The key is removed for this test, so an accidental call could not succeed even if the
    guard were wrong — it would raise rather than quietly bill someone.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert main(["--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out

    assert "DRY RUN" in out
    assert "no provider call was made" in out
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest and all(entry["status"] == "not_run" for entry in manifest)
    assert (
        json.loads((tmp_path / "run_config.json").read_text(encoding="utf-8"))["spend_approved"]
        is False
    )


@pytest.mark.parametrize("name", [Path(n).stem for n in COMPARISON_CASES])
def test_b_and_c_receive_the_same_evidence_word_for_word(tmp_path, name) -> None:
    """The control that makes the comparison mean anything. If B were handed a looser
    paraphrase than C, a C advantage would be partly an artefact of transcription and the
    result would say nothing about structure.
    """
    main(["--out", str(tmp_path), "--case", f"{name}.json"])

    b_user = (tmp_path / name / "prompt_b.txt").read_text(encoding="utf-8").split("=== USER ===")[1]
    c_user = (tmp_path / name / "prompt_c.txt").read_text(encoding="utf-8").split("=== USER ===")[1]

    assert b_user == c_user
    assert b_user.strip()


@pytest.mark.parametrize("name", [Path(n).stem for n in COMPARISON_CASES])
def test_the_committed_prompts_are_the_prompts_that_would_be_sent(tmp_path, name) -> None:
    """`prompts/` is committed so an operator can read what a run would cost them before
    paying for it. A copy that drifted from the code would be worse than not committing it.
    """
    main(["--out", str(tmp_path), "--case", f"{name}.json"])

    for filename in ("request.json", "prompt_b.txt", "prompt_c.txt"):
        committed = (PROMPTS_DIR / name / filename).read_text(encoding="utf-8")
        generated = (tmp_path / name / filename).read_text(encoding="utf-8")
        assert committed == generated, f"{name}/{filename} is stale; re-run the dry run"


def test_the_bundle_does_not_claim_a_deadline_it_does_not_enforce() -> None:
    """The correction this round exists for. A per-request timeout and a retry ceiling are
    settings; they do not multiply into a total deadline, and nothing here cancels a long
    call. The run config says so in the file the operator reads.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        main(["--out", tmp])
        config = json.loads((Path(tmp) / "run_config.json").read_text(encoding="utf-8"))

    assert config["deadline_enforced"] is False
    assert "timeout_seconds_per_request" in config
    assert "does not multiply" in config["note"]


# --- what survives a run, and what the run says it did -------------------------------------
#
# Reproduced first against the shipped bundle: a C reply that arrived and then failed the
# parse left no c_raw.txt and no c_call.json, and the run exited 0 with one failure.


def _reply(text: str):
    from virtualcell.research.backend import ModelReply

    return ModelReply(
        text=text,
        model_served="fake-model-dated-id",
        stop_reason="end_turn",
        input_tokens=911,
        output_tokens=42,
        max_request_attempts=3,
        timeout_seconds=120.0,
        elapsed_seconds=3.5,
    )


_DESIGN = json.dumps(
    {
        "restated_question": "Does scaffold degradation outpace deposition, measured how?",
        "assumptions": [],
        "hypotheses": [
            {
                "id": "H1",
                "statement": "degradation outpaces deposition",
                "support": "evidence_linked",
                "supporting_evidence_ids": ["obs-1"],
                "contradicting_evidence_ids": [],
                "applicability": None,
            }
        ],
        "experiments": [
            {
                "id": "E1",
                "design": "time course of mass loss against collagen deposition",
                "discriminates": ["H1"],
                "controls": ["scaffold-only"],
                "measurements": ["mass", "hydroxyproline"],
                "timepoints": ["day 3", "day 7", "day 14"],
                "branches": [{"outcome": "loss leads", "implication": "H1 stands"}],
                "priority_rationale": "one plate answers it",
            }
        ],
        "open_items": [],
        "evidence_used": ["obs-1"],
    }
)

#: Cites an id nobody supplied, so the report is produced *and* carries an integrity finding.
_DESIGN_WITH_BAD_CITATION = _DESIGN.replace('["obs-1"]', '["obs-99"]')


def _install_backend(monkeypatch, reply_or_error):
    """Point the runner's C path at a fake backend. No network, no key, no spend."""
    import virtualcell.research.backend as backend_mod

    class Fake:
        name = "fake"
        model = "fake-model"

        def design(self, prompt, *, max_output_tokens):
            if isinstance(reply_or_error, Exception):
                raise reply_or_error
            return reply_or_error

    monkeypatch.setattr(backend_mod, "get_research_backend", lambda model=None: Fake())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused-the-backend-is-replaced")


def _run_c(tmp_path, case="ecm_scaffold_single_cell.json"):
    return main(["--out", str(tmp_path), "--case", case, "--conditions", "c", "--spend-approved"])


def test_a_reply_that_fails_checking_is_still_preserved(tmp_path, monkeypatch) -> None:
    """Observed on the shipped bundle: a reply of prose instead of JSON produced
    `c_error.txt` and nothing else — no `c_raw.txt`, no `c_call.json`.

    The provider had answered and the answer had been billed for. Whether it parses is a
    different question with a different answer, and losing the text means losing the only
    record of what the model actually said, along with what it cost to find out.
    """
    _install_backend(monkeypatch, _reply("I think you should run a stiffness series first."))

    code = _run_c(tmp_path)

    case_dir = tmp_path / "ecm_scaffold_single_cell"
    assert (case_dir / "c_raw.txt").read_text(encoding="utf-8").startswith("I think you should")
    call = json.loads((case_dir / "c_call.json").read_text(encoding="utf-8"))
    assert call["output_tokens"] == 42
    assert call["elapsed_seconds"] == 3.5
    assert (case_dir / "c_error.txt").exists()
    # and it is still a failure, not a report
    assert not (case_dir / "c_report.json").exists()
    assert code == 4


def test_a_reply_that_never_arrived_is_not_invented(tmp_path, monkeypatch) -> None:
    """The other half. Nothing was received, so nothing is written — an empty `c_raw.txt` or
    a zeroed token count would read as a measurement of a call that produced nothing.
    """
    from virtualcell.research.backend import BackendUnavailable

    _install_backend(monkeypatch, BackendUnavailable("no key"))

    code = _run_c(tmp_path)

    case_dir = tmp_path / "ecm_scaffold_single_cell"
    assert not (case_dir / "c_raw.txt").exists()
    assert not (case_dir / "c_call.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["reply_received"] is False
    assert code == 3  # nothing ran, the CLI's own meaning for that


def test_a_failing_run_does_not_report_success(tmp_path, monkeypatch) -> None:
    """The shipped bundle ended `return 0` whatever happened, so a run in which every call
    failed told its caller the comparison had succeeded.
    """
    _install_backend(monkeypatch, _reply("not json"))

    assert _run_c(tmp_path) == 4


def test_a_report_with_integrity_findings_exits_five(tmp_path, monkeypatch) -> None:
    """Same code the CLI uses for the same situation: a report was produced and something in
    it does not check out. Distinct from 4, where no report exists at all.
    """
    _install_backend(monkeypatch, _reply(_DESIGN_WITH_BAD_CITATION))

    code = _run_c(tmp_path)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["status"] == "ok"
    codes = [f["code"] for f in manifest[0]["integrity_findings"]]
    # One bad id trips three checks, which is the check working: the id does not exist, so
    # the hypothesis claiming to be evidence-linked is not, and `evidence_used` names it too.
    assert "unknown_evidence_id" in codes
    assert "unsupported_evidence_link" in codes
    assert code == 5


def test_a_clean_run_exits_zero(tmp_path, monkeypatch) -> None:
    _install_backend(monkeypatch, _reply(_DESIGN))

    code = _run_c(tmp_path)

    case_dir = tmp_path / "ecm_scaffold_single_cell"
    assert (case_dir / "c_raw.txt").exists()
    assert (case_dir / "c_report.json").exists()
    assert (case_dir / "c_report.txt").exists()  # rendered from the same call
    assert code == 0


def test_the_manifest_is_current_after_every_entry(tmp_path, monkeypatch) -> None:
    """Written once at the end, the manifest describes nothing if the run dies partway — and
    that is exactly the run whose partial results someone needs.
    """
    import virtualcell.research.backend as backend_mod

    calls = {"n": 0}

    class HalfBroken:
        name = "fake"
        model = "fake-model"

        def design(self, prompt, *, max_output_tokens):
            calls["n"] += 1
            if calls["n"] == 1:
                return _reply(_DESIGN)
            raise KeyboardInterrupt("the operator gave up on the second case")

    monkeypatch.setattr(backend_mod, "get_research_backend", lambda model=None: HalfBroken())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused-the-backend-is-replaced")

    with pytest.raises(KeyboardInterrupt):
        main(
            [
                "--out",
                str(tmp_path),
                "--case",
                "ecm_scaffold_single_cell.json",
                "--case",
                "unrelated_subject.json",
                "--conditions",
                "c",
                "--spend-approved",
            ]
        )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["case"] for entry in manifest] == ["ecm_scaffold_single_cell"]
    assert manifest[0]["status"] == "ok"


def test_a_non_empty_output_folder_is_refused_and_nothing_is_deleted(tmp_path, capsys) -> None:
    """Two runs sharing a folder leave one run's manifest beside another run's reports, and
    every file still looks like it belongs. Clearing the folder to make room would destroy
    model outputs somebody paid for, so it is refused instead.
    """
    existing = tmp_path / "manifest.json"
    existing.write_text('[{"case": "from an earlier run"}]', encoding="utf-8")

    code = main(["--out", str(tmp_path)])

    assert code == 1
    assert "not empty" in capsys.readouterr().err
    assert json.loads(existing.read_text(encoding="utf-8"))[0]["case"] == "from an earlier run"
