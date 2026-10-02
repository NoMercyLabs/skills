#!/usr/bin/env python3
"""crucible: a script-accepted audit pipeline. Run `crucible.py --help` for the commands."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cruciblelib.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
