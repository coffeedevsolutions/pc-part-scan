"""MongoDB backend. Mirrors the write API of pcpartscan.dataset.

Collections (database `pcps` unless PCPS_DB overrides):

  lots              one doc per lot, _id = "<accountId>-<assetId>". Carries a
                    denormalised `last_obs` {at, bid, bid_count} so change
                    detection for bid observations costs one indexed read.
  bid_observations  insert-only time series. A new doc is written only when
                    the bid or bid count changed, plus one heartbeat per lot
                    per HEARTBEAT_HOURS so gaps are distinguishable from
                    "no scan ran".
  sold              closed lots with realized hammer price.
  manifests         parsed spec-sheet machine mixes, _id = lot key.
  model_runs        one doc per fit run: summary prices + full coefficients.
  backtests         one doc per backtest: how the grader did against lots
                    that have already closed, out of sample.
  snapshots         graded output of each scan run, _id = run id.
  meta              _id="index": counts, last run, last config.
  job_runs          one doc per scheduled job execution.
  ebay_listings     every eBay listing we have ever seen, _id = item id.
                    A row is live until `gone_at` is set; the set of rows
                    that went from live to gone IS the sold-comp feed,
                    since Browse will not sell us one (see ebaypanel.py).
  ebay_polls        one doc per (query, poll). Records that a query was
                    actually asked and answered, so a listing missing
                    from a FAILED poll is never mistaken for a sale.

All writes are idempotent upserts except bid_observations, which is guarded
by a unique (key, run_id, observed_at) index so re-running a backfill or a
retried job cannot duplicate history.
"""

from __future__ import annotations

import datetime as dt
import os

from pymongo import InsertOne, MongoClient, UpdateOne
from pymongo.errors import BulkWriteError

from ..dataset import (  # noqa: F401
    SCHEMA_VERSION, lot_key, model_summary, normalize_lot, project_lot,
    run_id, utcnow,
)

HEARTBEAT_HOURS = 24

_client: MongoClient | None = None
_indexed = False


def _db_name(client) -> str:
    """Which database to use: PCPS_DB, else the one named in the URI, else pcps.

    The URI leg matters. `MONGODB_URI=mongodb://host/analytics` names a
    database and every other Mongo tool honours it, so ignoring it in favour
    of a hardcoded default means a connection string that reads correctly
    silently writes somewhere else -- which is a bad afternoon to debug when
    the collections it wrote to were empty rather than absent.
    """
    explicit = os.environ.get("PCPS_DB")
    if explicit:
        return explicit
    try:
        from_uri = client.get_default_database(default=None)
    except Exception:
        from_uri = None
    return from_uri.name if from_uri is not None else "pcps"


def get_db():
    global _client, _indexed
    if _client is None:
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise SystemExit("MONGODB_URI is not set; cannot use the mongo store")
        _client = MongoClient(uri, appname="pcps-pipeline", tz_aware=False,
                              serverSelectionTimeoutMS=20000)
    db = _client[_db_name(_client)]
    if not _indexed:
        ensure_indexes(db)
        _indexed = True
    return db


def _migrate_component_sources(db) -> None:
    """Give pre-existing component_prices docs a provenance.

    Pins written before provenance existed carry no `source`, and the
    seeded-from-CSV rows are indistinguishable from real pins except by
    their note. Filtering on source alone would silently orphan every pin
    a user had already made, so classify the legacy docs once, by note,
    and default anything else to a real pin.
    """
    coll = db.component_prices
    if coll.count_documents({"source": {"$exists": False}}, limit=1) == 0:
        return
    coll.update_many(
        {"source": {"$exists": False},
         "note": {"$regex": "^seeded from", "$options": "i"}},
        {"$set": {"source": "seed"}})
    coll.update_many({"source": {"$exists": False}},
                     {"$set": {"source": "user"}})


def ensure_indexes(db) -> None:
    db.lots.create_index([("status", 1), ("auction_end_utc", 1)])
    db.lots.create_index([("location.state", 1)])
    db.bid_observations.create_index(
        [("key", 1), ("run_id", 1), ("observed_at", 1)], unique=True)
    db.bid_observations.create_index([("key", 1), ("observed_at", 1)])
    db.sold.create_index([("auction_end_utc", 1)])
    db.job_runs.create_index([("job", 1), ("started_at", -1)])
    db.ebay_listings.create_index([("query_key", 1), ("gone_at", 1)])
    db.ebay_listings.create_index([("cpu", 1), ("gone_at", 1)])
    db.ebay_polls.create_index([("query_key", 1), ("polled_at", -1)])
    _migrate_component_sources(db)


def _parse_ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------- lots

def upsert_lots(records: list[dict], observed_at: str, sold: bool) -> dict:
    """Merge API records into the lots collection. Returns {new, updated}."""
    db = get_db()
    recs = [r for r in records if r.get("accountId") and r.get("assetId")]
    if not recs:
        return {"new": 0, "updated": 0, "total": db.lots.estimated_document_count()}

    keys = [lot_key(r) for r in recs]
    finished = {d["_id"]: d["status"] for d in db.lots.find(
        {"_id": {"$in": keys}, "status": {"$in": ["sold", "closed"]}},
        {"_id": 1, "status": 1})}

    ops = []
    for rec in recs:
        k = lot_key(rec)
        norm = normalize_lot(rec, observed_at, sold)
        norm.pop("first_seen", None)
        if k in finished and not sold:
            # A finished auction never reopens: a later live sweep that
            # still lists the lot must not put it back on the board. Keep
            # the status it already had, though -- forcing "sold" onto a
            # lot marked "closed" invents a sale we never saw, and the lot
            # page then renders "sold --" with no price.
            norm["status"] = finished[k]
            norm.pop("final_price", None)
        ops.append(UpdateOne(
            {"_id": k},
            {"$set": norm, "$setOnInsert": {"first_seen": observed_at}},
            upsert=True))
    res = db.lots.bulk_write(ops, ordered=False)
    new = len(res.upserted_ids or {})
    return {"new": new, "updated": res.matched_count,
            "total": db.lots.estimated_document_count()}


def record_bids(records: list[dict], observed_at: str, run: str,
                source: str = "scan") -> int:
    """Insert one observation per lot whose bid state changed.

    A lot whose bid and bid count are unchanged since the previous
    observation is skipped, unless that observation is older than
    HEARTBEAT_HOURS -- the flat stretch in between is implied by the
    neighbouring points, which is what keeps the free-tier cluster small.
    """
    db = get_db()
    recs = [r for r in records
            if r.get("currentBid") is not None and r.get("accountId") and r.get("assetId")]
    if not recs:
        return 0

    keys = [lot_key(r) for r in recs]
    last = {d["_id"]: d.get("last_obs") for d in db.lots.find(
        {"_id": {"$in": keys}}, {"last_obs": 1})}
    now = _parse_ts(observed_at)

    inserts, marks = [], []
    for rec in recs:
        k = lot_key(rec)
        bid = float(rec["currentBid"])
        count = rec.get("bidCount")
        is_sold = bool(rec.get("isSoldAuction"))
        prev = last.get(k)
        if prev and prev.get("bid") == bid and prev.get("bid_count") == count:
            if is_sold:
                continue      # a closed lot's bid never changes; no heartbeat
            prev_at = _parse_ts(prev.get("at"))
            if prev_at and now and (now - prev_at) < dt.timedelta(hours=HEARTBEAT_HOURS):
                continue
        inserts.append(InsertOne({
            "key": k, "observed_at": observed_at, "run_id": run,
            "bid": bid, "bid_count": count,
            "time_remaining": rec.get("timeRemaining"),
            "auction_end_utc": rec.get("assetAuctionEndDateUtc"),
            "is_sold": is_sold,
            "reserve_not_met": bool(rec.get("isReserveNotMet")),
            "source": source,
        }))
        marks.append(UpdateOne({"_id": k}, {"$set": {
            "last_obs": {"at": observed_at, "bid": bid, "bid_count": count}}}))

    written = 0
    if inserts:
        try:
            res = db.bid_observations.bulk_write(inserts, ordered=False)
            written = res.inserted_count
        except BulkWriteError as e:
            # duplicates (same key/run/timestamp) are re-runs, not errors
            written = e.details.get("nInserted", 0)
    if marks:
        db.lots.bulk_write(marks, ordered=False)
    return written


def upsert_sold(records: list[dict], observed_at: str) -> dict:
    db = get_db()
    ops = []
    for rec in records:
        if not rec.get("isSoldAuction") or not rec.get("currentBid"):
            continue
        if not (rec.get("accountId") and rec.get("assetId")):
            continue
        doc = {**normalize_lot(rec, observed_at, sold=True),
               "final_price": float(rec["currentBid"])}
        doc.pop("first_seen", None)
        ops.append(UpdateOne({"_id": doc["key"]},
                             {"$set": doc,
                              "$setOnInsert": {"first_seen": observed_at}},
                             upsert=True))
    if not ops:
        return {"added": 0, "total": db.sold.estimated_document_count()}
    res = db.sold.bulk_write(ops, ordered=False)
    return {"added": len(res.upserted_ids or {}),
            "total": db.sold.estimated_document_count()}


def sold_lots() -> dict[str, dict]:
    """All sold lots keyed by lot key -- the shape harvest rebuilds from."""
    return {d["_id"]: d for d in get_db().sold.find({})}


def open_lots_closing_before(cutoff_iso: str, now_iso: str) -> list[dict]:
    """Open lots whose auction ends inside (now, cutoff] -- burst targets."""
    return list(get_db().lots.find(
        {"status": "open",
         "auction_end_utc": {"$gt": now_iso, "$lte": cutoff_iso}},
        {"account_id": 1, "auction_end_utc": 1}))


def save_grades(vals: list, run: str) -> int:
    """Denormalise the latest grade onto each lot for cheap board queries."""
    ops = [UpdateOne({"_id": v.lot_key}, {"$set": {"latest_grade": {
        "run_id": run, "grade": v.grade, "max_bid": round(v.max_bid, 2),
        "headroom": round(v.headroom, 2), "confidence": v.confidence,
    }}}) for v in vals]
    if not ops:
        return 0
    return get_db().lots.bulk_write(ops, ordered=False).matched_count


def open_lots_past_end(now_iso: str) -> list[dict]:
    """Lots still marked open whose auction end time has already passed.

    These are the ones worth asking the seller about: we tracked them, we
    published a max bid for them, and nothing has told us how they ended.
    """
    return list(get_db().lots.find(
        {"status": "open", "auction_end_utc": {"$ne": None, "$lt": now_iso}},
        {"key": 1, "account_id": 1, "asset_id": 1, "title": 1,
         "auction_end_utc": 1}))


def mark_closed(keys: list[str], observed_at: str) -> int:
    """Stop offering a lot as biddable once its auction has ended.

    Separate from `sold`: this only says the auction is over. A lot whose
    hammer price we never learned is still not something to bid on.
    """
    if not keys:
        return 0
    res = get_db().lots.update_many(
        {"_id": {"$in": keys}, "status": "open"},
        {"$set": {"status": "closed", "closed_seen_at": observed_at}})
    return res.modified_count


def open_lots_raw() -> dict[str, dict]:
    """Open lots mapped back onto the raw API shape the grader expects.

    An end time in the past excludes a lot even while it is still marked
    open: `pcps resolve` flips the status, but it runs on its own schedule
    and until then a finished auction must not be offered as biddable.
    """
    out = {}
    now = utcnow()
    for lot in get_db().lots.find(
            {"status": "open",
             "$or": [{"auction_end_utc": None},
                     {"auction_end_utc": {"$gte": now}}]}):
        last = lot.get("last_obs") or {}
        out[lot["_id"]] = project_lot(lot, last.get("bid"),
                                      last.get("bid_count"))
    return out


# ---------------------------------------------------------------- manifests

def save_manifest(key: str, machines: list[dict], source_files: list[str],
                  parsed_by: str = "regex") -> None:
    get_db().manifests.replace_one({"_id": key}, {
        "_id": key, "key": key,
        "parsed_at": utcnow(),
        "source_files": source_files,
        "parsed_by": parsed_by,
        "unit_total": sum(m.get("qty", 1) for m in machines),
        "machines": machines,
    }, upsert=True)


def load_manifest(key: str) -> dict | None:
    return get_db().manifests.find_one({"_id": key})


def all_manifests() -> dict[str, dict]:
    return {d["key"]: d for d in get_db().manifests.find({})}


# -------------------------------------------------------------- model runs

def record_components(run: str, single_model, bulk_model,
                      table_path: str | None) -> None:
    """One doc per fit run: chartable summary plus the full coefficients."""
    get_db().model_runs.replace_one({"_id": run}, {
        "_id": run,
        "schema_version": SCHEMA_VERSION,
        **model_summary(run, single_model, bulk_model, table_path),
        "single": single_model.to_json(),
        "bulk": bulk_model.to_json() if bulk_model else None,
    }, upsert=True)


def save_full_models(run: str, single_model, bulk_model) -> None:
    """No-op: record_components already stores the full coefficients."""


def component_overrides() -> dict[str, float]:
    """Prices a human deliberately pinned, keyed by CPU.

    Only source="user" docs qualify. Rows seeded from the legacy CSV are
    kept for reference but must never override a fit: they were themselves
    generated from an older fit, so honouring them froze the model at its
    past self. The special key "_ram_per_8gb" carries the RAM adder.
    """
    return {d["_id"]: float(d["value_usd"])
            for d in get_db().component_prices.find({"source": {"$ne": "seed"}})
            if d.get("value_usd") is not None}


def component_price_series(cpu: str) -> list[dict]:
    return [{"run_id": d["run_id"], "fitted_at": d["fitted_at"],
             "value_usd": d["cpu_base_value_usd"][cpu]}
            for d in get_db().model_runs.find(
                {f"cpu_base_value_usd.{cpu}": {"$exists": True}}).sort("run_id", 1)]


# ---------------------------------------------------------------- snapshots

def write_snapshot(run: str, payload: dict) -> str:
    get_db().snapshots.replace_one({"_id": run}, {
        "_id": run, "run_id": run, "generated_at": utcnow(), **payload,
    }, upsert=True)
    return f"snapshots/{run}"


def write_backtest(run: str, report: dict) -> str:
    """Persist one backtest run.

    The per-lot predictions are kept out of the document: 7,000 of them is
    megabytes, and on an M0 free tier the summary is what earns its space.
    They stay available by re-running, which takes seconds.
    """
    doc = {k: v for k, v in report.items() if k != "predictions"}
    get_db().backtests.replace_one({"_id": run}, {
        "_id": run, "run_id": run, "generated_at": utcnow(), **doc,
    }, upsert=True)
    return f"backtests/{run}"


def latest_backtest() -> dict | None:
    return get_db().backtests.find_one(sort=[("_id", -1)])


def update_index(run: str, extra: dict | None = None) -> dict:
    db = get_db()
    idx = {
        "_id": "index",
        "schema_version": SCHEMA_VERSION,
        "updated_at": utcnow(),
        "last_run_id": run,
        "counts": {
            "lots": db.lots.estimated_document_count(),
            "open_lots": db.lots.count_documents({"status": "open"}),
            "sold_lots": db.sold.estimated_document_count(),
            "bid_observations": db.bid_observations.estimated_document_count(),
            "manifests": db.manifests.estimated_document_count(),
            "snapshots": db.snapshots.estimated_document_count(),
            "model_runs": db.model_runs.estimated_document_count(),
            "backtests": db.backtests.estimated_document_count(),
        },
    }
    if extra:
        idx.update(extra)
    db.meta.replace_one({"_id": "index"}, idx, upsert=True)
    return idx


# ----------------------------------------------------------------- job runs

def job_start(job: str, run: str) -> None:
    get_db().job_runs.replace_one({"_id": f"{job}-{run}"}, {
        "_id": f"{job}-{run}", "job": job, "run_id": run,
        "started_at": utcnow(), "status": "running",
    }, upsert=True)


def last_success(job: str, before_run: str | None = None) -> dict | None:
    """The most recent successful run of `job`, excluding `before_run`.

    Excluding the current run matters: job_start writes a "running" doc
    before the work begins, and a caller asking "when did this last
    succeed" during its own run must not be able to see itself.
    """
    q: dict = {"job": job, "status": "ok"}
    if before_run:
        q["run_id"] = {"$ne": before_run}
    return get_db().job_runs.find_one(q, sort=[("finished_at", -1)])


def hours_ago(ts: str | None, now: dt.datetime | None = None) -> float | None:
    """Hours between `ts` and now, or None if it is missing or unparseable.

    Naive timestamps are read as UTC, which is what the pipeline writes;
    treating one as local time would silently shift every gap by the
    runner's offset and make the catch-up rule fire at the wrong moments.
    """
    when = _parse_ts(ts)
    if when is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return max(0.0, (now - when).total_seconds() / 3600.0)


def hours_since_last_success(job: str, before_run: str | None = None) -> float | None:
    """How long since `job` last finished cleanly. None if it never has."""
    return hours_ago((last_success(job, before_run) or {}).get("finished_at"))


def job_finish(job: str, run: str, status: str = "ok",
               counts: dict | None = None, error: str | None = None) -> None:
    get_db().job_runs.update_one({"_id": f"{job}-{run}"}, {"$set": {
        "finished_at": utcnow(), "status": status,
        "counts": counts or {}, "error": error,
    }}, upsert=True)


# ------------------------------------------------------------- eBay panel

def record_ebay_poll(query_key: str, cpu: str, ram_gb: int | None,
                     n_items: int, ok: bool) -> None:
    """Note that a query was asked, and whether eBay answered.

    Insert-only and cheap. Its whole job is to make the difference between
    "nothing is listed" and "we could not ask" durable, because the panel
    reads a listing's absence as a sale.
    """
    get_db().ebay_polls.insert_one({
        "query_key": query_key, "cpu": cpu, "ram_gb": ram_gb,
        "polled_at": utcnow(), "n_items": n_items, "ok": bool(ok),
    })


def upsert_ebay_listings(rows: list[dict], query_key: str) -> dict:
    """Record what a poll saw. New rows are born live; known rows advance.

    `first_seen` and `polls` are the panel's clock: how long a listing has
    been up and how many times we have confirmed it. A listing has to have
    been seen more than once before its disappearance counts for anything,
    which is what `polls` is for.
    """
    if not rows:
        return {"new": 0, "seen": 0}
    db = get_db()
    now = utcnow()
    ops, ids = [], [r["_id"] for r in rows]
    existing = {d["_id"] for d in
                db.ebay_listings.find({"_id": {"$in": ids}}, {"_id": 1})}
    for r in rows:
        doc = dict(r, query_key=query_key, last_seen=now)
        ops.append(UpdateOne(
            {"_id": r["_id"]},
            {"$set": doc,
             "$setOnInsert": {"first_seen": now, "first_price": r["last_price"]},
             # A listing that reappears after being marked gone was never
             # sold -- it fell out of search and came back. Clearing the
             # mark is the correction, and $unset on a field that is not
             # set is a no-op, so this costs nothing in the normal case.
             "$unset": {"gone_at": "", "gone_reason": ""},
             "$inc": {"polls": 1}},
            upsert=True))
    db.ebay_listings.bulk_write(ops, ordered=False)
    return {"new": len(ids) - len(existing), "seen": len(ids)}


def live_ebay_listings(query_key: str | None = None) -> list[dict]:
    """Listings currently believed to be up."""
    q: dict = {"gone_at": {"$exists": False}}
    if query_key:
        q["query_key"] = query_key
    return list(get_db().ebay_listings.find(q))


def mark_ebay_gone(marks: list[dict]) -> int:
    """Record that listings stopped appearing, with why we think so."""
    if not marks:
        return 0
    ops = [UpdateOne({"_id": m["_id"]},
                     {"$set": {"gone_at": m["gone_at"],
                               "gone_reason": m["gone_reason"]}})
           for m in marks]
    return get_db().ebay_listings.bulk_write(ops, ordered=False).modified_count


def ended_ebay_listings() -> list[dict]:
    """Every listing that has left, live or confirmed -- the sold-comp feed."""
    return list(get_db().ebay_listings.find({"gone_at": {"$exists": True}}))


def ebay_panel_stats() -> dict:
    db = get_db()
    return {
        "listings": db.ebay_listings.estimated_document_count(),
        "live": db.ebay_listings.count_documents({"gone_at": {"$exists": False}}),
        "ended": db.ebay_listings.count_documents({"gone_at": {"$exists": True}}),
        "confirmed": db.ebay_listings.count_documents(
            {"gone_reason": "confirmed_ended"}),
        "polls": db.ebay_polls.estimated_document_count(),
    }


def write_recovery(run: str, report: dict) -> str:
    get_db().recoveries.replace_one(
        {"_id": run}, {"_id": run, "run_id": run, "measured_at": utcnow(),
                       **report}, upsert=True)
    return run

