"""Checking a draft by file must change only how the draft travels.

A real host wrote a 130 KB draft out as tool arguments to check it, and again after a
two-field fix (`docs/research_sessions/eval1_persistence/host_trial/`). The file tool reads the
draft from a configured directory instead. Held here:

* the result is the inline tool's result, plus which file was read and its hash;
* the hash is of the bytes parsed, and a mismatch checks nothing;
* nothing outside the directory is read, links included, and nothing is ever written;
* the tool exists only when a directory is configured, and the HTTP transport never
  configures one;
* reading a file does not make its evidence server-retrieved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

mcp_server = pytest.importorskip(
    "virtualcell.mcp.server",
    reason="the MCP adapter needs the optional 'mcp' extra",
)
sdk_errors = pytest.importorskip("mcp.server.mcpserver.exceptions")

from virtualcell.mcp import draft_file  # noqa: E402
from virtualcell.mcp.payloads import ToolRefusal  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RECORDS = REPO / "docs" / "research_sessions" / "eval1_persistence" / "records"
FIRST = RECORDS / "condition_B_payload_1.json"
TOOL = "check_research_draft_file"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _call(server, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(tool, arguments))
    assert not result.is_error, result.content
    return result.structured_content


def _refusal(server, arguments: dict[str, Any]) -> ToolRefusal:
    with pytest.raises(sdk_errors.ToolError) as caught:
        asyncio.run(server.call_tool(TOOL, arguments))
    return ToolRefusal.parse(str(caught.value))


@pytest.fixture
def drafts(tmp_path: Path) -> Path:
    root = tmp_path / "drafts"
    root.mkdir()
    shutil.copy(FIRST, root / "first.json")
    return root


def test_the_tool_exists_only_when_a_directory_is_configured(drafts):
    def names(server):
        return {t.name for t in asyncio.run(server.list_tools())}

    assert TOOL not in names(mcp_server.build_server())
    assert TOOL in names(mcp_server.build_server(draft_dir=drafts))


def test_the_http_transport_never_configures_a_directory():
    source = (REPO / "src" / "virtualcell" / "mcp" / "remote.py").read_text(encoding="utf-8")
    assert "draft_dir" not in source
    assert draft_file.DRAFT_DIR_ENV not in source


def test_the_result_is_the_inline_result_plus_the_file_read(drafts):
    server = mcp_server.build_server(draft_dir=drafts)
    by_file = _call(server, TOOL, {"path": "first.json", "sha256": _sha(FIRST), "view": "compact"})
    inline = _call(
        mcp_server.build_server(),
        "check_research_draft",
        {**json.loads(FIRST.read_text(encoding="utf-8")), "view": "compact"},
    )
    assert by_file["input_file"] == {
        "path": "first.json",
        "sha256": _sha(FIRST),
        "bytes": FIRST.stat().st_size,
        "scope": by_file["input_file"]["scope"],
    }
    assert {k: v for k, v in by_file.items() if k != "input_file"} == {
        k: v for k, v in inline.items() if k != "input_file"
    }
    assert by_file["finding_count"] == 83
    assert {o["origin"] for o in by_file["evidence_origins"]} == {"host_supplied"}
    assert by_file["scientific_validity_checked"] is False


def test_compact_is_the_default_here(drafts):
    out = _call(
        mcp_server.build_server(draft_dir=drafts),
        TOOL,
        {"path": "first.json", "sha256": _sha(FIRST)},
    )
    assert out["view"] == "compact"
    assert out["findings"] is None


def test_a_hash_mismatch_checks_nothing(drafts):
    refusal = _refusal(
        mcp_server.build_server(draft_dir=drafts), {"path": "first.json", "sha256": "0" * 64}
    )
    assert refusal.error == "draft_file_hash_mismatch"
    assert _sha(FIRST) in refusal.detail


@pytest.mark.parametrize(
    ("path", "error"),
    [
        ("missing.json", "draft_file_not_found"),
        ("../outside.json", "draft_file_not_allowed"),
        ("/etc/hostname", "draft_file_not_allowed"),
    ],
)
def test_nothing_outside_the_directory_is_read(drafts, path, error):
    (drafts.parent / "outside.json").write_text("{}", encoding="utf-8")
    refusal = _refusal(
        mcp_server.build_server(draft_dir=drafts), {"path": path, "sha256": "0" * 64}
    )
    assert refusal.error in {error, "draft_file_not_found"}
    assert refusal.error != "draft_file_hash_mismatch"


def test_a_link_out_of_the_directory_is_refused(drafts):
    outside = drafts.parent / "secret.json"
    outside.write_text('{"question": "x"}', encoding="utf-8")
    (drafts / "link.json").symlink_to(outside)
    refusal = _refusal(
        mcp_server.build_server(draft_dir=drafts), {"path": "link.json", "sha256": _sha(outside)}
    )
    assert refusal.error == "draft_file_not_allowed"


def test_shape_and_size_are_limited(drafts, monkeypatch):
    server = mcp_server.build_server(draft_dir=drafts)
    (drafts / "notes.txt").write_text("{}", encoding="utf-8")
    assert _refusal(server, {"path": "notes.txt", "sha256": "0" * 64}).error == (
        "draft_file_not_allowed"
    )
    (drafts / "list.json").write_text("[]", encoding="utf-8")
    refused = _refusal(server, {"path": "list.json", "sha256": _sha(drafts / "list.json")})
    assert refused.error == "malformed_draft_file"
    with_view = drafts / "view.json"
    with_view.write_text(json.dumps({"question": "q", "view": "full"}), encoding="utf-8")
    refused = _refusal(server, {"path": "view.json", "sha256": _sha(with_view)})
    assert refused.error == "malformed_draft_file"
    monkeypatch.setattr(draft_file, "MAX_BYTES", 1_000)
    refused = _refusal(server, {"path": "first.json", "sha256": _sha(FIRST)})
    assert refused.error == "draft_file_too_large"


def test_the_file_is_never_written(drafts):
    path = drafts / "first.json"
    before = (_sha(path), os.stat(path).st_mtime_ns)
    _call(
        mcp_server.build_server(draft_dir=drafts),
        TOOL,
        {"path": "first.json", "sha256": _sha(path), "view": "compact"},
    )
    assert (_sha(path), os.stat(path).st_mtime_ns) == before


def test_the_existing_draft_checks_still_apply(drafts):
    """A bare string where a list belongs is refused by the inline tool's own validation."""
    draft = {"question": "q", "hypotheses": "H1"}
    broken = drafts / "broken.json"
    broken.write_text(json.dumps(draft), encoding="utf-8")
    with pytest.raises(sdk_errors.ToolError) as by_file:
        asyncio.run(
            mcp_server.build_server(draft_dir=drafts).call_tool(
                TOOL, {"path": "broken.json", "sha256": _sha(broken)}
            )
        )
    with pytest.raises(sdk_errors.ToolError) as inline:
        asyncio.run(mcp_server.build_server().call_tool("check_research_draft", draft))
    assert str(inline.value) in str(by_file.value)
