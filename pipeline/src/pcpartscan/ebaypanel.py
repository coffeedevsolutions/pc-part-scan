"""What you actually get for a machine, measured on eBay rather than assumed.

`Config.recovery` is the single most consequential number in the grader --
sweeping it 0.55 -> 2.00 moves the backtest win rate from 14% to 64%, while
every other lever barely registers. Until now it was a number somebody had
to type in, which is the one kind of input this system is supposed to refuse.

The obvious way to measure it is eBay's Marketplace Insights API, which
serves true sold prices. We are not getting access to it. So this module
measures the same thing the long way round, from the Browse API we do have.

THE TRICK. Browse returns ACTIVE listings only -- asks, not sales. But most
used-computer listings are fixed-price Good 'Til Cancelled, which renew
themselves indefinitely: left alone, a GTC listing does not expire, it just
sits there. So a GTC listing that was up yesterday and is gone today has
almost certainly sold, at the price it was last asking. Poll the same
queries daily, keep every item you have ever seen, and the disappearances
are a sold-comp feed that eBay never had to hand you.

WHAT THAT BUYS. Two numbers the grader has never had:

  recovery   median(eBay sale, net of fees) / median(GovDeals single sale)
             for the same CPU -- literally "what you get for it" over "what
             it costs you", which is the definition of Config.recovery.
  days_to_sell
             how long the money is tied up. A 2.5x recovery that takes five
             months to realise is a worse business than 1.4x in three weeks,
             and price alone cannot tell you which one you are looking at.

WHAT IT IS NOT. Four honest caveats, all of them recorded in the data rather
than absorbed silently:

  * A listing can leave the search result set without selling -- the seller
    pulled it, or it fell out of the top N on relevance. Confirmation via
    getItem separates "vanished from search" from "definitely ended", and
    `sales()` counts only what the caller asks it to count.
  * Best-offer listings sell BELOW the asking price by an unknown amount, so
    counting them at ask biases recovery up. They are flagged and reported
    as a separate band rather than mixed in.
  * Auctions end on a timer whether or not they sold, and Browse never says
    what they fetched. They are excluded from price entirely.
  * eBay listings are for machines with a drive, an OS and often a warranty.
    GovDeals pallets frequently have none of those (`Drive: no` on every
    line of a manifest is normal). The gap between the two is refurb work,
    which is `per_unit_handling` -- so a recovery measured here and a $3
    handling rate cannot both be right. `recovery()` reports the CPU-level
    detail so that trade can be seen rather than assumed away.
"""

from __future__ import annotations

import datetime as dt
import re

# eBay's final value fee for Computers/Tablets & Networking: 13.25% of the
# total (item + shipping) plus a fixed charge per order. Check these against
# your own seller account -- a store subscription changes them.
FEE_RATE = 0.1325
FEE_FIXED = 0.40

# A listing has to survive at least this many polls before its disappearance
# means anything. One poll is not evidence: an item that shows up once and
# is gone the next day is at least as likely to have been a ranking artefact
# as a sale.
MIN_POLLS = 2

# Per-CPU comp counts below which a ratio is an anecdote. Sales and asks
# get separate thresholds because they are separate populations: a busy CPU
# has fifty live listings and, over a month, perhaps five sales. One
# constant for both would either throw away most of the ask evidence or
# accept a single sale as a comp.
MIN_EBAY_SALES = 3
MIN_ASKS = 5
MIN_GOVDEALS_SALES = 2
# Per-CPU ratios needed before the pooled recovery figure is reported at all.
MIN_CPUS = 5

# A ratio outside this band means the two queries matched different things --
# a bare CPU model number pulling in loose processors, a workstation matched
# against a thin client -- not that the market moved.
RATIO_BOUNDS = (0.2, 20.0)


# eBay leaf categories. Searching the wrong one is not a small loss of
# precision: "desktop computer i5-8365u" in PC Desktops matches barebones
# shells and loose parts, because that CPU only ever shipped in laptops.
CATEGORY_DESKTOP = "179"        # PC Desktops & All-In-Ones
CATEGORY_LAPTOP = "177"         # PC Laptops & Netbooks

# Intel mobile parts, by how Intel names them. U is the low-power laptop
# line and H/HQ/HK the high-power one, both written as a trailing letter
# ("i5-8365u"); Y is written as an infix instead ("m3-7Y30"); and the Core
# m3/m5/m7 family is laptop-and-tablet-only whatever its digits say.
# Everything else -- K, T, S, F, R, bare -- is a desktop part.
#
# Getting this wrong is not a small loss of precision. Half our best-comped
# CPUs are laptop parts (i5-8365u alone has 151 GovDeals comps), and asking
# PC Desktops for one matches barebones shells and loose processors rather
# than machines.
_MOBILE_TAIL = re.compile(r"^\d+(?:hq|hk|u|h|y)$")
_MOBILE_INFIX = re.compile(r"^\d+y\d+$")
_MOBILE_FAMILIES = ("m3", "m5", "m7")


def is_mobile(cpu: str) -> bool:
    """Is this a laptop CPU? Decided by the model name, as Intel writes it."""
    name = (cpu or "").strip().lower()
    head, _, tail = name.partition("-")
    if head in _MOBILE_FAMILIES:
        return True
    return bool(_MOBILE_TAIL.match(tail) or _MOBILE_INFIX.match(tail))


def query_for(cpu: str, ram_gb: int | None = None) -> tuple[str, str]:
    """The eBay search text and category for one CPU.

    Returned together because they have to agree: the noun in the query and
    the category filter are two statements of the same belief about what
    kind of machine this CPU lives in, and letting them drift is how you end
    up measuring laptop prices against a desktop comp.
    """
    noun = "laptop" if is_mobile(cpu) else "desktop computer"
    cat = CATEGORY_LAPTOP if is_mobile(cpu) else CATEGORY_DESKTOP
    q = f"{noun} {cpu}" + (f" {ram_gb}GB" if ram_gb else "")
    return q, cat


def normalize(item: dict, cpu: str, ram_gb: int | None, now: str) -> dict | None:
    """One Browse item summary as a panel row, or None if unusable.

    Everything downstream keys off `_id`, `last_price` and `buying_options`,
    so a row missing any of them is dropped here rather than being carried
    as a half-record that later code has to keep testing for.
    """
    item_id = item.get("itemId")
    price = (item.get("price") or {}).get("value")
    if not item_id or price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    opts = [str(o) for o in (item.get("buyingOptions") or [])]
    return {
        "_id": str(item_id),
        "cpu": cpu,
        "ram_gb": ram_gb,
        "title": item.get("title") or "",
        "last_price": price,
        "currency": (item.get("price") or {}).get("currency") or "USD",
        "condition": item.get("condition"),
        "buying_options": opts,
        "auction": "AUCTION" in opts,
        "best_offer": "BEST_OFFER" in opts,
        "seller_score": (item.get("seller") or {}).get("feedbackScore"),
        "item_end_date": item.get("itemEndDate"),
        "last_seen": now,
    }


def query_key(cpu: str, ram_gb: int | None) -> str:
    """Stable identity for one poll target, used to scope disappearances.

    A listing may only be judged missing against the query it was found
    under: it never had a chance to appear in any other.
    """
    return f"{cpu}|{ram_gb or 0}"


def vanished(known: list[dict], seen_ids: set[str], now: str) -> list[dict]:
    """Which previously-live listings were absent from this poll.

    `known` is every live (not yet gone) row recorded under the query that
    was just polled. The caller owns the decision to trust the poll at all:
    a query that errored must not be passed here, or every listing under it
    is falsely marked sold on the strength of an HTTP failure.
    """
    out = []
    for row in known:
        if row["_id"] in seen_ids or row.get("gone_at"):
            continue
        out.append({
            "_id": row["_id"],
            "gone_at": now,
            "gone_reason": "vanished",
            "polls": int(row.get("polls") or 0),
        })
    return out


def _days(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    try:
        t0 = dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
        t1 = dt.datetime.fromisoformat(b.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (t1 - t0).total_seconds() / 86400.0)


def sales(rows: list[dict], include_best_offer: bool = False,
          confirmed_only: bool = False) -> list[dict]:
    """The panel rows that represent a sale at a price we can name.

    Auctions never qualify: Browse does not report what they fetched, so an
    ended auction is a data point about sell-through and about nothing else.

    `confirmed_only` restricts to listings a getItem call confirmed had
    ended, rather than ones that merely stopped appearing in search. It is
    the stricter population and the smaller one; both are reported so the
    difference between them is visible instead of being a choice buried in
    this function.
    """
    out = []
    for r in rows:
        if not r.get("gone_at") or r.get("auction"):
            continue
        if int(r.get("polls") or 0) < MIN_POLLS:
            continue
        if confirmed_only and r.get("gone_reason") != "confirmed_ended":
            continue
        if r.get("best_offer") and not include_best_offer:
            continue
        price = r.get("last_price")
        if not price or price <= 0:
            continue
        # Deliberately no "net" here. It used to carry
        # net_proceeds(price) at the DEFAULT shipping, while recovery()
        # recomputed it from the raw price with the caller's real shipping
        # -- so the two disagreed whenever --shipping was set, and the
        # ready-made field was the wrong one. Net proceeds depend on an
        # assumption this function is not told, so it reports the price and
        # lets the caller who owns that assumption apply it.
        out.append({
            "cpu": r.get("cpu"),
            "ram_gb": r.get("ram_gb"),
            "price": float(price),
            "best_offer": bool(r.get("best_offer")),
            "days_listed": _days(r.get("first_seen"), r.get("gone_at")),
        })
    return out


def net_proceeds(price: float, fee_rate: float = FEE_RATE,
                 fee_fixed: float = FEE_FIXED, shipping: float = 0.0) -> float:
    """What lands in your account after eBay takes its cut.

    Shipping defaults to zero because whether you eat it is a fact about how
    you list, not about the market. Set it and every recovery figure moves
    with it -- on a $120 desktop, $35 of freight is most of the margin.
    """
    return max(0.0, price * (1 - fee_rate) - fee_fixed - shipping)


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _by_cpu(singles: list[dict]) -> dict[str, list[float]]:
    """GovDeals single-unit realized prices, grouped by CPU."""
    out: dict[str, list[float]] = {}
    for s in singles:
        cpu = (s.get("machine") or {}).get("cpu")
        price = s.get("price")
        if cpu and price and price > 0:
            out.setdefault(cpu, []).append(float(price))
    return out


def recovery(ebay_sales: list[dict], singles: list[dict],
             shipping: float = 0.0) -> dict:
    """What you realise per unit, as a multiple of the GovDeals single price.

    This is exactly `Config.recovery`: the numerator is what a machine
    fetched on eBay net of fees, the denominator is what the same machine
    fetches sold on its own at a GovDeals auction, which is what the ceiling
    is fitted on.

    Paired per CPU and then pooled as a median of ratios rather than a ratio
    of pools. A ratio of pooled medians would let whichever CPUs happen to
    be common on eBay decide the answer for the whole corpus; the per-CPU
    pairing asks the same question of each model and takes the middle one.
    """
    gd = _by_cpu(singles)
    by_ebay: dict[str, list[float]] = {}
    days: dict[str, list[float]] = {}
    for s in ebay_sales:
        cpu = s.get("cpu")
        if not cpu:
            continue
        by_ebay.setdefault(cpu, []).append(
            net_proceeds(s["price"], shipping=shipping))
        if s.get("days_listed") is not None:
            days.setdefault(cpu, []).append(s["days_listed"])

    per_cpu = []
    for cpu, ebay_prices in sorted(by_ebay.items()):
        got = gd.get(cpu) or []
        if len(ebay_prices) < MIN_EBAY_SALES or len(got) < MIN_GOVDEALS_SALES:
            continue
        e, g = _median(ebay_prices), _median(got)
        if g <= 0:
            continue
        ratio = e / g
        if not (RATIO_BOUNDS[0] <= ratio <= RATIO_BOUNDS[1]):
            continue
        per_cpu.append({
            "cpu": cpu,
            "ratio": round(ratio, 3),
            "ebay_net_median": round(e, 2),
            "govdeals_median": round(g, 2),
            "n_ebay": len(ebay_prices),
            "n_govdeals": len(got),
            "median_days_listed": (round(_median(days[cpu]), 1)
                                   if days.get(cpu) else None),
        })

    ratios = [c["ratio"] for c in per_cpu]
    all_days = [d for ds in days.values() for d in ds]
    return {
        "recovery": round(_median(ratios), 3) if len(ratios) >= MIN_CPUS else None,
        "n_cpus": len(ratios),
        "n_sales": len(ebay_sales),
        "min_cpus": MIN_CPUS,
        "shipping_assumed": shipping,
        "fee_rate": FEE_RATE,
        "median_days_to_sell": round(_median(all_days), 1) if all_days else None,
        "per_cpu": per_cpu,
    }


def ask_bound(live: list[dict], singles: list[dict],
              shipping: float = 0.0) -> dict:
    """What recovery looks like from asking prices alone.

    Available immediately, with no panel history, which is its whole value:
    it can say today whether the current setting is in the right postcode,
    while the measured figure needs weeks of collection.

    It reads HIGH, for two compounding reasons, and is not a substitute for
    the measured number:

      * No listing sells above its own ask, and best-offer listings sell
        below theirs. So each pairing is optimistic.
      * The live pool is a survivor sample. Cheap listings sell and leave;
        over-priced ones stay up and keep being counted. The longer a
        listing has failed to sell, the more times this figure includes it.

    The second effect has no bound, so despite the name this is a strong
    prior rather than a mathematical ceiling: the honest reading is "the
    measured figure will almost certainly come in below this."
    """
    gd = _by_cpu(singles)
    by_cpu: dict[str, list[float]] = {}
    for row in live:
        cpu, price = row.get("cpu"), row.get("last_price")
        if cpu and price and price > 0 and not row.get("auction"):
            by_cpu.setdefault(cpu, []).append(
                net_proceeds(float(price), shipping=shipping))

    per_cpu, ratios = [], []
    for cpu, asks in sorted(by_cpu.items()):
        got = gd.get(cpu) or []
        if len(asks) < MIN_ASKS or len(got) < MIN_GOVDEALS_SALES:
            continue
        a, g = _median(asks), _median(got)
        if g <= 0:
            continue
        ratio = a / g
        if not (RATIO_BOUNDS[0] <= ratio <= RATIO_BOUNDS[1]):
            continue
        ratios.append(ratio)
        per_cpu.append({"cpu": cpu, "ratio": round(ratio, 3),
                        "ask_net_median": round(a, 2),
                        "govdeals_median": round(g, 2),
                        "n_asks": len(asks), "n_govdeals": len(got)})
    return {
        "upper_bound": round(_median(ratios), 3) if len(ratios) >= MIN_CPUS else None,
        "n_cpus": len(ratios),
        "n_listings": len(live),
        "min_cpus": MIN_CPUS,
        "per_cpu": per_cpu,
    }
