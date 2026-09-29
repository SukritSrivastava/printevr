"""Invoice line drafts from a calculator quote (BRD-cart-invoice FR-C1). Pure.

`invoice_lines[0]` is the article; any further lines are its per-order add-ons (and a
sample charge). Their subtotals add up to the quote's pre-GST subtotal exactly.
"""
import re
from decimal import Decimal

from ..catalogue import Catalogue, Product
from ..models import CalculateRequest
from ..quote import QuoteInput, calculate

DIM_HINTS = {"box": "(LxWxH)", "bag": "(HxLxS)", "flat": "(LxW)"}
DIM_ORDER = {"box": ("length", "width", "height"), "bag": ("height", "length", "side"), "flat": ("length", "width")}
_TIMES = re.compile(r"(?<=\d)\s*[×xX*]\s*(?=\d)")


def plain_number(value) -> str:
    """3.50 -> '3.5', 2 -> '2', 20 -> '20' (no trailing zeros, no exponent)."""
    return format(Decimal(str(value)).normalize(), "f")


def title_for(product: Product) -> str:
    if product.invoice_title:
        return product.invoice_title
    name = product.display_name
    if name.lower().startswith("customised"):
        return f"{name} printing"
    return f"Customised {name} printing"


def unit_label_for(product: Product, unit_plurals: dict[str, str]) -> str:
    if product.invoice_unit_label:
        return product.invoice_unit_label
    return unit_plurals.get(product.sale_unit) or f"{product.sale_unit}s"


def standard_size(size: str, kind: str) -> str:
    """'3 × 3 × 2 in' -> '3*3*2 in (LxWxH)'; '7 × 9 × 3 in (H × L × S)' -> '7*9*3 in (HxLxS)'."""
    hint = DIM_HINTS.get(kind)
    head = size.split("(", 1)[0].strip() if hint else size.strip()
    head = _TIMES.sub("*", head)
    return f"{head} {hint}" if hint else head


def custom_size(dims: dict, kind: str) -> str:
    """Entered numbers in the entered unit: '3.5*3.5*2 in (LxWxH)'."""
    numbers = "*".join(plain_number(dims[name]) for name in DIM_ORDER[kind])
    return f"{numbers} {dims.get('unit') or 'in'} {DIM_HINTS[kind]}"


def quote_input(body: CalculateRequest) -> QuoteInput:
    return QuoteInput(
        product_id=body.product_id,
        item_id=body.item_id,
        options=body.options,
        custom_dimensions=body.custom_dimensions.model_dump() if body.custom_dimensions else None,
        quantity=body.quantity,
        addons=body.addons,
        billing_type=body.billing_type,
    )


def quote_with_drafts(cat: Catalogue, body: CalculateRequest, unit_plurals: dict[str, str]) -> dict:
    """Runs the calculator unchanged, then adds `data.invoice_lines` to a success response."""
    result = calculate(cat, quote_input(body))
    if result["status"] == "success":
        result["data"]["invoice_lines"] = drafts(
            cat,
            result,
            options=body.options,
            custom_dimensions=body.custom_dimensions.model_dump() if body.custom_dimensions else None,
            outdoor=body.outdoor.model_dump() if body.outdoor else None,
            unit_plurals=unit_plurals,
        )
    return result


def spec(label: str | None, value: str, emphasis: bool = False) -> dict:
    return {"label": label, "value": value, "emphasis": emphasis}


def drafts(
    cat: Catalogue,
    result: dict,
    *,
    options: dict | None = None,
    custom_dimensions: dict | None = None,
    outdoor: dict | None = None,
    unit_plurals: dict[str, str],
) -> list[dict]:
    """Invoice line drafts for a successful quote; [] for anything else (manual quotes)."""
    if result.get("status") != "success":
        return []
    data = result["data"]
    product = cat.products[data["product"]["id"]]
    item = cat.item(data["product"]["item_id"]) if data["product"].get("item_id") else None
    title = title_for(product)

    specs: list[dict] = []
    if product.custom_dims == "area_sqft":
        if outdoor:
            size = f"{plain_number(outdoor['width'])}*{plain_number(outdoor['height'])} ft, {int(outdoor['pieces'])} pcs"
        else:
            size = f"{plain_number(data['quantity']['billed'])} sq ft"
        specs.append(spec("Size", size, True))
        if item is not None:
            specs.append(spec(product.size_label, item.size))
    elif custom_dimensions:
        specs.append(spec("Size", custom_size(custom_dimensions, product.custom_dims), True))
    elif item is not None:
        label = product.size_label if product.custom_dims == "none" else "Size"
        specs.append(spec(label, standard_size(item.size, product.custom_dims), True))

    chosen = {}
    if custom_dimensions:
        chosen = {k: v for k, v in (options or {}).items() if k in ("option_1", "option_2") and v}
    elif item is not None:
        chosen = {k: item.option(k) for k in ("option_1", "option_2") if item.option(k)}
    for key, value in chosen.items():
        specs.append(spec(product.option_labels.get(key, f"Option {key[-1]}"), value))

    per_unit = [a for a in data["addons"] if a["basis"] == "per_unit"]
    per_order = [a for a in data["addons"] if a["basis"] == "per_order"]
    for a in per_unit:
        specs.append(spec("Add-on", a["name"]))

    unit_price = Decimal(data["pricing"]["unit_price"]) + sum((Decimal(a["price"]) for a in per_unit), Decimal(0))
    price = format(unit_price.quantize(Decimal("0.01")), "f")
    main = {
        "source": "catalogue",
        "title": title,
        "specs": specs,
        "customisations": [],
        "quantity": data["quantity"]["billed"],
        "unit_label": unit_label_for(product, unit_plurals),
        "middle": {"kind": "none"},
        "catalogue_unit_price": price,
        "unit_price": price,
        "warnings": data["warnings"],
    }
    lines = [main]
    for a in per_order:
        lines.append(
            {
                "source": "addon",
                "addon_id": a["id"],
                "title": f"{a['name']} (add-on)",
                "specs": [spec("For", title)],
                "customisations": [],
                "quantity": 1,
                "unit_label": "order",
                "middle": {"kind": "none"},
                "catalogue_unit_price": a["price"],
                "unit_price": a["price"],
                "warnings": [],
            }
        )
    return lines
