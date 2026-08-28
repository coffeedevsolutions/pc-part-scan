"""A scan that runs after a dropped slot has to cover for the one that did not.

GitHub runs `schedule:` on a best-effort queue and sheds jobs under load.
This repo asks for nine scans a day and reliably gets three or four; on
2026-08-28 the 12:00, 14:00 and 16:00 slots all vanished and nothing
noticed, so the board served a snapshot from 08:36 as though it were
current. Nothing inside the repo can make the scheduler fire. What a run
CAN do is notice it is late and sweep deeper, which is exactly what --full
already does -- so a late run promotes itself.
"""

import datetime as dt

from pcpartscan import cli
from pcpartscan.store import mongo


# --- when to catch up -----------------------------------------------------

def test_a_late_run_promotes_itself():
    assert cli.needs_catchup(cli.CATCHUP_AFTER_HOURS) is True
    assert cli.needs_catchup(cli.CATCHUP_AFTER_HOURS + 5) is True


def test_an_on_time_run_stays_shallow():
    """The dense band is every two hours, so two hours is not late."""
    assert cli.needs_catchup(2.0) is False
    assert cli.needs_catchup(0.0) is False


def test_a_first_run_has_nothing_to_catch_up_on():
    """No previous success is an empty store, not a missed slot."""
    assert cli.needs_catchup(None) is False


def test_an_explicit_full_run_is_not_reported_as_a_promotion():
    """--full was already going deep; saying it "caught up" is noise."""
    assert cli.needs_catchup(99.0, already_full=True) is False


def test_the_threshold_catches_a_single_missed_slot():
    """Deliberately eager: a deep sweep costs a minute, a missed slot costs
    lots we never saw."""
    assert cli.CATCHUP_AFTER_HOURS <= 4.0


# --- how late is late -----------------------------------------------------

_NOW = dt.datetime(2026, 8, 28, 16, 0, 0, tzinfo=dt.timezone.utc)


def test_hours_ago_measures_the_real_gap():
    # the actual gap that went unnoticed on 2026-08-28
    assert round(mongo.hours_ago("2026-08-28T08:36:43Z", _NOW), 2) == 7.39
    assert cli.needs_catchup(mongo.hours_ago("2026-08-28T08:36:43Z", _NOW))


def test_a_naive_timestamp_is_read_as_utc():
    """The pipeline writes naive UTC; reading it as local time would shift
    every gap by the runner's offset."""
    aware = mongo.hours_ago("2026-08-28T14:00:00Z", _NOW)
    naive = mongo.hours_ago("2026-08-28T14:00:00", _NOW)
    assert aware == naive == 2.0


def test_a_missing_or_unparseable_timestamp_is_not_a_gap():
    """None must mean "cannot tell", never "infinitely late" -- a parse bug
    would otherwise promote every run to a deep sweep forever."""
    assert mongo.hours_ago(None, _NOW) is None
    assert mongo.hours_ago("", _NOW) is None
    assert mongo.hours_ago("not a date", _NOW) is None
    assert cli.needs_catchup(mongo.hours_ago(None, _NOW)) is False


def test_a_future_timestamp_clamps_to_zero():
    """Clock skew between runners must not read as a negative gap."""
    assert mongo.hours_ago("2026-08-28T18:00:00Z", _NOW) == 0.0
