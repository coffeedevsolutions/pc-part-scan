"""Finding out what the lots we priced actually sold for.

A lot only ever stopped being "open" if the keyword sweep happened to
surface it again. For a lot we graded that is left to chance: its end time
passes, it sits on the board reading "closed", and the one number that
would say whether our max bid was any good never arrives.
"""

import pytest

from pcpartscan import harvest


class _Store:
    """Just enough of the store for resolve_closed, recording what it did."""

    def __init__(self, pending):
        self.pending = pending
        self.closed: list[str] = []
        self.sold: list[dict] = []

    def run_id(self):
        return "TESTRUN"

    def utcnow(self):
        return "2026-08-24T23:00:00Z"

    def open_lots_past_end(self, now):
        return self.pending

    def mark_closed(self, keys, at):
        self.closed.extend(keys)
        return len(keys)

    def upsert_lots(self, recs, at, sold):
        self.sold.extend(recs)

    def upsert_sold(self, recs, at):
        pass

    def record_bids(self, recs, at, run):
        return len(recs)


def _lot(key, acct, asset, end="2026-08-24T18:00:00Z"):
    return {"key": key, "account_id": acct, "asset_id": asset,
            "auction_end_utc": end, "title": key}


@pytest.fixture
def store(monkeypatch):
    def _make(pending):
        s = _Store(pending)
        monkeypatch.setattr(harvest, "ds", s)
        monkeypatch.setattr(harvest, "POLITE_DELAY", 0)
        return s
    return _make


def _row(acct, asset, bid, end_utc, local=None):
    """One completed-auction row as the API returns it.

    The feed carries BOTH end dates: assetAuctionEndDate in the seller's
    local time and assetAuctionEndDateUtc. Only the second is comparable
    with our stored watermark.
    """
    return {"accountId": acct, "assetId": asset, "currentBid": bid,
            "isSoldAuction": True, "assetShortDescription": f"lot {asset}",
            "assetAuctionEndDateUtc": end_utc,
            "assetAuctionEndDate": local if local is not None else end_utc}


def _feed(rows):
    """A seller's completed-auction feed, newest first."""
    def search(*, account_ids, sold, page, rows_=None, **kw):
        assert sold is True
        assert kw.get("sort_field") == "auctionclose", \
            "the feed must be newest-first or big sellers are never reached"
        per = kw.get("rows", 100)
        mine = [r for r in rows if r["accountId"] == account_ids[0]]
        start = (page - 1) * per
        return mine[start:start + per], len(mine)
    return search


def test_it_records_what_a_tracked_lot_fetched(store, monkeypatch):
    s = store([_lot("7-1", 7, 1), _lot("7-2", 7, 2)])
    monkeypatch.setattr(harvest.gd, "search", _feed([
        _row(7, 1, 500.0, "2026-08-24T18:00:00"),
        _row(7, 2, 250.0, "2026-08-24T17:00:00"),
    ]))
    res = harvest.resolve_closed()
    assert res["resolved"] == 2
    assert {o["hammer"] for o in res["outcomes"]} == {500.0, 250.0}
    assert s.closed == []          # nothing left unexplained


def test_a_lot_with_no_result_still_stops_being_biddable(store, monkeypatch):
    """Withdrawn, relisted, or simply absent -- it is still not an auction."""
    s = store([_lot("7-1", 7, 1), _lot("7-9", 7, 9)])
    monkeypatch.setattr(harvest.gd, "search", _feed([
        _row(7, 1, 500.0, "2026-08-24T18:00:00"),
    ]))
    res = harvest.resolve_closed()
    assert res["resolved"] == 1
    assert s.closed == ["7-9"]


def test_it_stops_paging_once_the_feed_predates_what_we_want(store, monkeypatch):
    """A big seller has thousands of completed auctions.

    Sorted newest-first we can stop the moment the feed runs past the
    oldest lot we are looking for, instead of crawling the whole history.
    """
    rows = [_row(7, 1000 + i, 10.0, f"2026-08-{24 - i // 2:02d}T12:00:00")
            for i in range(400)]
    s = store([_lot("7-1000", 7, 1000, "2026-08-24T00:00:00Z")])
    calls = {"n": 0}
    inner = _feed(rows)

    def counting(**kw):
        calls["n"] += 1
        return inner(**kw)

    monkeypatch.setattr(harvest.gd, "search", counting)
    harvest.resolve_closed(rows=50)
    assert calls["n"] <= 2, f"crawled {calls['n']} pages of a 400-row feed"


def test_nothing_to_do_is_not_an_error(store, monkeypatch):
    store([])
    monkeypatch.setattr(harvest.gd, "search",
                        lambda **kw: pytest.fail("should not have searched"))
    res = harvest.resolve_closed()
    assert res == {"checked": 0, "resolved": 0, "sellers": 0, "outcomes": []}


def test_a_seller_we_never_asked_keeps_its_lots_open(store, monkeypatch):
    """--max-sellers is a budget for one run, not a verdict on the rest.

    Marking an unasked seller's lots closed takes them out of the open set
    for good: open_lots_past_end only returns status "open", so the next
    run never retries them and their hammer prices are lost to the feedback
    loop this whole command exists to feed.
    """
    s = store([_lot("7-1", 7, 1), _lot("7-2", 7, 2), _lot("9-5", 9, 5)])
    monkeypatch.setattr(harvest.gd, "search", _feed([
        _row(7, 1, 500.0, "2026-08-24T18:00:00"),
    ]))
    res = harvest.resolve_closed(max_sellers=1)   # only seller 7 is asked
    assert res["resolved"] == 1
    assert s.closed == ["7-2"]        # asked about, not found -> closed
    assert "9-5" not in s.closed      # never asked -> still open
    assert res["deferred"] == 1


def test_the_watermark_is_utc_on_both_sides(store, monkeypatch):
    """A seller west of Greenwich reports local times far behind UTC.

    Comparing those against our UTC watermark stopped paging a page early,
    and the lot we were looking for was then marked closed unresolved.
    """
    # wanted lot closed 2026-08-24T05:00Z; the feed shows it as 22:00 local
    s = store([_lot("7-2", 7, 2, "2026-08-24T05:00:00Z")])
    page1 = [_row(7, 900 + i, 10.0, "2026-08-24T06:00:00",
                  local="2026-08-23T23:00:00") for i in range(50)]
    page2 = [_row(7, 2, 750.0, "2026-08-24T05:00:00",
                  local="2026-08-23T22:00:00")]
    monkeypatch.setattr(harvest.gd, "search", _feed(page1 + page2))
    res = harvest.resolve_closed(rows=50)
    assert res["resolved"] == 1, "stopped paging before reaching the lot"
    assert s.closed == []


def test_a_feed_row_with_no_end_date_does_not_stop_paging(store, monkeypatch):
    s = store([_lot("7-2", 7, 2, "2026-08-24T05:00:00Z")])
    page1 = [_row(7, 900 + i, 10.0, "") for i in range(50)]
    page2 = [_row(7, 2, 750.0, "2026-08-24T05:00:00")]
    monkeypatch.setattr(harvest.gd, "search", _feed(page1 + page2))
    assert harvest.resolve_closed(rows=50)["resolved"] == 1
