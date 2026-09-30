"""Pydantic shapes for cart lines and invoices (BRD-cart-invoice sections 4 and 8.4)."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import CalculateRequest

MAX_LINES = 30
MAX_QTY = Decimal(10_000_000)
MAX_PRICE = Decimal(10_000_000)

Money = Annotated[Decimal, Field(ge=Decimal("0.01"), le=MAX_PRICE, decimal_places=2)]


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
    catalogue_unit_price: Decimal | None = Field(default=None, ge=0, le=MAX_PRICE, decimal_places=2)
    unit_price: Money
    warnings: list[dict] = Field(default_factory=list, max_length=10)
    price_edited: bool = False


class Customer(_Model):
    business_name: str = Field(min_length=1, max_length=60)
    contact_person: str | None = Field(default=None, max_length=60)
    address: str = Field(min_length=1, max_length=140)
    phone: str = Field(min_length=7, max_length=20, pattern=r"^[0-9 +\-]+$")

    @field_validator("contact_person")
    @classmethod
    def blank_is_none(cls, v: str | None) -> str | None:
        return v or None


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


class InvoiceDocument(_Model):
    """Everything the PDF shows. Stored invoices are rendered from this, never re-priced."""

    bill_no: int = Field(ge=1, le=10_000_000)
    invoice_date: date
    billing_type: Literal["without_gst", "with_gst"] = "without_gst"
    # With GST billing: the option chosen and its tax rows as issued (config/invoice.yaml gst_options).
    gst_option: str | None = None
    taxes: list[TaxLine] = Field(default_factory=list, max_length=4)
    customer: Customer
    lines: list[CartLine] = Field(min_length=1, max_length=MAX_LINES)
    payments: list[Payment] = Field(default_factory=list, max_length=20)
    saving_amount: Decimal | None = Field(default=None, ge=0, le=MAX_PRICE, decimal_places=2)


class InvoiceCreate(_Model):
    bill_no: int | None = Field(default=None, ge=1, le=10_000_000)
    invoice_date: date
    billing_type: Literal["without_gst", "with_gst"] = "without_gst"
    # A key from config/invoice.yaml gst_options; required (400 otherwise) with GST billing.
    gst_option: str | None = Field(default=None, max_length=40)
    customer: Customer
    lines: list[CartLine] = Field(min_length=1, max_length=MAX_LINES)
    payments: list[Payment] = Field(default_factory=list, max_length=4)
    saving_amount: Decimal | None = Field(default=None, ge=0, le=MAX_PRICE, decimal_places=2)
    print_mode: Literal["unpaid", "paid"]


class PaymentCreate(_Model):
    amount: Money
    date: date
    mode: Literal["upi", "cash", "bank_transfer", "cheque"] = "upi"
    note: str | None = Field(default=None, max_length=200)


class StaffLogin(BaseModel):
    passcode: str = Field(max_length=200)
