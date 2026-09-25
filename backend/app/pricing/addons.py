"""Optional add-ons (FR-6)."""
from dataclasses import dataclass
from decimal import Decimal

from ..catalogue import Addon


class UnknownAddon(Exception):
    pass


@dataclass(frozen=True)
class AppliedAddon:
    id: str
    name: str
    price: Decimal
    basis: str  # per_unit | per_order


def available_addons(product_addons: list[Addon], sample_charge: Decimal | None) -> list[AppliedAddon]:
    """The add-ons a line can take; sheet-priced ones (samples) need a sample charge on the item."""
    result = []
    for addon in product_addons:
        price = sample_charge if addon.from_sheet else addon.price
        if price is not None:
            result.append(AppliedAddon(id=addon.id, name=addon.name, price=price, basis=addon.basis))
    return result


def select_addons(available: list[AppliedAddon], requested: list[str]) -> list[AppliedAddon]:
    by_id = {a.id: a for a in available}
    unknown = [a for a in requested if a not in by_id]
    if unknown:
        raise UnknownAddon(", ".join(unknown))
    return [by_id[a] for a in dict.fromkeys(requested)]


def split(addons: list[AppliedAddon]) -> tuple[Decimal, Decimal]:
    """(per-unit sum, per-order sum)."""
    per_unit = sum((a.price for a in addons if a.basis == "per_unit"), Decimal(0))
    per_order = sum((a.price for a in addons if a.basis == "per_order"), Decimal(0))
    return per_unit, per_order
