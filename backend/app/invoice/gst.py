"""GST options for "With GST billing" invoices. Pure: Decimal in, Decimal out, no I/O.

The options themselves live in `config/invoice.yaml` (`gst_options`), the single place to add,
remove or relabel one. The cart gets them from GET /api/invoice-settings.

Tax is charged at invoice level on the taxable value (the invoice TOTAL). Each component is
computed and rounded to paise on its own, so 9% + 9% can differ by a paisa from 18%.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

PAISA = Decimal("0.01")


class InvalidGstOption(Exception):
    pass


@dataclass(frozen=True)
class GstComponent:
    name: str  # GST · CGST · SGST/UTGST
    rate: Decimal  # percent: 18 means 18%


# What a With GST invoice saved before GST became selectable was charged (the old fixed
# gst_rate: 0.18). Only used to reprint those; it is history, not a setting.
LEGACY_COMPONENTS = (GstComponent("GST", Decimal(18)),)


@dataclass(frozen=True)
class GstOption:
    key: str
    label: str
    components: tuple[GstComponent, ...]

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
    keys = [o.key for o in options]
    if len(set(keys)) != len(keys):
        raise ValueError("GST option keys must be unique")
    return tuple(options)


def find(options: Iterable[GstOption], key: str | None) -> GstOption:
    """The option for `key`; raises InvalidGstOption for a missing or unknown key."""
    options = tuple(options)
    if not key:
        raise InvalidGstOption("Select a GST rate for a With GST invoice")
    for option in options:
        if option.key == key:
            return option
    allowed = ", ".join(o.key for o in options)
    raise InvalidGstOption(f"Unknown GST rate {key!r}; use one of: {allowed}")


def tax_amounts(taxable: Decimal, components: Iterable[GstComponent]) -> tuple[TaxAmount, ...]:
    """One amount per component: taxable × rate / 100, rounded half up to paise on its own."""
    return tuple(
        TaxAmount(c.name, c.rate, (Decimal(taxable) * c.rate / 100).quantize(PAISA, rounding=ROUND_HALF_UP))
        for c in components
    )


def public(options: Iterable[GstOption]) -> list[dict]:
    """The options as JSON for the cart's dropdown and summary box."""
    return [
        {
            "key": o.key,
            "label": o.label,
            "components": [{"name": c.name, "rate": format(c.rate.normalize(), "f")} for c in o.components],
        }
        for o in options
    ]
