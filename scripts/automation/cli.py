"""The canonical entry point, runnable from the repository root with nothing set up.

    python scripts/automation/cli.py preflight --request run-request.json

The Routine starts in the repository root, so that is the only place the command has to work
from. The previous round documented ``python -m automation``, which needs ``scripts/`` on
``PYTHONPATH`` and therefore fails exactly where it is used:

    $ python -m automation preflight --request run-request.json
    No module named automation

The integration tests hid it by running with ``cwd=scripts``. A test that arranges the one
condition the real caller cannot provide is testing something else.

Running this file directly leaves ``__package__`` unset, so the relative imports inside the
package would fail. Putting the package's own parent on ``sys.path`` first and importing
absolutely is what makes a plain file path work with no wrapper, no install and no environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from automation.runner import main  # noqa: E402  (the path bootstrap above must run first)

if __name__ == "__main__":
    sys.exit(main())
