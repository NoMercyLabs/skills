#!/usr/bin/env python3
"""assay: a script-accepted audit pipeline. Run `assay.py --help` for the commands."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assaylib.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
