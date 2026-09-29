"""Reads config/invoice.yaml: business text and invoice settings, never in code (BRD 8.5)."""
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml


class InvoiceConfigError(Exception):
    pass


@dataclass(frozen=True)
class InvoiceConfig:
    bill_no_start: int
    gst_rate: Decimal
    advance_pct: Decimal
    pad_single_digit_unit_price: bool
    filename: str
    status_labels: dict[str, str]
    unit_plurals: dict[str, str]
    from_lines: list[str]
    payment_terms: dict
    totals: dict
    saving_lines: list[str]
    footer: dict

    @property
    def balance_pct(self) -> Decimal:
        return Decimal(100) - self.advance_pct


REQUIRED_TERMS = (
    "title",
    "billing_labels",
    "total",
    "advance",
    "received",
    "pending",
    "balance",
    "balance_after_excess",
    "paid_in_full",
)
REQUIRED_FOOTER = (
    "thanks",
    "contact_prefix",
    "email",
    "advance_note",
    "colour_note",
    "late_note",
    "terms_note",
    "gst_note_without_gst",
    "gst_note_with_gst",
)


def parse(raw: dict) -> InvoiceConfig:
    try:
        terms = dict(raw["payment_terms"])
        footer = dict(raw["footer"])
        missing = [f"payment_terms.{k}" for k in REQUIRED_TERMS if k not in terms]
        missing += [f"footer.{k}" for k in REQUIRED_FOOTER if k not in footer]
        if missing:
            raise InvoiceConfigError(f"invoice config: missing {', '.join(missing)}")
        return InvoiceConfig(
            bill_no_start=int(raw["bill_no_start"]),
            gst_rate=Decimal(str(raw["gst_rate"])),
            advance_pct=Decimal(str(raw["advance_pct"])),
            pad_single_digit_unit_price=bool(raw.get("pad_single_digit_unit_price", True)),
            filename=str(raw["filename"]),
            status_labels=dict(raw["status_labels"]),
            unit_plurals={str(k): str(v) for k, v in (raw.get("unit_plurals") or {}).items()},
            from_lines=[str(line) for line in raw["from_lines"]],
            payment_terms=terms,
            totals=dict(raw.get("totals") or {"gst_label": "GST ({gst_pct}%):"}),
            saving_lines=[str(line) for line in raw["saving_lines"]],
            footer=footer,
        )
    except KeyError as exc:
        raise InvoiceConfigError(f"invoice config: missing {exc.args[0]!r}") from None


@lru_cache(maxsize=4)
def load(path: Path) -> InvoiceConfig:
    path = Path(path)
    if not path.exists():
        raise InvoiceConfigError(f"Invoice config not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return parse(yaml.safe_load(fh) or {})
