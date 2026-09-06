"""Make ``scripts/automation`` importable without changing packaging.

The gate lives under ``scripts/`` rather than ``src/`` because it is not part of the
shipped library: nothing in ``virtualcell`` imports it, and installing the package must
not install it. That leaves it off ``pythonpath`` (``pyproject.toml`` lists only ``src``),
so this conftest puts ``scripts/`` on the path and the modules import as ``automation.*``.

Adding ``scripts`` to ``pythonpath`` in ``pyproject.toml`` would be the other way, but this
work item may not touch packaging, and a conftest keeps the dependency where the tests are
rather than in the project's public build configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
