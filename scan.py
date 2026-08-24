#!/usr/bin/env python3
"""Deprecated entry point.

The file-mode scheduled scan that used to run from the repository root is
retired: scanning now runs via the GitHub Actions workflows in
.github/workflows/, which write to MongoDB instead of committing data files
to git. See docs/ARCHITECTURE.md.

Nothing should commit scan output to this repository anymore.

For interactive file-mode use, the old entry point moved to
pipeline/scan.py; the production path is `pcps scan` (pip install
./pipeline) against MongoDB.
"""

print(__doc__)
raise SystemExit(0)
