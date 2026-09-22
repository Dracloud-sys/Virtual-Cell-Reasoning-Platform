"""Run the B/C development comparison against a real model, on a machine that has a key.

This exists because the environment the research path was built in has no provider
credential, so nothing here has ever been answered by a model. Re-confirming that failure
a fourth time tells nobody anything new. What is useful is a bundle someone with a key can
run unchanged — and that is what this is.

**Nothing runs by default.** With no flags it writes out every prompt it *would* send,
reports what it would cost in tokens, and makes zero provider calls. Spending money needs
`--spend-approved`, typed deliberately, because a budget nobody granted is not a budget.

What the two conditions are
---------------------------

* **B** — the same model, the same evidence, answering as a competent assistant would.
* **C** — the same model, the same evidence, through `ResearchService`.

They are matched on everything that could otherwise explain a difference: same model, same
`max_tokens`, same per-request timeout and retry ceiling, one call each, and **the same
user-side prompt text**, produced by the same `build_prompt` that `ResearchService` uses.
The only deliberate difference is the system prompt — which is the thing under test.

B is not weakened. Its instruction asks for the best answer a capable assistant would give,
and if that beats C, that is the result. `CONDITION_B_INSTRUCTION` is imported from
`build_condition_b.py` rather than restated here, so the two cannot drift apart.

Each call is a fresh stateless request with no conversation history, so B never sees C's
answer and C never sees B's. That is a property of the transport, not a promise.

What is preserved, separately
-----------------------------

Per case and condition:

* ``prompt_{b,c}.txt`` — exactly what was sent, system and user parts labelled.
* ``{b,c}_raw.txt`` — the model's reply **before anything parsed it**. For C this is the
  only place the original text survives; the report is what is left after checking.
* ``c_report.json`` / ``c_report.txt`` — the checked report, rendered both ways **from one
  call**. Running the CLI twice for two formats would be two calls, two bills and two
  different answers compared as if they were one.
* ``{b,c}_call.json`` — the run's settings and what the provider reported: model requested
  and served, tokens, stop reason, measured elapsed seconds.
* ``manifest.json`` — every attempted run and how it ended, written whether it succeeded or
  not. Reporting only the runs that went well would make this a demo.

Format compliance is not research quality
-----------------------------------------

C returns JSON and B returns prose, so C will trivially "pass" any structural check and B
will trivially fail one. That says nothing. The integrity findings recorded here are
checkable defects — a citation to an id nobody supplied — and the research judgement is a
person's, against `review_sheet.md`, which was written before any of this ran.

    python tests/benchmarks/research/run/run_comparison.py                 # dry run
    python tests/benchmarks/research/run/run_comparison.py --spend-approved
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE.parent / "cases"

#: The three cases this comparison uses, in order. One ECM question as asked, one where the
#: evidence disagrees with itself *and* comes from a different system than the question, and
#: one from an unrelated field — because a path that works only on the subject it was
#: demonstrated on has not been generalised.
COMPARISON_CASES = (
    "ecm_scaffold_single_cell.json",
    "contradicting_and_context_mismatch.json",
    "unrelated_subject.json",
)

#: Excluded from anything scored against real literature. Its only span is a placeholder DOI
#: that says so in its own text, and scoring a design built on an invented paper would be
#: measuring how well a model reasons from a fabrication.
EXCLUDED_CASES = ("species_mismatch.json",)


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=HERE,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _approx_tokens(text: str) -> int:
    """A rough count for the dry-run estimate only.

    Deliberately crude and labelled as such. The exact number comes back from the provider
    in ``usage`` after a real call; printing a precise-looking estimate here would invite it
    to be quoted as one.
    """
    return max(1, len(text) // 4)


def _load_cases(names: tuple[str, ...]) -> list[tuple[str, Path]]:
    cases: list[tuple[str, Path]] = []
    for name in names:
        if name in EXCLUDED_CASES:
            print(f"  skipping {name}: excluded from literature-based scoring (placeholder DOI)")
            continue
        path = CASES_DIR / name
        if not path.exists():
            raise SystemExit(f"case not found: {path}")
        cases.append((path.stem, path))
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--spend-approved",
        action="store_true",
        help=(
            "actually call the provider. Without this nothing is sent. Pass it only if you "
            "have approved this spend for this account."
        ),
    )
    parser.add_argument("--out", default=str(HERE / "out"), help="output directory")
    parser.add_argument(
        "--model",
        default=None,
        help="model id for BOTH conditions; defaults to the project's configured llm_model",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="overrides each case's budget, for both conditions, so they stay matched",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=None,
        help="run one case file name; repeatable. Defaults to the three comparison cases.",
    )
    parser.add_argument(
        "--conditions",
        default="b,c",
        help="which conditions to run (default both). Running one alone is not a comparison.",
    )
    args = parser.parse_args(argv)

    from virtualcell.core.config import get_settings
    from virtualcell.research import ResearchRequest, render_report_text
    from virtualcell.research.backend import (
        DEFAULT_MAX_RETRIES,
        DEFAULT_TIMEOUT_SECONDS,
        PROMPT_VERSION,
        RESEARCH_SYSTEM_PROMPT,
        AnthropicResearchBackend,
        ResearchBackendError,
        get_research_backend,
    )
    from virtualcell.research.service import ResearchService, build_prompt

    sys.path.insert(0, str(HERE.parent))
    from build_condition_b import CONDITION_B_INSTRUCTION  # noqa: E402

    conditions = tuple(c.strip().lower() for c in args.conditions.split(",") if c.strip())
    for condition in conditions:
        if condition not in {"b", "c"}:
            raise SystemExit(f"unknown condition {condition!r}; use b, c, or b,c")

    names = tuple(args.case) if args.case else COMPARISON_CASES
    cases = _load_cases(names)
    model = args.model or get_settings().llm_model
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    run_config = {
        "commit": _git_commit(),
        "started_utc": datetime.now(UTC).isoformat(),
        "model_requested": model,
        "prompt_version": PROMPT_VERSION,
        "max_output_tokens_override": args.max_output_tokens,
        "timeout_seconds_per_request": DEFAULT_TIMEOUT_SECONDS,
        "max_retries": DEFAULT_MAX_RETRIES,
        "deadline_enforced": False,
        "note": (
            "timeout_seconds is a per-request limit. It does not multiply with max_retries "
            "into a deadline, and none is enforced; elapsed_seconds in each *_call.json is "
            "the measured duration."
        ),
        "conditions": list(conditions),
        "cases": [name for name, _ in cases],
        "excluded_cases": list(EXCLUDED_CASES),
        "spend_approved": bool(args.spend_approved),
    }
    (out_dir / "run_config.json").write_text(json.dumps(run_config, indent=2), encoding="utf-8")

    manifest: list[dict] = []
    estimated_input = 0
    estimated_output = 0

    for name, path in cases:
        case_dir = out_dir / name
        case_dir.mkdir(parents=True, exist_ok=True)
        raw_request = json.loads(path.read_text(encoding="utf-8"))
        request = ResearchRequest.model_validate(raw_request)
        if args.max_output_tokens is not None:
            request = request.model_copy(
                update={
                    "budget": request.budget.model_copy(
                        update={"max_output_tokens": args.max_output_tokens}
                    )
                }
            )

        user_prompt = build_prompt(request)
        # The request as the contract sees it, evidence snapshot and content hashes
        # included, so a reader can check what the model was actually given.
        (case_dir / "request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")

        prompts = {
            "c": (RESEARCH_SYSTEM_PROMPT, user_prompt),
            "b": (CONDITION_B_INSTRUCTION, user_prompt),
        }
        for condition in conditions:
            system, user = prompts[condition]
            (case_dir / f"prompt_{condition}.txt").write_text(
                f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n", encoding="utf-8"
            )
            estimated_input += _approx_tokens(system) + _approx_tokens(user)
            estimated_output += request.budget.max_output_tokens

        if not args.spend_approved:
            for condition in conditions:
                manifest.append(
                    {
                        "case": name,
                        "condition": condition,
                        "status": "not_run",
                        "reason": "dry run: --spend-approved was not given",
                    }
                )
            continue

        for condition in conditions:
            system, user = prompts[condition]
            record: dict = {"case": name, "condition": condition}
            try:
                if condition == "c":
                    # The product path, not a re-implementation of it: the same service the
                    # CLI calls, with the same backend get_research_backend() returns.
                    backend = _Recording(get_research_backend(model))
                    report = ResearchService(backend=backend).investigate(request)
                    reply = backend.last
                    (case_dir / "c_raw.txt").write_text(reply.text, encoding="utf-8")
                    (case_dir / "c_report.json").write_text(
                        report.model_dump_json(indent=2), encoding="utf-8"
                    )
                    # Same report, second rendering, no second call.
                    (case_dir / "c_report.txt").write_text(
                        render_report_text(report), encoding="utf-8"
                    )
                    record["integrity_findings"] = [
                        {"code": f.code, "where": f.where} for f in report.integrity
                    ]
                    record["cli_equivalent_exit_code"] = 5 if report.integrity else 0
                else:
                    # Same transport, same limits, same model, same max_tokens — only the
                    # system prompt differs, which is the thing being compared.
                    b_backend = AnthropicResearchBackend(model=model, system_prompt=system)
                    reply = b_backend.design(
                        user, max_output_tokens=request.budget.max_output_tokens
                    )
                    (case_dir / "b_raw.txt").write_text(reply.text, encoding="utf-8")
                record["status"] = "ok"
                record["call"] = {
                    "model_requested": model,
                    "model_served": reply.model_served,
                    "stop_reason": reply.stop_reason,
                    "input_tokens": reply.input_tokens,
                    "output_tokens": reply.output_tokens,
                    "max_output_tokens": request.budget.max_output_tokens,
                    "timeout_seconds_per_request": reply.timeout_seconds,
                    "max_request_attempts": reply.max_request_attempts,
                    "elapsed_seconds": reply.elapsed_seconds,
                    "prompt_version": PROMPT_VERSION if condition == "c" else None,
                }
                (case_dir / f"{condition}_call.json").write_text(
                    json.dumps(record["call"], indent=2), encoding="utf-8"
                )
            except ResearchBackendError as exc:
                # Recorded, not swallowed. A condition that failed is part of the result.
                record["status"] = "failed"
                record["error"] = f"{type(exc).__name__}: {exc}"
                (case_dir / f"{condition}_error.txt").write_text(record["error"], encoding="utf-8")
                print(f"  {name} [{condition}] FAILED: {record['error']}")
            manifest.append(record)
            print(f"  {name} [{condition}] {record['status']}")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\nwrote {out_dir}")
    if not args.spend_approved:
        print(
            f"\nDRY RUN — no provider call was made.\n"
            f"  {len(cases)} case(s) x {len(conditions)} condition(s) = "
            f"{len(cases) * len(conditions)} call(s) if run.\n"
            f"  roughly {estimated_input} input tokens, up to {estimated_output} output "
            f"tokens.\n"
            f"  These are crude estimates (characters/4), not a quote. Apply your own "
            f"current per-token pricing, and re-run with --spend-approved only if you have "
            f"approved that spend.\n"
            f"  The exact prompts that would be sent are written under {out_dir}."
        )
    else:
        failed = [r for r in manifest if r.get("status") == "failed"]
        print(
            f"\n{len(manifest)} run(s), {len(failed)} failed. Submit every file written, "
            f"not a selection — see review_sheet.md."
        )
    return 0


class _Recording:
    """Wraps the real backend and keeps the reply, so the raw text can be preserved.

    `ResearchService` parses the reply and hands back a checked report; the original text
    is not part of that, and for a comparison it is the more important artifact — it is the
    only record of what the model actually said before anything corrected it. This changes
    nothing about the call: `design` is forwarded verbatim to the backend
    `get_research_backend()` returned.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.name = inner.name
        self.model = inner.model
        self.last = None

    def design(self, prompt: str, *, max_output_tokens: int):
        self.last = self._inner.design(prompt, max_output_tokens=max_output_tokens)
        return self.last


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
