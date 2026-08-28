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


def test_a_single_dropped_slot_in_the_dense_band_does_not_promote():
    """The deliberate cost of a threshold that clears the overnight gap.

    12:17 -> 16:17 with 14:17 dropped is a four-hour gap, under the
    threshold, so it sweeps shallow. That is the accepted trade: a shallow
    sweep still covers four pages, whereas a threshold low enough to catch
    it would fire on every normal overnight run and make `caught_up`
    meaningless. Written down as a choice so it is not mistaken for an
    oversight.
    """
    assert cli.needs_catchup(4.0) is False


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


# --- the threshold has to clear the schedule it is judging -----------------

def _scheduled_hours() -> list[int]:
    """The hours scan.yml actually asks to run at, read from the cron."""
    import pathlib
    import re

    text = (pathlib.Path(__file__).resolve().parents[2]
            / ".github/workflows/scan.yml").read_text()
    hours: set[int] = set()
    for line in re.findall(r'- cron: "([^"]+)"', text):
        fields = line.split()
        assert len(fields) == 5, line
        for part in fields[1].split(","):
            hours.add(int(part))
    return sorted(hours)


def _largest_scheduled_gap(hours: list[int]) -> float:
    """The longest wait the schedule asks for, wrapping past midnight."""
    return max(float((b - a) % 24)
               for a, b in zip(hours, hours[1:] + [hours[0] + 24]))


def test_the_threshold_clears_the_largest_scheduled_gap():
    """Otherwise a perfectly delivered day reports itself as behind.

    The overnight 03:17 -> 08:17 gap is five hours by design. A threshold
    under that promotes the 08:17 run to a deep sweep every single day and
    writes `caught_up: true`, which the weekly health routine reads as the
    scheduler failing. The metric would be poisoned by the schedule it is
    supposed to be measuring — so this test reads the cron rather than
    trusting a comment, and fails if either side moves without the other.
    """
    gap = _largest_scheduled_gap(_scheduled_hours())
    assert gap == 5.0, f"schedule changed: largest gap is now {gap}h"
    assert cli.CATCHUP_AFTER_HOURS > gap, (
        f"CATCHUP_AFTER_HOURS={cli.CATCHUP_AFTER_HOURS} does not clear the "
        f"{gap}h gap the schedule itself asks for")


def test_the_threshold_leaves_slack_for_a_late_start():
    """GitHub starts scheduled jobs late as a matter of course."""
    gap = _largest_scheduled_gap(_scheduled_hours())
    assert cli.CATCHUP_AFTER_HOURS - gap >= 1.0


def test_a_normal_overnight_gap_is_not_a_catch_up():
    """03:17 -> 08:17, delivered exactly on time, plus a late start."""
    assert cli.needs_catchup(5.0) is False
    assert cli.needs_catchup(5.75) is False


def test_the_gap_that_actually_went_unnoticed_still_promotes():
    """08:36 -> 16:14 on 2026-08-28: three dropped slots, nobody noticed."""
    assert cli.needs_catchup(7.4) is True


# --- the snapshot config the UI seeds from --------------------------------

def test_scan_flag_defaults_match_the_grader_defaults():
    """`snapshot.config` is a base the web app grades from, so it has to
    agree with the defaults the UI calls "default".

    Both pages seed their assumptions with `{...snap.config, ...saved}`, and
    a field is tagged `default` when it equals DEFAULT_CONFIG. If `pcps
    scan` wrote a config that differed from the grader's own defaults, every
    lot would render that value untagged — as a number the user chose, when
    nobody did. Today they agree because the argparse defaults were copied
    from Config; this reads the real parser and fails if either side moves
    alone.
    """
    from pcpartscan import grade

    args = cli.build_parser().parse_args(["scan"])
    cfg = grade.Config()
    for name in ("target_roi", "recovery", "buyer_premium"):
        assert getattr(args, name) == getattr(cfg, name), (
            f"pcps scan's --{name.replace('_', '-')} default "
            f"({getattr(args, name)}) has drifted from Config.{name} "
            f"({getattr(cfg, name)})")
