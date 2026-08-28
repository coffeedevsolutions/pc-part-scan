"""The collector must survive an eBay that answers searches but not items.

Confirmations are the one call made in an unbounded loop -- one per
departure, across every CPU -- so a getItem endpoint that times out instead
of answering is the failure mode that can take out the whole daily run:
max_confirm x max_cpus x CALL_TIMEOUT is hours against a job capped at
twenty minutes. Polling is also the part that cannot be caught up later. A
day of departures nobody recorded is simply gone, so when something has to
give, it has to be the confirmations.
"""

import argparse
import types

import pytest

from pcpartscan import cli, ebaypanel, pricing


class _Store:
    """Enough of store.mongo to run cmd_ebay_watch, in memory."""

    def __init__(self, live=None):
        self.live = list(live or [])
        self.polls, self.marked, self.finished = [], [], None

    # -- the bits cmd_ebay_watch calls
    def run_id(self):
        return "TESTRUN"

    def utcnow(self):
        return "2026-08-12T00:00:00Z"

    def job_start(self, *_a):
        pass

    def job_finish(self, _job, _run, status="ok", counts=None, error=None):
        self.finished = {"status": status, "counts": counts, "error": error}

    def record_ebay_poll(self, qk, cpu, ram, n, ok):
        self.polls.append({"qk": qk, "ok": ok, "n": n})

    def upsert_ebay_listings(self, rows, _qk):
        return {"new": len(rows), "seen": len(rows)}

    def live_ebay_listings(self, qk=None):
        return [r for r in self.live if qk is None or r.get("query_key") == qk]

    def mark_ebay_gone(self, marks):
        self.marked.extend(marks)
        return len(marks)

    def ebay_panel_stats(self):
        return {"listings": 0, "live": 0, "ended": 0, "confirmed": 0,
                "polls": len(self.polls)}


class _Adapter:
    """Search works; the item lookup never answers, and costs time."""

    enabled = True

    def __init__(self, clock, seconds_per_confirm=30.0):
        self.clock = clock
        self.cost = seconds_per_confirm
        self.confirms = 0

    def search(self, cpu, ram_gb=None):
        return [{"itemId": f"live|{cpu}", "title": cpu,
                 "price": {"value": "100.00", "currency": "USD"},
                 "buyingOptions": ["FIXED_PRICE"]}]

    def still_listed(self, _item_id):
        self.confirms += 1
        self.clock.t += self.cost
        return None                      # asked, no answer


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _install(monkeypatch, store, adapter, clock, singles):
    """Point cmd_ebay_watch at the fakes it imports at call time.

    `from .store import backend as ds` reads an ATTRIBUTE of the already
    imported pcpartscan.store package, so patching sys.modules does nothing
    and the command quietly talks to the real Mongo instead.
    """
    backend = types.ModuleType("pcpartscan.store.backend")
    for name in dir(store):
        if not name.startswith("_"):
            setattr(backend, name, getattr(store, name))
    monkeypatch.setattr("pcpartscan.store.backend", backend)
    monkeypatch.setattr(pricing, "EbayAdapter", lambda: adapter)
    monkeypatch.setattr(cli.time, "monotonic", clock, raising=False)
    monkeypatch.setattr("pcpartscan.harvest.load_observations",
                        lambda: {"singles": singles, "baskets": [], "lots": []})


def _singles(n_cpus=3):
    out = []
    for i in range(n_cpus):
        cpu = f"i{i}-0000"
        out += [{"key": "1-1", "price": 80.0, "title": "",
                 "machine": {"cpu": cpu}}] * ebaypanel.MIN_GOVDEALS_SALES
    return out


def _departures(cpus, per_cpu):
    return [{"_id": f"gone|{cpu}|{j}", "polls": 3,
             "query_key": ebaypanel.query_key(cpu, None)}
            for cpu in cpus for j in range(per_cpu)]


def test_confirmations_stop_at_the_wall_clock_budget(monkeypatch):
    """Whatever the per-query count allows, time is the real limit."""
    cpus = [f"i{i}-0000" for i in range(3)]
    store = _Store(live=_departures(cpus, 10))
    clock = _Clock()
    adapter = _Adapter(clock, seconds_per_confirm=30.0)
    _install(monkeypatch, store, adapter, clock, _singles(3))

    # 120s of budget at 30s a call: the checks land at 0/30/60/90/120s and
    # the budget is only spent once it is EXCEEDED, so five calls get
    # through -- and every CPU still gets polled, which is the trade.
    cli.cmd_ebay_watch(argparse.Namespace(
        max_cpus=3, max_confirm=25, confirm_seconds=120.0))

    assert adapter.confirms == 5
    assert len([p for p in store.polls if p["ok"]]) == 3
    assert store.finished["status"] == "ok"


def test_polling_survives_a_dead_item_endpoint(monkeypatch):
    """The searches that build the panel must not be lost to confirmations."""
    cpus = [f"i{i}-0000" for i in range(3)]
    store = _Store(live=_departures(cpus, 25))
    clock = _Clock()
    # each confirmation blows the whole budget
    adapter = _Adapter(clock, seconds_per_confirm=10_000.0)
    _install(monkeypatch, store, adapter, clock, _singles(3))

    cli.cmd_ebay_watch(argparse.Namespace(
        max_cpus=3, max_confirm=25, confirm_seconds=300.0))

    assert adapter.confirms == 1          # one call, then the budget is gone
    assert len(store.polls) == 3          # ...and all three CPUs still polled


def test_a_confirmation_that_errors_is_recorded_as_unconfirmed(monkeypatch):
    """Distinct from "vanished", which means nobody asked.

    Without the distinction an eBay outage looks exactly like a normal day
    in the stored data, and pads the all-departures band with departures
    nothing ever checked.
    """
    store = _Store(live=_departures(["i0-0000"], 2))
    clock = _Clock()
    adapter = _Adapter(clock, seconds_per_confirm=0.0)
    _install(monkeypatch, store, adapter, clock, _singles(1))

    cli.cmd_ebay_watch(argparse.Namespace(
        max_cpus=1, max_confirm=25, confirm_seconds=300.0))

    assert {m["gone_reason"] for m in store.marked} == {"unconfirmed"}
    assert store.finished["counts"]["unconfirmed"] == 2


def test_a_still_live_listing_is_not_marked_gone(monkeypatch):
    """A listing that fell out of search and is confirmed up stays up."""
    store = _Store(live=_departures(["i0-0000"], 2))
    clock = _Clock()
    adapter = _Adapter(clock, seconds_per_confirm=0.0)
    adapter.still_listed = lambda _id: True
    _install(monkeypatch, store, adapter, clock, _singles(1))

    cli.cmd_ebay_watch(argparse.Namespace(
        max_cpus=1, max_confirm=25, confirm_seconds=300.0))

    assert store.marked == []


def test_a_failed_search_is_never_diffed(monkeypatch):
    """A query that errored must not read as every listing under it selling."""
    store = _Store(live=_departures(["i0-0000"], 5))
    clock = _Clock()
    adapter = _Adapter(clock, seconds_per_confirm=0.0)
    adapter.search = lambda cpu, ram_gb=None: None      # eBay did not answer
    _install(monkeypatch, store, adapter, clock, _singles(1))

    cli.cmd_ebay_watch(argparse.Namespace(
        max_cpus=1, max_confirm=25, confirm_seconds=300.0))

    assert store.marked == []
    assert store.polls and not store.polls[0]["ok"]


def test_no_credentials_is_a_clear_stop(monkeypatch):
    store = _Store()
    clock = _Clock()
    adapter = _Adapter(clock)
    adapter.enabled = False
    _install(monkeypatch, store, adapter, clock, _singles(1))

    with pytest.raises(SystemExit, match="EBAY_CLIENT_ID"):
        cli.cmd_ebay_watch(argparse.Namespace(
            max_cpus=1, max_confirm=25, confirm_seconds=300.0))
