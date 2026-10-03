"""The products of an issued invoice, for per-product design and production tracking.

A product is one non-add-on line of the invoice, identified by its position in the stored
`lines` (`line_no`, from 0). Issued invoices are never re-priced or edited, so positions don't
move. Add-on lines are listed under the product they belong to. Pure: takes the stored lines.
"""
from decimal import Decimal

DETAILS_MAX = 4


def _qty(value) -> str:
    try:
        return f"{Decimal(str(value)).normalize():f}"
    except Exception:
        return str(value)


def products(lines: list | None) -> list[dict]:
    lines = list(lines or [])
    out: list[dict] = []
    by_id: dict[str, dict] = {}
    for i, line in enumerate(lines):
        if line.get("source") == "addon":
            continue
        specs = [
            f"{s.get('label', '')}: {s.get('value', '')}".strip(": ")
            for s in (line.get("specs") or [])
            if isinstance(s, dict)
        ]
        product = {
            "line_no": i,
            "title": line.get("title", ""),
            "quantity": _qty(line.get("quantity", "")),
            "unit_label": line.get("unit_label", ""),
            "details": specs[:DETAILS_MAX],
            "addons": [],
        }
        out.append(product)
        if line.get("id"):
            by_id[line["id"]] = product
    for line in lines:
        if line.get("source") == "addon" and line.get("parent_id") in by_id:
            by_id[line["parent_id"]]["addons"].append(line.get("title", ""))
    return out


def product_line_nos(lines: list | None) -> list[int]:
    return [p["line_no"] for p in products(lines)]
