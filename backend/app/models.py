"""Pydantic request models. Responses are plain dicts built in quote.py (money as strings)."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CustomDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    side: Decimal | None = None
    unit: Literal["in", "cm"] = "in"


class LoginRequest(BaseModel):
    password: str = Field(max_length=200)


class OutdoorSize(BaseModel):
    """What the UI multiplied into square feet; only used for the invoice line's Size text."""

    model_config = ConfigDict(extra="forbid")

    width: Decimal = Field(gt=0, le=10_000)
    height: Decimal = Field(gt=0, le=10_000)
    pieces: int = Field(ge=1, le=100_000)


class CalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outdoor: OutdoorSize | None = None

    product_id: str | None = None
    item_id: str | None = None
    options: dict[str, str | None] = Field(default_factory=dict)
    custom_dimensions: CustomDimensions | None = None
    quantity: Decimal = Field(gt=0, le=10_000_000)
    addons: list[str] = Field(default_factory=list, max_length=20)
    billing_type: Literal["gst", "invoice"] = "gst"
