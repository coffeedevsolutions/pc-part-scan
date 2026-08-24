"""eBay tells us what sellers are asking, never what anything fetched.

Marketplace Insights, which serves true sold prices, is restricted and we
are not getting it. The Browse API we do have returns ACTIVE listings, and
an active listing is by definition one that has not sold at that price.
Feeding an ask into the parts-out ceiling unadjusted would inflate every
lot it touched, so the ask-to-realized ratio is measured against our own
realized GovDeals singles before the source is allowed to speak.
"""

import pytest

from pcpartscan import pricing


class _Fake(pricing.EbayAdapter):
    """An adapter with credentials and a canned answer per CPU."""

    def __init__(self, asks):
        super().__init__()
        self.enabled = True
        self._asks = asks
        self.calls = 0

    def ask(self, machine):
        self.calls += 1
        return self._asks.get(machine.get("cpu"))


def _singles(pairs):
    """Two realized sales per CPU, so no CPU is a single anecdote."""
    out = []
    for cpu, price in pairs:
        out += [{"machine": {"cpu": cpu}, "price": price},
                {"machine": {"cpu": cpu}, "price": price}]
    return out


def _cpus(n, ask, realized):
    return ({f"i5-{8000 + i}": ask for i in range(n)},
            [(f"i5-{8000 + i}", realized) for i in range(n)])


def test_the_source_says_nothing_until_the_haircut_is_measured():
    asks, pairs = _cpus(pricing.EbayAdapter.MIN_CALIBRATION_PAIRS - 1, 200.0, 100.0)
    a = _Fake(asks)
    assert a.calibrate(_singles(pairs)) is None
    assert a.haircut is None
    # and with no haircut it contributes nothing, whatever the ask says
    assert a.value({"cpu": "i5-8000"}) is None


def test_the_haircut_is_the_median_realized_to_ask_ratio():
    asks, pairs = _cpus(pricing.EbayAdapter.MIN_CALIBRATION_PAIRS, 200.0, 100.0)
    a = _Fake(asks)
    assert a.calibrate(_singles(pairs)) == pytest.approx(0.5)
    assert a.haircut_n == pricing.EbayAdapter.MIN_CALIBRATION_PAIRS
    # an ask of $300 is then worth $150 to the ceiling, not $300
    a._asks["i9-9900"] = 300.0
    assert a.value({"cpu": "i9-9900"}) == pytest.approx(150.0)


def test_an_ask_below_the_realized_price_is_a_bad_match_not_a_bargain():
    """A ratio over 1 means the query matched something else entirely."""
    asks, pairs = _cpus(pricing.EbayAdapter.MIN_CALIBRATION_PAIRS, 50.0, 400.0)
    a = _Fake(asks)
    assert a.calibrate(_singles(pairs)) is None
    assert a.haircut_n == 0


def test_one_sale_is_an_anecdote_not_a_comp():
    asks, pairs = _cpus(pricing.EbayAdapter.MIN_CALIBRATION_PAIRS, 200.0, 100.0)
    a = _Fake(asks)
    lonely = [{"machine": {"cpu": cpu}, "price": p} for cpu, p in pairs]
    assert a.calibrate(lonely) is None


def test_no_credentials_means_no_calibration_and_no_calls():
    a = pricing.EbayAdapter()
    a.enabled = False
    assert a.calibrate(_singles(_cpus(50, 200.0, 100.0)[1])) is None
    assert a.value({"cpu": "i5-8500"}) is None


def test_marketplace_insights_is_gone_for_good():
    # its absence is the reason the haircut exists; a stray re-introduction
    # would quietly turn asks back into "sold prices"
    assert not hasattr(pricing.EbayAdapter, "INSIGHTS_URL")
    assert "EBAY_INSIGHTS" not in pricing.EbayAdapter.__init__.__code__.co_names
