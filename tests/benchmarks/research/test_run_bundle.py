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
