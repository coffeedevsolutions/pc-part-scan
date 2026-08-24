"""Per-unit prices for things the machine model cannot price.

The single-unit fit in pricing.py answers "what is this machine worth", from
its CPU, RAM and drive. It is the right model for a pallet of desktops and
the wrong model for a pallet of chargers -- it has no feature that says
"charger", so every one of them landed in a generic bucket at $61-88 a unit.
Sold comps put laptop chargers at about $3.

This module answers the cruder question the machine model cannot: "what does
one of THESE go for", where THESE is an item class from classify.py, priced
from sold lots of the same class and nothing else.

Two quotes per class, mirroring the floor/ceiling split the rest of the
system uses:

  bulk    dollars per unit in sold lots of five or more. What a pallet of
          them clears -- the resale-as-lot FLOOR.
  single  what one sold on its own fetched -- the parts-out CEILING.

Quantiles, not a fit. Within a class the spread is enormous (a Surface
keyboard and an HP USB keyboard are both "peripheral" and differ tenfold),
and a mean would sit in the gap between two clusters where nothing actually
trades.

Both quotes are taken low, and the ceiling is bounded twice over, because
this model knows less than the machine fit does and has to price like it.
Single-unit sales are a different population from pallets -- somebody lists
the good one on its own -- so a class median from them reads high against
the pallet it is being applied to: taking the tablet median of $151 to a
pallet of 2010 ThinkPad X201s produced a $53,000 ceiling and a grade of B
on a lot worth perhaps a tenth of that. So the ceiling is the 25th
percentile of single sales, capped at what the same class's PALLET price
implies once the corpus-wide bulk discount is undone. The two quotes are
independent readings of one class and are not allowed to disagree by more
than that discount.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import classify, specs
from .stats import quantile as _q

# Below this a class has no usable quote and lots of that kind stay UNRATED.
# Eight is not many, but these are quantiles of a tight population rather
# than coefficients of a wide model, and the alternative -- refusing to
# price a class until it has hundreds of comps -- means never pricing the
# long tail at all.
MIN_OBS = 8

# Sanity bounds. A "single unit" that fetched $4,000 is a mislabeled pallet;
# a pallet clearing 12 cents a unit is a scrap lot with a wrong count.
SINGLE_BOUNDS = (5.0, 3000.0)
BULK_UNIT_BOUNDS = (0.20, 2000.0)
BULK_MIN_UNITS = 5

# Stand-in for the bulk-discount fit when it is not trusted, taken from the
# corpus-wide ratio of pallet price to single-unit price across the classes
# with enough of both to measure it.
DEFAULT_K = 0.60


@dataclass
class ClassQuote:
    """What sold comps say one unit of this class is worth."""
    item_class: str
    family: str
    single_n: int = 0
    single_p25: float = 0.0
    single_p50: float = 0.0
    single_p75: float = 0.0
    bulk_n: int = 0
    bulk_p25: float = 0.0
    bulk_p50: float = 0.0
    bulk_p75: float = 0.0

    @property
    def has_ceiling(self) -> bool:
        return self.single_n >= MIN_OBS and self.single_p50 > 0

    @property
    def has_floor(self) -> bool:
        return self.bulk_n >= MIN_OBS and self.bulk_p25 > 0

    @property
    def usable(self) -> bool:
        """Can we price a lot of this class at all?"""
        return self.has_ceiling or self.has_floor

    def ceiling_per_unit(self, bulk_discount: float | None = DEFAULT_K) -> float:
        """Parts-out value of one unit, taken low and bounded by the pallets.

        `bulk_discount` is k from the bulk-discount fit -- the share of
        parts-out value a pallet clears. Dividing the pallet price by it
        recovers what the pallet implies one unit is worth, which is the
        ceiling this class has actually earned.
        """
        k = bulk_discount if bulk_discount and 0.05 <= bulk_discount <= 1.0 \
            else DEFAULT_K
        implied = self.bulk_p50 / k if self.has_floor and self.bulk_p50 else 0.0
        direct = self.single_p25 if self.has_ceiling else 0.0
        if direct and implied:
            return min(direct, implied)
        return direct or implied

    @property
    def floor_per_unit(self) -> float:
        return self.bulk_p25 if self.has_floor else 0.0

    def to_dict(self, bulk_discount: float | None = DEFAULT_K) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d.update(usable=self.usable, has_floor=self.has_floor,
                 has_ceiling=self.has_ceiling,
                 ceiling_per_unit=round(self.ceiling_per_unit(bulk_discount), 2),
                 floor_per_unit=round(self.floor_per_unit, 2))
        return d


@dataclass
class ClassPriceTable:
    quotes: dict[str, ClassQuote] = field(default_factory=dict)

    def get(self, item_class: str | None) -> ClassQuote | None:
        q = self.quotes.get(item_class or "")
        return q if q and q.usable else None

    def to_dict(self, bulk_discount: float | None = DEFAULT_K) -> dict:
        return {k: q.to_dict(bulk_discount)
                for k, q in sorted(self.quotes.items())}

    @classmethod
    def from_dict(cls, d: dict) -> "ClassPriceTable":
        out = cls()
        for k, v in (d or {}).items():
            fields = {f: v[f] for f in ClassQuote.__annotations__ if f in v}
            out.quotes[k] = ClassQuote(**fields)
        return out


def fit(lots: list[dict]) -> ClassPriceTable:
    """Build the table from priced sold lots.

    `lots` are dicts with `title`, `units` and `price` -- every sold lot
    whose title states how many things were in it, classified or not.
    """
    singles: dict[str, list[float]] = {}
    bulk: dict[str, list[float]] = {}
    fams: dict[str, str] = {}

    for lot in lots:
        price = float(lot.get("price") or 0)
        units = lot.get("units")
        if price <= 0 or not units or units < 1:
            continue
        c = classify.classify(lot.get("title") or "")
        if not c.known:
            continue
        fams[c.item_class] = c.family
        if units == 1:
            if SINGLE_BOUNDS[0] <= price <= SINGLE_BOUNDS[1]:
                singles.setdefault(c.item_class, []).append(price)
        elif units >= BULK_MIN_UNITS:
            per = price / units
            if BULK_UNIT_BOUNDS[0] <= per <= BULK_UNIT_BOUNDS[1]:
                bulk.setdefault(c.item_class, []).append(per)

    table = ClassPriceTable()
    for cls_name in set(singles) | set(bulk):
        s, b = singles.get(cls_name, []), bulk.get(cls_name, [])
        table.quotes[cls_name] = ClassQuote(
            item_class=cls_name, family=fams.get(cls_name) or "",
            single_n=len(s),
            single_p25=round(_q(s, 0.25), 2) if s else 0.0,
            single_p50=round(_q(s, 0.50), 2) if s else 0.0,
            single_p75=round(_q(s, 0.75), 2) if s else 0.0,
            bulk_n=len(b),
            bulk_p25=round(_q(b, 0.25), 2) if b else 0.0,
            bulk_p50=round(_q(b, 0.50), 2) if b else 0.0,
            bulk_p75=round(_q(b, 0.75), 2) if b else 0.0,
        )
    return table


def class_observations(sold_lots: dict) -> list[dict]:
    """Priced sold lots in the shape fit() wants, from the durable store."""
    out = []
    for key, lot in sold_lots.items():
        title = lot.get("title") or ""
        price = lot.get("final_price")
        n = specs.parse_unit_count(title)
        if not price or price <= 0 or n is None:
            continue
        out.append({"key": key, "title": title, "units": n,
                    "price": float(price)})
    return out
