"""A stale empty parse must never be permanent.

An empty manifest is how the pipeline records "we looked and could not read
the sheet". Treating that as final is what collapsed the bulk fit from 41
observations to 13: transient download failures and not-yet-uploaded spec
sheets were cached forever, permanently excluding those lots from the
exact-manifest corpus that fit_basket_model needs.
"""

import datetime as dt

from pcpartscan import harvest


def _ago(days: int) -> str:
    t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _no_fetch(*_a, **_k):
    raise AssertionError("should not have re-fetched")


def test_known_mix_is_reused_without_fetching(monkeypatch):
    monkeypatch.setattr(harvest, "fetch_manifest", _no_fetch)
    mans = {"1-2": {"machines": [{"cpu": "i5-8500", "qty": 4}],
                    "parsed_at": _ago(400)}}
    mix, spent = harvest.manifest_mix("1-2", 1, 2, mans, may_fetch=True)
    assert mix == [{"cpu": "i5-8500", "qty": 4}]
    assert spent is False


def test_recent_empty_parse_is_not_refetched(monkeypatch):
    monkeypatch.setattr(harvest, "fetch_manifest", _no_fetch)
    mans = {"1-2": {"machines": [], "parsed_at": _ago(1)}}
    mix, spent = harvest.manifest_mix("1-2", 1, 2, mans, may_fetch=True)
    assert mix == []
    assert spent is False


def test_stale_empty_parse_is_retried(monkeypatch):
    class M:
        def to_dict(self):
            return {"cpu": "i7-8700", "qty": 2}

    monkeypatch.setattr(harvest, "fetch_manifest", lambda *a, **k: [M()])
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)
    mans = {"1-2": {"machines": [],
                    "parsed_at": _ago(harvest.RETRY_EMPTY_DAYS + 1)}}
    mix, spent = harvest.manifest_mix("1-2", 1, 2, mans, may_fetch=True)
    assert mix == [{"cpu": "i7-8700", "qty": 2}]
    assert spent is True
    # the in-run view is updated so a second pass does not re-fetch
    assert mans["1-2"]["machines"] == [{"cpu": "i7-8700", "qty": 2}]


def test_unknown_lot_without_budget_does_not_fetch(monkeypatch):
    monkeypatch.setattr(harvest, "fetch_manifest", _no_fetch)
    mix, spent = harvest.manifest_mix("1-2", 1, 2, {}, may_fetch=False)
    assert mix == []
    assert spent is False
