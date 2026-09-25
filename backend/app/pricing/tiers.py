"""Tier matching, next-tier nudge and 'cheaper to order more' (FR-2, FR-3)."""
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


def better_option(current_subtotal: Decimal, candidates: list[tuple[int, Decimal]]) -> BetterOption | None:
    """Cheapest total among ordering exactly each higher tier's Qty from, if below the current total."""
    if not candidates:
        return None
    qty, subtotal = min(candidates, key=lambda c: (c[1], c[0]))
    if subtotal < current_subtotal:
        return BetterOption(qty=qty, subtotal=subtotal, saving=current_subtotal - subtotal)
    return None
