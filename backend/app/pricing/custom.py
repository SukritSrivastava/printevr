"""Custom-size pricing by interpolating between standard sizes, tier by tier (FR-4)."""
from dataclasses import dataclass
from decimal import Decimal

from .totals import round_up_to_step


class OutOfRange(Exception):
    def __init__(self, metric: Decimal, largest: Decimal):
        super().__init__(f"Size metric {metric} is above the largest standard size ({largest})")
        self.metric = metric
        self.largest = largest


@dataclass(frozen=True)
class PoolSize:
    """One distinct metric in the anchor pool, at one tier."""

    size: str
    metric: Decimal
    price: Decimal
    flags: tuple[str, ...]


@dataclass(frozen=True)
class Anchor:
    size: str
    metric: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class CustomPrice:
    method: str  # floor | interpolate
    unit_price: Decimal
    raw_unit_price: Decimal
    anchors: tuple[Anchor, ...]
    flags: tuple[str, ...]


def collapse(entries: list[PoolSize]) -> list[PoolSize]:
    """Several pool items at the same metric -> keep the highest price (step 5)."""
    best: dict[Decimal, PoolSize] = {}
    for e in entries:
        if e.metric not in best or e.price > best[e.metric].price:
            best[e.metric] = e
    return sorted(best.values(), key=lambda e: e.metric)


def price_custom(pool: list[PoolSize], m: Decimal, surcharge_pct: Decimal, round_step: Decimal) -> CustomPrice:
    sizes = collapse(pool)
    smallest, largest = sizes[0], sizes[-1]
    if m > largest.metric:
        raise OutOfRange(m, largest.metric)
    if m <= smallest.metric:
        method, raw, used = "floor", smallest.price, (smallest,)
    else:
        lo = max((s for s in sizes if s.metric <= m), key=lambda s: s.metric)
        hi = min((s for s in sizes if s.metric > m), key=lambda s: s.metric) if lo.metric < m else lo
        if hi is lo:
            method, raw, used = "interpolate", lo.price, (lo,)
        else:
            raw = lo.price + (m - lo.metric) / (hi.metric - lo.metric) * (hi.price - lo.price)
            method, used = "interpolate", (lo, hi)
    with_surcharge = raw * (1 + surcharge_pct / 100)
    return CustomPrice(
        method=method,
        unit_price=round_up_to_step(with_surcharge, round_step),
        raw_unit_price=raw,
        anchors=tuple(Anchor(size=s.size, metric=s.metric, unit_price=s.price) for s in used),
        flags=tuple(f for s in used for f in s.flags),
    )
