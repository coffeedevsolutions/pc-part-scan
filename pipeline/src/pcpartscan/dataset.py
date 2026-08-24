"""Structured, append-only dataset for GovDeals scan results.

Layout under data/:

  index.json                  dataset manifest: schema version, counts, last run
  lots.json                   current state of every lot ever seen, keyed
                              "<accountId>-<assetId>"
  bid_history.jsonl           APPEND-ONLY time series; one line per observation
                              of a lot's current bid. This is the thing that
                              cannot be reconstructed later, so it is never
                              rewritten -- only appended.
  sold.json                   lots observed in a closed/sold state, with the
                              realized hammer price
  components.json             fitted component prices, with one entry per fit
                              run so pricing can be compared over time
  models.json                 model coefficients and fit statistics per run
  manifests/<key>.json        parsed spec-sheet contents per lot
  snapshots/<run_id>.json     summary of each scan run

Design notes:

* bid_history is JSONL and append-only. Every other file is a full rewrite,
  written atomically via a temp file + os.replace so an interrupted run cannot
  truncate a good file.
* Nothing is ever deleted. A lot that disappears from live search is marked
  with a status change, not removed, so the historical record stays intact.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile

SCHEMA_VERSION = 2

ROOT = os.environ.get("PCPS_DATA", "data")
LOTS = os.path.join(ROOT, "lots.json")
BID_HISTORY = os.path.join(ROOT, "bid_history.jsonl")
SOLD = os.path.join(ROOT, "sold.json")
COMPONENTS = os.path.join(ROOT, "components.json")
MODELS = os.path.join(ROOT, "models.json")
INDEX = os.path.join(ROOT, "index.json")
MANIFEST_DIR = os.path.join(ROOT, "manifests")
SNAPSHOT_DIR = os.path.join(ROOT, "snapshots")


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ensure_dirs():
    for d in (ROOT, MANIFEST_DIR, SNAPSHOT_DIR):
        os.makedirs(d, exist_ok=True)


def read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: str, obj) -> None:
    """Atomic write: a crash mid-write leaves the previous file intact."""
    _ensure_dirs()
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_jsonl(path: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    _ensure_dirs()
    with open(path, "a") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    return len(rows)


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue          # tolerate a torn final line
    return out


# --------------------------------------------------------------------- lots

def lot_key(rec: dict) -> str:
    return f"{rec['accountId']}-{rec['assetId']}"


def normalize_lot(rec: dict, observed_at: str, sold: bool) -> dict:
    """Project a raw API record onto the stable dataset schema.

    Raw API fields change without notice; everything downstream reads this
    shape instead, and `raw_extra` keeps anything we have not modelled yet.
    """
    keep_raw = ("groupId", "auctionTypeId", "assetRestrictionCode",
                "hasReservePrice", "isReserveNotMet", "assetStrikePrice",
                "assetBidIncrement", "warehouseId", "eventId")
    return {
        "key": lot_key(rec),
        "account_id": rec.get("accountId"),
        "asset_id": rec.get("assetId"),
        "title": rec.get("assetShortDescription"),
        "category": rec.get("categoryDescription"),
        "category_code": rec.get("assetCategory"),
        "make": rec.get("makebrand"),
        "model": rec.get("model"),
        "seller": rec.get("companyName"),
        "location": {
            "city": rec.get("locationCity"),
            "state": rec.get("locationState"),
            "zip": rec.get("locationZip"),
            "country": rec.get("country"),
        },
        "currency": rec.get("currencyCode"),
        "auction_start": rec.get("assetAuctionStartDate"),
        "auction_end": rec.get("assetAuctionEndDate"),
        "auction_end_utc": rec.get("assetAuctionEndDateUtc"),
        "status": "sold" if sold else "open",
        "is_sold_auction": bool(rec.get("isSoldAuction")),
        "final_price": float(rec["currentBid"]) if sold and rec.get("currentBid") else None,
        "url": f"https://www.govdeals.com/asset/{rec.get('assetId')}/{rec.get('accountId')}",
        "photo": rec.get("photo"),
        "first_seen": observed_at,
        "last_seen": observed_at,
        "raw_extra": {k: rec.get(k) for k in keep_raw if rec.get(k) is not None},
    }


def upsert_lots(records: list[dict], observed_at: str, sold: bool) -> dict:
    """Merge API records into lots.json. Returns {new, updated}."""
    lots = read_json(LOTS, {})
    new = updated = 0
    for rec in records:
        k = lot_key(rec)
        norm = normalize_lot(rec, observed_at, sold)
        if k in lots:
            prev = lots[k]
            norm["first_seen"] = prev.get("first_seen", observed_at)
            # never downgrade a sold lot back to open
            if prev.get("status") == "sold" and not sold:
                norm["status"] = "sold"
                norm["final_price"] = prev.get("final_price")
            lots[k] = {**prev, **norm}
            updated += 1
        else:
            lots[k] = norm
            new += 1
    write_json(LOTS, lots)
    return {"new": new, "updated": updated, "total": len(lots)}


def record_bids(records: list[dict], observed_at: str, run: str) -> int:
    """Append one bid observation per lot. This is the historical time series."""
    rows = []
    for rec in records:
        bid = rec.get("currentBid")
        if bid is None:
            continue
        rows.append({
            "key": lot_key(rec),
            "observed_at": observed_at,
            "run_id": run,
            "current_bid": float(bid),
            "bid_count": rec.get("bidCount"),
            "time_remaining": rec.get("timeRemaining"),
            "auction_end_utc": rec.get("assetAuctionEndDateUtc"),
            "is_sold": bool(rec.get("isSoldAuction")),
            "reserve_not_met": bool(rec.get("isReserveNotMet")),
        })
    return append_jsonl(BID_HISTORY, rows)


def bid_history_for(key: str) -> list[dict]:
    return [r for r in read_jsonl(BID_HISTORY) if r.get("key") == key]


def sold_lots() -> dict[str, dict]:
    """All sold lots keyed by lot key -- the shape harvest rebuilds from."""
    return read_json(SOLD, {})


def project_lot(lot: dict, bid: float | None, bid_count) -> dict:
    """Map a normalized lot back onto the raw API shape the grader expects.

    Shared by both storage backends -- the grader must see one shape.
    """
    return {
        "accountId": lot["account_id"], "assetId": lot["asset_id"],
        "assetShortDescription": lot.get("title"),
        "currentBid": bid if bid is not None else 0.0,
        "bidCount": bid_count,
        "companyName": lot.get("seller"),
        "locationState": (lot.get("location") or {}).get("state"),
        "locationCity": (lot.get("location") or {}).get("city"),
        "assetAuctionEndDate": lot.get("auction_end"),
        "assetAuctionEndDateUtc": lot.get("auction_end_utc"),
        "assetAuctionEndDateDisplay": lot.get("auction_end") or "",
        "categoryDescription": lot.get("category"),
        "currencyCode": lot.get("currency"),
        "isSoldAuction": False,
    }


def open_lots_raw() -> dict[str, dict]:
    """Open lots mapped back onto the raw API shape the grader expects."""
    latest: dict[str, dict] = {}
    for r in read_jsonl(BID_HISTORY):     # chronological; last one wins
        if r.get("key"):
            latest[r["key"]] = r
    out = {}
    for key, lot in read_json(LOTS, {}).items():
        if lot.get("status") != "open":
            continue
        h = latest.get(key)
        out[key] = project_lot(lot, h.get("current_bid") if h else None,
                               h.get("bid_count") if h else None)
    return out


def save_grades(vals: list, run: str) -> int:
    """No-op in file mode: each run's snapshot already carries the grades."""
    return 0


def upsert_sold(records: list[dict], observed_at: str) -> dict:
    sold = read_json(SOLD, {})
    added = 0
    for rec in records:
        if not rec.get("isSoldAuction") or not rec.get("currentBid"):
            continue
        k = lot_key(rec)
        if k not in sold:
            added += 1
        sold[k] = {
            **normalize_lot(rec, observed_at, sold=True),
            "final_price": float(rec["currentBid"]),
        }
    write_json(SOLD, sold)
    return {"added": added, "total": len(sold)}


# --------------------------------------------------------------- manifests

def save_manifest(key: str, machines: list[dict], source_files: list[str]) -> None:
    write_json(os.path.join(MANIFEST_DIR, f"{key}.json"), {
        "key": key,
        "parsed_at": utcnow(),
        "source_files": source_files,
        "unit_total": sum(m.get("qty", 1) for m in machines),
        "machines": machines,
    })


def load_manifest(key: str) -> dict | None:
    return read_json(os.path.join(MANIFEST_DIR, f"{key}.json"), None)


def all_manifests() -> dict[str, dict]:
    if not os.path.isdir(MANIFEST_DIR):
        return {}
    out = {}
    for fn in os.listdir(MANIFEST_DIR):
        if fn.endswith(".json"):
            m = read_json(os.path.join(MANIFEST_DIR, fn), None)
            if m:
                out[m["key"]] = m
    return out


# -------------------------------------------------------------- components

def model_summary(run: str, single_model, bulk_model,
                  table_path: str | None) -> dict:
    """Chartable per-run summary of a fit. Shared by both storage backends."""
    names = single_model.space.names
    prices = {}
    for cpu in single_model.space.cpus:
        prices[cpu] = round(single_model.value(
            {"cpu": cpu, "ram_gb": 0, "form_factor": None, "has_drive": False}), 2)
    return {
        "run_id": run,
        "fitted_at": utcnow(),
        "n_observations": single_model.n_obs,
        "r2": round(single_model.r2, 4),
        "ram_per_8gb": round(float(single_model.coef[names.index("ram_gb")]), 2),
        "drive_adder": round(float(single_model.coef[names.index("has_drive")]), 2),
        "bulk_discount_k": round(bulk_model.k, 4) if bulk_model else None,
        "bulk_n": bulk_model.n_obs if bulk_model else 0,
        "bulk_r2": round(bulk_model.r2, 4) if bulk_model else None,
        "cpu_base_value_usd": prices,
        "static_table": table_path,
    }


def save_full_models(run: str, single_model, bulk_model) -> None:
    """Persist the full coefficients for this run (models.json in file mode)."""
    write_json(MODELS, {
        "schema_version": SCHEMA_VERSION,
        "run_id": run,
        "single": single_model.to_json(),
        "bulk": bulk_model.to_json() if bulk_model else None,
    })


def record_components(run: str, single_model, bulk_model, table_path: str | None) -> None:
    """Append this run's fitted component prices, keeping prior runs.

    Component prices drift as the market moves; keeping every fit means you can
    chart a CPU's value over time instead of only seeing today's number.
    """
    hist = read_json(COMPONENTS, {"schema_version": SCHEMA_VERSION, "runs": []})
    entry = model_summary(run, single_model, bulk_model, table_path)
    hist["runs"] = [r for r in hist.get("runs", []) if r.get("run_id") != run]
    hist["runs"].append(entry)
    hist["runs"].sort(key=lambda r: r["run_id"])
    hist["latest"] = entry
    hist["schema_version"] = SCHEMA_VERSION
    write_json(COMPONENTS, hist)


def component_price_series(cpu: str) -> list[dict]:
    """Value of one CPU across every fit run -- the historical trend."""
    hist = read_json(COMPONENTS, {"runs": []})
    return [{"run_id": r["run_id"], "fitted_at": r["fitted_at"],
             "value_usd": r["cpu_base_value_usd"].get(cpu)}
            for r in hist.get("runs", [])
            if cpu in r.get("cpu_base_value_usd", {})]


# ---------------------------------------------------------------- snapshots

def write_snapshot(run: str, payload: dict) -> str:
    path = os.path.join(SNAPSHOT_DIR, f"{run}.json")
    write_json(path, {"run_id": run, "generated_at": utcnow(), **payload})
    return path


def update_index(run: str, extra: dict | None = None) -> dict:
    lots = read_json(LOTS, {})
    sold = read_json(SOLD, {})
    idx = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utcnow(),
        "last_run_id": run,
        "counts": {
            "lots": len(lots),
            "open_lots": sum(1 for v in lots.values() if v.get("status") == "open"),
            "sold_lots": len(sold),
            "bid_observations": sum(1 for _ in open(BID_HISTORY)) if os.path.exists(BID_HISTORY) else 0,
            "manifests": len(all_manifests()),
            "snapshots": len(os.listdir(SNAPSHOT_DIR)) if os.path.isdir(SNAPSHOT_DIR) else 0,
        },
        "files": {
            "lots": os.path.relpath(LOTS, ROOT),
            "bid_history": os.path.relpath(BID_HISTORY, ROOT),
            "sold": os.path.relpath(SOLD, ROOT),
            "components": os.path.relpath(COMPONENTS, ROOT),
            "models": os.path.relpath(MODELS, ROOT),
        },
    }
    if extra:
        idx.update(extra)
    write_json(INDEX, idx)
    return idx
