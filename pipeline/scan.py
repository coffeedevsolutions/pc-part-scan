#!/usr/bin/env python3
"""pc-part-scan entry point.

  python scan.py                  refresh, grade live lots, update the dataset
  python scan.py --no-refresh     grade from the cached corpus only
  python scan.py --full           deep refresh (more sold pages, more manifests)
  python scan.py --backfill       import an existing cache/ dir into data/

Every run appends to data/bid_history.jsonl and writes a snapshot under
data/snapshots/, so the dataset accumulates a real time series rather than
being overwritten each time.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

# scan.py is the legacy file-mode entry point; the Mongo path is `pcps scan`.
os.environ.setdefault("PCPS_STORE", "files")

from pcpartscan import dataset as ds
from pcpartscan import grade, harvest, pricing


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-refresh", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--min-units", type=int, default=5)
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--target-roi", type=float, default=0.60)
    ap.add_argument("--recovery", type=float, default=0.55)
    ap.add_argument("--buyer-premium", type=float, default=0.0)
    ap.add_argument("--states", default="")
    a = ap.parse_args()

    if a.backfill:
        backfill()
        return 0

    run = ds.run_id()

    if not a.no_refresh:
        print("refreshing sold archive...")
        sold = harvest.sweep_sold(max_pages=12 if a.full else 4, run=run)
        print("building observations...")
        harvest.build_observations(sold, max_detail=600 if a.full else 120)
        print("refreshing live lots...")
        harvest.sweep_live(max_pages=8 if a.full else 4, run=run)

    cfg = grade.Config(target_roi=a.target_roi, recovery=a.recovery,
                       buyer_premium=a.buyer_premium)

    live = harvest.load_live()
    if a.states:
        want = {s.strip().upper() for s in a.states.split(",") if s.strip()}
        live = {k: v for k, v in live.items()
                if (v.get("locationState") or "").upper() in want}
        print(f"state filter {sorted(want)}: {len(live)} lots")

    single, bulk, table, ebay = grade.load_models()
    vals = grade.scan(live=live, cfg=cfg, min_units=a.min_units, limit=a.limit,
                      models=(single, bulk, table, ebay))

    # --- persist everything into the dataset --------------------------------
    ds.record_components(run, single, bulk, pricing.StaticTable.PATH)
    ds.write_json(ds.MODELS, {
        "schema_version": ds.SCHEMA_VERSION,
        "run_id": run,
        "single": single.to_json(),
        "bulk": bulk.to_json() if bulk else None,
    })
    gated = grade.CONFIDENCE_GATE
    ds.write_snapshot(run, {
        "config": asdict(cfg),
        "model_fit": {"single_r2": single.r2, "single_n": single.n_obs,
                      "bulk_k": bulk.k if bulk else None,
                      "bulk_r2": bulk.r2 if bulk else None,
                      "bulk_n": bulk.n_obs if bulk else 0},
        "screened": len(vals),
        "confidence_gate": gated,
        "lots": [asdict(v) for v in vals],
    })
    idx = ds.update_index(run, {"last_config": asdict(cfg)})

    actionable = [v for v in vals if v.grade in ("A", "B")
                  and v.headroom > 0 and v.confidence >= gated]

    print("\n" + grade.report(vals, top=a.top))
    print(f"\nrun {run}")
    print(f"dataset: {json.dumps(idx['counts'])}")
    print(f"{len(actionable)} lots pass the confidence gate with positive headroom")
    return 0


if __name__ == "__main__":
    sys.exit(main())
