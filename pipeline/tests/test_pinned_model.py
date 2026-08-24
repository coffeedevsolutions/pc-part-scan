"""A pinned price must actually replace the fitted one.

The Models page tells the user a pin is "used in valuations". That promise
was not kept when pins were blended in as a rival estimate: a source had to
cover half a lot's units to count at all, so a pin on one CPU in a mixed
pallet changed nothing, and every un-pinned attribute of that source --
RAM included -- was valued at zero.
"""

import numpy as np
import pytest

from pcpartscan import pricing


@pytest.fixture
def base():
    machines = [
        {"cpu": "i5-8500", "ram_gb": 8, "form_factor": "sff", "has_drive": True}
    ] * 6 + [
        {"cpu": "i7-9700", "ram_gb": 16, "form_factor": "tower", "has_drive": True}
    ] * 6
    space = pricing.FeatureSpace(machines)
    coef = np.zeros(len(space))
    coef[space.names.index("cpu=i5-8500")] = 100.0
    coef[space.names.index("cpu=i7-9700")] = 200.0
    coef[space.names.index("ram_gb")] = 5.0
    return pricing._FitModel(space, coef, n_obs=12, r2=0.9)


def test_pin_replaces_the_fitted_price(base):
    m = {"cpu": "i5-8500", "ram_gb": 0, "form_factor": "sff", "has_drive": False}
    assert base.value(m) == pytest.approx(100.0)
    pinned = pricing.PinnedModel(base, {"i5-8500": 250.0})
    assert pinned.value(m) == pytest.approx(250.0)


def test_pin_applies_however_little_of_the_lot_it_covers(base):
    """One pinned CPU among 99 unknown machines still counts."""
    mix = [
        {"cpu": "i5-8500", "ram_gb": 0, "form_factor": "sff", "has_drive": False,
         "qty": 1},
        {"cpu": None, "ram_gb": 0, "form_factor": "sff", "has_drive": False,
         "qty": 99},
    ]
    pinned = pricing.PinnedModel(base, {"i5-8500": 250.0})
    assert pinned.value_mix(mix) - base.value_mix(mix) == pytest.approx(150.0)
    assert pinned.pins_applied(mix) == 1


def test_ram_still_counts_on_a_pinned_machine(base):
    """The fit's RAM adder survives; pinning a CPU is not pricing a whole PC."""
    pinned = pricing.PinnedModel(base, {"i5-8500": 250.0})
    m = {"cpu": "i5-8500", "ram_gb": 16, "form_factor": "sff", "has_drive": False}
    assert pinned.value(m) == pytest.approx(250.0 + 5.0 * 2)


def test_unpinned_cpus_are_untouched(base):
    pinned = pricing.PinnedModel(base, {"i5-8500": 250.0})
    m = {"cpu": "i7-9700", "ram_gb": 0, "form_factor": "tower", "has_drive": False}
    assert pinned.value(m) == pytest.approx(base.value(m))


def test_the_fit_shows_through(base):
    """r2/n_obs/space still read as the underlying fit, for reporting."""
    pinned = pricing.PinnedModel(base, {"i5-8500": 250.0})
    assert pinned.r2 == base.r2
    assert pinned.n_obs == base.n_obs
    assert pinned.to_json()["n_obs"] == 12


def test_explicit_ram_pin_wins(base):
    pinned = pricing.PinnedModel(base, {"i5-8500": 250.0, "_ram_per_8gb": 0.0})
    m = {"cpu": "i5-8500", "ram_gb": 16, "form_factor": "sff", "has_drive": False}
    assert pinned.value(m) == pytest.approx(250.0)
