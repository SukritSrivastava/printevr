"""Pydantic shapes for cart lines and invoices (BRD-cart-invoice sections 4 and 8.4)."""
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import CalculateRequest

MAX_LINES = 30
MAX_QTY = Decimal(10_000_000)
MAX_PRICE = Decimal(10_000_000)

Money = Annotated[Decimal, Field(ge=Decimal("0.01"), le=MAX_PRICE, decimal_places=2)]

SALESPERSON_MAX = 100
HSN_MAX = 12
GSTIN = re.compile(r"^[0-9]{2}[0-9A-Z]{13}$")


class _Model(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class SpecLine(_Model):
    label: str | None = Field(default=None, max_length=60)
    value: str = Field(min_length=1, max_length=120)
    emphasis: bool = False

    @field_validator("label")
    @classmethod
    def blank_label_is_none(cls, v: str | None) -> str | None:
        return v or None


class MiddleNone(_Model):
    kind: Literal["none"] = "none"


class MiddleNote(_Model):
    kind: Literal["note"]
    text: str = Field(min_length=1, max_length=40)


class MiddleReference(_Model):
    kind: Literal["reference_price"]
    amount: Money


Middle = Annotated[MiddleNone | MiddleNote | MiddleReference, Field(discriminator="kind")]


class CartLine(_Model):
    id: str | None = Field(default=None, max_length=64)
    source: Literal["catalogue", "custom", "addon"]
    parent_id: str | None = Field(default=None, max_length=64)
    addon_id: str | None = Field(default=None, max_length=64)
    calc_request: CalculateRequest | None = None
    title: str = Field(min_length=1, max_length=80)
    specs: list[SpecLine] = Field(default_factory=list, max_length=12)
    customisations: list[SpecLine] = Field(default_factory=list, max_length=8)
    # Whole units, except square feet (outdoor), which the calculator bills to 0.01.
    quantity: Decimal = Field(ge=1, le=MAX_QTY, decimal_places=2)
    unit_label: str = Field(min_length=1, max_length=20)
    middle: Middle = Field(default_factory=MiddleNone)
    # The calculator's rate (catalogue lines and add-ons) and the rate billed. They differ when
    # staff overrode the price (`price_edited`, set by the server); both are stored as issued.
    catalogue_unit_price: Decimal | None = Field(default=None, ge=0, le=MAX_PRICE, decimal_places=2)
    # 0 only on a custom invoice (service.check_request); otherwise at least 0.01.
    unit_price: Decimal = Field(ge=0, le=MAX_PRICE, decimal_places=2)
    warnings: list[dict] = Field(default_factory=list, max_length=10)
    price_edited: bool = False
    # GST invoices only. None = take the product's code from config/products.yaml; "" = none.
    hsn_code: str | None = Field(default=None, max_length=HSN_MAX, pattern=r"^[0-9A-Za-z ]*$")


class Customer(_Model):
    business_name: str = Field(min_length=1, max_length=60)
    contact_person: str | None = Field(default=None, max_length=60)
    address: str = Field(min_length=1, max_length=140)
    phone: str = Field(min_length=7, max_length=20, pattern=r"^[0-9 +\-]+$")

    @field_validator("contact_person")
    @classmethod
    def blank_is_none(cls, v: str | None) -> str | None:
        return v or None


class CustomerInput(_Model):
    """Ship To as typed. A quotation needs none of it; a Non-GST invoice checks it as Customer."""

    business_name: str = Field(default="", max_length=60)
    contact_person: str | None = Field(default=None, max_length=60)
    address: str = Field(default="", max_length=140)
    phone: str = Field(default="", max_length=20, pattern=r"^[0-9 +\-]*$")

    @field_validator("contact_person")
    @classmethod
    def blank_is_none(cls, v: str | None) -> str | None:
        return v or None


class Party(_Model):
    """Buyer or consignee on a GST invoice. The buyer's name is required (checked in service)."""

    name: str = Field(default="", max_length=60)
    address: str = Field(default="", max_length=140)
    phone: str = Field(default="", max_length=20, pattern=r"^[0-9 +\-]*$")
    gstin: str = Field(default="", max_length=15)

    @field_validator("gstin")
    @classmethod
    def gstin_format(cls, v: str) -> str:
        v = v.upper()
        if v and not GSTIN.match(v):
            raise ValueError("GSTIN is 15 characters: a 2-digit state code, then letters and digits")
        return v


class GstDetails(_Model):
    """A GST invoice's own fields (BASTTA template). Blank text prints blank."""

    buyer: Party
    consignee_same: bool = True
    consignee: Party | None = None
    delivery_terms: str = Field(default="", max_length=60)
    payment_terms: str = Field(default="", max_length=40)
    po_date: date | None = None
    gr_rr_no: str = Field(default="", max_length=30)
    transport: str = Field(default="", max_length=40)
    vehicle_no: str = Field(default="", max_length=20)
    eway_bill_no: str = Field(default="", max_length=20)
    station: str = Field(default="", max_length=40)

    def shipped_to(self) -> Party:
        return self.buyer if self.consignee_same or self.consignee is None else self.consignee


class Payment(_Model):
    amount: Money
    date: date
    mode: Literal["upi", "cash", "bank_transfer", "cheque"] = "upi"
    note: str | None = Field(default=None, max_length=200)
    recorded_at: str | None = None


class TaxLine(_Model):
    """One GST row on the invoice, e.g. CGST @ 9% = 900.00."""

    name: str = Field(min_length=1, max_length=20)
    rate: Decimal = Field(ge=0, le=100)  # percent
    amount: Decimal = Field(ge=0, decimal_places=2)


Series = Literal["quotation", "non_gst", "gst"]


class InvoiceDocument(_Model):
    """Everything the PDF shows. Stored documents are rendered from this, never re-priced.

    `series` picks the template: quotation (Printevr quotation), non_gst (the Printevr invoice,
    which every invoice saved before the series existed is) or gst (BASTTA GST invoice).
    """

    series: Series = "non_gst"
    bill_no: int = Field(ge=1, le=10_000_000)
    invoice_date: date
    # Printevr invoices only; "with_gst" exists only on old records (legacy GST options).
    billing_type: Literal["without_gst", "with_gst"] = "without_gst"
    # Legacy With GST billing: the option chosen. GST invoices: the slab key (intra_18, ...).
    gst_option: str | None = None
    # Tax rows as issued: a legacy option's, or CGST, UGST and IGST on a GST invoice.
    taxes: list[TaxLine] = Field(default_factory=list, max_length=4)
    customer: CustomerInput
    gst: GstDetails | None = None
    lines: list[CartLine] = Field(min_length=1, max_length=MAX_LINES)
    payments: list[Payment] = Field(default_factory=list, max_length=20)
    saving_amount: Decimal | None = Field(default=None, ge=0, le=MAX_PRICE, decimal_places=2)
    # Percent due before printing (100 = in full). None on old records: config advance_pct.
    advance_pct: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2)
    # Read from old records only: never printed, no longer asked for.
    salesperson: str | None = Field(default=None, max_length=SALESPERSON_MAX)


class InvoiceCreate(_Model):
    """POST /api/invoices: a quotation, or an invoice of either bill type.

    The combinations are checked in service.check_request (400 for GST slab mistakes).
    """

    document_type: Literal["quotation", "invoice"] = "invoice"
    # Invoices only: non_gst = Printevr invoice, gst = BASTTA GST invoice. Ignored on a quotation.
    bill_type: Literal["non_gst", "gst"] | None = None
    # GST invoices only: a key from config/invoice.yaml gst_slabs.
    gst_slab: str | None = Field(default=None, max_length=40)
    gst: GstDetails | None = None
    bill_no: int | None = Field(default=None, ge=1, le=10_000_000)
    invoice_date: date
    customer: CustomerInput = Field(default_factory=CustomerInput)
    lines: list[CartLine] = Field(min_length=1, max_length=MAX_LINES)
    payments: list[Payment] = Field(default_factory=list, max_length=4)
    saving_amount: Decimal | None = Field(default=None, ge=0, le=MAX_PRICE, decimal_places=2)
    # Invoices only (Print (Unpaid as of now) / Print (Paid)); a quotation has no payment state.
    print_mode: Literal["unpaid", "paid"] | None = None
    # Invoices only. None = pay in full before printing; a split (e.g. 80) asks this percent
    # before printing and the rest before dispatch. Ignored on a quotation.
    advance_pct: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2)
    # Custom invoice: staff may override any line's rate (down to 0). Internal only: stored with
    # the invoice, never printed. Everything else (products, quantities, minimums, numbering)
    # is the normal flow.
    is_custom: bool = False

    @property
    def series(self) -> str:
        if self.document_type == "quotation":
            return "quotation"
        return "gst" if self.bill_type == "gst" else "non_gst"


class PaymentCreate(_Model):
    amount: Money
    date: date
    mode: Literal["upi", "cash", "bank_transfer", "cheque"] = "upi"
    note: str | None = Field(default=None, max_length=200)


class StaffLogin(BaseModel):
    passcode: str = Field(max_length=200)
