"""Render a development case as the **B** condition: the same model, the same evidence.

P4 compares three conditions, and only two of them are about this repository:

* **A** — the model alone, given the question and nothing else.
* **B** — the model given the question *and the same evidence*, answering normally.
* **C** — the same question and evidence through `ResearchService`.

B is the comparison that matters, and it is the easy one to get wrong. If B is handed a
looser paraphrase of the evidence than C receives, then C's advantage is partly an artefact
of transcription and the result says nothing about structure. So B is built from **the same
function C uses**: `build_prompt` produces exactly the text `ResearchService` sends, and
this script prints it with a plain instruction in front instead of the research system
prompt.

What is left deliberately different is the *only* thing under test: C's system prompt asks
for labelled hypotheses, decision branches and explicit unverified candidates, and its
output is then checked against the request. B is asked to help, as a competent assistant
would be asked.

Budgets must be matched too — same model, same max tokens, one call each. This script does
not call anything, so that is the operator's to hold.

    python tests/benchmarks/research/build_condition_b.py cases/thin_evidence.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from virtualcell.research import ResearchRequest
from virtualcell.research.service import build_prompt

#: Plain, capable, and pointedly *not* the research system prompt. B is the control: a
#: competent assistant given the same material, with none of the structure C imposes.
CONDITION_B_INSTRUCTION = """\
You are helping a researcher design a cell-level experiment. Using the question, context and
evidence below, give them your best answer: what you think is going on, what else it could
be, and what they should do next.
"""


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    path = Path(sys.argv[1])
    if not path.is_absolute() and not path.exists():
        path = Path(__file__).parent / path

    request = ResearchRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    print(CONDITION_B_INSTRUCTION)
    print(build_prompt(request))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
