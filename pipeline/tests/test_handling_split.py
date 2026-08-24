"""Sorting a charger is not testing and wiping a PC.

One handling rate for both is not caution, it is a defect. At $3 a unit
handling comes to 121% of expected revenue on the median charger pallet,
and all 21 in the backtest corpus get a max bid of zero however cheap they
are -- the tool cannot recommend one at any price.
"""

from pcpartscan import grade


def test_the_split_is_off_until_the_rates_differ():
    cfg = grade.Config()
    assert cfg.for_family("part") is cfg
    assert cfg.for_family("computer") is cfg
    assert cfg.for_family(None) is cfg


def test_only_parts_take_the_part_rate():
    cfg = grade.Config(per_unit_handling=4.0, part_handling=0.5)
    assert cfg.for_family("part").per_unit_handling == 0.5
    assert cfg.for_family("computer").per_unit_handling == 4.0
    # an unread lot is not a part lot; it keeps the machine rate
    assert cfg.for_family(None).per_unit_handling == 4.0


def test_the_original_config_is_never_mutated():
    cfg = grade.Config(per_unit_handling=4.0, part_handling=0.5)
    cfg.for_family("part")
    assert cfg.per_unit_handling == 4.0


def test_a_cheap_part_lot_becomes_biddable_at_a_sane_rate():
    """300 chargers worth about $4.20 a unit."""
    revenue = 300 * 4.20 * 0.9 * 0.55
    machine = grade.Config()
    assert machine.for_family("part").max_hammer(revenue, 300) == 0.0
    split = grade.Config(part_handling=0.25)
    assert split.for_family("part").max_hammer(revenue, 300) > 0.0
    # and the machine rate is untouched by the part rate
    assert (split.for_family("computer").max_hammer(revenue, 300)
            == machine.max_hammer(revenue, 300))


def test_breakeven_says_what_the_rate_would_have_to_be():
    v = grade.Valuation(
        lot_key="1-1", title="chargers", account_id=1, asset_id=1, units=300,
        current_bid=0.0, end_date="", state=None, exact_manifest=False)
    v.expected_revenue = 624.0
    cfg = grade.Config()
    grade._record_handling(v, cfg)
    assert v.handling_applied == 3.0
    assert v.handling_breakeven == round(624.0 / 1.6 / 300, 2)
    # at exactly the break-even rate there is nothing left to bid
    at_be = grade.Config(per_unit_handling=v.handling_breakeven)
    assert at_be.max_hammer(624.0, 300) < 1.0
