#!/usr/bin/env python3
"""Maintainer convenience shim for running cc-duet from a source checkout without installing the package."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cc_duet.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
