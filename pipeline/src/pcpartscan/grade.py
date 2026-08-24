"""Grade live GovDeals lots on profitability.

The output that matters is not "is the current bid cheap" -- lots close with a
late bid surge, so a mid-auction snapshot flatters everything. The output is
MAX BID: the most you can pay and still clear your target return. Headroom
(max_bid - current_bid) is then the actionable number, and it stays valid as
the auction runs.

  floor    resale-as-lot value, from the sold BULK-lot model
  ceiling  parts-out value, from the sold SINGLE-unit model (with any
           hand-pinned CPU prices substituted), optionally blended with eBay
  target   the blend you actually underwrite against (see Config.recovery)
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

from . import api as gd
from . import harvest
from . import pricing
from . import specs


@dataclass
class Config:
    # --- costs on top of the hammer price -------------------------------
    buyer_premium: float = 0.00   # GovDeals BP varies by seller; set per your account
    sales_tax: float = 0.00       # if you are not tax-exempt
    pickup_cost: float = 0.00     # flat per-lot travel/freight
    per_unit_handling: float = 3.00   # test, wipe, photograph, pack each machine

    # --- what you actually realize --------------------------------------
    # Fraction of the parts-out ceiling you expect to capture after dead units,
    # listing fees, and time. 0.55 is deliberately conservative.
    recovery: float = 0.55
    dead_rate: float = 0.10       # share of units assumed non-functional

    # --- underwriting ----------------------------------------------------
    target_roi: float = 0.60      # required return over all-in cost

    def all_in(self, hammer: float, units: int) -> float:
        return (hammer * (1 + self.buyer_premium) * (1 + self.sales_tax)
                + self.pickup_cost + self.per_unit_handling * units)

    def max_hammer(self, expected_revenue: float, units: int) -> float:
        """Invert all_in() to the highest hammer price meeting target_roi."""
        budget = expected_revenue / (1 + self.target_roi)
        budget -= self.pickup_cost + self.per_unit_handling * units
        denom = (1 + self.buyer_premium) * (1 + self.sales_tax)
        return max(0.0, budget / denom)


@dataclass
class Valuation:
    lot_key: str
    title: str
    account_id: int
    asset_id: int
    units: int
    current_bid: float
    end_date: str
    state: str | None
    exact_manifest: bool
    mix: list = field(default_factory=list)
    # Whether we know what is actually in the lot. False means too few units
    # have an identified CPU, so the rest fell back to a generic bucket and
    # the ceiling is driven by unit count rather than by contents.
    contents_known: bool = True
    identified_units: int = 0
    floor: float = 0.0
    floor_trusted: bool = True
    ceiling: float = 0.0
    ceiling_sources: dict = field(default_factory=dict)
    expected_revenue: float = 0.0
    max_bid: float = 0.0
    headroom: float = 0.0
    roi_at_current: float = 0.0
    confidence: float = 0.0
    grade: str = "F"

    @property
    def url(self):
        return f"https://www.govdeals.com/asset/{self.asset_id}/{self.account_id}"


def _confidence(v: Valuation, single: pricing._FitModel, n_cpu_known: int) -> float:
    """0-1. Driven by manifest quality and how much of the mix we can price."""
    c = 0.35 if v.exact_manifest else 0.10
    if v.units:
        c += 0.35 * min(1.0, n_cpu_known / max(1, v.units))
    c += 0.20 * min(1.0, single.r2)
    c += 0.10 if v.state else 0.0
    return round(min(1.0, c), 2)


# Without a spec sheet we do not know what CPUs are in a lot, so every machine
# falls back to a generic bucket value. That makes the ceiling a function of
# unit count alone -- a 253-unit lot of unknown junk then looks identical to a
# 253-unit lot of 11th-gen i7s. Such an estimate must never earn a top grade.
CONFIDENCE_GATE = 0.50
GATED_MAX_GRADE = "C"

# An independent source must cover at least this share of a lot's units
# before it joins the ceiling blend, so a handful of recognised machines
# cannot be extrapolated across a pallet of unknown ones. This gates rival
# estimates like eBay; pinned prices are not gated, because a pin overrides
# the fit per machine rather than competing with it.
MIN_SOURCE_COVERAGE = 0.5

# Share of a lot's units that must have an identified CPU before we will
# assert a price for the lot at all. Below this, most units priced at a
# generic bucket rate and the ceiling says more about how many things are on
# the pallet than about what they are -- 300 laptop chargers and 300 i7
# desktops come out within a few dollars a unit of each other. Rather than
# publish that number as a bid ceiling we abstain: the lot is UNRATED, still
# listed and still searchable, but with no max bid attached until the
# contents-aware valuation can price what is actually there.
MIN_IDENTIFIED_SHARE = 0.5
UNRATED = "U"


def _contents_known(identified_units: int, units: int) -> bool:
    """Do we know enough about the contents to stand behind a price?"""
    return units > 0 and identified_units >= units * MIN_IDENTIFIED_SHARE


def _grade(roi_headroom: float, confidence: float,
           contents_known: bool = True) -> str:
    """Grade on headroom-to-max-bid, discounted and then GATED by confidence.

    Sorts after "F" so an abstention never passes a "grade at least" filter
    and always ranks below a lot we actually priced.
    """
    if not contents_known:
        return UNRATED
    s = roi_headroom * (0.5 + 0.5 * confidence)
    if s >= 0.60:
        g = "A"
    elif s >= 0.35:
        g = "B"
    elif s >= 0.15:
        g = "C"
    elif s >= 0.0:
        g = "D"
    else:
        g = "F"
    if confidence < CONFIDENCE_GATE and g < GATED_MAX_GRADE:
        return GATED_MAX_GRADE      # "A"/"B" -> "C"; D/F are unaffected
    return g


def value_lot(rec: dict, single, basket, ebay, cfg: Config,
              fetch_manifest: bool = True) -> Valuation:
    title = rec.get("assetShortDescription") or ""
    units = specs.parse_unit_count(title)
    key = f"{rec['accountId']}-{rec['assetId']}"
    unknown_count = units is None
    if unknown_count:
        units = 1        # provisional; a manifest below will correct it

    mix, exact = [], False
    if (unknown_count or units >= 5) and fetch_manifest:
        try:
            ms = harvest.fetch_manifest(rec["accountId"], rec["assetId"])
            mix = [m.to_dict() for m in ms]
            got = sum(m["qty"] for m in mix)
            exact = bool(mix) and abs(got - units) <= max(1, units * 0.05)
            if exact:
                units = got
        except Exception:
            mix = []
    if not mix:
        mix = [specs.machine_from_text(title, units).to_dict()]

    n_cpu_known = sum(m["qty"] for m in mix if m.get("cpu"))

    v = Valuation(
        lot_key=key, title=title, account_id=rec["accountId"],
        asset_id=rec["assetId"], units=units,
        current_bid=float(rec.get("currentBid") or 0),
        end_date=rec.get("assetAuctionEndDateDisplay") or "",
        state=rec.get("locationState"), exact_manifest=exact, mix=mix,
    )

    # --- floor: what the whole lot clears at auction ---------------------
    # Reported either way, but only underwritten against when the bulk fit
    # is sound: a weak fit that reads high would raise max_bid on exactly
    # the pallet-sized lots where being wrong costs the most.
    v.floor = basket.value_mix(mix) if basket else 0.0
    v.floor_trusted = bool(basket and basket.trusted)

    # --- ceiling: parts-out, blended across available sources ------------
    per_source = {}
    per_source["govdeals_singles"] = single.value_mix(mix)

    def priced_source(value_of) -> float | None:
        """Total for a mix under one independent source, or None if sparse.

        A source that knows only a couple of the machines in a mixed pallet
        used to have its total scaled up to the whole lot, which let one
        known price speak for hundreds of unknown units and then carry
        equal weight in the blend. It now has to cover most of the lot
        before it is allowed an opinion at all.
        """
        total, hit = 0.0, 0
        for m in mix:
            val = value_of(m)
            if val is not None:
                total += val * m.get("qty", 1)
                hit += m.get("qty", 1)
        if not hit or hit < units * MIN_SOURCE_COVERAGE:
            return None
        return total * (units / hit) if hit < units else total

    if ebay.enabled:
        ev = priced_source(ebay.value)
        if ev is not None:
            per_source["ebay"] = ev

    v.ceiling_sources = {k: round(x, 2) for k, x in per_source.items()}
    v.ceiling = sum(per_source.values()) / len(per_source)

    # --- what you underwrite against -------------------------------------
    parts_out = v.ceiling * (1 - cfg.dead_rate) * cfg.recovery
    v.expected_revenue = max(parts_out, v.floor) if v.floor_trusted else parts_out

    v.max_bid = cfg.max_hammer(v.expected_revenue, v.units)
    v.headroom = v.max_bid - v.current_bid

    cost_now = cfg.all_in(v.current_bid, v.units)
    v.roi_at_current = (v.expected_revenue - cost_now) / cost_now if cost_now > 0 else 0.0

    v.identified_units = n_cpu_known
    v.contents_known = _contents_known(n_cpu_known, v.units)
    v.confidence = _confidence(v, single, n_cpu_known)
    rel = v.headroom / v.max_bid if v.max_bid > 0 else -1.0
    v.grade = _grade(rel, v.confidence, v.contents_known)
    return v


def load_models():
    obs = harvest.load_observations()
    if not obs.get("singles"):
        raise SystemExit(
            "no priced observations available. Run `python scan.py --full` "
            "to harvest the sold archive first.")
    single = pricing.fit_single_model(obs["singles"])
    try:
        basket = pricing.fit_basket_model(obs["baskets"], single)
    except ValueError as e:
        print(f"  note: basket model unavailable ({e}); floor falls back to 0")
        basket = None
    pricing.save_models(single, basket)
    # Pinned prices override the fit per machine. In store-backed mode they
    # are the ones a human set; in file mode they come from the editable
    # CSV. Either way the floor keeps using the raw fit, since the bulk
    # discount was measured against it.
    from .store import backend as ds
    if hasattr(ds, "component_overrides"):
        pins = ds.component_overrides()
    else:
        pins = pricing.StaticTable().as_pins()
    ceiling_model = pricing.PinnedModel(single, pins) if pins else single
    return ceiling_model, basket, pricing.EbayAdapter()


def scan(live: dict | None = None, cfg: Config | None = None,
         min_units: int = 5, limit: int = 60,
         models: tuple | None = None) -> list[Valuation]:
    cfg = cfg or Config()
    single, basket, ebay = models if models else load_models()
    live = live or harvest._load("live_raw.json", {})

    cands = []
    for k, r in live.items():
        t = r.get("assetShortDescription") or ""
        n = specs.parse_unit_count(t)
        if n is not None and n < min_units:
            continue
        if not specs.parse_form_factor(t) and not specs.parse_cpu(t) \
           and "computer" not in t.lower():
            continue
        cands.append(r)
    cands.sort(key=lambda r: -(r.get("currentBid") or 0))
    cands = cands[:limit]

    out = [value_lot(r, single, basket, ebay, cfg) for r in cands]
    # rank on confidence-weighted headroom: a big number we do not believe
    # should not outrank a smaller one we do. Abstentions have no number to
    # rank on at all, so they go last whatever their arithmetic says.
    out.sort(key=lambda v: (not v.contents_known,
                            -(v.headroom * v.confidence), -v.confidence))
    return out


def report(vals: list[Valuation], top: int = 20) -> str:
    L = []
    L.append(f"{'grade':<6}{'conf':<6}{'lot':<14}{'units':>6}{'bid':>10}"
             f"{'max bid':>10}{'headroom':>10}  closes")
    L.append("-" * 96)
    for v in vals[:top]:
        # An abstention's max bid and headroom are arithmetic on a ceiling we
        # do not stand behind; printing them invites reading them as advice.
        maxbid = f"{v.max_bid:>10,.0f}" if v.contents_known else f"{'—':>10}"
        head = f"{v.headroom:>10,.0f}" if v.contents_known else f"{'—':>10}"
        L.append(f"{v.grade:<6}{v.confidence:<6.2f}{v.lot_key:<14}{v.units:>6}"
                 f"{v.current_bid:>10,.0f}{maxbid}{head}"
                 f"  {v.end_date[:22]}")
        L.append(f"      {v.title[:74]}")
        if v.contents_known:
            L.append(f"      floor ${v.floor:,.0f}  ceiling ${v.ceiling:,.0f} "
                     f"{v.ceiling_sources}  {v.url}")
        else:
            L.append(f"      unrated: {v.identified_units}/{v.units} units "
                     f"identified  {v.url}")
    return "\n".join(L)


if __name__ == "__main__":
    vals = scan()
    print(report(vals))
