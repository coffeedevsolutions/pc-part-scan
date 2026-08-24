"""Reading what a lot holds out of the title sellers actually wrote.

Every title below is real, taken from the sold corpus or the live board.
They are here because each one broke a rule that looked obviously correct
until it met them.
"""

import pytest

from pcpartscan import classify as C


@pytest.mark.parametrize("title,want", [
    # --- the plain cases -------------------------------------------------
    ("Lot of 41 Various Models of Dell OptiPlex SFF Computers", "desktop"),
    ("Lot of 227 Apple Macbook Pro/Air laptops. (majority 2010-2017)", "laptop"),
    ("(19) monitors", "monitor"),
    ("Lot of 45 Kensington SD4750P USB-C 3.0 Dual 4K Hybrid Docking Stations",
     "dock"),

    # --- the head of a compound noun is its last word --------------------
    # "laptop" here is an adjective saying which kind of adapter.
    ("Large Lot of 300+ Laptop AC Adapters - Lenovo ThinkPad, HP", "adapter"),
    ("100 HP OEM 45W Blue Tip Connector Laptop/Desktop Chargers", "adapter"),
    ("Lot of 9 Computer Monitors", "monitor"),
    ("30 Dell E1916H desktop computer Monitors - 1 broken", "monitor"),
    # ...but a PLURAL noun is never an adjective, so this is three things.
    ("dell laptops monitors and towers", None),

    # --- a spec is not a subject -----------------------------------------
    # These read as pallets of hard drives until the attribute rule landed.
    ("(LOT OF 83 ) HP Chromebox G2 (Model 7LJ57UT#ABA) 32GB SSD, 1.8GHz, "
     "4GB RAM, Celeron 3867U", "desktop"),
    ("Lot of 60 Dell OptiPlex AIO Computers - No SSD's", "aio"),
    ("Computer: Dell OptiPlex 7080 with 24\" Monitor", "desktop"),
    ("Dell Latitude 5420 | 14\" FHD | Core i5-1145G7 | 16GB RAM | "
     "256GB NVMe SSD No OS No Charger", "laptop"),

    # --- itemised lots are mixed lots ------------------------------------
    ("IT- (57) Docking Stations, (1) HP PC, (9) Dell Monitors, Polycom", None),
    ("Lot of 94 Desktop Computers and 95 Computer Monitors Mixed Brands", None),
    ("9 Monitors, 8 HP Desktops, 5 HP Laptops, Cameras and Accessories", None),
    ("LOT OF 25 (MONITORS, LAPTOPS, DESKTOPS, GPS AND HEAD SETS)", None),
    # ...but a list of computer types is still a pallet of computers.
    ("Lot of Dell and HP Brand (29) Desktops and (15) Laptops.", "desktop"),

    # --- things sold FOR computers are not computers ---------------------
    ("lot of (16) TRANSIT CASE for 12 Notebooks, Laptops", None),
    ("Lot of 96 Samsung Monitor Stand Bases & Stand Bodies", None),
    ("Lot of 15 Assorted Monitor Desk Mounts", None),

    # --- a chassis number is not a count ---------------------------------
    ("25 x Dell OptiPlex 5250 All-in-One desktop computers for parts", "aio"),
    ("Dell Optiplex 7490 AIO Computer **No Stand", "aio"),
    ("(7) Seven HP Elite Desk 800 (LOT 1)", "desktop"),

    # --- furniture and everything else -----------------------------------
    ("$10 each Training Tables 4 each School Surplus #1", None),
    ("(2) GLASS TOP DESKS  LOT 377", None),
])
def test_classification(title, want):
    assert C.classify(title).item_class == want


def test_abstentions_say_why():
    r = C.classify("9 Monitors, 8 HP Desktops, 5 HP Laptops")
    assert not r.known
    assert r.reason and not r.reason.endswith(".")
    assert r.confidence == 0.0


def test_families():
    assert C.classify("(19) monitors").family == "part"
    assert C.classify("Lot of 25 laptops").family == "computer"
    assert C.family_of("adapter") == "part"
    assert C.family_of("desktop") == "computer"
    assert C.family_of(None) is None


def test_several_computer_kinds_still_prices_as_computers():
    # Which label wins between two computer classes barely matters -- both
    # go to the machine model -- so this records the behaviour rather than
    # arguing for it. What matters is that it does not abstain.
    r = C.classify("Lot of 13 Surface Pro 7+ Laptops")
    assert r.family == "computer"
    assert set(r.candidates) == {"laptop", "tablet"}
    assert r.confidence < 0.9      # less sure than a single-class reading
