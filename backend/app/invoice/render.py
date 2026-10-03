"""Invoice PDF in Printevr's format (BRD-cart-invoice section 7): InvoiceDocument -> bytes.

Non-GST invoices print here, with the payment summary under the items (config payment_summary).
GST invoices keep the BASTTA layout (render_gst.py) and quotations their own (render_quote.py).

compose() lays every page out as ops (paginate.py); draw() turns them into ReportLab calls
on a canvas created with invariant=1, so the same document always gives the same bytes.
"""
import io
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from reportlab.lib.colors import black, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from . import fmt, terms
from . import layout as L
from .config import InvoiceConfig
from .gst import LEGACY_COMPONENTS, GstComponent
from .models import InvoiceDocument
from .money import Money, compute, line_subtotal
from .paginate import Bar, BoxLayout, Box, Dot, Image, Op, Pill, Text, layout_box, layout_row, paginate, shift, wrap_runs


@dataclass
class Composed:
    pages: list[list[Op]]
    money: Money
    title: str


def doc_components(doc: InvoiceDocument) -> tuple[GstComponent, ...]:
    """The GST components an issued invoice was charged: stored with it, never re-read from config."""
    if doc.series == "gst":
        return tuple(GstComponent(t.name, t.rate) for t in doc.taxes)
    if doc.series == "quotation" or doc.billing_type != "with_gst":
        return ()
    if not doc.taxes:
        return LEGACY_COMPONENTS
    return tuple(GstComponent(t.name, t.rate) for t in doc.taxes)


def doc_advance_pct(doc: InvoiceDocument, cfg: InvoiceConfig) -> Decimal:
    """Percent due before printing, as issued. Old records without one used the config's."""
    return doc.advance_pct if doc.advance_pct is not None else cfg.advance_pct


def document_money(doc: InvoiceDocument, cfg: InvoiceConfig) -> Money:
    subtotals = [line_subtotal(Decimal(str(l.quantity)), l.unit_price) for l in doc.lines]
    return compute(subtotals, doc_components(doc), doc_advance_pct(doc, cfg), [p.amount for p in doc.payments])


def _payment_box(doc: InvoiceDocument, cfg: InvoiceConfig, m: Money) -> BoxLayout | None:
    """What goes between the last item and the totals: the payment summary (PAYMENT TERMS,
    then RECIEVABLES once something is received), else the reference's payment-terms box
    when print_payment_details is on, else nothing."""
    entries = [terms.PaymentEntry(p.amount, p.date, p.mode) for p in doc.payments]
    title = terms.title(cfg.payment_terms, "with_gst" if m.taxes else "without_gst")
    if cfg.payment_summary:
        s = cfg.payment_summary
        box = layout_box(title, terms.summary_terms(s, m, doc_advance_pct(doc, cfg)), metrics=L.SUMMARY_METRICS)
        received = terms.summary_receivables(s, m, entries)
        if not received:
            return box
        second = layout_box(
            s["receivables_title"], received, [True] * (len(received) - 1) + [False], metrics=L.SUMMARY_METRICS
        )
        top = box.height + L.SUMMARY_GAP
        return BoxLayout(ops=box.ops + shift(second.ops, top), height=top + second.height,
                         line_count=box.line_count + second.line_count)
    if cfg.print_payment_details:
        return layout_box(
            terms.title(cfg.payment_terms, doc.billing_type),
            terms.lines(cfg.payment_terms, m, doc_advance_pct(doc, cfg), entries),
        )
    return None


def compose(doc: InvoiceDocument, cfg: InvoiceConfig) -> Composed:
    L.register_fonts()
    m = document_money(doc, cfg)
    rows = [layout_row(line, cfg.pad_single_digit_unit_price) for line in doc.lines]
    # As on the template, an article and its add-on rows share a block: no rule between them.
    for row, following in zip(rows, doc.lines[1:]):
        if following.source == "addon":
            row.ops = [op for op in row.ops if not isinstance(op, Bar)]
    box = _payment_box(doc, cfg, m)
    # Without the payment box the totals still need the room below the last row.
    plans = paginate([r.height for r in rows], box.height if box else 0.0, len(m.taxes))

    pages: list[list[Op]] = []
    for plan in plans:
        ops: list[Op] = []
        if plan.first:
            ops += _page_one_top(doc, cfg)
        else:
            x, y, font, size = L.CONT_BILL
            ops.append(Text(x, y, f"Bill No : {doc.bill_no} (continued)", font, size))
        if plan.table_header and plan.rows:
            ops += _table_header(plan.header_top)
        for index, top in plan.rows:
            ops += rows[index].at(top)
        if plan.box_top is not None:
            if box is not None:
                ops += box.at(plan.box_top)
            ops += _totals_and_footer(doc, cfg, m)
        pages.append(ops)

    if len(pages) > 1:
        x, y, font, size = L.PAGE_NUMBER
        for n, ops in enumerate(pages, start=1):
            ops.append(Text(x, y, f"Page {n} of {len(pages)}", font, size, "right"))

    return Composed(pages=pages, money=m, title=f"INVOICE {doc.bill_no} - {fmt.caps(doc.customer.business_name)}")


# ---------------------------------------------------------------- page parts


def _text(spec: tuple, text: str, align: str = "left", tracking: str | None = None) -> Text:
    x, y, font, size = spec[:4]
    return Text(x, y, text, font, size, align, L.TRACKING.get(tracking or text, 0.0) if align == "left" else 0.0)


def _page_one_top(doc: InvoiceDocument, cfg: InvoiceConfig) -> list[Op]:
    bx, btop, bw, bbottom = L.BAND
    lx, ltop, lw, lh = L.LOGO
    ops: list[Op] = [
        Image(str(L.BAND_IMAGE), bx, btop, bw, bbottom - btop),
        Image(str(L.LOGO_IMAGE), lx, ltop, lw, lh),
        _text(L.DATE_LABEL, "Date"),
        _text(L.DATE_VALUE, L.VALUE_PREFIX + fmt.invoice_date(doc.invoice_date)),
        _text(L.BILL_LABEL, "Bill No"),
        _text(L.BILL_VALUE, L.VALUE_PREFIX + str(doc.bill_no)),
    ]
    for heading, bar in ((L.SHIP_TO_HEADING, L.SHIP_TO_RULE), (L.FROM_HEADING, L.FROM_RULE)):
        x, y, font, size, text = heading
        ops.append(Text(x, y, text, font, size, char_space=L.TRACKING.get(text, 0.0)))
        ops.append(Bar(bar[0], bar[1], bar[2], bar[3]))
    font, size = L.FROM_LINES_FONT
    for text, y in zip(cfg.from_lines, L.FROM_LINES_Y):
        ops.append(Text(L.FROM_LINES_X, y, text, font, size))
    ops += _ship_to(doc)
    return ops


def _ship_to(doc: InvoiceDocument) -> list[Op]:
    c = doc.customer
    x, size = L.SHIP_TO_X, L.SHIP_TO_SIZE
    entries: list[tuple[str, str, float]] = [(f"{fmt.caps(c.business_name)},", L.BOLD, size)]
    if c.contact_person:
        entries.append((f"{fmt.caps(c.contact_person)},", L.BOLD, size))
    address = fmt.caps(c.address)
    addr_size = size
    while True:
        lines = wrap_runs([(address, L.REGULAR)], addr_size, x, x, L.SHIP_TO_ADDRESS_MAX_X)
        if len(lines) <= L.SHIP_TO_ADDRESS_LINES or addr_size <= L.SHIP_TO_MIN_SIZE:
            break
        addr_size = round(addr_size - 0.25, 2)
    entries += [("".join(t for _, t, _ in line), L.REGULAR, addr_size) for line in lines]
    entries.append((f"{c.phone},", L.BOLD, size))
    return [Text(x, L.SHIP_TO_Y0 + i * L.SHIP_TO_STEP, t, f, s) for i, (t, f, s) in enumerate(entries)]


def _table_header(top: float) -> list[Op]:
    height = L.TABLE_PILL_Y[1] - L.TABLE_PILL_Y[0]
    ops: list[Op] = [Pill(L.TABLE_PILL_X[0], L.TABLE_PILL_X[1], top, top + height)]
    for text, x, offset, size in L.TABLE_LABELS:
        ops.append(Text(x, top + offset, text, L.REGULAR, size, char_space=L.TRACKING.get(text, 0.0)))
    return ops


def _bold_runs(template: str, x: float, y: float, size: float) -> list[Op]:
    ops: list[Op] = []
    for text, bold in terms.runs(template):
        font = L.BOLD if bold else L.REGULAR
        ops.append(Text(x, y, text, font, size))
        x += L.width(text, font, size)
    # Spaces at run edges carry no ink; keep each run's text as drawn.
    return [op for op in ops if op.text.strip()]


def _totals_and_footer(doc: InvoiceDocument, cfg: InvoiceConfig, m: Money) -> list[Op]:
    ops: list[Op] = []
    lx, ly, lfont, lsize, ltext = L.TOTAL_LABEL
    vx, vy, vfont, vsize = L.TOTAL_VALUE
    # One tax row per GST component, the last on the old TOTAL line; TOTAL moves up a line per row.
    rows = len(m.taxes)
    ops.append(Text(lx, ly - L.GST_LIFT * rows, ltext, lfont, lsize))
    ops.append(Text(vx, vy - L.GST_LIFT * rows, fmt.amount(m.total), vfont, vsize, "right"))
    for i, tax in enumerate(m.taxes):
        lift = L.GST_LIFT * (rows - 1 - i)
        label = cfg.totals["gst_label"].format(name=tax.name, rate=terms.pct(tax.rate))
        ops.append(Text(L.TOTAL_LABEL_RIGHT, ly - lift, label, lfont, lsize, "right"))
        ops.append(Text(vx, vy - lift, fmt.amount(tax.amount), vfont, vsize, "right"))

    px0, px1, ptop, pbottom = L.SUB_PILL
    ops.append(Pill(px0, px1, ptop, pbottom))
    ops.append(_text(L.SUB_LABEL, L.SUB_LABEL[4]))
    sx, sy, sfont, ssize = L.SUB_VALUE
    payable = fmt.amount(m.payable)
    while ssize > L.SUB_VALUE_MIN_SIZE and sx - L.width(payable, sfont, ssize) < L.SUB_VALUE_MIN_X:
        ssize = max(L.SUB_VALUE_MIN_SIZE, round(ssize - 0.25, 2))
    ops.append(Text(sx, sy, payable, sfont, ssize, "right"))

    if cfg.payment_summary:
        if cfg.payment_summary["upi_qr"]:
            ops.append(Image(str(L.UPI_QR_IMAGE), *L.UPI_QR))
        ufont, usize = L.UPI_FONT
        for i, text in enumerate(cfg.payment_summary["upi_lines"]):
            ops.append(Text(L.UPI_X, L.UPI_Y0 + i * L.UPI_STEP, text, ufont, usize))

    if doc.saving_amount is not None and doc.saving_amount > 0:
        for template, y in zip(cfg.saving_lines, L.SAVING_LINES_Y):
            ops += _bold_runs(template, L.SAVING_X, y, L.SAVING_SIZE)
        ax, ay, afont, asize = L.SAVING_AMOUNT
        saving = fmt.amount(doc.saving_amount)
        ops.append(Text(ax, ay, saving, afont, asize))
        gap, py, pfont, psize, ptext = L.APPROX
        ops.append(Text(ax + L.width(saving, afont, asize) + gap, py, ptext, pfont, psize))

    f = cfg.footer
    ops.append(_text(L.THANKS, f["thanks"], tracking="thanks"))
    ops.append(_text(L.CONTACT, f["contact_prefix"] + f["email"]))
    cx, _, cfont, csize = L.CONTACT
    email_x0 = cx + L.width(f["contact_prefix"], cfont, csize)
    email_x1 = email_x0 + L.width(f["email"], cfont, csize)
    ops.append(Bar(email_x0, email_x1, *L.EMAIL_RULE_Y))
    if cfg.print_payment_details:
        ops.append(_text(L.ADVANCE_NOTE, f["advance_note"]))
    ops.append(_text(L.COLOUR_NOTE, f["colour_note"]))
    if cfg.print_payment_details:
        ops.append(_text(L.LATE_NOTE, f["late_note"], tracking="late_note"))
    ops.append(_text(L.TERMS_NOTE, f["terms_note"], tracking="terms_note"))
    if m.taxes:
        gst_note = f["gst_note_with_gst"].format(gst_pct=terms.pct(sum((t.rate for t in m.taxes), Decimal(0))))
    else:
        gst_note = f["gst_note_without_gst"]
    ops.append(_text(L.GST_NOTE, gst_note))
    return ops


# ---------------------------------------------------------------- drawing


@lru_cache(maxsize=8)
def _image(path: str) -> ImageReader:
    return ImageReader(path)


def draw(composed: Composed) -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(L.PAGE_W, L.PAGE_H), invariant=1, pageCompression=1)
    c.setTitle(composed.title)
    c.setAuthor(L.AUTHOR)
    c.setCreator(L.AUTHOR)
    c.setProducer(L.AUTHOR)
    H = L.PAGE_H
    for ops in composed.pages:
        for op in ops:
            if isinstance(op, Image):
                c.drawImage(_image(op.path), op.x, H - op.top - op.h, width=op.w, height=op.h, mask="auto")
            elif isinstance(op, Text):
                c.setFillColor(black)
                c.setFont(op.font, op.size)
                if op.align == "center":
                    c.drawCentredString(op.x, H - op.y, op.text)
                elif op.align == "right":
                    c.drawRightString(op.x, H - op.y, op.text)
                elif op.skew:
                    c.saveState()
                    c.translate(op.x, H - op.y)
                    c.skew(0, op.skew)
                    c.drawString(0, 0, op.text, charSpace=op.char_space)
                    c.restoreState()
                elif op.char_space:
                    c.drawString(op.x, H - op.y, op.text, charSpace=op.char_space)
                else:
                    c.drawString(op.x, H - op.y, op.text)
            elif isinstance(op, Bar):
                c.setFillColor(black)
                c.rect(op.x0, H - op.bottom, op.x1 - op.x0, op.bottom - op.top, stroke=0, fill=1)
            elif isinstance(op, Dot):
                c.setFillColor(black)
                c.circle(op.cx, H - op.cy, op.d / 2, stroke=0, fill=1)
            # Pill and box coordinates are the OUTER edge of the stroke (as measured on the
            # reference), so the path runs half a stroke inside them.
            elif isinstance(op, Pill):
                i = L.PILL_STROKE / 2
                h = op.bottom - op.top - 2 * i
                c.setFillColor(white)
                c.setStrokeColor(black)
                c.setLineWidth(L.PILL_STROKE)
                c.roundRect(op.x0 + i, H - op.bottom + i, op.x1 - op.x0 - 2 * i, h, h / 2, stroke=1, fill=1)
            elif isinstance(op, Box):
                i = L.BOX_STROKE / 2
                c.setStrokeColor(black)
                c.setLineWidth(L.BOX_STROKE)
                c.rect(op.x0 + i, H - op.bottom + i, op.x1 - op.x0 - 2 * i, op.bottom - op.top - 2 * i, stroke=1, fill=0)
        c.showPage()
    c.save()
    return buf.getvalue()


def render(doc: InvoiceDocument, cfg: InvoiceConfig) -> bytes:
    return draw(compose(doc, cfg))


def render_document(doc: InvoiceDocument, cfg: InvoiceConfig) -> bytes:
    """The PDF in the template for the document's series."""
    if doc.series == "quotation":
        from .render_quote import compose_quotation

        return draw(compose_quotation(doc, cfg))
    if doc.series == "gst":
        from .render_gst import compose_gst

        return draw(compose_gst(doc, cfg))
    return render(doc, cfg)
