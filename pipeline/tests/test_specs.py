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
