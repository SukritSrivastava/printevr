"""BRD-cart-invoice 11.1 (G1-G5) and 11.2 (R1-R3): the generated PDF against reference_bill18.pdf."""
import json
from decimal import Decimal

import numpy as np
import pypdfium2 as pdfium
import pytest
from PIL import Image

from app.invoice import layout as L
from app.invoice.paginate import layout_row
from app.invoice.render import compose, render

from .invoice_helpers import FIXTURES, OUTPUT, cfg, chars, find_run, lines_by_baseline, open_pdf, rects, sogat_doc, sogat_raw

REFERENCE = json.loads((FIXTURES / "layout_reference.json").read_text(encoding="utf-8"))
FIXED_TOP = 280.0
FIXED_BOTTOM = 690.0


@pytest.fixture(scope="module")
def pdf_bytes():
    return render(sogat_doc(), cfg())


@pytest.fixture(scope="module")
def page(pdf_bytes):
    with open_pdf(pdf_bytes) as pdf:
        yield pdf.pages[0]


@pytest.fixture(scope="module")
def cs(page):
    return chars(page)


@pytest.fixture(scope="module")
def expected():
    return sogat_raw()["expected"]


def test_g1_one_page_canva_a4(pdf_bytes):
    with open_pdf(pdf_bytes) as pdf:
        assert len(pdf.pages) == 1
        p = pdf.pages[0]
        assert (float(p.width), float(p.height)) == pytest.approx((595.5, 842.25), abs=0.01)


def test_g2_fixed_text_matches_reference(cs):
    checked, missing = 0, []
    for run in REFERENCE["text"]:
        if run["text"] == "INVOICE" or FIXED_TOP <= run["baseline"] <= FIXED_BOTTOM:
            continue
        checked += 1
        if find_run(cs, run["text"], run["font"], run["size"], run["x0"], run["baseline"]) is None:
            missing.append(run)
    assert checked > 30
    assert missing == []


def _raster(path_or_bytes) -> np.ndarray:
    doc = pdfium.PdfDocument(path_or_bytes)
    img = doc[0].render(scale=100 / 72).to_pil().convert("L")
    return np.asarray(img, dtype=np.int16)


def test_g3_raster_matches_reference(pdf_bytes):
    ref = _raster(str(FIXTURES / "reference_bill18.pdf"))
    out = _raster(pdf_bytes)
    assert ref.shape == out.shape
    px = ref.shape[0] / L.PAGE_H
    failures = []
    for y0, y1 in ((0.0, FIXED_TOP), (FIXED_BOTTOM, L.PAGE_H)):
        a, b = int(round(y0 * px)), int(round(y1 * px))
        diff = np.abs(ref[a:b] - out[a:b]) > 48
        share = diff.mean()
        if share >= 0.015:
            failures.append((y0, y1, round(float(share) * 100, 2)))
            OUTPUT.mkdir(exist_ok=True)
            rgb = np.full(ref[a:b].shape + (3,), 255, np.uint8)
            rgb[ref[a:b] < 128] = [220, 0, 0]
            rgb[out[a:b] < 128] = [0, 0, 220]
            rgb[(ref[a:b] < 128) & (out[a:b] < 128)] = [0, 0, 0]
            Image.fromarray(rgb).save(OUTPUT / f"g3_overlay_{int(y0)}_{int(y1)}.png")
    assert failures == [], f"regions over 1.5% different (overlay in tests/output): {failures}"


def _row_rules(page) -> list[dict]:
    return sorted(
        (r for r in rects(page) if abs((r["bottom"] - r["top"]) - L.RULE_H) < 0.05 and r["x1"] - r["x0"] > 500),
        key=lambda r: r["top"],
    )


def _payment_box(page) -> dict:
    boxes = [r for r in rects(page) if r["x0"] == pytest.approx(L.BOX_X[0], abs=0.5) and r["x1"] == pytest.approx(L.BOX_X[1], abs=0.5)]
    assert len(boxes) == 1
    return boxes[0]


def test_g4_payment_box(page, cs, expected):
    box = _payment_box(page)
    rules = _row_rules(page)
    last_rule = (rules[-1]["top"] + rules[-1]["bottom"]) / 2
    assert box["top"] == pytest.approx(last_rule + 20.7, abs=0.3)
    assert box["bottom"] - box["top"] == pytest.approx(153.4, abs=0.5)

    inside = [c for c in cs if box["top"] < c["baseline"] < box["bottom"] and c["x0"] >= L.TERMS_X - 0.5]
    lines = [l for l in lines_by_baseline(inside) if l[0]["size"] < 14]
    assert ["".join(c["text"] for c in l) for l in lines] == expected["payment_lines"]

    bold = [
        "".join(c["text"] for c in l if c["font"] == "Montserrat-Bold").strip() for l in lines
    ]
    assert bold == [
        "Total Amount:- Rs. 148000/-",
        "80% amount pending (before printing & after sample & final confirmation):-  118400/-",
        "",
        "88400/-",
        "",
    ]
    dots = [c for c in page.curves if box["top"] < float(c["top"]) < box["bottom"]]
    assert len(dots) == 5
    for d in dots:
        assert (float(d["x0"]) + float(d["x1"])) / 2 == pytest.approx(L.TERMS_DOT_X, abs=0.2)
        assert float(d["x1"]) - float(d["x0"]) == pytest.approx(L.TERMS_DOT_D, abs=0.2)


def _cell(cs, text, font, size, y_range, anchor, align):
    for line in lines_by_baseline([c for c in cs if c["font"] == font and abs(c["size"] - size) < 0.3 and y_range[0] < c["baseline"] < y_range[1]]):
        # split a line into words separated by gaps wider than 3 pt
        words, cur = [], [line[0]]
        for c in line[1:]:
            if c["x0"] - cur[-1]["x1"] > 3:
                words.append(cur)
                cur = [c]
            else:
                cur.append(c)
        words.append(cur)
        for w in words:
            if "".join(c["text"] for c in w).strip() == text:
                x0, x1 = w[0]["x0"], w[-1]["x1"]
                pos = (x0 + x1) / 2 if align == "center" else x0
                if abs(pos - anchor) <= 0.5:
                    return True
    return False


def test_g5_item_rows(page, cs, expected):
    rules = _row_rules(page)
    assert len(rules) == 2  # one rule under each row
    tops = [L.FIRST_ROW_TOP] + [(r["top"] + r["bottom"]) / 2 for r in rules]
    doc = sogat_doc()
    for i, cells in enumerate(expected["line_cells"]):
        y_range = (tops[i], tops[i + 1])
        assert _cell(cs, cells["quantity"], L.BOLD_PS, L.NUM_SIZE, y_range, L.QTY_CENTER, "center"), cells
        assert _cell(cs, cells["unit"], L.REGULAR_PS, L.UNIT_LABEL_SIZE, y_range, L.QTY_CENTER, "center"), cells
        if doc.lines[i].middle.kind == "note":
            row = [c for c in cs if y_range[0] < c["baseline"] < y_range[1] and c["x0"] >= L.NOTE_X - 0.5 and c["x1"] <= L.NOTE_MAX_X + 0.5]
            note = "".join(c["text"] for l in lines_by_baseline(row) for c in l if c["font"] == L.BOLD_PS)
            assert note == cells["middle"]
            assert min(c["x0"] for c in row) == pytest.approx(L.NOTE_X, abs=0.5)
        else:
            assert _cell(cs, cells["middle"], L.REGULAR_PS, L.NUM_SIZE, y_range, L.REF_PRICE_CENTER, "center"), cells
        assert _cell(cs, cells["price"], L.REGULAR_PS, L.NUM_SIZE, y_range, L.PRICE_CENTER, "center"), cells
        assert _cell(cs, cells["subtotal"], L.BOLD_PS, L.NUM_SIZE, y_range, L.SUBTOTAL_CENTER, "center"), cells
        # Titles and specs print in capitals
        left = "".join(c["text"] for c in cs if y_range[0] < c["baseline"] < y_range[1] and c["x1"] <= L.TITLE_MAX_X + 0.5)
        assert left == left.upper()
        assert doc.lines[i].title.upper() in left.replace("\n", "")


def test_second_row_offsets_match_reference():
    """BRD 7.4 check: R 372.5 gives title 394.7, first spec 407.35, rule 449.85."""
    row = layout_row(sogat_doc().lines[1])
    ops = row.at(372.5)
    texts = [op for op in ops if hasattr(op, "text")]
    assert texts[0].y == pytest.approx(394.7, abs=0.01)
    spec_ys = sorted({round(op.y, 2) for op in texts if op.size == L.SPEC_SIZE})
    assert spec_ys[0] == pytest.approx(407.35, abs=0.01)
    assert 372.5 + row.height == pytest.approx(449.85, abs=0.01)


# ---------------------------------------------------------------- R1-R3


def _big_doc(n_lines=12, n_specs=8):
    base = sogat_raw()["lines"][1]
    lines = []
    for i in range(n_lines):
        line = dict(base, title=f"Customised test article {i + 1} printing")
        line["specs"] = [{"label": f"Spec {j + 1}", "value": f"Value number {j + 1} for line {i + 1}"} for j in range(n_specs)]
        lines.append(line)
    return sogat_doc(lines=lines)


def test_r1_pagination():
    doc = _big_doc()
    composed = compose(doc, cfg())
    n = len(composed.pages)
    assert n > 1
    data = render(doc, cfg())
    with open_pdf(data) as pdf:
        assert len(pdf.pages) == n
        seen_titles = []
        for number, page in enumerate(pdf.pages, start=1):
            cs = chars(page)
            texts = ["".join(c["text"] for c in l) for l in lines_by_baseline(cs)]
            assert f"Page {number} of {n}" in texts
            seen_titles += [t for t in texts if t.startswith("CUSTOMISED TEST ARTICLE")]
            has_box = any(t.startswith("PAYMENT TERMS") for t in texts)
            has_totals = "SUB TOTAL :" in "".join(texts)
            assert has_box == has_totals == (number == n)
            if number > 1:
                assert any(t == f"Bill No : {doc.bill_no} (continued)" for t in texts)
            # nothing but the page number and footer below the rule limit
            for r in _row_rules(page):
                assert r["bottom"] <= L.ROW_RULE_LIMIT + 1
        # every row printed exactly once, in order: no row split across pages
        assert seen_titles == [f"CUSTOMISED TEST ARTICLE {i + 1} PRINTING" for i in range(12)]


def test_r2_with_gst_totals():
    data = render(sogat_doc(billing_type="with_gst", payments=[]), cfg())
    with open_pdf(data) as pdf:
        cs = chars(pdf.pages[0])
    assert find_run(cs, "TOTAL:", L.BOLD_PS, 12.70, 434.48, 687.89, y_tol=0.05)
    assert find_run(cs, "148000", L.REGULAR_PS, 12.70, 490.65, 687.80, y_tol=0.05)
    gst = [l for l in lines_by_baseline(cs) if abs(l[0]["baseline"] - 703.89) < 0.2]
    text = "".join(c["text"] for c in gst[0])
    assert text.startswith("GST (18%):") and text.endswith("26640")
    colon = [c for c in gst[0] if c["text"] == ":"][0]
    assert colon["x1"] == pytest.approx(L.TOTAL_LABEL_RIGHT, abs=0.05)
    sub = [l for l in lines_by_baseline(cs) if abs(l[0]["baseline"] - 733.72) < 0.2 and l[0]["size"] < 15]
    assert "".join(c["text"] for c in sub[0]) == "174640"
    joined = ["".join(c["text"] for c in l) for l in lines_by_baseline(cs)]
    assert "PAYMENT TERMS     (WITH GST BILLING)" in joined
    assert any(t.endswith("Note:-  18%  gst has been added to the total") for t in joined)


def test_r3_deterministic():
    assert render(sogat_doc(), cfg()) == render(sogat_doc(), cfg())


def test_pdf_metadata_and_size(pdf_bytes):
    assert len(pdf_bytes) < 1_000_000
    with open_pdf(pdf_bytes) as pdf:
        assert pdf.metadata["Title"] == "INVOICE 18 - SOGAT JUTTI STORE"
        assert pdf.metadata["Author"] == "PRINTEVR VENTURE"


def test_unpaid_and_no_saving_hide_blocks():
    data = render(sogat_doc(payments=[], saving_amount=None), cfg())
    with open_pdf(data) as pdf:
        joined = "".join(c["text"] for c in chars(pdf.pages[0]))
    assert "SAVING" not in joined and "APPROX" not in joined and "Recieved" not in joined


def test_short_line_and_long_text_wrap_inside_columns():
    long = "Very long value text that certainly has to wrap onto a second and even third line " * 1
    line = dict(sogat_raw()["lines"][0], title="Customised extremely long article name that cannot fit on one line at all")
    line["specs"] = [{"label": "Material and finishing details", "value": long}]
    line["middle"] = {"kind": "note", "text": "A note that is rather long for column"}
    data = render(sogat_doc(lines=[line], customer={**sogat_raw()["customer"], "contact_person": ""}), cfg())
    with open_pdf(data) as pdf:
        cs = chars(pdf.pages[0])
    items = [c for c in cs if L.FIRST_ROW_TOP < c["baseline"] < 460 and c["x0"] < L.QTY_CENTER - 20 and c["text"] != " "]
    assert max(c["x1"] for c in items) <= L.TITLE_MAX_X + 0.3
    note = [c for c in cs if c["x0"] >= L.NOTE_X - 0.5 and c["x1"] < 440 and L.FIRST_ROW_TOP < c["baseline"] < 460 and c["text"] != " "]
    assert note and max(c["x1"] for c in note) <= L.NOTE_MAX_X + 0.3
    # blank contact person: the address moves up one step
    assert find_run(cs, "SECTOR 67, MOHALI, INDIA, 160062", L.REGULAR_PS, 8.26, 39.4, 176.60, y_tol=0.05)
