"""GST invoice PDF in BASTTA's format (docs/templates/gst_invoice.pdf): InvoiceDocument -> ops.

Header, buyer and consignee, delivery/transport fields, the item table (serial no.,
description with spec lines, HSN, quantity, units, rate, amount), then all five tax rows
(non-applicable ones at 0% and 0.00), Total, bank details, terms and the signatory block.
With print_payment_details off (config/invoice.yaml) the Payment Terms field, the bank details
and the late-payment term are left off; gst_invoice.print_bank_details brings the bank details back.
Money is printed with Indian digit grouping and two decimals.
"""
from decimal import Decimal

from . import fmt, terms
from . import layout as L
from . import layout_gst as G
from .config import InvoiceConfig
from .models import CartLine, InvoiceDocument, Party
from .money import Money, line_subtotal
from .paginate import Bar, Dot, Op, Text, shift, wrap_runs
from .render import Composed, document_money

TAX_KEYS = ("cgst", "ugst", "igst")


def compose_gst(doc: InvoiceDocument, cfg: InvoiceConfig) -> Composed:
    L.register_fonts()
    g = cfg.gst_invoice
    m = document_money(doc, cfg)
    rows = [_row(i + 1, line) for i, line in enumerate(doc.lines)]

    # Pages: rows in order, never split; the last page's rows end above the totals.
    plans: list[list[tuple[int, float]]] = [[]]
    y = G.FIRST_TITLE_Y
    for index, (ops, lowest) in enumerate(rows):
        if y + lowest + G.TABLE_END_RULE[2] > G.PAGE_ROWS_END and plans[-1]:
            plans.append([])
            y = G.FIRST_TITLE_Y - G.CONT_HEADER_SHIFT
        plans[-1].append((index, y))
        y += lowest + G.ROW_GAP
    last_end = _table_end(plans[-1], rows)
    if last_end is not None and last_end > G.LAST_PAGE_ROWS_END:
        plans.append([])

    pages: list[list[Op]] = []
    for n, plan in enumerate(plans):
        ops: list[Op] = []
        dy = 0.0
        if n == 0:
            ops += _header(doc, g, cfg)
        else:
            x, base, font, size = G.CONT_NUMBER
            ops.append(Text(x, base, f"{g['number_label']} {doc.bill_no} (continued)", font, size))
            dy = -G.CONT_HEADER_SHIFT
        if plan:
            ops += shift(_table_header(g["table_labels"]), dy)
            for index, title_y in plan:
                ops += shift(rows[index][0], title_y)
            end = _table_end(plan, rows)
            x0, x1, _, thick = G.TABLE_END_RULE
            ops.append(Bar(x0, x1, end - thick / 2, end + thick / 2))
        pages.append(ops)
    pages[-1] += _totals(m, g) + _footer(g, cfg.print_payment_details, bool(g.get("print_bank_details")))

    if len(pages) > 1:
        x, base, font, size = L.PAGE_NUMBER
        for n, ops in enumerate(pages, start=1):
            ops.append(Text(x, base, f"Page {n} of {len(pages)}", font, size, "right"))
    buyer = doc.gst.buyer.name if doc.gst else doc.customer.business_name
    return Composed(pages=pages, money=m, title=f"GST INVOICE {doc.bill_no} - {fmt.caps(buyer)}")


def _table_end(plan: list[tuple[int, float]], rows) -> float | None:
    if not plan:
        return None
    index, title_y = plan[-1]
    return title_y + rows[index][1] + G.TABLE_END_RULE[2]


# ---------------------------------------------------------------- header


def _fit(text: str, font: str, size: float, max_w: float, min_size: float) -> float:
    while L.width(text, font, size) > max_w and size > min_size:
        size = max(min_size, round(size - 0.25, 2))
    return size


def _header(doc: InvoiceDocument, g: dict, cfg: InvoiceConfig) -> list[Op]:
    ops: list[Op] = []
    cx, base, font, size = G.COPY_LABEL
    ops.append(Text(cx, base, g["copy_label"], font, size, "center"))
    x, base, font, size = G.SELLER_NAME
    ops.append(Text(x, base, g["seller_name"], font, size, skew=G.SELLER_NAME_SKEW))
    for text, base in zip(g["seller_lines"], G.SELLER_LINES_Y):
        ops.append(Text(G.SELLER_LINES_X, base, text, G.BOLD, G.SELLER_LINES_SIZE))
    for spec, gap, label, value in (
        (G.DATE_LABEL, G.DATE_GAP, g["date_label"], fmt.gst_date(doc.invoice_date)),
        (G.NUMBER_LABEL, G.NUMBER_GAP, g["number_label"], str(doc.bill_no)),
    ):
        x, base, font, size = spec
        ops.append(Text(x, base, label, font, size))
        vx = x + L.width(label, font, size) + gap
        ops.append(Text(vx, base, value, font, _fit(value, font, size, G.HEADER_VALUE_MAX_X - vx, 6.0)))

    details = doc.gst
    for heading, spec in ((g["buyer_heading"], G.BUYER_HEADING), (g["consignee_heading"], G.CONSIGNEE_HEADING)):
        x, base, font, size = spec
        ops.append(Text(x, base, heading, font, size))
    if details is not None:
        ops += _party(details.buyer, g, *G.BUYER_X, G.BUYER_Y0)
        ops += _party(details.shipped_to(), g, *G.CONSIGNEE_X, G.CONSIGNEE_Y0)
        values = {
            "delivery_terms": details.delivery_terms,
            "payment_terms": details.payment_terms,
            "po_date": fmt.gst_date(details.po_date) if details.po_date else "",
            "gr_rr_no": details.gr_rr_no,
            "transport": details.transport,
            "vehicle_no": details.vehicle_no,
            "eway_bill_no": details.eway_bill_no,
            "station": details.station,
        }
    else:
        values = {k: "" for k in G.FIELDS}
    for key, (x, base, size, max_x) in G.FIELDS.items():
        if key == "payment_terms" and not cfg.print_payment_details:
            continue  # no payment details on a printed invoice
        text = (g["field_labels"][key] + values[key]).rstrip()
        ops.append(Text(x, base, text, G.BOLD, _fit(text, G.BOLD, size, max_x - x, G.FIELD_MIN_SIZE)))
    return ops


def _party(party: Party, g: dict, x: float, max_x: float, y0: float) -> list[Op]:
    """Name, address (up to three lines, shrinking to fit), phone and GSTIN, one under another."""
    size = G.PARTY_SIZE
    entries: list[tuple[str, float]] = []
    if party.name:
        name = fmt.caps(party.name)
        entries.append((name, _fit(name, G.BOLD, size, max_x - x, G.PARTY_MIN_SIZE)))
    if party.address:
        address = fmt.caps(party.address)
        addr_size = size
        while True:
            lines = wrap_runs([(address, G.BOLD)], addr_size, x, x, max_x)
            if len(lines) <= G.PARTY_ADDRESS_LINES or addr_size <= G.PARTY_MIN_SIZE:
                break
            addr_size = round(addr_size - 0.25, 2)
        entries += [("".join(t for _, t, _ in line), addr_size) for line in lines]
    if party.phone:
        entries.append((g["party_phone"].format(value=party.phone), size))
    if party.gstin:
        entries.append((g["party_gstin"].format(value=party.gstin), size))
    return [Text(x, y0 + i * G.PARTY_STEP, text, G.BOLD, s) for i, (text, s) in enumerate(entries)]


# ---------------------------------------------------------------- table


def _table_header(labels: dict) -> list[Op]:
    ops: list[Op] = []
    first, last, cy = G.DOTS
    x = first + G.DOT_D / 2
    while x <= last:
        ops.append(Dot(x, cy, G.DOT_D))
        x += G.DOT_STEP
    for key, (cx, base, size) in G.TABLE_LABELS.items():
        ops.append(Text(cx, base, labels[key], G.BOLD, size, "center"))
    x0, x1, top, bottom = G.HEADER_RULE
    ops.append(Bar(x0, x1, top, bottom))
    return ops


def _row(serial: int, line: CartLine) -> tuple[list[Op], float]:
    """One line with its first title baseline at y = 0. Returns (ops, lowest baseline offset)."""
    ops: list[Op] = []
    x, offset, font, size = G.SERIAL
    ops.append(Text(x, offset, f"{serial}.", font, size))
    title = fmt.caps(line.title)
    title_size = _fit(title, G.BOLD, G.TITLE_SIZE, G.TITLE_MAX_X - G.TITLE_X, G.TITLE_MIN_SIZE)
    titles = wrap_runs([(title, G.BOLD)], title_size, G.TITLE_X, G.TITLE_X, G.TITLE_MAX_X)
    for i, pieces in enumerate(titles):
        ops += [Text(px, i * G.TITLE_STEP, t, f, title_size) for px, t, f in pieces]
    lowest = (len(titles) - 1) * G.TITLE_STEP

    y = lowest + G.SPEC_FIRST
    # Specs, then (like the Printevr invoice) a CUSTOMISATIONS:- heading over the customisations.
    specs: list = list(line.specs)
    if line.customisations:
        specs += [None, *line.customisations]
    for spec in specs:
        runs = []
        if spec is None:
            runs = [(L.CUSTOMISATIONS_HEADING, G.BOLD)]
        elif spec.label:
            runs += [(f"{fmt.caps(spec.label)}:- ", G.BOLD)]
        if spec is not None:
            runs.append((fmt.caps(spec.value), G.REGULAR))
        for pieces in wrap_runs(runs, G.SPEC_SIZE, G.SPEC_X, G.SPEC_X, G.SPEC_MAX_X):
            ops += [Text(px, y, t, f, G.SPEC_SIZE) for px, t, f in pieces]
            lowest = y
            y += G.SPEC_STEP

    qty = Decimal(str(line.quantity))
    price = Decimal(str(line.unit_price))
    cells = {
        "hsn": line.hsn_code or "",
        "quantity": fmt.quantity(qty),
        "units": fmt.caps(line.unit_label),
        "rate": fmt.inr(price),
        "amount": fmt.inr(line_subtotal(qty, price)),
    }
    font, size = G.NUM_FONT
    for key, (cx, max_w) in G.NUM_COLUMNS.items():
        if cells[key]:
            ops.append(Text(cx, G.NUMBERS_OFFSET, cells[key], font, _fit(cells[key], font, size, max_w, G.NUM_MIN_SIZE), "center"))
    return ops, max(lowest, G.NUMBERS_OFFSET)


# ---------------------------------------------------------------- totals and footer


def _totals(m: Money, g: dict) -> list[Op]:
    t = g["totals"]
    font, size = G.TOTALS_FONT
    taxes = dict(zip(TAX_KEYS, m.taxes))
    rows = [("sub_total", t["sub_total"], m.total)]
    for key in TAX_KEYS:
        tax = taxes.get(key)
        rate = terms.pct(tax.rate) if tax else "0"
        name = tax.name if tax else key.upper()
        rows.append((key, t["tax"].format(name=name, rate=rate), tax.amount if tax else Decimal("0")))
    rows.append(("after_tax", t["after_tax"], m.payable))
    ops: list[Op] = []
    for key, label, amount in rows:
        base = G.TOTALS_Y[key]
        ops.append(Text(G.TOTALS_LABEL_RIGHT, base, label, font, size, "right"))
        ops.append(Text(G.TOTALS_VALUE_RIGHT, base, fmt.inr(amount), font, size, "right"))
    ops.append(Bar(*G.TOTAL_RULE_1))
    x, base, tfont, tsize = G.TOTAL_LABEL
    ops.append(Text(x, base, t["total"], tfont, tsize))
    value = fmt.inr(m.payable)
    label_end = x + L.width(t["total"], tfont, tsize) + 6
    vsize = _fit(value, tfont, tsize, G.TOTAL_VALUE_RIGHT - label_end, 8.0)
    ops.append(Text(G.TOTAL_VALUE_RIGHT, base, value, tfont, vsize, "right"))
    ops.append(Bar(*G.TOTAL_RULE_2))
    return ops


def _footer(g: dict, payment_details: bool = True, bank_details: bool = False) -> list[Op]:
    """Bank details (with the payment details, or on their own with print_bank_details), terms,
    and the signatory block."""
    ops: list[Op] = []
    font, size = G.BANK_FONT
    for i, text in enumerate(g["bank_lines"] if payment_details or bank_details else []):
        ops.append(Text(G.BANK_X, G.BANK_Y0 + i * G.BANK_STEP, text, font, size))
    x, base, hfont, hsize = G.TERMS_HEADING
    ops.append(Text(x, base, g["terms_heading"], hfont, hsize))
    ops.append(Bar(x, x + L.width(g["terms_heading"], hfont, hsize), *G.TERMS_RULE_Y))
    terms_lines = g["terms_lines"] if payment_details else g.get("terms_lines_without_payment", g["terms_lines"])
    for i, text in enumerate(terms_lines):
        tsize = _fit(text, G.REGULAR, G.TERMS_SIZE, G.TERMS_MAX_X - G.TERMS_X, 5.0)
        ops.append(Text(G.TERMS_X, G.TERMS_Y0 + i * G.TERMS_STEP, text, G.REGULAR, tsize))
    cx, base, cfont, csize = G.CERTIFIED
    ops.append(Text(cx, base, g["certified"], cfont, _fit(g["certified"], cfont, csize, G.CERTIFIED_MAX_W, 4.5), "center"))
    cx, base, sfont, ssize = G.SIGNATORY
    ops.append(Text(cx, base, g["signatory"], sfont, ssize, "center"))
    return ops
