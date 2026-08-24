#!/usr/bin/env python3
"""Generate the golden fixture for the TypeScript valuation parity test.

Takes graded lots from a snapshot and re-derives the config-dependent
numbers (expected revenue, max bid, headroom, ROI, grade) under several
config variants using the Python grader. The TS port in packages/valuation
must reproduce every number to the cent -- CI enforces it.

Usage: python pipeline/tools/make_valuation_golden.py <snapshot.json> <out.json>
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))
os.environ.setdefault("PCPS_STORE", "files")

from pcpartscan import grade

CONFIGS = [
    {},                                                     # defaults
    {"target_roi": 0.40, "recovery": 0.70},
    {"target_roi": 1.00, "recovery": 0.40, "dead_rate": 0.25},
    {"buyer_premium": 0.125, "sales_tax": 0.07, "pickup_cost": 150.0,
     "per_unit_handling": 5.0},
    # the family split: parts must take the cheaper rate and machines must
    # not, which only shows up when the two differ
    {"per_unit_handling": 4.0, "part_handling": 0.5},
]


def regrade(lot: dict, base: grade.Config) -> dict:
    cfg = base.for_family(lot.get("item_family"))
    parts_out = lot["ceiling"] * (1 - cfg.dead_rate) * cfg.recovery
    rev = (max(parts_out, lot["floor"])
           if lot.get("floor_trusted", True) else parts_out)
    max_bid = cfg.max_hammer(rev, lot["units"])
    headroom = max_bid - lot["current_bid"]
    cost_now = cfg.all_in(lot["current_bid"], lot["units"])
    roi = (rev - cost_now) / cost_now if cost_now > 0 else 0.0
    rel = headroom / max_bid if max_bid > 0 else -1.0
    return {
        "expected_revenue": round(rev, 2),
        "max_bid": round(max_bid, 2),
        "headroom": round(headroom, 2),
        "roi_at_current": round(roi, 6),
        "grade": grade._grade(rel, lot["confidence"],
                              lot.get("contents_known", True)),
        "handling_applied": round(cfg.per_unit_handling, 2),
        "handling_breakeven": round(max(
            0.0, (rev / (1 + cfg.target_roi) - cfg.pickup_cost) / lot["units"]
        ) if lot["units"] > 0 else 0.0, 6),
    }


def main() -> int:
    snapshot_path, out_path = sys.argv[1], sys.argv[2]
    with open(snapshot_path) as f:
        snap = json.load(f)
    lots = [{k: lot[k] for k in
             ("lot_key", "units", "current_bid", "floor", "ceiling", "confidence")}
            for lot in snap["lots"]]
    # Cover the floor gate on both settings: an untrusted floor must drop out
    # of expected revenue entirely rather than raising the bid ceiling.
    lots = ([{**lot, "floor_trusted": True} for lot in lots]
            + [{**lot, "lot_key": lot["lot_key"] + "#untrusted",
                "floor_trusted": False} for lot in lots])
    # And cover abstention: a lot whose contents we cannot identify must come
    # out UNRATED under every config, however good its arithmetic looks.
    lots = ([{**lot, "contents_known": True} for lot in lots]
            + [{**lot, "lot_key": lot["lot_key"] + "#unrated",
                "contents_known": False} for lot in lots])
    # And cover the handling split: a part lot must pick up the part rate.
    lots = ([{**lot, "item_family": "computer"} for lot in lots]
            + [{**lot, "lot_key": lot["lot_key"] + "#part",
                "item_family": "part"} for lot in lots])
    cases = []
    for overrides in CONFIGS:
        cfg = grade.Config(**overrides)
        cases.append({
            "config": {
                "buyer_premium": cfg.buyer_premium, "sales_tax": cfg.sales_tax,
                "pickup_cost": cfg.pickup_cost,
                "per_unit_handling": cfg.per_unit_handling,
                "part_handling": cfg.part_handling,
                "recovery": cfg.recovery, "dead_rate": cfg.dead_rate,
                "target_roi": cfg.target_roi,
            },
            "expected": {lot["lot_key"]: regrade(lot, cfg) for lot in lots},
        })
    with open(out_path, "w") as f:
        json.dump({"source_snapshot": os.path.basename(snapshot_path),
                   "confidence_gate": grade.CONFIDENCE_GATE,
                   "lots": lots, "cases": cases}, f, indent=1, sort_keys=True)
    print(f"golden: {len(lots)} lots x {len(cases)} configs -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
