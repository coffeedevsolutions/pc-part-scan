"""The 300-charger lot, end to end.

Before item classes existed this lot carried a max bid of $5,470 and a
grade of C: the machine model had no feature meaning "charger", so all 300
units fell into a generic bucket at $69 each. Sold comps put laptop
chargers between $1 and $5.25 a unit across nineteen pallets.
"""

from pcpartscan import classprice, grade


class _Model:
    r2 = 0.9

    def value_mix(self, mix):
        # the generic bucket, which is exactly what must stop being used here
        return sum(m.get("qty", 1) for m in mix) * 69.0

    def value(self, m):
        return 69.0


class _NoEbay:
    enabled = False

    def value(self, machine):        # pragma: no cover - never reached
        return None


CHARGERS = ("Large Lot of 300+ Laptop AC Adapters - Lenovo ThinkPad, HP, "
            "Motorola, TopSync - Mixed 65W/72W/90W/170W")


def _table():
    lots = [{"title": f"{n} HP OEM 65W Laptop/Desktop Chargers",
             "units": n, "price": n * per}
            for n, per in [(100, 3.0)] * 10 + [(50, 1.0)] * 10]
    return classprice.fit(lots)


def _rec(title, bid):
    return {"accountId": 1, "assetId": 2, "assetShortDescription": title,
            "currentBid": bid, "assetAuctionEndDateDisplay": "",
            "locationState": "ON"}


def _value(title, bid, table, monkeypatch):
    monkeypatch.setattr(grade.harvest, "fetch_manifest",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    return grade.value_lot(_rec(title, bid), _Model(), None, _NoEbay(),
                           grade.Config(), class_table=table)


def test_chargers_are_priced_as_chargers(monkeypatch):
    v = _value(CHARGERS, 2800.0, _table(), monkeypatch)
    assert v.units == 300
    assert v.item_class == "adapter"
    assert v.item_family == "part"
    assert v.priced_by == "class"
    # the generic bucket would have said 300 x $69 = $20,700
    assert v.ceiling < 2000
    assert v.max_bid < v.current_bid          # $2,800 is far too much
    assert v.grade == "F"


def test_an_unpriceable_class_still_abstains(monkeypatch):
    # no comps for chargers at all: better to say nothing than to fall back
    # to the machine model that has no idea what one is
    v = _value(CHARGERS, 2800.0, classprice.ClassPriceTable(), monkeypatch)
    assert v.priced_by is None
    assert v.grade == grade.UNRATED


def test_class_pricing_is_capped_at_grade_c(monkeypatch):
    # a giveaway price on a class-priced lot still cannot earn an A
    v = _value(CHARGERS, 1.0, _table(), monkeypatch)
    assert v.confidence <= grade.CLASS_MAX_CONFIDENCE
    assert v.grade >= grade.GATED_MAX_GRADE   # "C", "D" or "F" -- never A/B


def test_identified_machines_still_take_the_machine_path(monkeypatch):
    v = _value("Lot of 25 Dell Optiplex 7050 SFF i5-7500 desktops", 100.0,
               _table(), monkeypatch)
    assert v.priced_by == "machines"
    assert v.item_class == "desktop"
    assert v.ceiling_sources.get("govdeals_singles")
