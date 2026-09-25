"""Runs one calculation end to end: request -> priced line (BRD sections 6 and 7)."""
from dataclasses import dataclass, field
from decimal import Decimal

from . import dims as dimslib
from .catalogue import Catalogue, Item, Product
from .pricing import addons as addonlib
from .pricing import custom as customlib
from .pricing import tiers as tierlib
from .pricing import totals as totlib

MAX_DIMENSION_IN = Decimal(60)

WARNING_TEXT = {
    "CUSTOM_ESTIMATE": "Estimate - final price confirmed after design review",
    "PRODUCTION_TIME_UNKNOWN": "Confirm production time",
}


class QuoteError(Exception):
    def __init__(self, code: str, message: str, http_status: int, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


@dataclass
class QuoteInput:
    product_id: str | None = None
    item_id: str | None = None
    options: dict[str, str | None] = field(default_factory=dict)
    custom_dimensions: dict | None = None
    quantity: Decimal = Decimal(0)
    addons: list[str] = field(default_factory=list)
    billing_type: str = "gst"


@dataclass(frozen=True)
class TierPrice:
    unit_price: Decimal
    flags: tuple[str, ...]
    custom: customlib.CustomPrice | None = None


def s(value: Decimal) -> str:
    """Decimal -> plain string without exponent."""
    return format(value.normalize(), "f") if value == value.to_integral_value() else format(value, "f")


def m2(value: Decimal) -> str:
    return format(totlib.money(value), "f")


def num(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def validation(message: str, **details) -> QuoteError:
    return QuoteError("VALIDATION_ERROR", message, 422, details)


# ---------------------------------------------------------------- resolution


def _parse_custom_dims(product: Product, raw: dict) -> tuple[tuple[Decimal, ...], str]:
    unit = (raw.get("unit") or "in").lower()
    if unit not in ("in", "cm"):
        raise validation("Dimension unit must be 'in' or 'cm'", field="custom_dimensions.unit")
    names = dimslib.DIM_NAMES[product.custom_dims]
    values = []
    for name in names:
        value = raw.get(name)
        if value is None:
            raise validation(f"{name} is required for this product", field=f"custom_dimensions.{name}")
        try:
            d = Decimal(str(value))
        except Exception:
            raise validation(f"{name} must be a number", field=f"custom_dimensions.{name}") from None
        if not d.is_finite() or d <= 0:
            raise validation(f"{name} must be above 0", field=f"custom_dimensions.{name}")
        if d.as_tuple().exponent < -2:
            raise validation(f"{name} can have at most 2 decimals", field=f"custom_dimensions.{name}")
        inches = d / dimslib.CM_PER_INCH if unit == "cm" else d
        if inches > MAX_DIMENSION_IN:
            raise validation(
                f"{name} must be at most {MAX_DIMENSION_IN} in", field=f"custom_dimensions.{name}"
            )
        values.append(inches)
    return tuple(values), unit


def _check_options(product: Product, options: dict[str, str | None]) -> dict[str, str | None]:
    clean = {k: (v or None) for k, v in options.items() if k in ("option_1", "option_2")}
    for key in product.anchor_match:
        valid = {i.option(key) for i in product.items}
        if clean.get(key) not in valid:
            raise QuoteError(
                "UNKNOWN_ITEM",
                f"{product.option_labels.get(key, key)} {clean.get(key)!r} is not offered for {product.display_name}",
                404,
                {"field": f"options.{key}", "allowed": sorted(v for v in valid if v)},
            )
    return clean


def _pick_exact(product: Product, pool: list[Item], key: tuple, options: dict) -> Item | None:
    matches = [
        i
        for i in pool
        if dimslib.canonical(product.custom_dims, i.dims) == key
        and all(options.get(k) in (None, i.option(k)) for k in ("option_1", "option_2") if options.get(k))
    ]
    if not matches:
        return None
    return max(matches, key=lambda i: (i.product_id == product.id, i.tiers[0].price))


def _describe(item: Item) -> str:
    return ", ".join(p for p in (item.size, item.option_1, item.option_2) if p)


# ---------------------------------------------------------------- calculation


def calculate(cat: Catalogue, req: QuoteInput) -> dict:
    if (req.item_id is None) == (req.custom_dimensions is None):
        raise validation("Send exactly one of item_id or custom_dimensions")

    custom_info = None
    matched_note = None
    if req.item_id is not None:
        item = cat.item(req.item_id)
        if item is None:
            raise QuoteError("UNKNOWN_ITEM", f"Unknown item {req.item_id!r}", 404, {"item_id": req.item_id})
        product = cat.products[item.product_id]
        if req.product_id and req.product_id != product.id:
            raise QuoteError("UNKNOWN_ITEM", f"Item {req.item_id!r} is not a {req.product_id!r} item", 404)
    else:
        product = cat.product(req.product_id or "")
        if product is None:
            raise QuoteError("UNKNOWN_ITEM", f"Unknown product {req.product_id!r}", 404, {"product_id": req.product_id})
        if not product.supports_custom:
            raise QuoteError(
                "CUSTOM_NOT_SUPPORTED", f"{product.display_name} has no custom sizes", 422, {"product_id": product.id}
            )
        options = _check_options(product, req.options)
        dims, unit = _parse_custom_dims(product, req.custom_dimensions)
        pool = cat.anchor_pool(product, options)
        exact = _pick_exact(product, pool, dimslib.canonical(product.custom_dims, dims), options)
        if exact is not None:
            item = exact
            matched_note = f"Requested size matches standard {exact.size}"
        else:
            item = None
            custom_info = {"dims": dims, "unit": unit, "pool": pool, "options": options}

    # ---- quantity
    quantity = req.quantity
    if quantity is None or not quantity.is_finite() or quantity <= 0:
        raise validation("Quantity must be at least 1", field="quantity")
    if product.custom_dims == "area_sqft":
        if quantity.as_tuple().exponent < -2:
            raise validation("Square feet can have at most 2 decimals", field="quantity")
    elif quantity != quantity.to_integral_value():
        raise validation(f"Quantity must be a whole number of {product.sale_unit}s", field="quantity")

    manual = _manual_base(product, item, custom_info)
    if product.max_qty is not None and quantity > product.max_qty:
        return {
            **manual,
            "reason": "MANUAL_QUOTE",
            "message": f"Quantities above {product.max_qty} {product.sale_unit}s need a manual quote",
        }

    # ---- price source (one function for standard and custom)
    if item is not None:
        tiers_src = item.tiers
        breakpoints = item.breakpoints
        tier_labels = [t.label for t in tiers_src]

        def price_at(i: int) -> TierPrice:
            return TierPrice(tiers_src[i].price, tiers_src[i].flags)

        production_time = item.production_time
        description = _describe(item)
        sample_charge = item.sample_charge
    else:
        pool: list[Item] = custom_info["pool"]
        breakpoints = pool[0].breakpoints
        tier_labels = [t.label for t in pool[0].tiers]
        m = dimslib.metric(product.custom_dims, custom_info["dims"])

        def price_at(i: int) -> TierPrice:
            entries = [
                customlib.PoolSize(size=p.size, metric=p.metric, price=p.tiers[i].price, flags=p.tiers[i].flags)
                for p in pool
            ]
            cp = customlib.price_custom(entries, m, product.custom_surcharge_pct, product.custom_round_step)
            return TierPrice(cp.unit_price, cp.flags, cp)

        try:
            price_at(0)
        except customlib.OutOfRange as exc:
            return {
                **manual,
                "reason": "CUSTOM_OUT_OF_RANGE",
                "message": (
                    f"Custom size (metric {m2(exc.metric)} {dimslib.METRIC_UNIT}) is larger than the largest "
                    f"standard size ({m2(exc.largest)} {dimslib.METRIC_UNIT})"
                ),
            }
        production_time = pool[0].production_time
        opts = [custom_info["options"].get(k) for k in ("option_1", "option_2")]
        size_text = dimslib.format_dims(custom_info["dims"])
        if product.custom_dims == "bag":
            size_text += " (H × L × S)"
        description = ", ".join([*(o for o in opts if o), f"custom {size_text}"])
        sample_charge = None

    try:
        match = tierlib.resolve_tier(breakpoints, quantity, product.below_min_policy)
    except tierlib.BelowMinimum as exc:
        raise QuoteError(
            "BELOW_MIN", f"Minimum order is {exc.minimum} {product.sale_unit}s", 422, {"minimum": exc.minimum}
        ) from None

    current = price_at(match.index)
    open_flags = list(dict.fromkeys(cat.open_flags(current.flags)))
    if open_flags and product.flagged_price_policy == "block":
        raise QuoteError(
            "PRICE_BLOCKED", f"Price under review ({', '.join(open_flags)})", 422, {"flags": open_flags}
        )

    # ---- add-ons and totals
    available = addonlib.available_addons(product.addons, sample_charge)
    try:
        chosen = addonlib.select_addons(available, req.addons)
    except addonlib.UnknownAddon as exc:
        raise validation(f"Add-on not available for this product: {exc}", field="addons") from None
    per_unit, per_order = addonlib.split(chosen)

    def line_subtotal(unit_price: Decimal, qty: Decimal) -> Decimal:
        return totlib.subtotal(unit_price, per_unit, qty, per_order)

    sub = line_subtotal(current.unit_price, match.billed_qty)
    tot = totlib.totals(sub, product.gst_rate, req.billing_type)

    # ---- nudge and better option
    next_tier = None
    nxt = tierlib.units_to_next(breakpoints, match.index, match.billed_qty)
    if nxt is not None:
        next_from, to_go = nxt
        next_tier = {
            "qty_from": next_from,
            "units_to_next": num(to_go),
            "unit_price": m2(price_at(match.index + 1).unit_price),
        }
    better = None
    if product.suggest_more:
        candidates = [
            (breakpoints[j], line_subtotal(price_at(j).unit_price, Decimal(breakpoints[j])))
            for j in range(match.index + 1, len(breakpoints))
        ]
        best = tierlib.better_option(sub, candidates)
        if best is not None:
            better = {"qty": best.qty, "subtotal": m2(best.subtotal), "saving": m2(best.saving)}

    # ---- warnings
    warnings = []
    if open_flags:
        warnings.append(
            {
                "code": "PRICE_UNDER_REVIEW",
                "message": f"Price under review ({', '.join(open_flags)}) - confirm before sending",
                "flags": open_flags,
            }
        )
    if current.custom is not None:
        warnings.append({"code": "CUSTOM_ESTIMATE", "message": WARNING_TEXT["CUSTOM_ESTIMATE"]})
    if match.moq_applied:
        warnings.append(
            {
                "code": "MOQ_APPLIED",
                "message": f"Minimum order is {breakpoints[0]} - quoted for {breakpoints[0]}",
            }
        )
    if production_time.strip().lower() == "not stated":
        warnings.append({"code": "PRODUCTION_TIME_UNKNOWN", "message": WARNING_TEXT["PRODUCTION_TIME_UNKNOWN"]})

    micro = totlib.micro_price(current.unit_price, product.yield_factor)
    quantity_block = {
        "requested": num(quantity),
        "billed": num(match.billed_qty),
        "sale_unit": product.sale_unit,
    }
    if product.yield_factor > 1 and product.micro_unit:
        quantity_block["micro"] = {
            "amount": num(match.billed_qty * product.yield_factor),
            "unit": product.micro_unit,
            "approx": product.micro_approx,
        }

    custom_block = None
    if current.custom is not None:
        cp = current.custom
        custom_block = {
            "method": cp.method,
            "metric": m2(dimslib.metric(product.custom_dims, custom_info["dims"])),
            "metric_unit": dimslib.METRIC_UNIT,
            "anchors": [{"size": a.size, "metric": m2(a.metric), "unit_price": m2(a.unit_price)} for a in cp.anchors],
            "raw_unit_price": s(cp.raw_unit_price),
            "surcharge_pct": s(product.custom_surcharge_pct),
            "round_step": m2(product.custom_round_step),
        }

    notes = list(product.notes)
    if matched_note:
        notes.insert(0, matched_note)

    return {
        "status": "success",
        "data": {
            "product": {
                "id": product.id,
                "name": product.display_name,
                "category": product.category,
                "item_id": item.id if item is not None else None,
                "description": description,
            },
            "quantity": quantity_block,
            "pricing": {
                "tier_applied": {
                    "qty_from": breakpoints[match.index],
                    "label": tier_labels[match.index],
                    "range": tierlib.tier_range(breakpoints, match.index),
                },
                "unit_price": m2(current.unit_price),
                "micro_unit_price": m2(micro) if micro is not None else None,
                "micro_uom": product.micro_uom if micro is not None else None,
                "micro_approx": product.micro_approx if micro is not None else False,
                "next_tier": next_tier,
                "better_option": better,
                "custom_estimate": custom_block,
            },
            "addons": [
                {"id": a.id, "name": a.name, "price": m2(a.price), "basis": a.basis} for a in chosen
            ],
            "totals": {
                "subtotal": m2(tot.subtotal),
                "billing_type": tot.billing_type,
                "gst_rate_percent": s(tot.gst_rate * 100),
                "gst_amount": m2(tot.gst_amount),
                "grand_total": m2(tot.grand_total),
            },
            "production_time": production_time,
            "warnings": warnings,
            "notes": notes,
        },
    }


def _manual_base(product: Product, item: Item | None, custom_info: dict | None) -> dict:
    if item is not None:
        description = _describe(item)
    else:
        size_text = dimslib.format_dims(custom_info["dims"])
        description = ", ".join(
            [*(v for v in custom_info["options"].values() if v), f"custom {size_text}"]
        )
    return {
        "status": "manual_quote",
        "data": {"product": {"id": product.id, "name": product.display_name, "description": description}},
    }

