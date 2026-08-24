"""Build and refresh a local cache of GovDeals sold comps and live lots.

Two kinds of comp observation come out of this:

  singles  - a sold lot of exactly one machine whose CPU is in the title.
             Gives a direct $/machine price point. Strongest signal.
  baskets  - a sold bulk lot with a spec-sheet PDF attached, so the exact
             machine mix is known. Feeds the least-squares component fit.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error

from . import api as gd
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


def fetch_manifest(account_id: int, asset_id: int,
                   use_cache: bool = True) -> list[specs.Machine]:
    """Detail-fetch a lot, download any spec PDF, return the parsed machine mix.

    A previous parse attempt -- successful or empty -- is stored by the
    backend and returned as-is, so scheduled runs do not re-download the
    same unparseable spec sheets forever.
    """
    key = f"{account_id}-{asset_id}"
    if use_cache:
        cached = ds.load_manifest(key)
        if cached is not None:
            return [specs.Machine(**m) for m in cached.get("machines", [])]
    os.makedirs(ATTACH, exist_ok=True)
    detail = gd.asset(asset_id, account_id)
    out: list[specs.Machine] = []
    seen_sizes: set[int] = set()
    used: list[str] = []
    for att in detail.get("assetAttachments") or []:
        fn = att.get("fileName") or ""
        if not fn.lower().endswith(".pdf"):
            continue
        dest = os.path.join(ATTACH, f"{account_id}_{asset_id}_{fn}")
        if not os.path.exists(dest):
            try:
                gd.download(gd.attachment_url(account_id, fn), dest)
            except Exception:
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
    # an empty result is recorded too: "attempted, unparseable" is exactly
    # what keeps rescans cheap and gives the manifest-triage routine its queue
    ds.save_manifest(key, [m.to_dict() for m in out], used)
    return out


def build_observations(sold: dict, max_detail: int = 400) -> dict:
    """Turn raw sold records into priced observations.

    Returns {"singles": [...], "baskets": [...]}.
    """
    manifests = _load("manifests.json", None)
    if manifests is None:
        # fresh runner: prime the scratch cache from the durable store so the
        # detail budget goes to lots never attempted, not re-fetches
        manifests = {k: m.get("machines", [])
                     for k, m in ds.all_manifests().items()}
    singles, baskets = [], []
    detail_budget = max_detail

    for key, r in sold.items():
        title = r.get("assetShortDescription") or ""
        price = r.get("currentBid")
        if not price or price <= 0 or not r.get("isSoldAuction"):
            continue
        n = specs.parse_unit_count(title)
        if n is None:
            continue          # plural title with no stated count -- unusable
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
        if key in manifests:
            mix = [specs.Machine(**m) for m in manifests[key]]
        elif detail_budget > 0:
            detail_budget -= 1
            try:
                mix = fetch_manifest(r["accountId"], r["assetId"])
            except Exception:
                mix = []
            manifests[key] = [m.to_dict() for m in mix]
            time.sleep(POLITE_DELAY)
            if len(manifests) % 25 == 0:
                _save("manifests.json", manifests)
                _p(f"  manifests cached: {len(manifests)}")
        else:
            mix = []

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

    _save("manifests.json", manifests)
    obs = {"singles": singles, "baskets": baskets}
    _save("observations.json", obs)
    _p(f"observations: {len(singles)} singles, {len(baskets)} baskets "
       f"({sum(1 for b in baskets if b['exact'])} with exact manifests)")
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
    """Rebuild priced observations from the committed dataset alone.

    cache/ is scratch and gitignored, so a fresh clone has none of it. The
    durable record -- data/sold.json plus data/manifests/ -- is enough to
    rebuild every observation, which is what lets a scheduled run start from a
    bare checkout.
    """
    sold_lots = ds.sold_lots()
    manifests = ds.all_manifests()
    singles, baskets = [], []

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

        man = manifests.get(key)
        mix = man["machines"] if man else []
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

    obs = {"singles": singles, "baskets": baskets}
    _save("observations.json", obs)
    _p(f"observations (from dataset): {len(singles)} singles, {len(baskets)} baskets "
       f"({sum(1 for b in baskets if b['exact'])} with exact manifests)")
    return obs


def load_observations() -> dict:
    """Prefer the scratch cache when present, else rebuild from the dataset."""
    obs = _load("observations.json", None)
    if obs and obs.get("singles"):
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
