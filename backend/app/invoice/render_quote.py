"""Quotation PDF in Printevr's format (docs/templates/quotation.pdf): InvoiceDocument -> ops.

The invoice's page (band, Date line, Ship To, From) with QUOTATION in the pill and Quote No;
columns ITEM, QUANTITY, MARKET PRICE, DISCOUNTED PRICE, SUBTOTAL; then TOTAL, SUB TOTAL, the
the saving block and the footer notes. No tax rows and no payment details of any kind: no
payment terms, UPI or bank details, none of the footer's payment notes and no GST note.
"""
from . import fmt
from . import layout as L
from . import layout_quote as Q
from .config import InvoiceConfig
from .models import InvoiceDocument
from .paginate import Bar, Columns, Image, Op, Pill, RowLayout, Text, layout_row
from .render import Composed, _bold_runs, _ship_to, document_money

COLUMNS = Columns(
    title_x=Q.TITLE_X,
    title_max_x=Q.TITLE_MAX_X,
    qty_center=Q.QTY_CENTER,
    note_x=Q.NOTE_X,
    note_max_x=Q.NOTE_MAX_X,
    ref_center=Q.REF_PRICE_CENTER,
    price_center=Q.PRICE_CENTER,
    subtotal_center=Q.SUBTOTAL_CENTER,
    rule_x=Q.ROW_RULE_X,
    empty_ref=Q.EMPTY_CELL,
)


def rows_for(doc: InvoiceDocument, pad: bool) -> list[RowLayout]:
    """One row per line. Articles are numbered (1.TITLE, as on the template); an add-on gets its
    own row, without a number and without a rule between it and its article."""
    rows: list[RowLayout] = []
    number = 0
    for i, line in enumerate(doc.lines):
        if line.source == "addon":
            title = line.title
        else:
            number += 1
            title = f"{number}.{line.title}"
        row = layout_row(line, pad, COLUMNS, title)
        following = doc.lines[i + 1] if i + 1 < len(doc.lines) else None
        if following is not None and following.source == "addon":
            row.ops = [op for op in row.ops if not isinstance(op, Bar)]
        rows.append(row)
    return rows


def compose_quotation(doc: InvoiceDocument, cfg: InvoiceConfig) -> Composed:
    L.register_fonts()
    m = document_money(doc, cfg)
    q = cfg.quotation
    rows = rows_for(doc, cfg.pad_single_digit_unit_price)

    # Pages: rows in order, never split; the totals block needs the last page clear below its rows.
    plans: list[list[tuple[int, float]]] = [[]]
    top = Q.FIRST_ROW_TOP
    for index, row in enumerate(rows):
        if top + row.height > Q.ROW_RULE_LIMIT and plans[-1]:
            plans.append([])
            top = Q.CONT_ROW_TOP
        plans[-1].append((index, top))
        top += row.height
    if top > Q.LAST_ROW_RULE_LIMIT:
        plans.append([])  # totals and footer on a page of their own

    pages: list[list[Op]] = []
    for n, plan in enumerate(plans):
        ops: list[Op] = []
        if n == 0:
            ops += _page_one_top(doc, cfg)
            ops += _table_header(Q.TABLE_PILL_Y[0], q["table_labels"])
        else:
            x, y, font, size = L.CONT_BILL
            ops.append(Text(x, y, f"{q['number_label']} : {doc.bill_no} (continued)", font, size))
            if plan:
                ops += _table_header(Q.CONT_TABLE_PILL_TOP, q["table_labels"])
        for index, row_top in plan:
            ops += rows[index].at(row_top)
        pages.append(ops)
    pages[-1] += _totals_and_footer(doc, cfg, m.total)

    if len(pages) > 1:
        x, y, font, size = L.PAGE_NUMBER
        for n, ops in enumerate(pages, start=1):
            ops.append(Text(x, y, f"Page {n} of {len(pages)}", font, size, "right"))
    title = f"{q['title']} {doc.bill_no} - {fmt.caps(doc.customer.business_name)}".rstrip(" -")
    return Composed(pages=pages, money=m, title=title)


def _page_one_top(doc: InvoiceDocument, cfg: InvoiceConfig) -> list[Op]:
    q = cfg.quotation
    bx, btop, bw, bbottom = L.BAND
    lx, ltop, lw, lh = L.LOGO
    title = q["title"]
    size = Q.TITLE_SIZE
    while _spaced_width(title, Q.TITLE_FONT, size) > Q.TITLE_MAX_W and size > 12:
        size = round(size - 0.25, 2)
    title_x = Q.TITLE_CENTER_X - _spaced_width(title, Q.TITLE_FONT, size) / 2
    ops: list[Op] = [
        Image(str(Q.BAND_IMAGE), bx, btop, bw, bbottom - btop),
        Image(str(L.LOGO_IMAGE), lx, ltop, lw, lh),
        Text(title_x, Q.TITLE_BASELINE, title, Q.TITLE_FONT, size, char_space=Q.TITLE_CHAR_SPACE),
    ]
    # As on the template: "Date   01 OCT 2026" and "Quote No : 7"; a longer label pushes its value along.
    x, y, font, size = L.DATE_LABEL
    ops.append(Text(x, y, "Date", font, size, char_space=L.TRACKING["Date"]))
    x, y, font, size = L.DATE_VALUE
    ops.append(Text(x, y, fmt.quote_date(doc.invoice_date), font, size))
    x, y, font, size = L.BILL_LABEL
    ops.append(Text(x, y, q["number_label"], font, size))
    value_x = max(L.BILL_VALUE[0], x + L.width(q["number_label"], font, size) + Q.NUMBER_GAP)
    ops.append(Text(value_x, y, Q.NUMBER_PREFIX + str(doc.bill_no), font, size))
    for heading, bar in ((L.SHIP_TO_HEADING, L.SHIP_TO_RULE), (L.FROM_HEADING, L.FROM_RULE)):
        x, y, font, size, text = heading
        ops.append(Text(x, y, text, font, size, char_space=L.TRACKING.get(text, 0.0)))
        ops.append(Bar(bar[0], bar[1], bar[2], bar[3]))
    font, size = L.FROM_LINES_FONT
    for text, y in zip(cfg.from_lines, L.FROM_LINES_Y):
        ops.append(Text(L.FROM_LINES_X, y, text, font, size))
    if doc.customer.business_name or doc.customer.address or doc.customer.phone:
        ops += _ship_to(doc)
    return ops


def _spaced_width(text: str, font: str, size: float) -> float:
    return L.width(text, font, size) + Q.TITLE_CHAR_SPACE * (len(text) - 1)


def _table_header(top: float, labels: dict) -> list[Op]:
    height = Q.TABLE_PILL_Y[1] - Q.TABLE_PILL_Y[0]
    ops: list[Op] = [Pill(Q.TABLE_PILL_X[0], Q.TABLE_PILL_X[1], top, top + height)]
    for key, (x, offset, size, align) in Q.TABLE_LABELS.items():
        ops.append(Text(x, top + offset, labels[key], L.REGULAR, size, align))
    for key, (cx, first, second, size) in (("market_price", Q.MARKET_LABEL), ("discounted_price", Q.DISCOUNTED_LABEL)):
        upper, lower = labels[key]
        ops.append(Text(cx, top + first, upper, L.REGULAR, size, "center"))
        ops.append(Text(cx, top + second, lower, L.REGULAR, size, "center"))
    return ops


def _totals_and_footer(doc: InvoiceDocument, cfg: InvoiceConfig, total) -> list[Op]:
    q = cfg.quotation
    lx, ly, lfont, lsize, ltext = Q.TOTAL_LABEL
    vx, vy, vfont, vsize = Q.TOTAL_VALUE
    amount = fmt.amount(total)
    ops: list[Op] = [Text(lx, ly, ltext, lfont, lsize), Text(vx, vy, amount, vfont, vsize, "right")]

    px0, px1, ptop, pbottom = Q.SUB_PILL
    ops.append(Pill(px0, px1, ptop, pbottom))
    sx, sy, sfont, ssize, stext = Q.SUB_LABEL
    ops.append(Text(sx, sy, stext, sfont, ssize))
    vx, vy, vfont, vsize = Q.SUB_VALUE
    while vsize > Q.SUB_VALUE_MIN_SIZE and vx - L.width(amount, vfont, vsize) < Q.SUB_VALUE_MIN_X:
        vsize = max(Q.SUB_VALUE_MIN_SIZE, round(vsize - 0.25, 2))
    ops.append(Text(vx, vy, amount, vfont, vsize, "right"))


    if doc.saving_amount is not None and doc.saving_amount > 0:
        for template, y in zip(cfg.saving_lines, Q.SAVING_LINES_Y):
            ops += _bold_runs(template, Q.SAVING_X, y, Q.SAVING_SIZE)
        ax, ay, afont, asize = Q.SAVING_AMOUNT
        saving = fmt.amount(doc.saving_amount)
        ops.append(Text(ax, ay, saving, afont, asize))
        gap, py, pfont, psize, ptext = Q.APPROX
        ops.append(Text(ax + L.width(saving, afont, asize) + gap, py, ptext, pfont, psize))

    f = cfg.footer
    for spec, text in (
        (Q.THANKS, f["thanks"]),
        (Q.CONTACT, f["contact_prefix"] + f["email"]),
        (Q.COLOUR_NOTE, f["colour_note"]),
        (Q.TERMS_NOTE, f["terms_note"]),
    ):
        x, y, font, size = spec
        ops.append(Text(x, y, text, font, size))
    cx, _, cfont, csize = Q.CONTACT
    email_x0 = cx + L.width(f["contact_prefix"], cfont, csize)
    ops.append(Bar(email_x0, email_x0 + L.width(f["email"], cfont, csize), *Q.EMAIL_RULE_Y))
    return ops
