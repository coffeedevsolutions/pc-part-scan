"""Measuring what we get for a machine instead of being told.

Config.recovery decides more than every other setting combined -- 0.55 to
2.00 moves the backtest win rate 14% to 64% -- and it was the one number a
human had to supply. eBay can answer it, but not directly: Browse serves
active listings, and sold prices live behind Marketplace Insights, which we
do not have. So the panel infers sales from listings that stop appearing,
and these tests hold the inference honest.
"""

from pcpartscan import ebaypanel


def _row(**kw):
    base = {"_id": "v1|1|0", "cpu": "i7-4770", "ram_gb": None,
            "last_price": 200.0, "auction": False, "best_offer": False,
            "polls": 5, "first_seen": "2026-08-01T00:00:00Z",
            "gone_at": "2026-08-11T00:00:00Z", "gone_reason": "vanished"}
    base.update(kw)
    return base


def _single(cpu, price):
    return {"key": "1-1", "price": price, "title": "",
            "machine": {"cpu": cpu, "ram_gb": 8}}


# --- what counts as a sale ------------------------------------------------

def test_a_departed_fixed_price_listing_is_a_sale():
    got = ebaypanel.sales([_row()])
    assert len(got) == 1
    assert got[0]["price"] == 200.0
    assert got[0]["days_listed"] == 10.0


def test_a_listing_still_up_is_not_a_sale():
    assert ebaypanel.sales([_row(gone_at=None)]) == []


def test_an_auction_is_never_a_price_observation():
    """Browse never says what an auction fetched, only that it ended."""
    assert ebaypanel.sales([_row(auction=True)]) == []


def test_a_listing_seen_once_is_not_evidence():
    """Appearing and vanishing between two polls is as likely a ranking blip."""
    assert ebaypanel.sales([_row(polls=1)]) == []
    assert len(ebaypanel.sales([_row(polls=ebaypanel.MIN_POLLS)])) == 1


def test_best_offer_is_excluded_unless_asked_for():
    """A best-offer listing sold BELOW its ask by an unknown amount."""
    rows = [_row(best_offer=True)]
    assert ebaypanel.sales(rows) == []
    assert len(ebaypanel.sales(rows, include_best_offer=True)) == 1


def test_confirmed_only_is_the_stricter_population():
    rows = [_row(_id="a", gone_reason="vanished"),
            _row(_id="b", gone_reason="confirmed_ended")]
    assert len(ebaypanel.sales(rows)) == 2
    assert len(ebaypanel.sales(rows, confirmed_only=True)) == 1


# --- disappearance --------------------------------------------------------

def test_only_listings_absent_from_the_poll_are_marked():
    known = [_row(_id="a", gone_at=None), _row(_id="b", gone_at=None)]
    marks = ebaypanel.vanished(known, {"a"}, "2026-08-12T00:00:00Z")
    assert [m["_id"] for m in marks] == ["b"]
    assert marks[0]["gone_reason"] == "vanished"


def test_an_already_gone_listing_is_not_marked_twice():
    assert ebaypanel.vanished([_row(_id="a")], set(), "2026-08-12T00:00:00Z") == []


# --- the ratio ------------------------------------------------------------

def test_recovery_is_ebay_net_over_govdeals_realized():
    """The whole point: what you get, over what it costs you."""
    sales = [{"cpu": "i7-4770", "price": 200.0, "days_listed": 10.0}
             for _ in range(3)]
    singles = [_single("i7-4770", 80.0), _single("i7-4770", 80.0)]
    r = ebaypanel.recovery(sales, singles)
    assert r["n_cpus"] == 1
    c = r["per_cpu"][0]
    # 200 less 13.25% and $0.40, over 80
    assert c["ebay_net_median"] == round(200 * (1 - 0.1325) - 0.40, 2)
    assert c["ratio"] == round(c["ebay_net_median"] / 80.0, 3)


def test_shipping_comes_straight_off_the_ratio():
    sales = [{"cpu": "i7-4770", "price": 200.0} for _ in range(3)]
    singles = [_single("i7-4770", 80.0)] * 2
    free = ebaypanel.recovery(sales, singles)["per_cpu"][0]["ratio"]
    paid = ebaypanel.recovery(sales, singles, shipping=35.0)["per_cpu"][0]["ratio"]
    assert paid < free
    assert round(free - paid, 3) == round(35.0 / 80.0, 3)


def test_a_thin_cpu_is_not_a_comp():
    sales = [{"cpu": "i7-4770", "price": 200.0}]        # one eBay sale
    singles = [_single("i7-4770", 80.0)] * 4
    assert ebaypanel.recovery(sales, singles)["per_cpu"] == []
    sales = [{"cpu": "i7-4770", "price": 200.0}] * 4
    singles = [_single("i7-4770", 80.0)]               # one GovDeals sale
    assert ebaypanel.recovery(sales, singles)["per_cpu"] == []


def test_a_nonsense_ratio_is_a_bad_match_not_a_market_move():
    """A bare model number pulls in loose CPUs, not whole computers."""
    sales = [{"cpu": "i7-4770", "price": 4000.0}] * 3
    singles = [_single("i7-4770", 1.0)] * 2
    assert ebaypanel.recovery(sales, singles)["per_cpu"] == []


def test_pooled_recovery_needs_several_cpus_to_report_at_all():
    def corpus(n):
        sales, singles = [], []
        for i in range(n):
            cpu = f"i{i}-0000"
            sales += [{"cpu": cpu, "price": 200.0}] * 3
            singles += [_single(cpu, 80.0)] * 2
        return sales, singles

    sales, singles = corpus(ebaypanel.MIN_CPUS - 1)
    r = ebaypanel.recovery(sales, singles)
    assert r["recovery"] is None and r["n_cpus"] == ebaypanel.MIN_CPUS - 1

    sales, singles = corpus(ebaypanel.MIN_CPUS)
    r = ebaypanel.recovery(sales, singles)
    assert r["recovery"] is not None


def test_the_median_is_of_ratios_not_of_pools():
    """One CPU being common on eBay must not decide the whole corpus.

    Ratios of 1.0 and 4.0 give a median of 2.5 however many listings sit
    behind each; a ratio of the pooled medians would be dragged toward
    whichever CPU happened to be listed more.
    """
    sales, singles = [], []
    for cpu, price, n in (("a-1", 100.0, 50), ("b-1", 400.0, 3)):
        sales += [{"cpu": cpu, "price": price}] * n
        singles += [_single(cpu, 100.0)] * 2
    for i in range(ebaypanel.MIN_CPUS):        # padding to clear MIN_CPUS
        cpu = f"pad{i}-1"
        sales += [{"cpu": cpu, "price": 200.0}] * 3
        singles += [_single(cpu, 100.0)] * 2
    r = ebaypanel.recovery(sales, singles)
    ratios = {c["cpu"]: c["ratio"] for c in r["per_cpu"]}
    assert ratios["a-1"] < 1.0 < ratios["b-1"]
    assert r["recovery"] == round(ratios["pad0-1"], 3)   # the middle one


# --- the bound available today -------------------------------------------

def test_asks_read_higher_than_the_prices_things_sell_at():
    """The ask figure is optimistic by construction, not a hard ceiling.

    No listing sells above its own ask, and the live pool is a survivor
    sample that keeps re-counting whatever has failed to sell -- so asks
    read high. They are not a mathematical bound on the median of sales,
    which is why this asserts the direction on a matched population rather
    than claiming the inequality always holds.
    """
    live, singles = [], []
    for i in range(ebaypanel.MIN_CPUS):
        cpu = f"i{i}-0000"
        live += [{"cpu": cpu, "last_price": 200.0, "auction": False}] * ebaypanel.MIN_ASKS
        singles += [_single(cpu, 80.0)] * 2
    b = ebaypanel.ask_bound(live, singles)
    assert b["upper_bound"] is not None

    sales = [{"cpu": f"i{i}-0000", "price": 150.0}
             for i in range(ebaypanel.MIN_CPUS) for _ in range(3)]
    measured = ebaypanel.recovery(sales, singles)
    assert measured["recovery"] < b["upper_bound"]


def test_auctions_are_not_asks():
    live = ([{"cpu": "i7-4770", "last_price": 1.0, "auction": True}]
            * (ebaypanel.MIN_ASKS + 2))
    assert ebaypanel.ask_bound(live, [_single("i7-4770", 80.0)] * 2)["per_cpu"] == []


def test_asks_and_sales_have_separate_thresholds():
    """A CPU with fifty listings and four sales is normal, not a defect."""
    singles = [_single("i7-4770", 80.0)] * 2
    thin = [{"cpu": "i7-4770", "last_price": 200.0, "auction": False}
            ] * (ebaypanel.MIN_ASKS - 1)
    assert ebaypanel.ask_bound(thin, singles)["per_cpu"] == []
    assert len(ebaypanel.ask_bound(thin + thin[:1], singles)["per_cpu"]) == 1


# --- normalization --------------------------------------------------------

def test_a_browse_item_becomes_a_panel_row():
    row = ebaypanel.normalize({
        "itemId": "v1|123|0", "title": "Dell OptiPlex i7-4770",
        "price": {"value": "189.99", "currency": "USD"},
        "buyingOptions": ["FIXED_PRICE", "BEST_OFFER"],
        "condition": "Used", "seller": {"feedbackScore": 900},
    }, "i7-4770", 8, "2026-08-01T00:00:00Z")
    assert row["_id"] == "v1|123|0"
    assert row["last_price"] == 189.99
    assert row["best_offer"] is True and row["auction"] is False


def test_an_item_without_a_price_is_dropped():
    assert ebaypanel.normalize({"itemId": "v1|1|0"}, "x", None, "t") is None
    assert ebaypanel.normalize(
        {"price": {"value": "10"}}, "x", None, "t") is None
    assert ebaypanel.normalize(
        {"itemId": "a", "price": {"value": "0"}}, "x", None, "t") is None


# --- asking the right question -------------------------------------------

def test_mobile_cpus_are_searched_as_laptops():
    """Half our best-comped CPUs are laptop parts.

    "desktop computer i5-8365u" in PC Desktops matches barebones shells and
    loose parts: that CPU never shipped in a desktop. The query noun and the
    category have to agree, and both have to follow the CPU.
    """
    for cpu in ("i5-8365u", "i7-10610u", "i7-4700hq", "i9-9880h", "m3-7y30"):
        q, cat = ebaypanel.query_for(cpu)
        assert ebaypanel.is_mobile(cpu), cpu
        assert q.startswith("laptop "), q
        assert cat == ebaypanel.CATEGORY_LAPTOP


def test_desktop_cpus_stay_in_the_desktop_category():
    for cpu in ("i5-10500", "i7-10700", "i7-4790k", "i5-8500t", "i3-9100f",
                "g3420"):
        q, cat = ebaypanel.query_for(cpu)
        assert not ebaypanel.is_mobile(cpu), cpu
        assert q.startswith("desktop computer "), q
        assert cat == ebaypanel.CATEGORY_DESKTOP


def test_ram_is_appended_only_when_known():
    assert ebaypanel.query_for("i5-10500", 16)[0].endswith(" 16GB")
    assert not ebaypanel.query_for("i5-10500", None)[0].endswith("GB")
    assert not ebaypanel.query_for("i5-10500", 0)[0].endswith("GB")


# --- what the caller owns ------------------------------------------------

def test_sales_reports_price_not_net():
    """Net proceeds depend on a shipping assumption sales() is not told.

    It used to emit a `net` computed at the DEFAULT shipping while
    recovery() recomputed one from the raw price with the caller's real
    shipping. The two disagreed the moment --shipping was set, and the
    ready-made field was the wrong one -- so it no longer exists.
    """
    row = ebaypanel.sales([_row()])[0]
    assert "net" not in row
    assert row["price"] == 200.0
