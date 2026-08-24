"""Grade lots that have already closed, and compare with what they fetched.

Everything else in this system is a claim about the future checked against
nothing. `single_r2 = 0.94` says the fit explains the corpus it was fitted
on; it says nothing about whether a max bid of $4,613 was a good number. The
only way to find out is to make the prediction on a lot whose outcome is
already known -- and to make it WITHOUT that outcome in the training data.

So: k-fold. Split the sold corpus into folds, and for each fold refit every
model (single-unit, bulk discount, per-class quotes) on the other folds
alone before grading the held-out lots. A lot never contributes to the model
that prices it. Anything less and the answer is arithmetic about itself.

Everything is reported by lot size, and that is not a nicety. Pooling
hides a trap: a sold lot of ONE machine with its CPU in the title is
exactly what the single-unit model is fitted to predict, so hammer/ceiling
comes out at 1.0 for those whatever the model is worth. 87% of the
machine-priced corpus is single units. Read the pooled row and you would
conclude the ceiling predicts clearing prices perfectly; read the 50+ row
and you find it overestimates by about 30%. Only the pallet rows say
anything about pallets, which is all this tool ever buys.

Two ratios come out, and they answer different questions.

`hammer / floor` is the accuracy test. The floor claims to be what a pallet
like this clears at auction, and the hammer IS what it cleared, so a
well-calibrated floor centres on 1.0. Anything else is the model being
wrong, and the direction says how.

`hammer / max_bid` is the margin test. Max bid is deliberately far below
what a lot is worth -- it is the most you can pay and still clear the
target return after recovery and dead units -- so this ratio SHOULD sit
above 1 most of the time. What it tells you is the win rate: the share of
lots cheap enough to be worth bidding on at all.

What is deliberately not here is a breakdown by grade. Grade is a function
of headroom against the CURRENT bid, and the sold archive was swept after
close: only 3 of 7,149 lots carry any observation taken before their
auction ended. Replaying a grade would mean inventing the bid it was
graded against. Confidence, which does not depend on the bid, is bucketed
instead -- and once the burst sampler has run for a season there will be
real pre-close bids to replay properly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from . import classprice, grade, harvest, pricing, specs
from .stats import quantile as _q

# Enough folds that each model still sees most of the corpus, few enough
# that refitting stays cheap -- the single-unit fit is the expensive part.
FOLDS = 5

# A fold's models are only worth predicting from if they are as well-fed as
# a real run's. Below this the fold is skipped rather than reported.
MIN_FOLD_SINGLES = 100


@dataclass
class Prediction:
    """What we would have said about a lot, and what it actually fetched."""
    lot_key: str
    title: str
    units: int
    hammer: float
    grade: str
    confidence: float
    priced_by: str | None
    item_class: str | None
    floor: float
    ceiling: float
    max_bid: float
    expected_revenue: float
    floor_trusted: bool = True
    end: str | None = None

    @property
    def hammer_over_max_bid(self) -> float | None:
        return self.hammer / self.max_bid if self.max_bid > 0 else None

    @property
    def hammer_over_floor(self) -> float | None:
        return self.hammer / self.floor if self.floor > 0 else None

    @property
    def hammer_over_ceiling(self) -> float | None:
        return self.hammer / self.ceiling if self.ceiling > 0 else None

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["hammer_over_max_bid"] = _r(self.hammer_over_max_bid)
        d["hammer_over_floor"] = _r(self.hammer_over_floor)
        d["hammer_over_ceiling"] = _r(self.hammer_over_ceiling)
        return d


def _r(x, n=4):
    return round(x, n) if x is not None else None


def _fold_of(key: str, folds: int) -> int:
    """Stable fold assignment, so a rerun reproduces the same split."""
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % folds


MIN_BUCKET = 5


@dataclass
class Bucket:
    """How one group of predictions turned out."""
    name: str
    n: int = 0
    n_priced: int = 0
    bid_ratios: list = field(default_factory=list)     # hammer / max_bid
    floor_ratios: list = field(default_factory=list)   # hammer / floor
    ceil_ratios: list = field(default_factory=list)    # hammer / ceiling

    def add(self, p: Prediction):
        self.n += 1
        r = p.hammer_over_max_bid
        if r is not None:
            self.n_priced += 1
            self.bid_ratios.append(r)
        f = p.hammer_over_floor
        if f is not None:
            self.floor_ratios.append(f)
        c = p.hammer_over_ceiling
        if c is not None:
            self.ceil_ratios.append(c)

    @staticmethod
    def _spread(v: list) -> dict:
        if len(v) < MIN_BUCKET:
            return {}
        return {"p10": round(_q(v, 0.10), 3), "p25": round(_q(v, 0.25), 3),
                "median": round(_q(v, 0.50), 3), "p75": round(_q(v, 0.75), 3),
                "p90": round(_q(v, 0.90), 3), "n": len(v)}

    def to_dict(self) -> dict:
        d = {"name": self.name, "n": self.n, "n_priced": self.n_priced,
             "vs_max_bid": self._spread(self.bid_ratios),
             "vs_floor": self._spread(self.floor_ratios),
             "vs_ceiling": self._spread(self.ceil_ratios)}
        if len(self.bid_ratios) >= MIN_BUCKET:
            # the share cheap enough to buy at our own ceiling
            d["win_rate"] = round(
                sum(1 for r in self.bid_ratios if r <= 1.0)
                / len(self.bid_ratios), 3)
        if len(self.floor_ratios) >= MIN_BUCKET:
            # how often the floor lands within a factor of two either way --
            # a coarse but honest "is this number in the right postcode"
            d["floor_within_2x"] = round(
                sum(1 for r in self.floor_ratios if 0.5 <= r <= 2.0)
                / len(self.floor_ratios), 3)
        return d


def _sold_rows(sold_lots: dict) -> list[dict]:
    """Sold lots in the raw shape value_lot expects, plus the outcome."""
    rows = []
    for key, lot in sold_lots.items():
        price = lot.get("final_price")
        if not price or price <= 0:
            continue
        acct, asset = lot.get("account_id"), lot.get("asset_id")
        if not acct or not asset:
            continue
        rows.append({
            "key": key,
            "hammer": float(price),
            "end": lot.get("auction_end_utc") or lot.get("auction_end"),
            "rec": {
                "accountId": acct, "assetId": asset,
                "assetShortDescription": lot.get("title") or "",
                # the bid we are predicting must not be an input to the
                # prediction, so the grader sees an unbid lot
                "currentBid": 0,
                "assetAuctionEndDateDisplay": "",
                "locationState": (lot.get("location") or {}).get("state"),
            },
        })
    return rows


def run(sold_lots: dict, manifests: dict, cfg: grade.Config | None = None,
        folds: int = FOLDS, progress=None) -> dict:
    """Replay the grader over the sold corpus, out of sample.

    Returns a report dict: overall and per-bucket ratio distributions, plus
    every prediction, so the workbench can draw the calibration curve and
    put an honest range on a live lot's max bid.
    """
    cfg = cfg or grade.Config()
    rows = _sold_rows(sold_lots)
    preds: list[Prediction] = []
    skipped_folds = []

    for f in range(folds):
        train_keys = {r["key"] for r in rows if _fold_of(r["key"], folds) != f}
        test = [r for r in rows if _fold_of(r["key"], folds) == f]
        if not test:
            continue

        train = {k: v for k, v in sold_lots.items() if k in train_keys}
        obs = _observations(train, manifests)
        if len(obs["singles"]) < MIN_FOLD_SINGLES:
            skipped_folds.append(f)
            continue

        single = pricing.fit_single_model(obs["singles"])
        try:
            basket = pricing.fit_basket_model(obs["baskets"], single)
        except ValueError:
            basket = None
        table = classprice.fit(obs["lots"])
        ebay = _Silent()

        for r in test:
            v = grade.value_lot(r["rec"], single, basket, ebay, cfg,
                                class_table=table, manifests=manifests)
            preds.append(Prediction(
                lot_key=r["key"], title=v.title, units=v.units,
                hammer=r["hammer"], grade=v.grade, confidence=v.confidence,
                priced_by=v.priced_by, item_class=v.item_class,
                floor=round(v.floor, 2), ceiling=round(v.ceiling, 2),
                max_bid=round(v.max_bid, 2),
                expected_revenue=round(v.expected_revenue, 2),
                floor_trusted=v.floor_trusted, end=r["end"]))
        if progress:
            progress(f + 1, folds, len(preds))

    return _report(preds, cfg, folds, skipped_folds)


class _Silent:
    """eBay stands down for a backtest: its asks are today's, not the lot's."""
    enabled = False

    def value(self, machine):        # pragma: no cover - never reached
        return None


def _observations(sold: dict, manifests: dict) -> dict:
    """Priced observations from one fold's training lots, without network.

    The per-lot rules come from harvest.observation_for, the same function
    the production fit uses. Re-implementing them here is how a backtest
    quietly stops describing the model it claims to be testing.
    """
    singles, baskets = [], []
    for key, lot in sold.items():
        title = lot.get("title") or ""
        n = specs.parse_unit_count(title)
        mix = list((manifests.get(key) or {}).get("machines") or [])
        obs = harvest.observation_for(key, title, lot.get("final_price"),
                                      n, mix)
        if obs is None:
            continue
        (singles if obs[0] == "single" else baskets).append(obs[1])
    return {"singles": singles, "baskets": baskets,
            "lots": classprice.class_observations(sold)}


def _report(preds: list[Prediction], cfg: grade.Config, folds: int,
            skipped: list[int]) -> dict:
    overall = Bucket("all")
    pallets = Bucket("pallets (5+)")
    by_size: dict[str, Bucket] = {}
    by_conf: dict[str, Bucket] = {}
    by_path: dict[str, Bucket] = {}
    by_class: dict[str, Bucket] = {}
    for p in preds:
        overall.add(p)
        if p.units >= PALLET_MIN_UNITS:
            pallets.add(p)
        by_size.setdefault(_size_band(p.units),
                           Bucket(_size_band(p.units))).add(p)
        by_conf.setdefault(_conf_band(p.confidence),
                           Bucket(_conf_band(p.confidence))).add(p)
        path = p.priced_by or "unrated"
        by_path.setdefault(path, Bucket(path)).add(p)
        if p.item_class:
            by_class.setdefault(p.item_class, Bucket(p.item_class)).add(p)

    return {
        "folds": folds,
        "skipped_folds": skipped,
        "config": cfg.__dict__.copy(),
        "n_lots": len(preds),
        "overall": overall.to_dict(),
        "pallets": pallets.to_dict(),
        "by_size": {k: b.to_dict() for k, b in sorted(by_size.items())},
        "by_confidence": {k: b.to_dict() for k, b in sorted(by_conf.items())},
        "by_path": {k: b.to_dict() for k, b in sorted(by_path.items())},
        "by_class": {k: b.to_dict() for k, b in sorted(by_class.items())},
        "win_curves": win_curves(preds, cfg),
        "predictions": [p.to_dict() for p in preds],
    }


# Target returns to price the win rate at. The default is 0.60; the rest
# are there so the curve says what loosening it would actually buy.
ROI_GRID = (0.20, 0.30, 0.40, 0.50, 0.60, 0.80, 1.00)
RECOVERY_GRID = (0.55, 0.80, 1.00, 1.30, 1.60, 2.00)


def _win_rate(preds, cfg) -> dict:
    wins, ratios = 0, []
    for p in preds:
        parts_out = p.ceiling * (1 - cfg.dead_rate) * cfg.recovery
        rev = max(parts_out, p.floor) if p.floor_trusted else parts_out
        mb = cfg.max_hammer(rev, p.units)
        if mb <= 0:
            continue
        ratios.append(p.hammer / mb)
        wins += p.hammer <= mb
    if not ratios:
        return {}
    return {"n": len(ratios), "win_rate": round(wins / len(ratios), 3),
            "median_ratio": round(_q(ratios, 0.5), 3)}


def win_curves(preds: list[Prediction], cfg: grade.Config) -> dict:
    """What each assumption would have won, on the same predictions.

    Max bid falls straight out of expected revenue and the config, so both
    sweeps are recomputed without refitting anything. This is the output
    that turns a backtest into a decision, and the two levers behave very
    differently: the target return barely moves the win rate, while
    recovery moves it a lot -- which is itself the finding.

    Abstentions are excluded, and so are lots below the board's five-unit
    floor. Their numbers exist only as diagnostics, and counting a lot we
    refused to price -- or would never have been shown -- as one we would
    have won is exactly the self-flattery a backtest is here to prevent.
    """
    usable = [p for p in preds if p.priced_by and p.ceiling > 0
              and p.units >= PALLET_MIN_UNITS]
    by_roi, by_rec = [], []
    for roi in ROI_GRID:
        r = _win_rate(usable, grade.Config(**{**cfg.__dict__,
                                              "target_roi": roi}))
        if r:
            by_roi.append({"target_roi": roi, **r})
    for rec in RECOVERY_GRID:
        r = _win_rate(usable, grade.Config(**{**cfg.__dict__,
                                              "recovery": rec}))
        if r:
            by_rec.append({"recovery": rec, **r})
    # A small grid too, so the board can answer "at MY assumptions, what
    # share of past pallets would I have won?" without shipping 7,000
    # predictions to the browser. Forty-two numbers buys the whole surface.
    grid = []
    for roi in ROI_GRID:
        for rec in RECOVERY_GRID:
            r = _win_rate(usable, grade.Config(
                **{**cfg.__dict__, "target_roi": roi, "recovery": rec}))
            if r:
                grid.append({"target_roi": roi, "recovery": rec,
                             "win_rate": r["win_rate"]})
    return {"by_target_roi": by_roi, "by_recovery": by_rec, "grid": grid,
            "n_pallets": len(usable)}


SIZE_BANDS = ((1, 1, "1 unit"), (2, 4, "2-4"), (5, 49, "5-49"),
              (50, 10 ** 9, "50+"))

# The board only ever shows lots of five or more, so that is the population
# the win curve has to be about. Including singles would flatter it with
# lots nobody would have bid on.
PALLET_MIN_UNITS = 5


def _size_band(units: int) -> str:
    for lo, hi, label in SIZE_BANDS:
        if lo <= units <= hi:
            return label
    return "?"


def _conf_band(c: float) -> str:
    """Confidence in bands, since it is the one score a replay can honour."""
    for lo in (0.8, 0.6, 0.4, 0.2):
        if c >= lo:
            return f"{lo:.1f}+"
    return "<0.2"


def report_text(rep: dict, top: int = 12) -> str:
    """The report as two tables, for the CLI and the routines."""
    L = []
    o = rep["overall"]
    pal = rep.get("pallets") or {}
    L.append(f"backtest: {rep['n_lots']:,} closed lots, {rep['folds']}-fold "
             f"out of sample; {o['n_priced']:,} of them got a price")
    L.append(f"          {pal.get('n', 0):,} are pallets of five or more -- "
             f"the only ones the board would ever have shown you")
    if not o["vs_floor"] and not o["vs_max_bid"]:
        L.append("  not enough priced predictions to say anything")
        return "\n".join(L)

    def table(title, key, extra_label, extra_key, note):
        rows = [("all", o), ("pallets (5+)", rep.get("pallets") or {})]
        for label, k in (("size", "by_size"), ("confidence", "by_confidence"),
                         ("pricing path", "by_path"), ("kind", "by_class")):
            rows.append((f"-- by {label}", None))
            rows += [(b["name"], b) for b in
                     sorted(rep[k].values(), key=lambda b: -b["n"])[:top]]
        out = ["", title, note,
               f"{'bucket':<14}{'n':>7}{'p10':>8}{'p25':>8}{'median':>8}"
               f"{'p75':>8}{'p90':>8}{extra_label:>9}", "-" * 70]
        for name, b in rows:
            if b is None:
                out.append(name)
                continue
            sp = b.get(key) or {}
            if not sp:
                out.append(f"{name:<14}{b['n']:>7,}{'-':>8}{'-':>8}{'-':>8}"
                           f"{'-':>8}{'-':>8}{'-':>9}")
                continue
            ex = b.get(extra_key)
            out.append(f"{name:<14}{sp['n']:>7,}{sp['p10']:>8.2f}"
                       f"{sp['p25']:>8.2f}{sp['median']:>8.2f}"
                       f"{sp['p75']:>8.2f}{sp['p90']:>8.2f}"
                       f"{(f'{ex:.0%}' if ex is not None else '-'):>9}")
        return out

    L += table("hammer / CEILING -- the summed per-unit value", "vs_ceiling",
               "", "",
               "on pallets this lands near the bulk discount, which says the "
               "ceiling is a wholesale price and not a parts-out one")
    L += table("hammer / FLOOR -- the resale-as-lot estimate", "vs_floor",
               "within2x", "floor_within_2x",
               "the floor claims to be what a pallet like this clears, so "
               "1.00 is right")
    L += table("MARGIN -- hammer / max bid", "vs_max_bid", "win", "win_rate",
               "max bid is deliberately below value, so >1 is expected; "
               "'win' is the share cheap enough to buy")

    curves = rep.get("win_curves") or {}
    for label, key, field in (("TARGET RETURN", "by_target_roi", "target_roi"),
                              ("RECOVERY", "by_recovery", "recovery")):
        rows = curves.get(key) or []
        if not rows:
            continue
        L += ["", f"WHAT {label} COSTS",
              "share of priced PALLETS (5+ units) that closed at or below "
              "max bid",
              f"{label.lower():<14}{'win rate':>10}"
              f"{'median hammer/max bid':>24}", "-" * 48]
        for c in rows:
            L.append(f"{c[field]:<14.0%}{c['win_rate']:>10.1%}"
                     f"{c['median_ratio']:>24.2f}")
    return "\n".join(L)
