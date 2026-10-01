"""Emails each new invoice and each recorded payment, with its PDF, to config/invoice.yaml `email.to`.

Non-GST and GST invoices are emailed; quotations are not. The body lists the sale (customer,
bill, items, totals, payment status) as simple HTML with a plain-text copy. Every value typed by staff is escaped in the
HTML. Sending is best effort: a mail failure is logged and never stops the invoice being
saved or downloaded. Without SMTP_PASSWORD (or without the `email` block) nothing is sent.
"""
import logging
import smtplib
from email.message import EmailMessage
from html import escape
from typing import Literal

from ..settings import Settings
from . import fmt
from .config import InvoiceConfig
from .money import line_subtotal
from .service import Rendered

log = logging.getLogger("printevr.invoice")

SEND_TIMEOUT_S = 15


def _one_line(text: str) -> str:
    """Header-safe: no line breaks can reach the Subject."""
    return " ".join(text.split())


def compose(cfg: InvoiceConfig, r: Rendered, kind: Literal["new", "payment"]) -> EmailMessage:
    email = cfg.email
    labels = email["labels"]
    doc, m = r.doc, r.money
    status = email["status_labels"][r.status]
    fields = {"bill_no": r.bill_no, "business": r.business_name, "status": status}
    rs = lambda value: labels["currency"] + fmt.amount(value)  # noqa: E731
    suffix = "_gst" if r.series == "gst" else ""

    facts = [(labels["customer"], r.business_name), (labels["bill_no"], str(r.bill_no))]
    items: list[tuple[str, str, str, str]] = []
    totals: list[tuple[str, str]] = []
    if doc:
        facts.append((labels["invoice_date"], fmt.payment_date(doc.invoice_date)))
        for line in doc.lines:
            qty = f"{fmt.quantity(line.quantity)} {line.unit_label}"
            items.append((line.title, qty, rs(line.unit_price), rs(line_subtotal(line.quantity, line.unit_price))))
    if m:
        totals.append((labels["total"], rs(m.total)))
        if m.payable != m.total:
            totals.append((labels["payable"], rs(m.payable)))
        totals += [
            (labels["status"], status),
            (labels["received"], rs(m.received)),
            (labels["pending"], rs(m.payable - m.received)),
        ]
    intro = email[f"intro_{kind}{suffix}"].format(**fields)

    msg = EmailMessage()
    msg["Subject"] = _one_line(email[f"subject_{kind}{suffix}"].format(**fields))
    msg.set_content(_plain(intro, facts, labels, items, totals))
    msg.add_alternative(_html(intro, facts, labels, items, totals), subtype="html")
    msg.add_attachment(r.pdf, maintype="application", subtype="pdf", filename=r.filename)
    return msg


def _plain(intro, facts, labels, items, totals) -> str:
    out = [intro, ""]
    out += [f"{k}: {v}" for k, v in facts]
    if items:
        out += ["", f"{labels['items']}:"]
        out += [f"- {title}: {qty} x {price} = {sub}" for title, qty, price, sub in items]
    if totals:
        out.append("")
        out += [f"{k}: {v}" for k, v in totals]
    out += ["", labels["attached"]]
    return "\n".join(out) + "\n"


CELL = 'style="padding:4px 8px;border-bottom:1px solid #ddd;text-align:{align}"'


def _html(intro, facts, labels, items, totals) -> str:
    e = lambda s: escape(str(s), quote=True)  # noqa: E731

    def rows(pairs):
        return "".join(
            f'<tr><th {CELL.format(align="left")}>{e(k)}</th><td {CELL.format(align="left")}>{e(v)}</td></tr>' for k, v in pairs
        )

    parts = [
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#111;max-width:640px">',
        f"<p>{e(intro)}</p>",
        f'<table style="border-collapse:collapse;margin-bottom:16px">{rows(facts)}</table>',
    ]
    if items:
        head = "".join(
            f'<th {CELL.format(align=a)}>{e(labels[k])}</th>'
            for k, a in (("item", "left"), ("quantity", "right"), ("unit_price", "right"), ("subtotal", "right"))
        )
        body = "".join(
            "<tr>" + "".join(f'<td {CELL.format(align=a)}>{e(v)}</td>' for v, a in zip(item, ("left", "right", "right", "right"))) + "</tr>"
            for item in items
        )
        parts.append(f"<h3 style=\"font-size:15px;margin:0 0 6px\">{e(labels['items'])}</h3>")
        parts.append(f'<table style="border-collapse:collapse;width:100%;margin-bottom:16px"><tr>{head}</tr>{body}</table>')
    if totals:
        parts.append(f'<table style="border-collapse:collapse;margin-bottom:16px">{rows(totals)}</table>')
    parts.append(f"<p>{e(labels['attached'])}</p></div>")
    return "".join(parts)


def send(settings: Settings, cfg: InvoiceConfig | None, r: Rendered, kind: Literal["new", "payment"]) -> bool:
    """True when the email went out."""
    email = cfg.email if cfg else None
    if not email or not settings.smtp_password or r.series == "quotation":
        return False
    sender = settings.smtp_user or email["to"]
    try:
        msg = compose(cfg, r, kind)
    except (KeyError, ValueError) as exc:  # a bad template in config/invoice.yaml
        log.error("invoice email not built bill_no=%s kind=%s: %s", r.bill_no, kind, exc)
        return False
    msg["From"] = sender
    msg["To"] = email["to"]
    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=SEND_TIMEOUT_S) as smtp:
            smtp.login(sender, settings.smtp_password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        log.error("invoice email failed bill_no=%s kind=%s: %s", r.bill_no, kind, exc)
        return False
    log.info("invoice emailed bill_no=%s kind=%s", r.bill_no, kind)
    return True
