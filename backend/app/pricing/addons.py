"""Optional add-ons (FR-6)."""
from dataclasses import dataclass, replace
from decimal import Decimal

from ..catalogue import Addon
from .totals import money


class UnknownAddon(Exception):
    pass


@dataclass(frozen=True)
class AppliedAddon:
    id: str
    name: str
    price: Decimal  # a percent add-on's price depends on the unit price: see `at`
    basis: str  # per_unit | per_order
    percent: Decimal | None = None

    def at(self, unit_price: Decimal) -> "AppliedAddon":
        """This add-on priced for a line at `unit_price` (percent add-ons round to the paisa)."""
        if self.percent is None:
            return self
        return replace(self, price=money(unit_price * self.percent / 100))


def available_addons(product_addons: list[Addon], sample_charge: Decimal | None) -> list[AppliedAddon]:
    """The add-ons a line can take; sheet-priced ones (samples) need a sample charge on the item."""
    result = []
    for addon in product_addons:
        if addon.percent is not None:
            result.append(
                AppliedAddon(id=addon.id, name=addon.name, price=Decimal(0), basis=addon.basis, percent=addon.percent)
            )
            continue
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


def split(addons: list[AppliedAddon], unit_price: Decimal = Decimal(0)) -> tuple[Decimal, Decimal]:
    """(per-unit sum, per-order sum) for a line at `unit_price`."""
    priced = [a.at(unit_price) for a in addons]
    per_unit = sum((a.price for a in priced if a.basis == "per_unit"), Decimal(0))
    per_order = sum((a.price for a in priced if a.basis == "per_order"), Decimal(0))
    return per_unit, per_order


def per_unit_at(addons: list[AppliedAddon], unit_price: Decimal) -> Decimal:
    return split(addons, unit_price)[0]
