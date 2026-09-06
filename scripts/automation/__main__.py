"""``python -m automation`` — see :mod:`automation.runner` for the commands and exit codes."""

from __future__ import annotations

import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
