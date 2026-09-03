"""The full verification gate, as one command.

    python scripts/verify.py

Exists because the gate was previously assembled by hand each session, from memory, and the
composition drifted: a run that skipped a scorecard or pointed `--basetemp` inside the
repository looked exactly like a run that passed. A gate you have to remember how to build is
a gate you will eventually build wrong on the run that mattered.

What it checks, and why each one is here:

* **full pytest** - the suite.
* **benchmark suite** - a second run of `tests/benchmarks` on its own, so a scorecard
  regression is attributable rather than buried in a 1600-test summary.
* **every scorecard** - discovered by globbing `eval_*_v0.py`, never listed. The same rule
  PR18 applied to the description drift test: a hard-coded list of domains makes "a new domain
  is covered automatically" false the moment someone forgets to extend it.
* **ruff check / format --check** - lint and formatting, in that order.
* **kernel diff** - `reasoning/kernel/` must be byte-identical to the base ref. Three
  verticals have now landed without touching it, and that claim is only worth making if
  something enforces it.

Two harness details it handles so a caller does not have to:

* pytest's temp directory goes **outside** the repository. Fixture files written inside it are
  picked up by `ruff check .` on the next run, which turns a clean tree into phantom lint
  errors, and they linger as untracked noise in `git status`.
* every subprocess runs under ``sys.executable``, so the gate cannot silently execute against
  a different interpreter than the one that was invoked.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS = ROOT / "tests" / "benchmarks"
KERNEL = "src/virtualcell/reasoning/kernel/"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    seconds: float


# A scorecard prints a table and then nothing; its headline is in the middle, not at the end.
# Matching on it keeps the summary line ("passed 10/10") in the report rather than whichever
# question happened to sort last.
_HEADLINE = ("| passed ", "passed ", "handled ")


def _run(name: str, argv: list[str], *, headline: bool = False) -> Result:
    started = time.monotonic()
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    elapsed = time.monotonic() - started
    stream = (proc.stdout or "") + (proc.stderr or "")
    lines = [line.strip() for line in stream.splitlines() if line.strip()]

    detail = ""
    if headline:
        detail = next((line for line in lines if any(t in line for t in _HEADLINE)), "")
    if not detail and lines:
        detail = lines[-1]
    return Result(name, proc.returncode == 0, detail or f"exit {proc.returncode}", elapsed)


def _scorecards() -> list[Path]:
    """Every benchmark evaluator, found rather than listed."""
    return sorted(BENCHMARKS.glob("eval_*_v0.py"))


def _kernel_diff(base: str) -> Result:
    started = time.monotonic()
    proc = subprocess.run(
        ["git", "diff", "--stat", f"{base}...HEAD", "--", KERNEL],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        # An unknown base ref is a setup problem, not a kernel change. Say which.
        return Result("kernel unchanged", False, f"cannot diff against {base!r}", elapsed)
    changed = proc.stdout.strip()
    return Result(
        "kernel unchanged",
        not changed,
        f"0 lines vs {base}" if not changed else changed.splitlines()[-1].strip(),
        elapsed,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base",
        default="origin/main",
        help="ref the kernel is compared against (default: origin/main)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="skip the standalone benchmark re-run and the scorecard tables",
    )
    parser.add_argument(
        "--no-kernel-diff",
        action="store_true",
        help="skip the kernel comparison (use when the base ref is unavailable offline)",
    )
    args = parser.parse_args()

    py = sys.executable
    basetemp = Path(tempfile.mkdtemp(prefix="vcrp-pytest-"))
    results: list[Result] = []
    try:
        results.append(
            _run("pytest (full)", [py, "-m", "pytest", "-q", "--basetemp", str(basetemp)])
        )
        if not args.fast:
            results.append(
                _run(
                    "pytest (benchmarks)",
                    [py, "-m", "pytest", "tests/benchmarks", "-q", "--basetemp", str(basetemp)],
                )
            )
            for evaluator in _scorecards():
                module = f"tests.benchmarks.{evaluator.stem}"
                name = evaluator.stem.removeprefix("eval_").removesuffix("_v0")
                results.append(_run(f"scorecard: {name}", [py, "-m", module], headline=True))
        results.append(_run("ruff check", [py, "-m", "ruff", "check", "."]))
        results.append(_run("ruff format", [py, "-m", "ruff", "format", "--check", "."]))
        if not args.no_kernel_diff:
            results.append(_kernel_diff(args.base))
    finally:
        # Leaving these behind is the failure this script exists partly to prevent.
        shutil.rmtree(basetemp, ignore_errors=True)

    width = max(len(r.name) for r in results)
    print()
    print("=" * (width + 58))
    for r in results:
        print(f"  {'PASS' if r.ok else 'FAIL'}  {r.name:<{width}}  {r.seconds:5.1f}s  {r.detail}")
    print("=" * (width + 58))

    failed = [r.name for r in results if not r.ok]
    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        print("Re-run the failing step on its own for the full output.")
        return 1
    print(f"\nAll {len(results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
