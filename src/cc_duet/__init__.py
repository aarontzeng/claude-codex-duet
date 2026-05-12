from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__all__ = ["__version__"]


def _fallback_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    match = re.search(r'^version = "([^"]+)"$', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise RuntimeError("Unable to determine package version from pyproject.toml")
    return match.group(1)


try:
    __version__ = version("claude-codex-duet")
except PackageNotFoundError:
    __version__ = _fallback_version()
