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


class CalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str | None = None
    item_id: str | None = None
    options: dict[str, str | None] = Field(default_factory=dict)
    custom_dimensions: CustomDimensions | None = None
    quantity: Decimal = Field(gt=0, le=10_000_000)
    addons: list[str] = Field(default_factory=list, max_length=20)
    billing_type: Literal["gst", "invoice"] = "gst"
