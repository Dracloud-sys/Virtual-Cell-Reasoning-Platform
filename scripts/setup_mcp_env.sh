#!/usr/bin/env bash
# Prepare the interpreter the MCP server runs on, before a host tries to load it.
#
# A host reads `.mcp.json` and spawns the command in it at session start. If the
# interpreter named there cannot import `virtualcell` and `mcp`, the server fails to
# start and the tools are simply absent — there is no error the host surfaces usefully,
# so the failure looks like "the tools do not exist". This script is what makes that
# interpreter exist, and it runs from the environment's **Setup script** field so it
# finishes before any MCP loading happens.
#
# Same procedure CLAUDE.md already documents for the verification venv, with two
# differences: it installs `.[mcp]` rather than `.[dev]`, and it is idempotent so a new
# session that already has a good venv pays almost nothing.
#
# `[llm]` is deliberately NOT installed. The MCP research tools call no model and need no
# API key; adding it would pull a dependency nothing on this path uses.
#
#     bash scripts/setup_mcp_env.sh
#
# On success it prints the absolute interpreter path. That path is what goes in the
# environment's VCRP_PYTHON variable, which `.mcp.json` reads.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${REPO_ROOT}/.venv-mcp"
PYBIN="${VENV}/bin/python"

# The guard is the point. An unset PY312 would become `--python ""`, which does not fail
# loudly, and falling back to whatever `python3` happens to be answers a different
# question: this project's floor is 3.12 and the container's default python3 is older.
PY312="$(command -v python3.12 || true)"
if [ -z "${PY312}" ]; then
    echo "setup_mcp_env: no python3.12 on PATH; not falling back to python3" >&2
    exit 1
fi

# Idempotent: a session that already has a working venv re-runs this in well under a
# second, which matters because the setup script runs on every new session.
if [ -x "${PYBIN}" ] && "${PYBIN}" -c "import virtualcell, mcp" >/dev/null 2>&1; then
    echo "${PYBIN}"
    exit 0
fi

if [ ! -x "${PYBIN}" ]; then
    if command -v uv >/dev/null 2>&1; then
        uv venv --python "${PY312}" "${VENV}" >&2
    else
        "${PY312}" -m venv "${VENV}" >&2
    fi
fi

if command -v uv >/dev/null 2>&1; then
    uv pip install --python "${PYBIN}" -e "${REPO_ROOT}[mcp]" >&2
else
    "${PYBIN}" -m pip install --quiet --upgrade pip >&2
    "${PYBIN}" -m pip install --quiet -e "${REPO_ROOT}[mcp]" >&2
fi

# Prove it before claiming it. A venv that exists but cannot import the package would
# leave the host with a server that dies on spawn.
"${PYBIN}" -c "import virtualcell, mcp" >&2
echo "${PYBIN}"
