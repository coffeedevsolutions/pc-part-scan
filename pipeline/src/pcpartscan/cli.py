"""pcps -- the pipeline command line.

  pcps smoke                 verify MongoDB connectivity, print collection counts
  pcps backfill [--data d]   load the legacy data/ tree into MongoDB (idempotent)
  pcps scan [--full] ...     harvest, fit, grade; writes to the active store
  pcps archive --out dir     dump every collection to jsonl.gz for archiving

The store backend is selected by environment: MONGODB_URI set -> MongoDB,
otherwise flat files under data/ (PCPS_STORE=files|mongo overrides).
The connection string is never printed.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sys
from dataclasses import asdict


def _counts_line(db) -> str:
    names = ["lots", "bid_observations", "sold", "manifests",
             "model_runs", "snapshots", "backtests", "job_runs"]
    return "  ".join(f"{n}={db[n].estimated_document_count()}" for n in names)


def cmd_smoke(_a) -> int:
    from .store import mongo
    db = mongo.get_db()
    db.client.admin.command("ping")
    info = db.client.server_info()
    print(f"connected: MongoDB {info.get('version')} db={db.name}")
    print(f"counts: {_counts_line(db)}")
    return 0


def cmd_backfill(a) -> int:
    from pymongo import InsertOne, UpdateOne
    from pymongo.errors import BulkWriteError

    from . import dataset as fileds
    from .store import mongo

    d = a.data
    db = mongo.get_db()
    run = mongo.run_id()
    mongo.job_start("backfill", run)
    try:
        lots = fileds.read_json(os.path.join(d, "lots.json"), {})
        sold = fileds.read_json(os.path.join(d, "sold.json"), {})
        rows = fileds.read_jsonl(os.path.join(d, "bid_history.jsonl"))
        comps = fileds.read_json(os.path.join(d, "components.json"), {"runs": []})
        models = fileds.read_json(os.path.join(d, "models.json"), {})
        index = fileds.read_json(os.path.join(d, "index.json"), {})

        # --- lots, with last_obs primed from the tail of the bid history ----
        # insert-only ($setOnInsert): a database that live scans have already
        # advanced must never be regressed by the frozen legacy tree -- a $set
        # here would revert sold lots to open and clobber final_price/last_obs
        last: dict[str, dict] = {}
        for r in rows:                      # file is chronological
            if r.get("key"):
                last[r["key"]] = r
        ops = []
        for key, lot in lots.items():
            doc = {"_id": key, **lot}
            h = last.get(key)
            if h:
                doc["last_obs"] = {"at": h.get("observed_at"),
                                   "bid": h.get("current_bid"),
                                   "bid_count": h.get("bid_count")}
            ops.append(UpdateOne({"_id": key}, {"$setOnInsert": doc},
                                 upsert=True))
        n_new = 0
        if ops:
            n_new = len(db.lots.bulk_write(ops, ordered=False).upserted_ids or {})
        print(f"lots: {n_new} inserted, {len(ops) - n_new} already present")

        ops = [UpdateOne({"_id": k}, {"$setOnInsert": {"_id": k, **v}},
                         upsert=True)
               for k, v in sold.items()]
        n_new = 0
        if ops:
            n_new = len(db.sold.bulk_write(ops, ordered=False).upserted_ids or {})
        print(f"sold: {n_new} inserted, {len(ops) - n_new} already present")

        n_man = 0
        for path in glob.glob(os.path.join(d, "manifests", "*.json")):
            m = fileds.read_json(path, None)
            if not m:
                continue
            key = m["key"]
            db.manifests.update_one(
                {"_id": key},
                {"$setOnInsert": {"_id": key, "parsed_by": "regex", **m}},
                upsert=True)
            n_man += 1
        print(f"manifests: {n_man} processed (insert-only)")

        inserted = 0
        batch: list[InsertOne] = []

        def flush():
            nonlocal inserted, batch
            if not batch:
                return
            try:
                res = db.bid_observations.bulk_write(batch, ordered=False)
                inserted += res.inserted_count
            except BulkWriteError as e:   # duplicates on re-run are expected
                inserted += e.details.get("nInserted", 0)
            batch = []

        for r in rows:
            if not r.get("key") or r.get("current_bid") is None:
                continue
            batch.append(InsertOne({
                "key": r["key"], "observed_at": r.get("observed_at"),
                "run_id": r.get("run_id"), "bid": r["current_bid"],
                "bid_count": r.get("bid_count"),
                "time_remaining": r.get("time_remaining"),
                "auction_end_utc": r.get("auction_end_utc"),
                "is_sold": bool(r.get("is_sold")),
                "reserve_not_met": bool(r.get("reserve_not_met")),
                "source": "backfill",
            }))
            if len(batch) >= 5000:
                flush()
        flush()
        print(f"bid_observations: {inserted} inserted ({len(rows)} in file)")

        n_runs = 0
        for entry in comps.get("runs", []):
            doc = {"_id": entry["run_id"], **entry}
            if models.get("run_id") == entry["run_id"]:
                doc["single"] = models.get("single")
                doc["bulk"] = models.get("bulk")
            db.model_runs.update_one({"_id": entry["run_id"]},
                                     {"$setOnInsert": doc}, upsert=True)
            n_runs += 1
        print(f"model_runs: {n_runs} processed (insert-only)")

        # seed the editable component-price table from the CSV (insert-only:
        # workbench edits are never overwritten by a re-run)
        csv_path = os.path.join(d, "component_prices.csv")
        n_prices = n_bad = 0
        if os.path.exists(csv_path):
            import csv as _csv
            with open(csv_path, newline="") as f:
                for row in _csv.DictReader(f):
                    # the CSV is hand-edited; one bad row must not abort
                    try:
                        key = (row.get("key") or "").strip()
                        value = float(row["value_usd"])
                    except (KeyError, TypeError, ValueError):
                        n_bad += 1
                        continue
                    if not key:
                        n_bad += 1
                        continue
                    db.component_prices.update_one(
                        {"_id": key},
                        {"$setOnInsert": {
                            "value_usd": value,
                            "note": (row.get("note") or "").strip(),
                            # reference only -- never overrides a live fit
                            "source": "seed",
                        }},
                        upsert=True)
                    n_prices += 1
        print(f"component_prices: {n_prices} processed (insert-only), "
              f"{n_bad} malformed rows skipped")

        idx = mongo.update_index(index.get("last_run_id", run),
                                 {"last_config": index.get("last_config")})
        print(f"index: {json.dumps(idx['counts'])}")
        mongo.job_finish("backfill", run, counts=idx["counts"])
    except Exception as e:
        mongo.job_finish("backfill", run, status="error", error=str(e))
        raise
    return 0


def cmd_scan(a) -> int:
    from . import grade, harvest, pricing
    from .store import backend as ds

    is_mongo = hasattr(ds, "job_start")
    if os.environ.get("GITHUB_ACTIONS") == "true" and not is_mongo:
        # an empty/rotated MONGODB_URI secret must fail the job loudly --
        # a file-backend scan on an ephemeral runner silently discards data
        raise SystemExit(
            "refusing to scan with the file backend in CI: MONGODB_URI is "
            "unset or empty, so all output would be discarded with the runner")
    run = ds.run_id()
    if is_mongo:
        ds.job_start("scan", run)
    try:
        if not a.no_refresh:
            print("refreshing sold archive...")
            sold = harvest.sweep_sold(max_pages=12 if a.full else 4, run=run)
            print("building observations...")
            detail = 600 if a.full else 120
            if is_mongo:
                # single pass against the full accumulated corpus: the sweep
                # above already upserted its records into the store
                harvest.build_observations_from_dataset(max_detail=detail)
            else:
                harvest.build_observations(sold, max_detail=detail)
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

        single, bulk, ebay, classes = grade.load_models()
        vals = grade.scan(live=live, cfg=cfg, min_units=a.min_units,
                          limit=a.limit, models=(single, bulk, ebay, classes))

        ds.record_components(run, single, bulk, pricing.StaticTable.PATH)
        ds.save_full_models(run, single, bulk)
        ds.write_snapshot(run, {
            "config": asdict(cfg),
            "model_fit": {"single_r2": single.r2, "single_n": single.n_obs,
                          "bulk_k": bulk.k if bulk else None,
                          "bulk_r2": bulk.r2 if bulk else None,
                          "bulk_n": bulk.n_obs if bulk else 0},
            "screened": len(vals),
            "confidence_gate": grade.CONFIDENCE_GATE,
            "class_prices": classes.to_dict(
                bulk.k if bulk and bulk.trusted else None),
            "ebay": ebay.to_json(),
            "lots": [asdict(v) for v in vals],
        })
        idx = ds.update_index(run, {"last_config": asdict(cfg)})

        ds.save_grades(vals, run)

        print("\n" + grade.report(vals, top=a.top))
        print(f"\nrun {run}")
        print(f"dataset: {json.dumps(idx['counts'])}")
        if is_mongo:
            ds.job_finish("scan", run, counts=idx["counts"])
    except Exception as e:
        if is_mongo:
            ds.job_finish("scan", run, status="error", error=str(e))
        raise
    return 0


def cmd_burst(a) -> int:
    """Tight-loop bid sampling for lots closing soon.

    The detail endpoint carries no bid fields, so a burst polls per SELLER:
    one /search/list scoped to accountIds=[acct] returns the current bid for
    every lot that seller has live, covering all of their closing lots in a
    single request. Change-only writes keep the volume proportional to what
    actually moved, and the upserts refresh auction_end_utc so sniping-driven
    extensions are captured.
    """
    import datetime as dt
    import time as _time

    from . import api as gd
    from . import harvest
    from .store import mongo

    run = mongo.run_id()
    mongo.job_start("burst", run)
    deadline = _time.monotonic() + a.window * 60
    cycles = observations = 0
    try:
        while True:
            cycle_start = _time.monotonic()
            now = dt.datetime.now(dt.timezone.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            cutoff = (now + dt.timedelta(minutes=a.horizon)
                      ).strftime("%Y-%m-%dT%H:%M:%SZ")
            targets = mongo.open_lots_closing_before(cutoff, now_iso)
            if not targets:
                print("no open lots closing inside the horizon; done")
                break
            accounts = sorted({t["account_id"] for t in targets
                               if t.get("account_id")})[:a.max_accounts]
            recs: dict[str, dict] = {}
            for acct in accounts:
                page, fetched = 1, 0
                while True:
                    try:
                        batch, total = gd.search(account_ids=[acct], text="*",
                                                 rows=100, page=page)
                    except Exception as e:
                        print(f"  account {acct} page {page}: {e}")
                        break
                    for r in batch:
                        recs[f"{r['accountId']}-{r['assetId']}"] = r
                    fetched += len(batch)
                    _time.sleep(harvest.POLITE_DELAY)
                    if not batch or fetched >= total or page >= 3:
                        break
                    page += 1
            observed = mongo.utcnow()
            # keep only lots actually closing inside the horizon: per-seller
            # search returns the seller's whole inventory, and a burst should
            # not accumulate their far-future non-computer listings
            rec_list = [r for r in recs.values()
                        if "" < (r.get("assetAuctionEndDateUtc") or "") <= cutoff]
            mongo.upsert_lots(rec_list, observed, sold=False)
            n = mongo.record_bids(rec_list, observed, run, source="burst")
            observations += n
            cycles += 1
            print(f"cycle {cycles}: {len(targets)} closing lots across "
                  f"{len(accounts)} sellers, {len(recs)} records, "
                  f"{n} changed observations", flush=True)
            if _time.monotonic() + a.interval > deadline:
                break
            _time.sleep(max(0.0, a.interval - (_time.monotonic() - cycle_start)))
        mongo.job_finish("burst", run, counts={
            "cycles": cycles, "observations": observations})
        print(f"burst done: {cycles} cycles, {observations} observations")
    except Exception as e:
        mongo.job_finish("burst", run, status="error", error=str(e),
                         counts={"cycles": cycles, "observations": observations})
        raise
    return 0


def cmd_triage_queue(a) -> int:
    from . import routine
    print(json.dumps(routine.triage_queue(a.limit), indent=1))
    return 0


def cmd_triage_fetch(a) -> int:
    from . import routine
    for p in routine.triage_fetch(a.key, a.out):
        print(p)
    return 0


def cmd_save_manifest(a) -> int:
    from . import routine
    with open(a.file) as f:
        payload = json.load(f)
    result = routine.save_llm_manifest(
        a.key, payload["machines"], payload.get("source_files", []),
        allow_mismatch=a.allow_mismatch)
    print(json.dumps(result))
    return 0


def cmd_resolve(a) -> int:
    """Ask sellers what our tracked lots actually sold for."""
    from . import harvest
    from .store import backend as ds

    if not hasattr(ds, "open_lots_past_end"):
        raise SystemExit("resolve needs the mongo store; set MONGODB_URI")
    is_mongo = True
    run = ds.run_id()
    ds.job_start("resolve", run)
    try:
        res = harvest.resolve_closed(max_sellers=a.max_sellers, run=run)
        if res["outcomes"]:
            print()
            print(f"{'lot':<14}{'hammer':>10}  title")
            for o in sorted(res["outcomes"],
                            key=lambda o: -o["hammer"])[:a.top]:
                print(f"{o['key']:<14}{o['hammer']:>10,.0f}  {o['title'][:56]}")
        if is_mongo:
            ds.job_finish("resolve", run, counts={"resolved": res["resolved"],
                                                  "checked": res["checked"]})
    except Exception as e:
        if is_mongo:
            ds.job_finish("resolve", run, status="error", error=str(e))
        raise
    print(f"\nrun {run}")
    return 0


def cmd_backtest(a) -> int:
    """Replay the grader over closed lots and report how it did."""
    from . import backtest, grade
    from .store import backend as ds

    if not hasattr(ds, "write_backtest"):
        raise SystemExit("backtest needs the mongo store; set MONGODB_URI")
    run = ds.run_id()
    cfg = grade.Config(target_roi=a.target_roi, recovery=a.recovery)
    sold, mans = ds.sold_lots(), ds.all_manifests()
    print(f"replaying {len(sold):,} closed lots over {a.folds} folds...")

    def progress(f, n, k):
        print(f"  fold {f}/{n}: {k:,} predictions", flush=True)

    rep = backtest.run(sold, mans, cfg=cfg, folds=a.folds, progress=progress)
    print()
    print(backtest.report_text(rep, top=a.top))
    ds.write_backtest(run, rep)
    print(f"\nrun {run}")
    return 0


def cmd_digest(a) -> int:
    from . import routine
    print(json.dumps(routine.digest(), indent=1, default=str))
    return 0


def cmd_health(a) -> int:
    from . import routine
    print(json.dumps(routine.health(), indent=1, default=str))
    return 0


def cmd_archive(a) -> int:
    from .store import mongo
    db = mongo.get_db()
    os.makedirs(a.out, exist_ok=True)
    names = ["lots", "bid_observations", "sold", "manifests",
             "model_runs", "snapshots", "backtests", "meta", "job_runs"]
    for name in names:
        path = os.path.join(a.out, f"{name}.jsonl.gz")
        n = 0
        with gzip.open(path, "wt") as f:
            for doc in db[name].find({}):
                f.write(json.dumps(doc, default=str, sort_keys=True) + "\n")
                n += 1
        print(f"{name}: {n} docs -> {path} "
              f"({os.path.getsize(path) / 1e6:.1f} MB)")
    return 0


def cmd_ebay_watch(a) -> int:
    """Poll eBay for the CPUs we price, and record what has left since.

    This is the collector for the recovery measurement (see ebaypanel.py).
    Every run does two things: write down every live listing for each CPU,
    and notice which listings that were up last time are not up now. The
    second is the valuable one -- a fixed-price listing that vanishes has
    almost certainly sold, and that is the only route to a realised eBay
    price without the Marketplace Insights API we are not getting.

    It is deliberately cheap and repeatable: one search per CPU, at most one
    confirmation call per disappearance, and nothing is destructive, so a
    re-run after a failure simply re-observes.
    """
    from . import ebaypanel, harvest, pricing
    from .store import backend as ds

    if not hasattr(ds, "upsert_ebay_listings"):
        raise SystemExit("ebay-watch needs the mongo store; set MONGODB_URI")

    ebay = pricing.EbayAdapter()
    if not ebay.enabled:
        raise SystemExit(
            "no eBay credentials: set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET")

    # The CPUs worth tracking are the ones we actually price lots with, most
    # common first: a CPU with two GovDeals comps can never clear
    # ebaypanel.MIN_GOVDEALS_SALES on the other side of the ratio, so
    # spending a query on it buys nothing.
    obs = harvest.load_observations()
    counts: dict[str, int] = {}
    for one in obs["singles"]:
        cpu = (one.get("machine") or {}).get("cpu")
        if cpu:
            counts[cpu] = counts.get(cpu, 0) + 1
    cpus = [c for c, n in sorted(counts.items(), key=lambda kv: -kv[1])
            if n >= ebaypanel.MIN_GOVDEALS_SALES][:a.max_cpus]
    if not cpus:
        print("no CPU has enough GovDeals comps to pair against yet")
        return 0

    run = ds.run_id()
    ds.job_start("ebay-watch", run)
    totals = {"queries": 0, "failed": 0, "listings": 0, "new": 0,
              "gone": 0, "confirmed": 0}
    try:
        for cpu in cpus:
            qk = ebaypanel.query_key(cpu, None)
            items = ebay.search(cpu)
            totals["queries"] += 1
            if items is None:
                # Never diff on a failed query: with no result set, every
                # listing under it looks like it disappeared.
                totals["failed"] += 1
                ds.record_ebay_poll(qk, cpu, None, 0, ok=False)
                continue
            now = ds.utcnow()
            rows = [r for r in (ebaypanel.normalize(it, cpu, None, now)
                                for it in items) if r]
            ds.record_ebay_poll(qk, cpu, None, len(rows), ok=True)
            res = ds.upsert_ebay_listings(rows, qk)
            totals["listings"] += res["seen"]
            totals["new"] += res["new"]

            seen_ids = {r["_id"] for r in rows}
            marks = ebaypanel.vanished(ds.live_ebay_listings(qk), seen_ids, now)
            # One confirmation call per disappearance turns "fell out of the
            # search results" into "definitely ended". Both are stored; the
            # estimator decides which population to trust.
            for m in marks[:a.max_confirm]:
                still = ebay.still_listed(m["_id"])
                if still is True:
                    m["skip"] = True
                elif still is False:
                    m["gone_reason"] = "confirmed_ended"
                    totals["confirmed"] += 1
            marks = [m for m in marks if not m.get("skip")]
            totals["gone"] += ds.mark_ebay_gone(marks)

        stats = ds.ebay_panel_stats()
        print(f"polled {totals['queries']} CPUs "
              f"({totals['failed']} failed), {totals['listings']} listings "
              f"({totals['new']} new), {totals['gone']} left "
              f"({totals['confirmed']} confirmed ended)")
        print(f"panel: {stats['listings']} listings, {stats['live']} live, "
              f"{stats['ended']} ended, over {stats['polls']} polls")
        ds.job_finish("ebay-watch", run, counts=totals)
    except Exception as e:
        ds.job_finish("ebay-watch", run, status="error", error=str(e))
        raise
    print(f"\nrun {run}")
    return 0


def cmd_recovery(a) -> int:
    """What we actually get for a machine, as a multiple of what it costs.

    Reports two numbers deliberately kept apart. The ask figure comes from
    live listings and is available immediately, but reads high: nothing
    sells above its own ask, and the live pool is a survivor sample that
    keeps re-counting whatever failed to sell. The measured figure comes
    from listings that have left the panel and is the one to trust -- it
    needs the collector to have been running long enough for some to sell.
    """
    from . import ebaypanel, harvest
    from .store import backend as ds

    if not hasattr(ds, "ended_ebay_listings"):
        raise SystemExit("recovery needs the mongo store; set MONGODB_URI")

    obs = harvest.load_observations()
    singles = obs["singles"]
    ended = ds.ended_ebay_listings()
    live = ds.live_ebay_listings()

    bound = ebaypanel.ask_bound(live, singles, shipping=a.shipping)
    strict = ebaypanel.recovery(
        ebaypanel.sales(ended, confirmed_only=True), singles, shipping=a.shipping)
    loose = ebaypanel.recovery(
        ebaypanel.sales(ended), singles, shipping=a.shipping)
    with_offers = ebaypanel.recovery(
        ebaypanel.sales(ended, include_best_offer=True), singles,
        shipping=a.shipping)

    def line(label, r, extra=""):
        val = r.get("recovery") if "recovery" in r else r.get("upper_bound")
        n = r.get("n_sales", r.get("n_listings", 0))
        if val is None:
            print(f"  {label:<34} -- {r['n_cpus']}/{r['min_cpus']} CPUs "
                  f"paired, {n} listings{extra}")
        else:
            print(f"  {label:<34} {val:>6.2f}x  "
                  f"({r['n_cpus']} CPUs, {n} listings){extra}")

    stats = ds.ebay_panel_stats()
    print(f"panel: {stats['listings']} listings, {stats['live']} live, "
          f"{stats['ended']} ended ({stats['confirmed']} confirmed), "
          f"{stats['polls']} polls")
    print(f"assumptions: {ebaypanel.FEE_RATE:.1%} eBay fee, "
          f"${ebaypanel.FEE_FIXED:.2f}/order, ${a.shipping:.2f} shipping\n")
    line("from live asks (reads high)", bound)
    line("measured (confirmed ended)", strict)
    line("measured (all departures)", loose)
    line("measured (incl. best-offer at ask)", with_offers, "  -- biased high")

    best = strict if strict["recovery"] is not None else loose
    if best.get("median_days_to_sell") is not None:
        print(f"\n  median days to sell: {best['median_days_to_sell']}")
    if best["per_cpu"]:
        print(f"\n{'cpu':<14}{'ratio':>7}{'ebay net':>10}{'govdeals':>10}"
              f"{'n':>5}{'days':>7}")
        for c in sorted(best["per_cpu"], key=lambda c: -c["ratio"])[:a.top]:
            days = c["median_days_listed"]
            print(f"{c['cpu']:<14}{c['ratio']:>6.2f}x{c['ebay_net_median']:>10,.0f}"
                  f"{c['govdeals_median']:>10,.0f}{c['n_ebay']:>5}"
                  f"{(f'{days:.0f}' if days is not None else '--'):>7}")

    if best["recovery"] is None:
        print("\nNot enough departures yet to measure recovery. The upper "
              "bound above is what asks alone can say; run `pcps ebay-watch` "
              "daily and this fills in as listings sell.")
    else:
        run = ds.run_id()
        ds.write_recovery(run, {"bound": bound, "strict": strict,
                                "loose": loose, "with_offers": with_offers,
                                "shipping": a.shipping})
        print(f"\nrun {run}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pcps")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("smoke", help="verify MongoDB connectivity")

    p = sub.add_parser("backfill", help="load the data/ tree into MongoDB")
    p.add_argument("--data", default="data")

    p = sub.add_parser("scan", help="harvest, fit and grade")
    p.add_argument("--no-refresh", action="store_true")
    p.add_argument("--full", action="store_true")
    p.add_argument("--min-units", type=int, default=5)
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--target-roi", type=float, default=0.60)
    p.add_argument("--recovery", type=float, default=0.55)
    p.add_argument("--buyer-premium", type=float, default=0.0)
    p.add_argument("--states", default="")

    p = sub.add_parser("burst", help="tight-loop bid sampling near auction close")
    p.add_argument("--window", type=int, default=20,
                   help="minutes to keep sampling (default 20)")
    p.add_argument("--horizon", type=int, default=100,
                   help="target lots closing within this many minutes")
    p.add_argument("--interval", type=int, default=150,
                   help="seconds between cycles (default 150)")
    p.add_argument("--max-accounts", type=int, default=120,
                   help="cap on sellers polled per cycle")

    p = sub.add_parser("archive", help="dump collections to jsonl.gz")
    p.add_argument("--out", default="dump")

    p = sub.add_parser("triage-queue",
                       help="bulk lots whose spec sheet defeated the parser (JSON)")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("triage-fetch", help="download a lot's PDF attachments")
    p.add_argument("--key", required=True)
    p.add_argument("--out", default="attachments")

    p = sub.add_parser("save-manifest",
                       help="store a model-extracted manifest (validated)")
    p.add_argument("--key", required=True)
    p.add_argument("--file", required=True,
                   help='JSON: {"machines": [...], "source_files": [...]}')
    p.add_argument("--allow-mismatch", action="store_true")

    p = sub.add_parser("resolve",
                       help="find out what tracked lots actually sold for")
    p.add_argument("--max-sellers", type=int, default=40)
    p.add_argument("--top", type=int, default=15)

    p = sub.add_parser("backtest",
                       help="replay the grader over closed lots")
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--top", type=int, default=8,
                   help="rows per breakdown table")
    p.add_argument("--target-roi", type=float, default=0.60)
    p.add_argument("--recovery", type=float, default=0.55)

    p = sub.add_parser("ebay-watch",
                       help="poll eBay listings and record what has sold")
    p.add_argument("--max-cpus", type=int, default=60,
                   help="how many CPUs to poll, most-comped first")
    p.add_argument("--max-confirm", type=int, default=25,
                   help="confirmation calls per query for vanished listings")

    p = sub.add_parser("recovery",
                       help="what we get for a machine, measured on eBay")
    p.add_argument("--shipping", type=float, default=0.0,
                   help="what you pay to ship one unit, if you eat it")
    p.add_argument("--top", type=int, default=15)

    sub.add_parser("digest", help="daily digest inputs (JSON)")
    sub.add_parser("health", help="weekly health-review inputs (JSON)")

    a = ap.parse_args(argv)
    return {"smoke": cmd_smoke, "backfill": cmd_backfill, "scan": cmd_scan,
            "backtest": cmd_backtest, "resolve": cmd_resolve,
            "burst": cmd_burst, "archive": cmd_archive,
            "triage-queue": cmd_triage_queue, "triage-fetch": cmd_triage_fetch,
            "save-manifest": cmd_save_manifest,
            "ebay-watch": cmd_ebay_watch, "recovery": cmd_recovery,
            "digest": cmd_digest, "health": cmd_health}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
