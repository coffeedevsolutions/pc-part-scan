"""Small numeric helpers shared across the pricing and evaluation code."""

from __future__ import annotations


def quantile(values: list[float], f: float) -> float:
    """The f-quantile by nearest rank, on an unsorted list.

    Deliberately the simple definition rather than an interpolating one:
    these are prices, and a quantile that lands on a price something
    actually fetched is easier to defend than one that lands between two.
    """
    v = sorted(values)
    return v[min(len(v) - 1, int(f * len(v)))]
