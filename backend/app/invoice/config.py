"""Reads config/invoice.yaml: business text and invoice settings, never in code (BRD 8.5)."""
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml

from .gst import GstOption, GstSlab, parse_options, parse_slabs


class InvoiceConfigError(Exception):
    pass


@dataclass(frozen=True)
class InvoiceConfig:
    bill_no_start: int
    # Old "With GST billing" options: only for reading invoices saved with them.
    legacy_gst_options: tuple[GstOption, ...]
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
    # Where new invoices and payments are emailed, with subject and body text; None = no emails.
    email: dict | None = None
    # GST invoices: the slabs (grouped for the dropdown) and the BASTTA template's text.
    gst_slab_groups: tuple[dict, ...] = ()
    gst_slabs: tuple[GstSlab, ...] = ()
    seller_state_code: str = ""
    gst_invoice: dict | None = None
    # Quotations: the Printevr template's title, number label and table labels.
    quotation: dict | None = None
    # False: printed invoices carry no payment terms, payment notes, bank details or
    # payment-related terms (config/invoice.yaml print_payment_details).
    print_payment_details: bool = True
    # The PAYMENT TERMS + RECIEVABLES block on every invoice (config/invoice.yaml
    # payment_summary); None = not printed (print_payment_details decides alone).
    payment_summary: dict | None = None

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
    "paid_received",
    "paid_pending",
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


REQUIRED_EMAIL = (
    "to", "subject_new", "subject_payment", "subject_new_gst", "subject_payment_gst", "intro_new", "intro_payment",
    "intro_new_gst", "intro_payment_gst", "labels", "status_labels",
)
EMAIL_LABELS = (
    "customer", "bill_no", "invoice_date", "items", "item", "quantity", "unit_price", "subtotal",
    "total", "payable", "status", "received", "pending", "attached", "currency",
)
REQUIRED_QUOTATION = ("quote_no_start", "title", "number_label", "filename", "table_labels")
REQUIRED_GST_INVOICE = (
    "bill_no_start", "filename", "seller_name", "seller_lines", "copy_label", "date_label", "number_label",
    "buyer_heading", "consignee_heading", "party_phone", "party_gstin", "field_labels", "field_defaults",
    "table_labels", "totals", "bank_lines", "terms_heading", "terms_lines", "certified", "signatory",
)
GST_FIELDS = ("delivery_terms", "payment_terms", "po_date", "gr_rr_no", "transport", "vehicle_no", "eway_bill_no", "station")


def _section(raw: dict | None, name: str, required: tuple[str, ...]) -> dict:
    section = dict(raw or {})
    missing = [f"{name}.{k}" for k in required if k not in section]
    if name == "gst_invoice" and isinstance(section.get("field_labels"), dict):
        missing += [f"gst_invoice.field_labels.{k}" for k in GST_FIELDS if k not in section["field_labels"]]
    if missing:
        raise InvoiceConfigError(f"invoice config: missing {', '.join(missing)}")
    return section


def _email(raw: dict | None) -> dict | None:
    if not raw:
        return None
    email = {k: v if isinstance(v, dict) else str(v) for k, v in dict(raw).items()}
    missing = [f"email.{k}" for k in REQUIRED_EMAIL if not email.get(k)]
    if isinstance(email.get("labels"), dict):
        missing += [f"email.labels.{k}" for k in EMAIL_LABELS if k not in email["labels"]]
    if isinstance(email.get("status_labels"), dict):
        missing += [f"email.status_labels.{k}" for k in ("unpaid", "part_paid", "paid") if k not in email["status_labels"]]
    if missing:
        raise InvoiceConfigError(f"invoice config: missing {', '.join(missing)}")
    return email


SUMMARY_KEYS = ("total", "advance", "balance", "receivables_title", "received", "pending", "paid_in_full", "modes")


def _summary(raw: dict | None) -> dict | None:
    if not raw:
        return None
    summary = dict(raw)
    missing = [f"payment_summary.{k}" for k in SUMMARY_KEYS if k not in summary]
    if missing:
        raise InvoiceConfigError(f"invoice config: missing {', '.join(missing)}")
    summary["modes"] = {str(k): str(v) for k, v in dict(summary["modes"]).items()}
    return summary


def _flag(value, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvoiceConfigError(f"invoice config: {name} must be true or false")
    return value


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
            legacy_gst_options=parse_options(raw.get("legacy_gst_options") or []),
            advance_pct=Decimal(str(raw["advance_pct"])),
            pad_single_digit_unit_price=bool(raw.get("pad_single_digit_unit_price", True)),
            filename=str(raw["filename"]),
            status_labels=dict(raw["status_labels"]),
            unit_plurals={str(k): str(v) for k, v in (raw.get("unit_plurals") or {}).items()},
            from_lines=[str(line) for line in raw["from_lines"]],
            payment_terms=terms,
            totals=dict(raw.get("totals") or {"gst_label": "{name} @ {rate}%:"}),
            saving_lines=[str(line) for line in raw["saving_lines"]],
            footer=footer,
            email=_email(raw.get("email")),
            gst_slab_groups=tuple(dict(g) for g in raw["gst_slab_groups"]),
            gst_slabs=parse_slabs(raw["gst_slabs"], raw["gst_slab_groups"], raw["gst_component_names"]),
            seller_state_code=str(raw.get("seller_state_code") or ""),
            gst_invoice=_section(raw.get("gst_invoice"), "gst_invoice", REQUIRED_GST_INVOICE),
            quotation=_section(raw.get("quotation"), "quotation", REQUIRED_QUOTATION),
            print_payment_details=_flag(raw.get("print_payment_details", True), "print_payment_details"),
            payment_summary=_summary(raw.get("payment_summary")),
        )
    except KeyError as exc:
        raise InvoiceConfigError(f"invoice config: missing {exc.args[0]!r}") from None
    except ValueError as exc:
        raise InvoiceConfigError(f"invoice config: {exc}") from None


@lru_cache(maxsize=4)
def load(path: Path) -> InvoiceConfig:
    path = Path(path)
    if not path.exists():
        raise InvoiceConfigError(f"Invoice config not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return parse(yaml.safe_load(fh) or {})
