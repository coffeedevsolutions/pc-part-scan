"""Build and refresh a local cache of GovDeals sold comps and live lots.

Two kinds of comp observation come out of this:

  singles  - a sold lot of exactly one machine whose CPU is in the title.
             Gives a direct $/machine price point. Strongest signal.
  baskets  - a sold bulk lot with a spec-sheet PDF attached, so the exact
             machine mix is known. Feeds the least-squares component fit.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error

from . import api as gd
from . import classprice
from . import specs
from .store import backend as ds

CACHE = "cache"
ATTACH = os.path.join(CACHE, "attachments")

# Queries used to sweep the sold archive. Broad on purpose -- the API dedupes
# by assetId on our side, so overlap is free.
QUERIES = [
    "optiplex", "dell computers", "desktop computers", "sff computers",
    "all-in-one computers", "micro computers", "thinkcentre", "prodesk",
    "elitedesk", "precision workstation", "computer lot", "lot of computers",
]

POLITE_DELAY = 0.35  # seconds between API calls


def _p(*a):
    print(*a, flush=True)


def _load(name, default):
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def _save(name, obj):
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, name), "w") as f:
        json.dump(obj, f)


def sweep_sold(queries=QUERIES, rows=100, max_pages=12, run: str | None = None) -> dict[str, dict]:
    """Page the global sold archive across several queries. Returns {key: record}.

    Every record also lands in the structured dataset: the lot itself in
    lots.json / sold.json, and one bid observation in bid_history.jsonl.
    """
    run = run or ds.run_id()
    observed = ds.utcnow()
    found = _load("sold_raw.json", {})
    before = len(found)
    for q in queries:
        for page in range(1, max_pages + 1):
            try:
                batch, total = gd.search(text=q, sold=True, page=page, rows=rows)
            except urllib.error.HTTPError as e:
                _p(f"  [{q}] page {page}: HTTP {e.code}, stopping this query")
                break
            if not batch:
                break
            for r in batch:
                found[f"{r['accountId']}-{r['assetId']}"] = r
            _p(f"  [{q}] page {page}: +{len(batch)}  (corpus {len(found)}, query total {total})")
            time.sleep(POLITE_DELAY)
            if page * rows >= total:
                break
    _save("sold_raw.json", found)
    recs = list(found.values())
    ds.upsert_lots(recs, observed, sold=True)
    ds.upsert_sold(recs, observed)
    ds.record_bids(recs, observed, run)
    _p(f"sold corpus: {len(found)} records (+{len(found)-before} new)")
    return found


def sweep_live(queries=QUERIES, rows=100, max_pages=8, run: str | None = None) -> dict[str, dict]:
    run = run or ds.run_id()
    observed = ds.utcnow()
    found = {}
    for q in queries:
        for page in range(1, max_pages + 1):
            try:
                batch, total = gd.search(text=q, sold=False, page=page, rows=rows)
            except urllib.error.HTTPError as e:
                _p(f"  [{q}] page {page}: HTTP {e.code}")
                break
            if not batch:
                break
            for r in batch:
                found[f"{r['accountId']}-{r['assetId']}"] = r
            time.sleep(POLITE_DELAY)
            if page * rows >= total:
                break
    _save("live_raw.json", found)
    recs = list(found.values())
    ds.upsert_lots(recs, observed, sold=False)
    n = ds.record_bids(recs, observed, run)
    _p(f"live corpus: {len(found)} open lots ({n} bid observations recorded)")
    return found


RETRY_EMPTY_DAYS = 7    # how long a cached empty parse suppresses re-attempts


def _empty_and_stale(manifest: dict) -> bool:
    if manifest.get("machines"):
        return False
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(days=RETRY_EMPTY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (manifest.get("parsed_at") or "") < cutoff


def fetch_manifest(account_id: int, asset_id: int,
                   use_cache: bool = True) -> list[specs.Machine]:
    """Detail-fetch a lot, download any spec PDF, return the parsed machine mix.

    Parse attempts are stored durably -- including empty ones, so scheduled
    runs do not re-download the same unparseable sheets every time. But an
    empty result can also be transient (a download blip, a spec sheet the
    seller has not uploaded yet), so cached-empty entries expire after
    RETRY_EMPTY_DAYS, and an attempt with a failed download is not cached
    at all.
    """
    key = f"{account_id}-{asset_id}"
    if use_cache:
        cached = ds.load_manifest(key)
        if cached is not None and not _empty_and_stale(cached):
            return [specs.Machine(**m) for m in cached.get("machines", [])]
    os.makedirs(ATTACH, exist_ok=True)
    detail = gd.asset(asset_id, account_id)
    out: list[specs.Machine] = []
    seen_sizes: set[int] = set()
    used: list[str] = []
    download_failed = False
    for att in detail.get("assetAttachments") or []:
        fn = att.get("fileName") or ""
        if not fn.lower().endswith(".pdf"):
            continue
        dest = os.path.join(ATTACH, f"{account_id}_{asset_id}_{fn}")
        if not os.path.exists(dest):
            try:
                gd.download(gd.attachment_url(account_id, fn), dest)
            except Exception:
                download_failed = True
                continue
        # sellers often attach the same sheet twice ("- Copy") -- dedupe by size
        sz = os.path.getsize(dest)
        if sz in seen_sizes:
            continue
        seen_sizes.add(sz)
        try:
            parsed = specs.parse_manifest_pdf(dest)
        except Exception:
            continue
        out.extend(parsed)
        used.append(fn)
    if out or not download_failed:
        # cache the attempt only when every attachment was actually inspected:
        # a network blip must stay retryable on the next run
        ds.save_manifest(key, [m.to_dict() for m in out], used)
    return out


def manifest_mix(key: str, account_id, asset_id,
                 manifests: dict[str, dict],
                 may_fetch: bool) -> tuple[list[dict], bool]:
    """The machine mix for one bulk lot. Returns (mix, spent_fetch_budget).

    The single decision point for "do we already know this lot's mix, and
    if not may we go find out". Both observation builders route through it
    so neither can resurrect a stale empty parse: an empty attempt older
    than RETRY_EMPTY_DAYS is re-fetched, exactly as fetch_manifest would.
    """
    man = manifests.get(key)
    if man is not None and (man.get("machines") or not _empty_and_stale(man)):
        return list(man.get("machines") or []), False
    if not (may_fetch and account_id and asset_id):
        return list((man or {}).get("machines") or []), False
    try:
        mix = [m.to_dict() for m in fetch_manifest(account_id, asset_id)]
    except Exception:
        mix = []
    time.sleep(POLITE_DELAY)
    # keep the in-run view current so one pass never re-fetches the same lot
    manifests[key] = {"key": key, "machines": mix, "parsed_at": ds.utcnow()}
    return mix, True


def build_observations(sold: dict, max_detail: int = 400) -> dict:
    """Turn raw sold records into priced observations.

    Returns {"singles": [...], "baskets": [...]}.
    """
    # the durable store is the only manifest source of truth; the old
    # scratch copy in cache/manifests.json was a lossy duplicate that
    # dropped parse timestamps, which is what made empty parses permanent
    manifests = dict(ds.all_manifests())
    singles, baskets, lots = [], [], []
    detail_budget = max_detail

    for key, r in sold.items():
        title = r.get("assetShortDescription") or ""
        price = r.get("currentBid")
        if not price or price <= 0 or not r.get("isSoldAuction"):
            continue
        n = specs.parse_unit_count(title)
        if n is None:
            continue          # plural title with no stated count -- unusable
        # every priced lot with a stated count feeds the per-class table,
        # including the ones the machine model has no features for
        lots.append({"key": key, "title": title, "units": n,
                     "price": float(price)})
        if n == 1:
            m = specs.machine_from_text(title, 1)
            if m.cpu:
                singles.append({
                    "key": key, "price": float(price), "title": title,
                    "machine": m.to_dict(),
                    "end": r.get("assetAuctionEndDate"),
                    "state": r.get("locationState"),
                })
            continue

        if n < 5:
            continue

        # bulk lot -- try for an exact manifest
        mix_d, spent = manifest_mix(key, r.get("accountId"), r.get("assetId"),
                                    manifests, detail_budget > 0)
        if spent:
            detail_budget -= 1
        mix = [specs.Machine(**m) for m in mix_d]

        units = sum(m.qty for m in mix)
        baskets.append({
            "key": key, "price": float(price), "title": title,
            "stated_units": n,
            "manifest_units": units,
            "exact": bool(mix) and abs(units - n) <= max(1, n * 0.05),
            "mix": [m.to_dict() for m in mix],
            "fallback": specs.machine_from_text(title, n).to_dict(),
            "end": r.get("assetAuctionEndDate"),
            "state": r.get("locationState"),
        })

    obs = {"singles": singles, "baskets": baskets, "lots": lots}
    _save("observations.json", obs)
    _p(f"observations: {len(singles)} singles, {len(baskets)} baskets "
       f"({sum(1 for b in baskets if b['exact'])} with exact manifests), "
       f"{len(lots)} class comps")
    return obs


if __name__ == "__main__":
    import sys
    md = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    _p("=== sweeping sold archive ===")
    sold = sweep_sold()
    _p("\n=== building observations ===")
    build_observations(sold, max_detail=md)
    _p("\n=== sweeping live lots ===")
    sweep_live()


def build_observations_from_dataset(max_detail: int = 0) -> dict:
    """Rebuild priced observations from the durable store alone.

    cache/ is scratch and gitignored, so a fresh clone or CI runner has none
    of it. The durable record -- sold lots plus manifests -- is enough to
    rebuild every observation, which is what lets a scheduled run start from
    a bare checkout. With max_detail > 0, bulk lots that have never had a
    manifest attempt get one, up to that budget.
    """
    sold_lots = ds.sold_lots()
    manifests = ds.all_manifests()
    singles, baskets = [], []
    lots = classprice.class_observations(sold_lots)
    detail_budget = max_detail

    for key, lot in sold_lots.items():
        title = lot.get("title") or ""
        price = lot.get("final_price")
        if not price or price <= 0:
            continue
        n = specs.parse_unit_count(title)
        if n is None:
            continue

        if n == 1:
            m = specs.machine_from_text(title, 1)
            if m.cpu:
                singles.append({
                    "key": key, "price": float(price), "title": title,
                    "machine": m.to_dict(),
                    "end": lot.get("auction_end"),
                    "state": (lot.get("location") or {}).get("state"),
                })
            continue
        if n < 5:
            continue

        mix, spent = manifest_mix(key, lot.get("account_id"),
                                  lot.get("asset_id"), manifests,
                                  detail_budget > 0)
        if spent:
            detail_budget -= 1
        units = sum(m.get("qty", 1) for m in mix)
        baskets.append({
            "key": key, "price": float(price), "title": title,
            "stated_units": n, "manifest_units": units,
            "exact": bool(mix) and abs(units - n) <= max(1, n * 0.05),
            "mix": mix,
            "fallback": specs.machine_from_text(title, n).to_dict(),
            "end": lot.get("auction_end"),
            "state": (lot.get("location") or {}).get("state"),
        })

    obs = {"singles": singles, "baskets": baskets, "lots": lots}
    _save("observations.json", obs)
    _p(f"observations (from dataset): {len(singles)} singles, {len(baskets)} baskets "
       f"({sum(1 for b in baskets if b['exact'])} with exact manifests), "
       f"{len(lots)} class comps")
    return obs


def load_observations() -> dict:
    """Prefer the scratch cache when present, else rebuild from the dataset."""
    obs = _load("observations.json", None)
    # a cache written before the per-class table existed has no "lots" key;
    # rebuilding is cheap and beats silently pricing nothing by class
    if obs and obs.get("singles") and obs.get("lots"):
        return obs
    return build_observations_from_dataset()


def load_live() -> dict:
    """Open lots: scratch cache if present, else reconstruct from the dataset.

    The dataset stores lots in normalized form, so this maps the fields the
    grader needs back onto the raw API shape it expects.
    """
    live = _load("live_raw.json", None)
    if live:
        return live
    out = ds.open_lots_raw()
    _p(f"live lots (from dataset): {len(out)}")
    return out
