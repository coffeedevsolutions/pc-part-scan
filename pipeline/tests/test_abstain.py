"""A lot we cannot identify gets no price at all.

Without a readable spec sheet every unit falls back to a generic bucket, so
the ceiling is really a function of unit count: 300 laptop power adapters
and 300 i7 desktops come out within a few dollars a unit of each other. The
old behaviour published that number as a bid ceiling anyway, capped at grade
C. Capping is not enough -- a C with $40k of headroom still reads as an
invitation. These lots are now UNRATED and rank last.
"""

from pcpartscan import grade


def _model(per_unit: float):
    class M:
        r2 = 0.9

        def value_mix(self, mix):
            return sum(m.get("qty", 1) for m in mix) * per_unit

    return M()


class _NoEbay:
    enabled = False

    def value(self, machine):        # pragma: no cover - never reached
        return None


def _rec(title: str, bid: float = 100.0):
    return {"accountId": 1, "assetId": 2, "assetShortDescription": title,
            "currentBid": bid, "assetAuctionEndDateDisplay": "",
            "locationState": "TX"}


def _value(title: str, monkeypatch, per_unit: float = 80.0):
    # no network: the grader must fall back to inferring the mix from title
    monkeypatch.setattr(grade.harvest, "fetch_manifest",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    return grade.value_lot(_rec(title), _model(per_unit), None, _NoEbay(),
                           grade.Config())


def test_unidentifiable_lot_is_unrated(monkeypatch):
    v = _value("Lot of 300 laptop power adapters", monkeypatch)
    assert v.units == 300
    assert v.identified_units == 0
    assert v.contents_known is False
    assert v.grade == grade.UNRATED


def test_identified_lot_still_gets_a_letter(monkeypatch):
    v = _value("Lot of 25 Dell Optiplex 7050 SFF i5-7500 desktops", monkeypatch)
    assert v.identified_units == v.units
    assert v.contents_known is True
    assert v.grade in ("A", "B", "C", "D", "F")


def test_unrated_sorts_after_every_letter():
    # "grade at least D" filters compare letters directly, so the abstention
    # has to lose that comparison rather than sneak through as a blank
    assert all(grade.UNRATED > g for g in ("A", "B", "C", "D", "F"))


def test_partial_identification_needs_a_majority():
    assert grade._contents_known(49, 100) is False
    assert grade._contents_known(50, 100) is True
    assert grade._contents_known(0, 0) is False


def test_abstention_beats_a_generous_grade():
    # the arithmetic says A; not knowing the contents overrules it
    assert grade._grade(0.95, 1.0) == "A"
    assert grade._grade(0.95, 1.0, contents_known=False) == grade.UNRATED


def test_a_lot_with_no_stated_count_is_not_priced_as_one(monkeypatch):
    """"LAPTOPS" is a pallet, and a pallet is not one laptop.

    Every number in the system is per unit, so a missing count silently
    became units=1 -- which turned a pallet into a $21 max bid and hid it at
    the bottom of the board rather than flagging it as unreadable.
    """
    v = _value("LAPTOPS", monkeypatch)
    assert v.count_known is False
    assert v.contents_known is False
    assert v.grade == grade.UNRATED


def test_a_stated_count_is_still_used(monkeypatch):
    v = _value("LAPTOPS APPROX 150", monkeypatch)
    assert v.count_known is True
    assert v.units == 150


def test_a_spec_sheet_settles_a_count_the_title_never_gave(monkeypatch):
    """"PALLET OF DESKTOPS" with a readable 40-machine sheet is 40 machines.

    The count started at a provisional 1 and the manifest was then checked
    for agreement with it -- so any sheet listing three or more machines
    failed the tolerance, and a fully identified lot went UNRATED for
    having "no stated count".
    """
    machines = [{"cpu": "i5-8500", "qty": 40, "ram_gb": 8}]
    monkeypatch.setattr(grade.harvest, "fetch_manifest",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    v = grade.value_lot(_rec("PALLET OF DESKTOPS"), _model(80.0), None,
                        _NoEbay(), grade.Config(),
                        manifests={"1-2": {"machines": machines}})
    assert v.units == 40
    assert v.count_known is True
    assert v.exact_manifest is True
    assert v.contents_known is True
    assert v.grade != grade.UNRATED


def test_a_stated_count_is_still_reconciled_against_the_sheet(monkeypatch):
    """A title that DOES give a number keeps the agreement check."""
    monkeypatch.setattr(grade.harvest, "fetch_manifest",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    v = grade.value_lot(_rec("Lot of 40 Dell OptiPlex desktops"), _model(80.0),
                        None, _NoEbay(), grade.Config(),
                        manifests={"1-2": {"machines":
                                           [{"cpu": "i5-8500", "qty": 3}]}})
    assert v.units == 40           # the sheet disagrees, so it is not adopted
    assert v.exact_manifest is False
