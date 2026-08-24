#!/usr/bin/env python3
"""Query the historical dataset.

  python analyze.py bids 7484-44150       bid curve for one lot
  python analyze.py cpu i7-11700          fitted value of a CPU across runs
  python analyze.py sold optiplex         realized prices for matching sold lots
  python analyze.py sellers               sold volume and median price by seller
  python analyze.py summary               dataset overview
"""

from __future__ import annotations

import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from pcpartscan import dataset as ds
from pcpartscan import specs


def summary():
    idx = ds.read_json(ds.INDEX, {})
    print("dataset", f"v{idx.get('schema_version')}", "last run", idx.get("last_run_id"))
    for k, v in (idx.get("counts") or {}).items():
        print(f"  {k:<20} {v:,}")
    comp = ds.read_json(ds.COMPONENTS, {})
    latest = comp.get("latest") or {}
    if latest:
        print(f"\nlatest fit: n={latest.get('n_observations')} "
              f"R2={latest.get('r2')}  bulk k={latest.get('bulk_discount_k')} "
              f"(n={latest.get('bulk_n')}, R2={latest.get('bulk_r2')})")
        print(f"  fit runs recorded: {len(comp.get('runs', []))}")


def bids(key: str):
    rows = sorted(ds.bid_history_for(key), key=lambda r: r["observed_at"])
    if not rows:
        print(f"no bid history for {key}")
        return
    lot = ds.read_json(ds.LOTS, {}).get(key, {})
    print(f"{key}  {lot.get('title','')}")
    print(f"closes {lot.get('auction_end_utc')}  status={lot.get('status')}\n")
    prev = None
    for r in rows:
        delta = "" if prev is None else f"  {r['current_bid']-prev:+,.0f}"
        print(f"  {r['observed_at']}  ${r['current_bid']:>10,.2f}{delta}"
              f"   remaining={r.get('time_remaining')}")
        prev = r["current_bid"]
    if len(rows) > 1:
        print(f"\n  {rows[0]['current_bid']:,.0f} -> {rows[-1]['current_bid']:,.0f} "
              f"over {len(rows)} observations")


def cpu(name: str):
    series = ds.component_price_series(name)
    if not series:
        print(f"no fitted history for {name}")
        comp = ds.read_json(ds.COMPONENTS, {}).get("latest", {})
        known = sorted(comp.get("cpu_base_value_usd", {}))
        print("known CPUs:", ", ".join(known) if known else "(none)")
        return
    print(f"{name}: fitted base value across {len(series)} run(s)")
    for s in series:
        print(f"  {s['fitted_at']}  ${s['value_usd']:,.2f}")


def sold(pattern: str):
    rx = re.compile(pattern, re.I)
    recs = [v for v in ds.read_json(ds.SOLD, {}).values()
            if v.get("title") and rx.search(v["title"]) and v.get("final_price")]
    if not recs:
        print("no matches")
        return
    per_unit = []
    for v in recs:
        n = specs.parse_unit_count(v["title"])
        if n:
            per_unit.append(v["final_price"] / n)
    prices = sorted(v["final_price"] for v in recs)
    print(f"{len(recs)} sold lots matching /{pattern}/")
    print(f"  lot price   median ${st.median(prices):,.0f}   "
          f"range ${prices[0]:,.0f}-${prices[-1]:,.0f}")
    if per_unit:
        pu = sorted(per_unit)
        print(f"  per unit    median ${st.median(pu):,.2f}   "
              f"p25 ${pu[len(pu)//4]:,.2f}  p75 ${pu[3*len(pu)//4]:,.2f}  n={len(pu)}")
    print("\n  highest:")
    for v in sorted(recs, key=lambda z: -z["final_price"])[:8]:
        n = specs.parse_unit_count(v["title"])
        # an unparseable count is shown as such -- never silently treated as 1,
        # which would print a 200-machine pallet as a $17,400 single machine
        unit = f"({n:>4} u, ${v['final_price']/n:>7,.2f}/u)" if n else "( ?  u,        -   )"
        print(f"    ${v['final_price']:>9,.0f}  {unit}  {v['title'][:50]}")


def sellers():
    recs = [v for v in ds.read_json(ds.SOLD, {}).values() if v.get("final_price")]
    by: dict[str, list[float]] = {}
    for v in recs:
        by.setdefault(v.get("seller") or "?", []).append(v["final_price"])
    rows = sorted(by.items(), key=lambda kv: -len(kv[1]))[:20]
    print(f"{'seller':<44}{'lots':>6}{'median':>11}{'total':>13}")
    print("-" * 74)
    for name, ps in rows:
        print(f"{name[:43]:<44}{len(ps):>6}{st.median(ps):>11,.0f}{sum(ps):>13,.0f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd, arg = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    fns = {"summary": lambda: summary(), "sellers": lambda: sellers(),
           "bids": lambda: bids(arg), "cpu": lambda: cpu(arg),
           "sold": lambda: sold(arg or ".")}
    if cmd not in fns:
        print(__doc__); sys.exit(1)
    if cmd in ("bids", "cpu") and not arg:
        print(f"{cmd} needs an argument"); sys.exit(1)
    fns[cmd]()
