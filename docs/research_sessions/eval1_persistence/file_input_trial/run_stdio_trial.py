"""Over a real MCP stdio session (not the Claude Code host): check v1 and v2 by file reference."""

import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DRAFTS = Path(sys.argv[1])
OUT = Path(sys.argv[2])


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "virtualcell.mcp"],
        env={**os.environ, "VIRTUALCELL_MCP_DRAFT_DIR": str(DRAFTS)},
    )
    records = []
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        names = sorted(t.name for t in tools.tools)
        for name in ("draft_v1.json", "draft_v2.json"):
            args = {"path": name, "sha256": sha(DRAFTS / name), "view": "compact"}
            started = time.perf_counter()
            result = await session.call_tool("check_research_draft_file", args)
            elapsed = time.perf_counter() - started
            sc = result.structured_content
            (OUT / f"stdio_{name.replace('draft_', 'check_')}").write_text(
                json.dumps(sc, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            records.append(
                {
                    "file": name,
                    "is_error": result.is_error,
                    "argument_bytes": len(json.dumps(args, separators=(",", ":"))),
                    "file_bytes_read_by_server": (DRAFTS / name).stat().st_size,
                    "structured_bytes": len(
                        json.dumps(sc, separators=(",", ":"), ensure_ascii=False)
                    ),
                    "text_block_chars": sum(
                        len(c.text) for c in result.content if getattr(c, "text", None)
                    ),
                    "seconds": round(elapsed, 3),
                }
            )
    print(json.dumps({"tools": names, "calls": records}, indent=1))


asyncio.run(main())
