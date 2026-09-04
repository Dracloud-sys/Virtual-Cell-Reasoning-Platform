"""A default install must not grow a protocol server.

The MCP SDK is real weight, and most of what this platform does is reachable
through the API and the CLI without it. So it is an extra - and an extra is only
honest if the boundary is enforced somewhere other than a promise in a docstring.

These tests hide the SDK from the import system and check both halves of the
claim: everything that does not need it still imports, and the one module that
does need it fails loudly rather than at some later call.
"""

from __future__ import annotations

import importlib
import sys
from importlib.abc import MetaPathFinder

import pytest


class _SdkHidden(MetaPathFinder):
    """Make ``mcp`` unimportable, the way a default install has it."""

    def find_spec(self, name, path=None, target=None):  # noqa: ANN001, ANN201
        if name == "mcp" or name.startswith("mcp."):
            raise ModuleNotFoundError(f"No module named {name!r} (simulated)", name=name)
        return None


@pytest.fixture
def sdk_hidden(monkeypatch: pytest.MonkeyPatch):
    """Hide the SDK and every module that already imported it, then restore."""
    for module in [m for m in sys.modules if m == "mcp" or m.startswith("mcp.")]:
        monkeypatch.delitem(sys.modules, module)
    for module in [m for m in sys.modules if m.startswith("virtualcell.mcp")]:
        monkeypatch.delitem(sys.modules, module)
    monkeypatch.setattr(sys, "meta_path", [_SdkHidden(), *sys.meta_path])
    yield


@pytest.mark.parametrize(
    "module",
    [
        "virtualcell.cli",
        "virtualcell.platform.service",
        "virtualcell.mcp",
        "virtualcell.mcp.payloads",
        "virtualcell.mcp.guidance",
    ],
)
def test_the_platform_and_the_pure_mcp_modules_import_without_the_sdk(
    sdk_hidden, module: str
) -> None:
    """`virtualcell.mcp` itself is included on purpose: the payload shapes and the
    safety text are testable without a protocol, and keeping them importable is what
    makes that true rather than merely intended."""
    assert importlib.import_module(module) is not None


def test_only_the_server_module_needs_the_sdk(sdk_hidden) -> None:
    """It must fail at import, not at the first call: a server that constructs and then
    dies mid-conversation is worse than one that never starts."""
    with pytest.raises(ModuleNotFoundError) as caught:
        importlib.import_module("virtualcell.mcp.server")
    assert "mcp" in str(caught.value)


def test_the_package_exports_nothing_that_requires_the_sdk(sdk_hidden) -> None:
    package = importlib.import_module("virtualcell.mcp")
    assert package.__all__
    for name in package.__all__:
        assert getattr(package, name) is not None, name
