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


def resolve_closed(max_sellers: int = 40, rows: int = 100,
                   max_pages: int = 6, run: str | None = None) -> dict:
    """Find out what the lots we were tracking actually sold for.

    A lot only ever became "sold" here if the keyword sweep happened to
    surface it again, which for a lot we graded is left entirely to chance:
    its end time passes, it stays `status: open` forever, it sits on the
    board reading "closed", and we never learn the one number that would
    tell us whether our max bid was any good.

    So ask directly. Every seller's completed auctions are one scoped
    search, so the lots we tracked resolve in one request per seller rather
    than one per lot -- the same trick the burst sampler uses on the way in.

    Returns {"checked", "resolved", "sellers", "outcomes"}, where outcomes
    pairs each resolved lot with the hammer price.
    """
    run = run or ds.run_id()
    observed = ds.utcnow()
    pending = ds.open_lots_past_end(observed)
    if not pending:
        _p("no tracked lots have closed since the last sweep")
        return {"checked": 0, "resolved": 0, "sellers": 0, "outcomes": []}

    by_seller: dict[int, dict[int, str]] = {}
    for lot in pending:
        by_seller.setdefault(lot["account_id"], {})[lot["asset_id"]] = (
            lot.get("auction_end_utc") or "")
    _p(f"{len(pending)} closed lots across {len(by_seller)} sellers")

    found: dict[str, dict] = {}
    sellers = sorted(by_seller, key=lambda a: -len(by_seller[a]))[:max_sellers]
    asked: set[int] = set()
    for acct in sellers:
        asked.add(acct)
        want = by_seller[acct]
        # Oldest lot we care about from this seller. A big seller has
        # thousands of completed auctions; sorted newest-first we can stop
        # the moment the feed is older than anything we are looking for,
        # which turns an unbounded crawl into a page or two.
        #
        # Both sides of that comparison have to be UTC. The feed carries
        # BOTH assetAuctionEndDate (seller-local) and ...Utc, and comparing
        # the local one against our UTC watermark stops a page early for
        # any seller west of Greenwich -- whose lots were then marked
        # closed having never been looked for.
        ends_wanted = [e for e in want.values() if e]
        oldest = min(ends_wanted) if ends_wanted else ""
        for page in range(1, max_pages + 1):
            try:
                batch, total = gd.search(account_ids=[acct], sold=True,
                                         page=page, rows=rows,
                                         sort_field="auctionclose",
                                         sort_order="desc")
            except urllib.error.HTTPError as e:
                _p(f"  seller {acct}: HTTP {e.code}, skipping")
                break
            if not batch:
                break
            for r in batch:
                if r.get("assetId") in want:
                    found[f"{r['accountId']}-{r['assetId']}"] = r
            time.sleep(POLITE_DELAY)
            # A row with no end date says nothing about how far back the
            # feed has run; letting it in as "" made the minimum zero and
            # stopped paging immediately.
            ends = [(r.get("assetAuctionEndDateUtc") or "")[:19]
                    for r in batch]
            ends = [e for e in ends if e]
            if oldest and ends and min(ends) < oldest[:19]:
                break        # the feed has run past everything we wanted
            if page * rows >= total:
                break

    recs = list(found.values())
    if recs:
        ds.upsert_lots(recs, observed, sold=True)
        ds.upsert_sold(recs, observed)
        ds.record_bids(recs, observed, run)
    # Anything still unresolved AT A SELLER WE ASKED was withdrawn, relisted
    # or simply not in the completed feed. Mark those closed so they stop
    # being offered as biddable; an unknown outcome is still not an open
    # auction. Lots at sellers we never got to must stay open, or one run
    # with a low --max-sellers silently discards every one of them: they
    # would leave the open set, never be asked about again, and their
    # hammer prices would be lost to the feedback loop for good.
    stale = [l["key"] for l in pending
             if l["key"] not in found and l["account_id"] in asked]
    ds.mark_closed(stale, observed)

    outcomes = [{"key": k, "hammer": float(r.get("currentBid") or 0),
                 "title": r.get("assetShortDescription") or ""}
                for k, r in found.items() if r.get("currentBid")]
    skipped = len(pending) - len(outcomes) - len(stale)
    _p(f"resolved {len(outcomes)} of {len(pending)} "
       f"({len(stale)} closed with no result recorded"
       + (f", {skipped} left open at sellers not asked this run)" if skipped
          else ")"))
    return {"checked": len(pending), "resolved": len(outcomes),
            "sellers": len(asked), "deferred": skipped, "outcomes": outcomes}


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


# Sold lots of this size or larger are treated as bulk; between 2 and 4 a
# lot is neither a clean single-unit comp nor a pallet, and is skipped.
BULK_MIN_UNITS = 5


def observation_for(key: str, title: str, price: float, units: int,
                    mix: list[dict], end=None, state=None) -> tuple | None:
    """One priced observation from one sold lot, or None if unusable.

    The single source of these rules. They used to be written out in each
    of the three places that needed them -- the two sweep builders and the
    backtest -- so a change to, say, the exact-manifest tolerance would
    silently give the backtest a different training population from the
    production fit, which is exactly the thing that invalidates an
    out-of-sample claim.

    Returns ("single" | "basket", record).
    """
    if not price or price <= 0 or units is None:
        return None
    if units == 1:
        m = specs.machine_from_text(title, 1)
        if not m.cpu:
            return None          # a single with no CPU prices nothing
        return "single", {"key": key, "price": float(price), "title": title,
                          "machine": m.to_dict(), "end": end, "state": state}
    if units < BULK_MIN_UNITS:
        return None
    got = sum(m.get("qty", 1) for m in mix)
    return "basket", {
        "key": key, "price": float(price), "title": title,
        "stated_units": units, "manifest_units": got,
        "exact": bool(mix) and abs(got - units) <= max(1, units * 0.05),
        "mix": list(mix),
        "fallback": specs.machine_from_text(title, units).to_dict(),
        "end": end, "state": state,
    }


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
        mix_d = []
        if n >= BULK_MIN_UNITS:
            mix_d, spent = manifest_mix(key, r.get("accountId"),
                                        r.get("assetId"), manifests,
                                        detail_budget > 0)
            if spent:
                detail_budget -= 1
        obs = observation_for(key, title, price, n, mix_d,
                              end=r.get("assetAuctionEndDate"),
                              state=r.get("locationState"))
        if obs is None:
            continue
        (singles if obs[0] == "single" else baskets).append(obs[1])

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

        mix = []
        if n >= BULK_MIN_UNITS:
            mix, spent = manifest_mix(key, lot.get("account_id"),
                                      lot.get("asset_id"), manifests,
                                      detail_budget > 0)
            if spent:
                detail_budget -= 1
        obs = observation_for(key, title, price, n, mix,
                              end=lot.get("auction_end"),
                              state=(lot.get("location") or {}).get("state"))
        if obs is None:
            continue
        (singles if obs[0] == "single" else baskets).append(obs[1])

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
