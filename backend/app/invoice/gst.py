"""GST slabs for GST invoices, and the legacy options old invoices were saved with. Pure:
Decimal in, Decimal out, no I/O.

The slabs live in `config/invoice.yaml` (`gst_slabs`), the single place to add, remove or
relabel one. The cart gets them from GET /api/invoice-settings.

Tax is charged at invoice level on the taxable value (the pre-tax subtotal). A slab always has
three components, CGST, UGST and IGST, and the ones that don't apply are 0%. Each is computed
and rounded to paise on its own, so 9% + 9% can differ by a paisa from 18%.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

PAISA = Decimal("0.01")
SLAB_COMPONENTS = ("cgst", "ugst", "igst")


class InvalidGstOption(Exception):
    pass


@dataclass(frozen=True)
class GstComponent:
    name: str  # CGST · UGST · IGST (legacy: GST · SGST/UTGST)
    rate: Decimal  # percent: 18 means 18%


# What a With GST invoice saved before GST became selectable was charged (the old fixed
# gst_rate: 0.18). Only used to reprint those; it is history, not a setting.
LEGACY_COMPONENTS = (GstComponent("GST", Decimal(18)),)


@dataclass(frozen=True)
class GstOption:
    """A legacy "With GST billing" option (config `legacy_gst_options`), for reading old records."""

    key: str
    label: str
    components: tuple[GstComponent, ...]

    @property
    def total_rate(self) -> Decimal:
        return sum((c.rate for c in self.components), Decimal(0))


@dataclass(frozen=True)
class GstSlab:
    key: str  # intra_18
    group: str  # intra | inter
    label: str  # "9% CGST + 9% SGST/UTGST (18%)"
    components: tuple[GstComponent, ...]  # always CGST, UGST, IGST in that order

    @property
    def total_rate(self) -> Decimal:
        return sum((c.rate for c in self.components), Decimal(0))


@dataclass(frozen=True)
class TaxAmount:
    name: str
    rate: Decimal
    amount: Decimal


def parse_options(raw: list) -> tuple[GstOption, ...]:
    options = []
    for item in raw:
        components = tuple(GstComponent(str(c["name"]), Decimal(str(c["rate"]))) for c in item["components"])
        if not components:
            raise ValueError(f"GST option {item['key']!r} has no components")
        options.append(GstOption(key=str(item["key"]), label=str(item["label"]), components=components))
    _unique([o.key for o in options], "GST option")
    return tuple(options)


def parse_slabs(raw: list, groups: list, names: dict) -> tuple[GstSlab, ...]:
    group_keys = [str(g["key"]) for g in groups]
    slabs = []
    for item in raw:
        if str(item["group"]) not in group_keys:
            raise ValueError(f"GST slab {item['key']!r} has an unknown group {item['group']!r}")
        components = tuple(GstComponent(str(names[c]), Decimal(str(item[c]))) for c in SLAB_COMPONENTS)
        if any(c.rate < 0 for c in components):
            raise ValueError(f"GST slab {item['key']!r} has a negative rate")
        slabs.append(GstSlab(key=str(item["key"]), group=str(item["group"]), label=str(item["label"]), components=components))
    _unique([s.key for s in slabs], "GST slab")
    return tuple(slabs)


def _unique(keys: list[str], what: str) -> None:
    if len(set(keys)) != len(keys):
        raise ValueError(f"{what} keys must be unique")


def find_slab(slabs: Iterable[GstSlab], key: str | None) -> GstSlab:
    """The slab for `key`; raises InvalidGstOption for a missing or unknown key."""
    slabs = tuple(slabs)
    if not key:
        raise InvalidGstOption("Select a GST slab for a GST invoice")
    for slab in slabs:
        if slab.key == key:
            return slab
    allowed = ", ".join(s.key for s in slabs)
    raise InvalidGstOption(f"Unknown GST slab {key!r}; use one of: {allowed}")


def tax_amounts(taxable: Decimal, components: Iterable[GstComponent]) -> tuple[TaxAmount, ...]:
    """One amount per component: taxable × rate / 100, rounded half up to paise on its own."""
    return tuple(
        TaxAmount(c.name, c.rate, (Decimal(taxable) * c.rate / 100).quantize(PAISA, rounding=ROUND_HALF_UP))
        for c in components
    )


def _rate(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def public_slabs(groups: list, slabs: Iterable[GstSlab]) -> list[dict]:
    """The slabs as JSON for the cart's grouped dropdown and summary box, in config order."""
    slabs = tuple(slabs)
    return [
        {
            "key": g["key"],
            "label": g["label"],
            "slabs": [
                {
                    "key": s.key,
                    "label": s.label,
                    "components": [{"name": c.name, "rate": _rate(c.rate)} for c in s.components],
                }
                for s in slabs
                if s.group == g["key"]
            ],
        }
        for g in groups
    ]
