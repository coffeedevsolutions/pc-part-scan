"""Deterministic data access for the scheduled Claude routines.

The routines (docs/ROUTINES.md) do judgment work -- reading spec-sheet PDFs
the regex parser could not, writing a digest, spotting drift. Everything
mechanical they need lives here as `pcps` subcommands emitting JSON, so the
routine prompts stay short and their behaviour stays testable.
"""

from __future__ import annotations

import datetime as dt
import json
import os

from . import api as gd
from . import specs
from .store import mongo


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def triage_queue(limit: int = 10) -> list[dict]:
    """Bulk lots whose spec sheet defeated the regex parser.

    Empty manifest attempts (machines == []) on lots whose title states five
    or more units, open lots first, then the most recently closed -- growing
    the exact-manifest corpus is the bulk model's whole bottleneck.
    """
    db = mongo.get_db()
    empty = {d["_id"]: d for d in db.manifests.find({"machines": {"$size": 0}})}
    if not empty:
        return []
    lots = {d["_id"]: d for d in db.lots.find({"_id": {"$in": list(empty)}})}
    rows = []
    for key, man in empty.items():
        lot = lots.get(key)
        if not lot:
            continue
        n = specs.parse_unit_count(lot.get("title") or "")
        if n is None or n < 5:
            continue
        rows.append({
            "key": key,
            "account_id": lot["account_id"],
            "asset_id": lot["asset_id"],
            "title": lot.get("title"),
            "stated_units": n,
            "status": lot.get("status"),
            "attempted_at": man.get("parsed_at"),
            "source_files_seen": man.get("source_files", []),
        })
    rows.sort(key=lambda r: (r["status"] != "open", r["key"]), reverse=False)
    return rows[:limit]


def triage_fetch(key: str, out_dir: str) -> list[str]:
    """Download a lot's PDF attachments for a human/model to read."""
    account_id, asset_id = (int(x) for x in key.split("-"))
    os.makedirs(out_dir, exist_ok=True)
    detail = gd.asset(asset_id, account_id)
    paths = []
    for att in detail.get("assetAttachments") or []:
        fn = att.get("fileName") or ""
        if not fn.lower().endswith(".pdf"):
            continue
        dest = os.path.join(out_dir, f"{key}_{fn}".replace("/", "_"))
        try:
            gd.download(gd.attachment_url(account_id, fn), dest)
            paths.append(dest)
        except Exception as e:  # keep going; report what worked
            print(f"  download failed for {fn}: {e}")
    return paths


MACHINE_FIELDS = {"cpu", "generation", "ram_gb", "form_factor",
                  "chassis", "has_drive", "qty"}


def save_llm_manifest(key: str, machines: list[dict],
                      source_files: list[str],
                      allow_mismatch: bool = False) -> dict:
    """Validate and store a manifest extracted by a model.

    Quantities must be positive integers and, unless allow_mismatch is set,
    reconcile with the unit count stated in the lot title (±5%, min 1).
    """
    db = mongo.get_db()
    lot = db.lots.find_one({"_id": key})
    if not lot:
        raise SystemExit(f"unknown lot {key}")
    clean = []
    for m in machines:
        extra = set(m) - MACHINE_FIELDS
        if extra:
            raise SystemExit(f"unexpected machine fields: {sorted(extra)}")
        qty = m.get("qty")
        if not isinstance(qty, int) or qty <= 0:
            raise SystemExit(f"bad qty in {m}")
        clean.append({f: m.get(f) for f in MACHINE_FIELDS})
    total = sum(m["qty"] for m in clean)
    stated = specs.parse_unit_count(lot.get("title") or "")
    reconciled = stated is not None and abs(total - stated) <= max(1, stated * 0.05)
    if not reconciled and not allow_mismatch:
        raise SystemExit(
            f"quantities sum to {total} but the title states {stated}; "
            "re-check the sheet or pass --allow-mismatch")
    mongo.save_manifest(key, clean, source_files, parsed_by="llm")
    return {"key": key, "units": total, "stated": stated,
            "reconciled": reconciled, "machines": len(clean)}


def digest() -> dict:
    """Everything the daily digest needs, as one JSON blob."""
    db = mongo.get_db()
    now = _now()
    day_ago = _iso(now - dt.timedelta(days=1))
    day_ahead = _iso(now + dt.timedelta(days=1))

    snap = db.snapshots.find_one(sort=[("_id", -1)]) or {"lots": [], "run_id": None}
    graded = {v["lot_key"]: v for v in snap.get("lots", [])}
    watched = {d["_id"] for d in db.watchlist.find({})}

    top = sorted(
        (v for v in graded.values()
         if v["grade"] in ("A", "B") and v["headroom"] > 0),
        key=lambda v: -(v["headroom"] * v["confidence"]))[:5]

    closing_watched = list(db.lots.find({
        "_id": {"$in": list(watched)}, "status": "open",
        "auction_end_utc": {"$lte": day_ahead},
    }, {"title": 1, "auction_end_utc": 1, "last_obs": 1}))

    surprises = []
    for lot in db.sold.find({"auction_end_utc": {"$gte": day_ago}}):
        v = graded.get(lot["_id"])
        if not v or not lot.get("final_price"):
            continue
        expected = v["expected_revenue"]
        price = lot["final_price"]
        if expected > 0 and (price / expected > 1.5 or price / expected < 0.5):
            surprises.append({
                "key": lot["_id"], "title": lot.get("title"),
                "final_price": price, "model_expected": round(expected, 2),
                "ratio": round(price / expected, 2),
            })

    jobs = list(db.job_runs.find({"started_at": {"$gte": day_ago}},
                                 {"job": 1, "status": 1, "started_at": 1,
                                  "error": 1}).sort("started_at", -1))
    return {
        "generated_at": _iso(now),
        "snapshot_run": snap.get("run_id"),
        "top_actionable": top,
        "watched_closing_24h": [
            {"key": d["_id"], "title": d.get("title"),
             "closes": d.get("auction_end_utc"),
             "bid": (d.get("last_obs") or {}).get("bid")}
            for d in closing_watched],
        "sold_surprises_24h": surprises,
        "job_runs_24h": [{k: v for k, v in j.items() if k != "_id"} for j in jobs],
    }


def health() -> dict:
    """Trend + drift inputs for the weekly health review."""
    db = mongo.get_db()
    now = _now()
    week_ago = _iso(now - dt.timedelta(days=7))

    runs = [{k: d.get(k) for k in ("run_id", "fitted_at", "n_observations",
                                   "r2", "bulk_discount_k", "bulk_n", "bulk_r2")}
            for d in db.model_runs.find(sort=[("run_id", -1)], limit=14)]

    hist: dict[int, int] = {}
    for d in db.lots.find({"auction_end_utc": {"$ne": None}},
                          {"auction_end_utc": 1}):
        try:
            h = int(d["auction_end_utc"][11:13])
            hist[h] = hist.get(h, 0) + 1
        except (TypeError, ValueError, IndexError):
            continue

    raw_keys: dict[str, int] = {}
    for d in db.lots.find({"last_seen": {"$gte": week_ago}},
                          {"raw_extra": 1}).limit(3000):
        for k in (d.get("raw_extra") or {}):
            raw_keys[k] = raw_keys.get(k, 0) + 1

    bad_jobs = [{k: v for k, v in j.items() if k != "_id"}
                for j in db.job_runs.find(
                    {"started_at": {"$gte": week_ago},
                     "status": {"$nin": ["ok", "running"]}})]
    week_jobs = db.job_runs.count_documents({"started_at": {"$gte": week_ago}})

    empty_manifests = db.manifests.count_documents({"machines": {"$size": 0}})
    return {
        "generated_at": _iso(now),
        "model_runs_recent_first": runs,
        "close_hour_histogram_utc": {str(h): hist.get(h, 0) for h in range(24)},
        "raw_extra_keys_last_week": raw_keys,
        "job_runs_last_week": week_jobs,
        "job_failures_last_week": bad_jobs,
        "manifests_total": db.manifests.estimated_document_count(),
        "manifests_empty": empty_manifests,
        "counts": (db.meta.find_one({"_id": "index"}) or {}).get("counts", {}),
    }
