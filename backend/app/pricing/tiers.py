"""Tier matching, next-tier nudge and 'cheaper to order more' (FR-2, FR-3)."""
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal


class BelowMinimum(Exception):
    def __init__(self, minimum: int):
        super().__init__(f"Minimum order is {minimum}")
        self.minimum = minimum


@dataclass(frozen=True)
class TierMatch:
    index: int
    billed_qty: Decimal
    moq_applied: bool


def resolve_tier(breakpoints: list[int], quantity: Decimal, below_min_policy: str) -> TierMatch:
    """Highest tier whose Qty from is at or below the quantity."""
    lowest = breakpoints[0]
    if quantity < lowest:
        if below_min_policy == "block":
            raise BelowMinimum(lowest)
        return TierMatch(index=0, billed_qty=Decimal(lowest), moq_applied=True)
    index = max(i for i, qty_from in enumerate(breakpoints) if qty_from <= quantity)
    return TierMatch(index=index, billed_qty=quantity, moq_applied=False)


def tier_range(breakpoints: list[int], index: int) -> str:
    start = breakpoints[index]
    if index + 1 < len(breakpoints):
        return f"{start}-{breakpoints[index + 1] - 1}"
    return f"{start}+"


def units_to_next(breakpoints: list[int], index: int, billed_qty: Decimal) -> tuple[int, Decimal] | None:
    if index + 1 >= len(breakpoints):
        return None
    next_from = breakpoints[index + 1]
    return next_from, Decimal(next_from) - billed_qty


@dataclass(frozen=True)
class BetterOption:
    qty: int
    subtotal: Decimal
    saving: Decimal


@dataclass(frozen=True)
class TierSpan:
    qty_from: int
    qty_to: int | None
    unit_price: Decimal
    overpay_from: int | None


def schedule(
    breakpoints: list[int],
    unit_prices: list[Decimal],
    subtotal_at: Callable[[Decimal, Decimal], Decimal],
    *,
    suggest_more: bool,
    max_qty: int | None,
) -> list[TierSpan]:
    """Every tier with its range and overpay zone (BRD-tier-slider-back-nav section 7).

    `unit_prices[i]` is tier i's unit price including per-unit add-ons; `subtotal_at(unit_price,
    qty)` is the quote's own subtotal rule (with per-order add-ons), so the zone starts exactly
    where `better_option` would begin to offer a higher breakpoint.
    """
    spans = []
    for i, qty_from in enumerate(breakpoints):
        last = i + 1 == len(breakpoints)
        qty_to = max_qty if last else breakpoints[i + 1] - 1
        overpay = None
        if suggest_more and not last:
            best = min(subtotal_at(unit_prices[j], Decimal(breakpoints[j])) for j in range(i + 1, len(breakpoints)))
            overpay = _first_above(best, qty_from, qty_to, unit_prices[i], subtotal_at)
        spans.append(TierSpan(qty_from=qty_from, qty_to=qty_to, unit_price=unit_prices[i], overpay_from=overpay))
    return spans


def _first_above(
    limit: Decimal, lo: int, hi: int, unit_price: Decimal, subtotal_at: Callable[[Decimal, Decimal], Decimal]
) -> int | None:
    """Smallest whole quantity in [lo, hi] whose subtotal is above `limit`, or None."""
    if unit_price <= 0:
        return None
    # Section 7: floor((best_higher - per_order_addons) / unit_price) + 1, where the per-order part is
    # subtotal_at(unit_price, 0). The subtotal rounds to paise, so step to the exact edge after.
    per_order = subtotal_at(unit_price, Decimal(0))
    q = max(lo, int((limit - per_order) // unit_price) + 1)
    while q > lo and subtotal_at(unit_price, Decimal(q - 1)) > limit:
        q -= 1
    while subtotal_at(unit_price, Decimal(q)) <= limit:
        q += 1
    return q if q <= hi else None


def better_option(current_subtotal: Decimal, candidates: list[tuple[int, Decimal]]) -> BetterOption | None:
    """Cheapest total among ordering exactly each higher tier's Qty from, if below the current total."""
    if not candidates:
        return None
    qty, subtotal = min(candidates, key=lambda c: (c[1], c[0]))
    if subtotal < current_subtotal:
        return BetterOption(qty=qty, subtotal=subtotal, saving=current_subtotal - subtotal)
    return None
