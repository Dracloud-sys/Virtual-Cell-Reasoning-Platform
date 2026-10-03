"""Read a draft the host already wrote to a file, instead of having it re-typed as arguments.

Measured on a real host (`docs/research_sessions/eval1_persistence/host_trial/`): to check a
130 KB draft that sat in a file, and once more after a two-field fix, the host model wrote
the whole draft out as tool arguments each time. One attempt was rejected by the client as
unparseable JSON. The check itself was cheap; carrying the draft was not.

So on the **stdio** server, and only when the operator names a directory, a draft can be
checked by path. What this adds is transport only:

* the file must resolve, after following every link, to a regular ``.json`` file inside the
  named directory, and be no larger than :data:`MAX_BYTES`;
* the caller states the SHA-256 it expects. The hash is computed over the bytes read, and
  those same bytes are parsed, so the draft checked is the draft the caller named;
* the parsed object goes to the same check as the inline arguments: the same validation,
  the same integrity checks, the same plan analysis. Nothing about the draft is trusted
  more because the server read it. In particular an evidence span is classified against
  what this server issued, exactly as when it arrives inline; reading a file is not
  retrieving a source.

The file is opened read-only and never written. No URL, no path outside the directory, and
nothing over HTTP: `remote.py` never passes a directory, so the tool does not exist there.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: Large enough for the largest recorded draft (130 KB) many times over; small enough that
#: a wrong path cannot pull a big file into memory.
MAX_BYTES = 2 * 1024 * 1024

#: The environment variable naming the directory drafts may be read from. Unset, the tool
#: is not registered.
DRAFT_DIR_ENV = "VIRTUALCELL_MCP_DRAFT_DIR"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DraftInput(BaseModel):
    """Which file was checked, as the server read it."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="The file, relative to the allowed draft directory.")
    sha256: str = Field(description="SHA-256 of the bytes read; equal to the one requested.")
    bytes: int
    scope: str = (
        "Read by this stdio server from its configured draft directory. Not an upload, and "
        "not available over HTTP. Reading the file classifies no evidence as retrieved."
    )


class DraftFileRefused(ValueError):
    """A draft file that will not be read, with the reason a caller can act on."""

    def __init__(self, error: str, detail: str, remedy: str) -> None:
        super().__init__(detail)
        self.error, self.detail, self.remedy = error, detail, remedy


def draft_dir_from_env() -> Path | None:
    """The configured draft directory, resolved, or None when none is configured."""
    value = os.environ.get(DRAFT_DIR_ENV, "").strip()
    if not value:
        return None
    root = Path(value).resolve()
    if not root.is_dir():
        raise SystemExit(f"{DRAFT_DIR_ENV}={value!r} is not a directory")
    return root


def read_draft_file(root: Path, path: str, sha256: str) -> tuple[dict[str, Any], DraftInput]:
    """The draft object and what was read, or `DraftFileRefused`. Never writes."""
    expected = sha256.strip().lower()
    if not _SHA256.match(expected):
        raise DraftFileRefused(
            "malformed_draft_file",
            f"sha256 must be 64 hexadecimal characters; got {sha256!r}.",
            "Send the SHA-256 of the file as hex (for example from `sha256sum`).",
        )
    if "\x00" in path:
        raise DraftFileRefused("draft_file_not_allowed", "the path contains a NUL byte.", _IN)
    root = root.resolve()
    try:
        target = (root / path).resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        raise DraftFileRefused(
            "draft_file_not_found", f"{path!r} does not exist in the draft directory.", _IN
        ) from None
    except (OSError, RuntimeError) as exc:
        raise DraftFileRefused("draft_file_not_allowed", f"{path!r}: {exc}", _IN) from None
    if not target.is_relative_to(root):
        raise DraftFileRefused(
            "draft_file_not_allowed",
            f"{path!r} resolves outside the draft directory.",
            _IN,
        )
    if target.suffix.lower() != ".json":
        raise DraftFileRefused("draft_file_not_allowed", f"{path!r} is not a .json file.", _IN)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise DraftFileRefused("draft_file_not_allowed", f"{path!r}: {exc.strerror}", _IN) from None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise DraftFileRefused(
                "draft_file_not_allowed", f"{path!r} is not a regular file.", _IN
            )
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise DraftFileRefused(
            "draft_file_too_large",
            f"{path!r} is larger than {MAX_BYTES} bytes.",
            "Check a smaller draft, or send it inline to check_research_draft.",
        )

    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise DraftFileRefused(
            "draft_file_hash_mismatch",
            f"{path!r} has SHA-256 {actual}, not the {expected} that was asked for.",
            "Recompute the hash of the file you mean to check; nothing was checked.",
        )
    try:
        draft = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DraftFileRefused(
            "malformed_draft_file", f"{path!r} is not UTF-8 JSON: {exc}", _SHAPE
        ) from None
    if not isinstance(draft, dict):
        raise DraftFileRefused(
            "malformed_draft_file",
            f"{path!r} holds a {type(draft).__name__}, not a JSON object.",
            _SHAPE,
        )
    relative = target.relative_to(root).as_posix()
    return draft, DraftInput(path=relative, sha256=actual, bytes=len(data))


_IN = "Name a .json file inside the configured draft directory, relative to it."
_SHAPE = (
    "The file must be one JSON object whose keys are check_research_draft's arguments "
    "(question, hypotheses, experiments, evidence, ...), without view."
)
