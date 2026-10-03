"""Shared helpers for the invoice tests: fixtures and PDF measurement."""
import dataclasses
import io
import json
import re
from pathlib import Path

import pdfplumber

from app.invoice import config as invoice_config
from app.invoice.models import InvoiceDocument
from app.settings import get_settings

FIXTURES = Path(__file__).parent / "fixtures" / "invoice"
OUTPUT = Path(__file__).parent / "output"


def cfg():
    return invoice_config.load(get_settings().invoice_config_file)


def full_cfg():
    """The config with the reference's payment-terms box printed, as on reference_bill18.pdf and
    the templates (not the newer payment summary), so the golden layout stays locked."""
    return dataclasses.replace(cfg(), print_payment_details=True, payment_summary=None)


def sogat_raw() -> dict:
    return json.loads((FIXTURES / "sogat_jutti_bill18.json").read_text(encoding="utf-8"))


def sogat_doc(**changes) -> InvoiceDocument:
    raw = {k: v for k, v in sogat_raw().items() if k not in ("expected", "_comment")}
    raw.update(changes)
    return InvoiceDocument.model_validate(raw)


def base_font(fontname: str) -> str:
    """'AAAAAA+Montserrat-Bold' -> 'Montserrat-Bold'."""
    return re.sub(r"^[A-Z]{4,6}\+", "", fontname)


def open_pdf(data: bytes):
    return pdfplumber.open(io.BytesIO(data))


def chars(page) -> list[dict]:
    """Characters with a true baseline (our PDFs have their MediaBox at 0)."""
    top = float(page.height)
    out = []
    for c in page.chars:
        out.append(
            {
                "text": c["text"],
                "x0": float(c["x0"]),
                "x1": float(c["x1"]),
                "baseline": top - float(c["matrix"][5]),
                "font": base_font(c["fontname"]),
                "size": float(c["size"]),
            }
        )
    return out


def lines_by_baseline(cs: list[dict], tol: float = 0.3) -> list[list[dict]]:
    """Group characters into visual lines (same baseline), each sorted by x."""
    groups: list[list[dict]] = []
    for c in sorted(cs, key=lambda c: (round(c["baseline"], 1), c["x0"])):
        if groups and abs(groups[-1][0]["baseline"] - c["baseline"]) <= tol:
            groups[-1].append(c)
        else:
            groups.append([c])
    return [sorted(g, key=lambda c: c["x0"]) for g in groups]


def find_run(cs: list[dict], text: str, font: str, size: float, x0: float, baseline: float,
             size_tol=0.05, x_tol=1.0, y_tol=1.0) -> dict | None:
    """Find `text` drawn in one font/size, starting within x_tol of x0, on a baseline within y_tol."""
    candidates = sorted(
        (c for c in cs if c["font"] == font and abs(c["size"] - size) <= size_tol and abs(c["baseline"] - baseline) <= y_tol),
        key=lambda c: c["x0"],
    )
    for i, c in enumerate(candidates):
        if c["text"] != text[0] or abs(c["x0"] - x0) > x_tol:
            continue
        got = "".join(ch["text"] for ch in candidates[i : i + len(text)])
        if got == text:
            return {"x0": c["x0"], "baseline": c["baseline"], "x1": candidates[i + len(text) - 1]["x1"]}
    return None


def rects(page) -> list[dict]:
    """Filled or stroked rectangles, in top-left coordinates.

    Stroked rectangles are measured at the outer edge of the stroke (what you see, and how
    layout_reference.json measured the reference).
    """
    out = []
    for r in page.rects:
        grow = float(r.get("linewidth") or 0) / 2 if r.get("stroke") else 0.0
        out.append(
            {"x0": float(r["x0"]) - grow, "x1": float(r["x1"]) + grow, "top": float(r["top"]) - grow,
             "bottom": float(r["bottom"]) + grow, "fill": r.get("fill"), "stroke": r.get("stroke")}
        )
    return out
