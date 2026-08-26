"""Every line of the mix carries what one of its machines is worth.

The lot page could say a pallet held 40 i5-8500s and, separately, that the
lot was worth $3,240 -- with nothing connecting the two. The per-unit price
is what the model actually produced for that spec, so it belongs on the
line, and the line total has to multiply out to the ceiling the valuation
starts from or one of the two numbers is wrong.
"""

from pcpartscan import grade


class _Model:
    r2 = 0.9

    def value(self, machine):
        return 100.0 if machine.get("cpu") == "i7-8700" else 40.0

    def value_mix(self, mix):
        return sum(self.value(m) * m.get("qty", 1) for m in mix)


class _NoEbay:
    enabled = False

    def value(self, machine):        # pragma: no cover - never reached
        return None


def _rec(title: str):
    return {"accountId": 1, "assetId": 2, "assetShortDescription": title,
            "currentBid": 0.0, "assetAuctionEndDateDisplay": "",
            "locationState": "TX"}


def _value(title, monkeypatch, manifests=None):
    monkeypatch.setattr(grade.harvest, "fetch_manifest",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    return grade.value_lot(_rec(title), _Model(), None, _NoEbay(),
                           grade.Config(), manifests=manifests)


def test_each_line_priced_and_the_lines_sum_to_the_ceiling(monkeypatch):
    machines = [{"cpu": "i7-8700", "qty": 10},
                {"cpu": "i3-6100", "qty": 30}]
    v = _value("Lot of 40 Dell OptiPlex desktops", monkeypatch,
               manifests={"1-2": {"machines": machines}})
    assert [m["unit_value"] for m in v.mix] == [100.0, 40.0]
    assert sum(m["unit_value"] * m["qty"] for m in v.mix) == v.ceiling
    assert v.ceiling == 10 * 100.0 + 30 * 40.0


def test_the_manifest_cache_never_learns_a_price(monkeypatch):
    """The mix comes out of the manifests collection; prices must not go in.

    grade.py builds the mix from cached manifest documents. Writing the
    valuation onto those dicts would put a model output into the manifest
    store, where the next run would read it back as if it were something
    the seller's spec sheet had said.
    """
    machines = [{"cpu": "i7-8700", "qty": 40}]
    cache = {"1-2": {"machines": machines}}
    _value("Lot of 40 Dell OptiPlex desktops", monkeypatch, manifests=cache)
    assert "unit_value" not in machines[0]
    assert "unit_value" not in cache["1-2"]["machines"][0]


def test_a_class_priced_lot_puts_the_one_rate_on_every_line(monkeypatch):
    """One price for the kind of thing, so one price on each line."""
    quote = grade.classprice.ClassQuote(
        item_class="adapter", family="part", single_n=40, single_p25=6.0, single_p50=9.0,
        single_p75=14.0, bulk_n=12, bulk_p25=2.0, bulk_p50=3.0,
        bulk_p75=4.0)
    v = _value("Lot of 300 laptop power adapters", monkeypatch)
    got = grade._value_by_class(v, quote, grade.Config(), 0.60)
    per_unit = round(quote.ceiling_per_unit(0.60), 2)
    assert per_unit > 0
    assert all(m["unit_value"] == per_unit for m in got.mix)
