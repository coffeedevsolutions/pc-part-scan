"""Golden tests for the title/spec parsing that everything downstream trusts."""

from pcpartscan import specs


def test_unit_count_from_lot_title():
    assert specs.parse_unit_count(
        "Lot of 48 Various Models of Dell OptiPlex Towers/SFF Computers") == 48


def test_unit_count_single_machine():
    assert specs.parse_unit_count("Dell OptiPlex 7050 SFF i5-7500") == 1


def test_unit_count_unstated_plural_is_none():
    assert specs.parse_unit_count("Dell OptiPlex Computers") is None


def test_parse_cpu():
    assert specs.parse_cpu("Dell OptiPlex 7080 i7-10700 16GB") == "i7-10700"


def test_cpu_generation():
    assert specs.cpu_generation("i7-10700") == 10
    assert specs.cpu_generation("i5-4590") == 4


def test_machine_from_text_roundtrip():
    m = specs.machine_from_text("Dell OptiPlex 7050 SFF i5-7500 8GB RAM", 1)
    d = m.to_dict()
    assert d["cpu"] == "i5-7500"
    assert d["qty"] == 1


# --- a dash introduces a size as often as it introduces a count ----------
# "Samsung Monitors - 27 Inch" read as a 27-unit pallet, so a single $40
# monitor entered the per-class comps at $1.48 a unit.

import pytest

from pcpartscan import specs as _specs


@pytest.mark.parametrize("title", [
    "Samsung Monitors - 27 Inch",
    "Lot of Dell Monitors - 24 inch widescreen",
    'Monitor - 27" widescreen',
    "Desk - 60 x 30",
    "Rack - 42 U server cabinet",
    "Cart - 15 lb capacity",
    "Adapter - 90 W barrel",
])
def test_a_measurement_after_a_dash_is_not_a_count(title):
    n = _specs.parse_unit_count(title)
    assert n in (None, 1), f"{title!r} parsed as {n} units"


@pytest.mark.parametrize("title,want", [
    ("Bulk Auction: 40 Dell Latitude 7320 Touchscreen Laptops", 40),
    ("Dell Laptops - Lot of 120 Tested Latitude Laptops", 120),
    ("Tower Desktop Computers - Lot of 31 Dell / Lenovo / HP", 31),
])
def test_a_real_count_after_a_lead_in_still_reads(title, want):
    assert _specs.parse_unit_count(title) == want
