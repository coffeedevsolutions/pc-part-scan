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
  snapshots         graded output of each scan run, _id = run id.
  meta              _id="index": counts, last run, last config.
  job_runs          one doc per scheduled job execution.

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


def get_db():
    global _client, _indexed
    if _client is None:
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise SystemExit("MONGODB_URI is not set; cannot use the mongo store")
        _client = MongoClient(uri, appname="pcps-pipeline", tz_aware=False,
                              serverSelectionTimeoutMS=20000)
    db = _client[os.environ.get("PCPS_DB", "pcps")]
    if not _indexed:
        ensure_indexes(db)
        _indexed = True
    return db


def ensure_indexes(db) -> None:
    db.lots.create_index([("status", 1), ("auction_end_utc", 1)])
    db.lots.create_index([("location.state", 1)])
    db.bid_observations.create_index(
        [("key", 1), ("run_id", 1), ("observed_at", 1)], unique=True)
    db.bid_observations.create_index([("key", 1), ("observed_at", 1)])
    db.sold.create_index([("auction_end_utc", 1)])
    db.job_runs.create_index([("job", 1), ("started_at", -1)])


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
    already_sold = {d["_id"] for d in db.lots.find(
        {"_id": {"$in": keys}, "status": "sold"}, {"_id": 1})}

    ops = []
    for rec in recs:
        k = lot_key(rec)
        norm = normalize_lot(rec, observed_at, sold)
        norm.pop("first_seen", None)
        if k in already_sold and not sold:
            # never downgrade a sold lot back to open, and keep its price
            norm["status"] = "sold"
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


def open_lots_raw() -> dict[str, dict]:
    """Open lots mapped back onto the raw API shape the grader expects."""
    out = {}
    for lot in get_db().lots.find({"status": "open"}):
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


def job_finish(job: str, run: str, status: str = "ok",
               counts: dict | None = None, error: str | None = None) -> None:
    get_db().job_runs.update_one({"_id": f"{job}-{run}"}, {"$set": {
        "finished_at": utcnow(), "status": status,
        "counts": counts or {}, "error": error,
    }}, upsert=True)
