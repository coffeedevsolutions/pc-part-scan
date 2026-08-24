"""Per-class comps, and the two ways they are deliberately held down."""

from pcpartscan import classprice, grade


def _lots(title, n, price, units):
    return [{"title": title, "units": units, "price": price} for _ in range(n)]


def test_a_class_needs_enough_comps_before_it_is_used():
    thin = classprice.fit(_lots("Lot of 20 monitors", classprice.MIN_OBS - 1,
                                400.0, 20))
    assert thin.get("monitor") is None
    enough = classprice.fit(_lots("Lot of 20 monitors", classprice.MIN_OBS,
                                  400.0, 20))
    assert enough.get("monitor") is not None


def test_bulk_and_single_comps_are_kept_apart():
    lots = (_lots("Lot of 50 laptops", 10, 1000.0, 50)      # $20/unit
            + _lots("Dell Latitude laptop", 10, 200.0, 1))  # $200 each
    q = classprice.fit(lots).get("laptop")
    assert q.bulk_n == 10 and q.single_n == 10
    assert q.floor_per_unit == 20.0          # the pallet price, at p25
    assert q.single_p50 == 200.0


def test_the_ceiling_cannot_outrun_what_pallets_of_the_same_thing_fetch():
    """The failure that made a 2010 ThinkPad pallet worth $53,000.

    Single-unit sales skew to the good one somebody listed on its own. A
    class ceiling taken from them alone reads far above what a pallet of
    the same class actually implies, so the pallet price -- undiscounted by
    k -- caps it.
    """
    lots = (_lots("Lot of 50 tablets", 12, 1350.0, 50)        # $27/unit
            + _lots("Microsoft Surface tablet", 12, 400.0, 1))
    q = classprice.fit(lots).get("tablet")
    assert q.single_p25 == 400.0
    # pallets say $27/unit; at k=0.6 that implies $45 a unit parts-out
    assert q.ceiling_per_unit(0.6) == 45.0
    # and a healthier k caps it tighter still, never looser than the singles
    assert q.ceiling_per_unit(0.9) == 30.0
    assert q.ceiling_per_unit(0.05) == 400.0


def test_a_class_priced_lot_can_never_beat_the_confidence_gate():
    """Knowing a pallet is laptops is worth a look, never a top grade.

    This path cannot tell an 11th-gen i7 from a 2010 ThinkPad, and that
    difference is the whole trade.
    """
    assert grade.CLASS_MAX_CONFIDENCE < grade.CONFIDENCE_GATE
    assert grade._grade(0.95, grade.CLASS_MAX_CONFIDENCE) == grade.GATED_MAX_GRADE


def test_round_trip_through_the_snapshot():
    table = classprice.fit(_lots("Lot of 30 monitors", 10, 300.0, 30))
    back = classprice.ClassPriceTable.from_dict(table.to_dict())
    assert back.get("monitor").floor_per_unit == table.get("monitor").floor_per_unit
