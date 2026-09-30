"""Emails each new invoice and each recorded payment, with its PDF, to config/invoice.yaml `email.to`.

Sending is best effort: a mail failure is logged and never stops the invoice being
saved or downloaded. Without SMTP_PASSWORD (or without the `email` block) nothing is sent.
"""
import logging
import smtplib
from email.message import EmailMessage
from typing import Literal

from ..settings import Settings
from .config import InvoiceConfig
from .service import Rendered

log = logging.getLogger("printevr.invoice")

SEND_TIMEOUT_S = 15


def send(settings: Settings, cfg: InvoiceConfig | None, r: Rendered, kind: Literal["new", "payment"]) -> bool:
    """True when the email went out."""
    email = cfg.email if cfg else None
    if not email or not settings.smtp_password:
        return False
    fields = {"bill_no": r.bill_no, "business": r.business_name, "status": cfg.status_labels[r.status]}
    sender = settings.smtp_user or email["to"]
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = email["to"]
    msg["Subject"] = email[f"subject_{kind}"].format(**fields)
    msg.set_content(email[f"body_{kind}"].format(**fields))
    msg.add_attachment(r.pdf, maintype="application", subtype="pdf", filename=r.filename)
    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=SEND_TIMEOUT_S) as smtp:
            smtp.login(sender, settings.smtp_password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        log.error("invoice email failed bill_no=%s kind=%s: %s", r.bill_no, kind, exc)
        return False
    log.info("invoice emailed bill_no=%s kind=%s", r.bill_no, kind)
    return True
