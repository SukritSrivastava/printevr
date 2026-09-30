"""Salesperson name (not in the BRD): required on print, stored, and printed under Bill No."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from app.invoice import layout as L
from app.invoice.render import compose, render
from app.invoice.store import Store

from .invoice_helpers import chars, find_run, lines_by_baseline, open_pdf, sogat_doc, cfg
from .test_invoice_api import app, auth, client, invoice_body, k1_line, rows, token  # noqa: F401 (fixtures)

LABEL_X, BASELINE, _, SIZE = L.SALES_LABEL


def sales_line(pdf: bytes) -> list[dict]:
    with open_pdf(pdf) as p:
        cs = chars(p.pages[0])
    return [c for c in cs if abs(c["baseline"] - BASELINE) < 1.0]


def text_of(cs: list[dict]) -> str:
    return "".join(c["text"] for c in sorted(cs, key=lambda c: c["x0"]))


def paid_in_full(line: dict) -> list[dict]:
    payable = Decimal(str(line["quantity"])) * Decimal(line["unit_price"])
    return [{"amount": str(payable), "date": "2026-09-29", "mode": "upi", "note": None}]


# ---------------------------------------------------------------- API


@pytest.mark.parametrize("name", [None, "", "   ", "x" * 101, "Mr.\nX", "Mr.\tX"])
def test_print_needs_a_plain_salesperson_name(app, client, auth, name):  # noqa: F811
    body = invoice_body([k1_line(client)])
    if name is None:
        del body["salesperson"]
    else:
        body["salesperson"] = name
    r = client.post("/api/invoices", json=body, headers=auth)
    assert r.status_code == 422, r.text
    assert client.get("/api/invoices", headers=auth).json()["total"] == 0


def test_salesperson_is_trimmed_and_stored(app, client, auth):  # noqa: F811
    body = invoice_body([k1_line(client)], salesperson="   Mr.    X  ")
    assert client.post("/api/invoices", json=body, headers=auth).status_code == 201
    [row], _ = rows(app)
    assert row.salesperson == "Mr. X"
    assert client.get("/api/invoices/19", headers=auth).json()["salesperson"] == "Mr. X"
    assert client.get("/api/invoices", headers=auth).json()["invoices"][0]["salesperson"] == "Mr. X"


@pytest.mark.parametrize("mode", ["unpaid", "paid"])
def test_paid_and_unpaid_pdfs_show_the_salesperson(client, auth, mode):  # noqa: F811
    line = k1_line(client)
    payments = paid_in_full(line) if mode == "paid" else []
    r = client.post("/api/invoices", json=invoice_body([line], print_mode=mode, payments=payments), headers=auth)
    assert r.status_code == 201, r.text
    assert r.headers["x-invoice-status"] == mode
    with open_pdf(r.content) as p:
        cs = chars(p.pages[0])
    # Same font, size and x as the Bill No label; one 18 pt step below it.
    assert find_run(cs, "Salesperson", L.REGULAR_PS, SIZE, LABEL_X, BASELINE, x_tol=0.2, y_tol=0.2)
    assert text_of(sales_line(r.content)).replace(" ", "") == "Salesperson:Mr.X"
    assert find_run(cs, "Bill No", L.REGULAR_PS, 12.0, 28.55, 96.23, x_tol=0.2, y_tol=0.2)
    # A re-download renders the same salesperson from the stored record.
    again = client.get(f"/api/invoices/{r.headers['x-bill-no']}/pdf", headers=auth)
    assert text_of(sales_line(again.content)) == text_of(sales_line(r.content))


# ---------------------------------------------------------------- PDF layout


def test_the_line_is_the_only_change_to_the_invoice():
    base = compose(sogat_doc(), cfg()).pages
    named = compose(sogat_doc(salesperson="Mr. X"), cfg()).pages
    assert len(base) == len(named)
    extra = [op for op in named[0] if op not in base[0]]
    assert [op.text for op in extra] == ["Salesperson", ":  Mr. X"]
    assert all(op.size == SIZE and op.font == L.REGULAR and op.y == BASELINE for op in extra)
    assert all(op in named[0] for op in base[0])


def test_value_follows_the_label_with_the_bill_no_gap():
    label, value = [op for op in compose(sogat_doc(salesperson="Mr. X"), cfg()).pages[0] if getattr(op, "y", None) == BASELINE]
    bill_gap = 73.49 - 28.55 - L.width("Bill No", L.REGULAR, 12.0)
    assert value.x - (label.x + L.width(label.text, L.REGULAR, SIZE)) == pytest.approx(bill_gap, abs=0.01)


@pytest.mark.parametrize(
    "name",
    [
        "Venkataramanan Subrahmanyam Iyer-Krishnamurthy",  # 46 characters: fits at full size
        "Wwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwww",  # 100 wide
    ],
)
def test_long_names_stay_in_the_band(name):
    pdf = render(sogat_doc(salesperson=name), cfg())
    cs = sales_line(pdf)
    assert cs and max(c["x1"] for c in cs) <= L.SALES_VALUE_MAX_X + 0.01
    assert min(c["size"] for c in cs) >= L.SALES_MIN_SIZE - 0.01
    # Nothing else on page 1 moved: every other baseline and x is as without the name.
    with open_pdf(render(sogat_doc(), cfg())) as p:
        base = [(c["text"], round(c["x0"], 2), round(c["baseline"], 2)) for c in chars(p.pages[0])]
    with open_pdf(pdf) as p:
        named = [(c["text"], round(c["x0"], 2), round(c["baseline"], 2)) for c in chars(p.pages[0])
                 if abs(c["baseline"] - BASELINE) >= 1.0]
    assert named == base
    # The descenders stay inside the header band.
    assert BASELINE + 0.3 * SIZE < L.BAND[3]


def test_46_char_name_prints_in_full_and_100_wide_is_cut_short():
    full = "Venkataramanan Subrahmanyam Iyer-Krishnamurthy"
    assert text_of(sales_line(render(sogat_doc(salesperson=full), cfg()))).endswith(full)
    wide = "W" * 100
    shown = text_of(sales_line(render(sogat_doc(salesperson=wide), cfg())))
    assert shown.endswith("...") and "W" * 20 in shown


def test_old_invoices_without_a_salesperson_reprint_unchanged():
    assert render(sogat_doc(salesperson=None), cfg()) == render(sogat_doc(), cfg())
    assert lines_by_baseline(sales_line(render(sogat_doc(), cfg()))) == []


# ---------------------------------------------------------------- storage


def test_column_is_added_to_an_existing_database(tmp_path):
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    Store(url)
    with create_engine(url).begin() as conn:
        conn.execute(text("ALTER TABLE invoices DROP COLUMN salesperson"))
    Store(url)
    with create_engine(url).begin() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(invoices)"))]
    assert "salesperson" in cols
