#!/usr/bin/env python3
"""pc-part-scan legacy entry point (file-mode).

  python scan.py                  refresh, grade live lots, update data/
  python scan.py --no-refresh     grade from the cached corpus only
  python scan.py --full           deep refresh (more sold pages, more manifests)
  python scan.py --backfill       import an existing cache/ dir into data/

This is a thin wrapper: it pins the file storage backend and delegates to the
single scan implementation in `pcpartscan.cli` (`pcps scan`), so the two entry
points cannot drift.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

# scan.py is the legacy file-mode entry point; the Mongo path is `pcps scan`.
os.environ.setdefault("PCPS_STORE", "files")

from pcpartscan import cli
from pcpartscan import dataset as ds
from pcpartscan import harvest


def backfill():
    """Import a legacy cache/ directory into the structured dataset."""
    run = ds.run_id()
    observed = ds.utcnow()
    sold = harvest._load("sold_raw.json", {})
    live = harvest.load_live()
    mans = harvest._load("manifests.json", {})

    if sold:
        recs = list(sold.values())
        print("sold:", ds.upsert_lots(recs, observed, sold=True))
        print("sold index:", ds.upsert_sold(recs, observed))
        print("bid rows:", ds.record_bids(recs, observed, run))
    if live:
        recs = list(live.values())
        print("live:", ds.upsert_lots(recs, observed, sold=False))
        print("bid rows:", ds.record_bids(recs, observed, run))
    n = 0
    for key, machines in mans.items():
        if machines:
            ds.save_manifest(key, machines, source_files=[])
            n += 1
    print(f"manifests migrated: {n}")
    print("index:", json.dumps(ds.update_index(run)["counts"], indent=1))


def main():
    args = sys.argv[1:]
    if "--backfill" in args:
        backfill()
        return 0
    return cli.main(["scan", *args])


if __name__ == "__main__":
    sys.exit(main())
