"""The backtest has to be harder on the grader than the grader is on itself."""

import pytest

from pcpartscan import backtest, grade


def _lot(key, title, price, acct=1, asset=None):
    return key, {"title": title, "final_price": price,
                 "account_id": acct, "asset_id": asset or int(key.split("-")[1]),
                 "location": {"state": "TX"},
                 "auction_end_utc": "2026-01-01T00:00:00Z"}


def _corpus(n=400):
    """Sold singles the model can learn, plus pallets to predict."""
    sold = {}
    for i in range(n):
        cpu = ["i5-8500", "i7-8700", "i3-8100"][i % 3]
        price = [90.0, 140.0, 60.0][i % 3]
        k, v = _lot(f"1-{1000 + i}", f"Dell OptiPlex 7050 SFF {cpu} 8GB RAM",
                    price, asset=1000 + i)
        sold[k] = v
    for i in range(60):
        k, v = _lot(f"2-{2000 + i}", f"Lot of 20 Dell OptiPlex SFF Computers",
                    600.0, acct=2, asset=2000 + i)
        sold[k] = v
    return sold


def test_a_lot_never_helps_price_itself():
    """The whole point: no lot may appear in the fit that grades it."""
    rows = backtest._sold_rows(_corpus())
    for folds in (3, 5):
        for f in range(folds):
            test = {r["key"] for r in rows if backtest._fold_of(r["key"], folds) == f}
            train = {r["key"] for r in rows if backtest._fold_of(r["key"], folds) != f}
            assert not (test & train)
        # and every lot is tested exactly once
        assigned = [backtest._fold_of(r["key"], folds) for r in rows]
        assert len(assigned) == len(rows)
        assert set(assigned) <= set(range(folds))


def test_fold_assignment_is_stable_across_runs():
    assert backtest._fold_of("11961-61", 5) == backtest._fold_of("11961-61", 5)


def test_the_predicted_bid_is_never_an_input():
    """A lot's own clearing price must not leak in through currentBid."""
    rows = backtest._sold_rows(_corpus(20))
    assert rows and all(r["rec"]["currentBid"] == 0 for r in rows)


def test_it_reports_by_size_because_singles_are_tautological():
    """A single unit is what the single-unit model is fitted to predict.

    Pooling them with pallets makes the ceiling look perfectly calibrated
    when it is only reproducing its own training target.
    """
    rep = backtest.run(_corpus(), {}, folds=3)
    assert rep["n_lots"] > 0
    assert "1 unit" in rep["by_size"]
    assert "5-49" in rep["by_size"]
    # the headline bucket is pallets, not everything
    assert rep["pallets"]["n"] > 0
    assert rep["pallets"]["n"] < rep["n_lots"]


def test_the_win_curve_covers_only_lots_the_board_would_have_shown():
    rep = backtest.run(_corpus(), {}, folds=3)
    curves = rep["win_curves"]
    assert curves["by_target_roi"] and curves["by_recovery"]
    # a lower bar can never win fewer lots
    rates = [c["win_rate"] for c in curves["by_target_roi"]]
    assert rates == sorted(rates, reverse=True)
    rec = [c["win_rate"] for c in curves["by_recovery"]]
    assert rec == sorted(rec)
    # singles are excluded, so the curve population is the pallet population
    assert all(c["n"] <= rep["pallets"]["n"] for c in curves["by_recovery"])


def test_abstentions_are_not_counted_as_wins():
    preds = [
        backtest.Prediction(lot_key="1-1", title="x", units=20, hammer=100.0,
                            grade="U", confidence=0.0, priced_by=None,
                            item_class=None, floor=0.0, ceiling=5000.0,
                            max_bid=0.0, expected_revenue=0.0),
    ]
    curves = backtest.win_curves(preds, grade.Config())
    assert curves["by_recovery"] == []


def test_report_survives_an_empty_corpus():
    rep = backtest.run({}, {}, folds=3)
    assert rep["n_lots"] == 0
    assert "not enough" in backtest.report_text(rep)
