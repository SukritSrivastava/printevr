"""Every position, size and font on the invoice (BRD-cart-invoice section 7).

Measured from backend/tests/fixtures/invoice/reference_bill18.pdf. Coordinates are points
from the TOP-LEFT of the page, y growing downward; a text's y is its BASELINE. The
renderer flips them (y_rl = PAGE_H - y). Don't change these without re-running the
golden tests (tests/test_invoice_golden.py).
"""
from functools import lru_cache
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ASSETS = Path(__file__).resolve().parents[2] / "assets"
FONT_DIR = ASSETS / "fonts"
BAND_IMAGE = ASSETS / "invoice" / "invoice_band.png"
LOGO_IMAGE = ASSETS / "invoice" / "printevr_logo.png"

REGULAR = "Montserrat"
BOLD = "Montserrat-Bold"
FONT_FILES = {REGULAR: "Montserrat-Regular.ttf", BOLD: "Montserrat-Bold.ttf"}
# PostScript names as embedded in the PDF (what PDF readers report)
REGULAR_PS = "Montserrat-Regular"
BOLD_PS = "Montserrat-Bold"

# ---- 7.1 page and drawing rules
PAGE_W = 595.5
PAGE_H = 842.25  # Canva's A4, not ReportLab's
PILL_STROKE = 1.5
BOX_STROKE = 1.5
RULE_H = 0.7
AUTHOR = "PRINTEVR VENTURE"

# ---- letter spacing (pt per character)
# Canva set some runs tighter or looser than the stock Montserrat TTFs: the two small
# notes carry uniform tracking, and the headings use slightly different glyph widths.
# These values make each run start and end where it does on the reference
# ((reference width - our width) / (characters - 1)). Left-aligned runs only.
TRACKING = {
    "Date": -0.277,
    "FROM - PRINTEVR": -0.213,
    "SHIP TO": -0.206,
    "ITEM": -0.135,
    "QUANTITY": -0.049,
    "PRICE PER PCS": -0.143,
    "SUBTOTAL": -0.166,
    "SUB TOTAL :": -0.226,
    "thanks": -0.09,
    "late_note": 0.143,
    "terms_note": 0.144,
}

# ---- 7.2 fixed top of page 1
BAND = (0.0, 0.0, PAGE_W, 120.03)  # x0, top, width, bottom
LOGO = (494.3, 119.6, 88.6, 30.7)  # x, top, width, height

DATE_LABEL = (28.55, 78.22, REGULAR, 12.0)  # x, baseline, font, size
DATE_VALUE = (73.49, 78.22, REGULAR, 12.0)
BILL_LABEL = (28.55, 96.23, REGULAR, 12.0)
BILL_VALUE = (73.49, 96.23, REGULAR, 12.0)
VALUE_PREFIX = ":  "

SHIP_TO_HEADING = (39.40, 143.39, REGULAR, 13.94, "SHIP TO")
SHIP_TO_RULE = (39.4, 99.2, 144.2, 145.1)  # x0, x1, top, bottom
FROM_HEADING = (353.01, 141.38, REGULAR, 13.51, "FROM - PRINTEVR")
FROM_RULE = (353.0, 475.4, 142.2, 143.0)
FROM_LINES_X = 354.39
FROM_LINES_Y = (160.08, 175.26, 190.43, 205.61)
FROM_LINES_FONT = (REGULAR, 10.55)

# ---- 7.3 Ship To block
SHIP_TO_X = 39.40
SHIP_TO_Y0 = 164.21
SHIP_TO_STEP = 12.39
SHIP_TO_SIZE = 8.26
SHIP_TO_MIN_SIZE = 6.0  # an address that won't fit two lines shrinks to this
SHIP_TO_ADDRESS_MAX_X = 339.4
SHIP_TO_ADDRESS_LINES = 2

# ---- table header (7.2) and its continuation-page copy (7.7)
TABLE_PILL_X = (22.1, 553.3)
TABLE_PILL_Y = (248.4, 275.9)  # top, bottom on page 1
# label, x, offset of the baseline from the pill top, size
TABLE_LABELS = (
    ("ITEM", 43.47, 266.58 - 248.4, 10.11),
    ("QUANTITY", 264.37, 264.36 - 248.4, 10.38),
    ("PRICE PER PCS", 412.87, 263.24 - 248.4, 9.10),
    ("SUBTOTAL", 488.55, 263.20 - 248.4, 9.13),
)

# ---- 7.4 item rows
FIRST_ROW_TOP = 275.9
CONT_ROW_TOP = 67.5
TITLE_X = 37.7
TITLE_MAX_X = 272.0
TITLE_OFFSET = 22.2  # first title baseline = R + this
TITLE_SIZE = 11.0
TITLE_MIN_SIZE = 9.0
TITLE_SHRINK_STEP = 0.25
TITLE_LINE_STEP = 12.5
TITLE_MAX_LINES = 2

NUMBERS_OFFSET = 7.2  # numbers baseline = first title baseline + this
NUM_SIZE = 9.66
QTY_CENTER = 291.4
UNIT_LABEL_SIZE = 5.74
UNIT_LABEL_OFFSET = 6.1  # below the numbers baseline
NOTE_X = 313.15
NOTE_MAX_X = 432.0
NOTE_SIZE = 7.66
NOTE_MIN_SIZE = 6.0
NOTE_SHRINK_STEP = 0.25
NOTE_OFFSET = -0.8  # the note sits 0.8 pt above the numbers baseline
NOTE_LINE_STEP = 8.5
REF_PRICE_CENTER = 387.5
PRICE_CENTER = 448.0
SUBTOTAL_CENTER = 512.9

SPEC_FIRST_OFFSET = 12.65  # first spec baseline = last title baseline + this
SPEC_STEP = 8.0
SPEC_SIZE = 6.0
SPEC_X = 55.46
SPEC_MAX_X = 272.0
SPEC_DOT_X = 49.3
SPEC_DOT_D = 2.0
SPEC_DOT_RISE = 1.55  # dot centre above the baseline
SPEC_WIDE_LABEL = 150.0  # wider labels wrap values back to SPEC_X
CUSTOMISATIONS_HEADING = "CUSTOMISATIONS:-"
CUSTOMISATIONS_X = 39.4
CUSTOMISATIONS_GAP = 12.0  # heading baseline = previous baseline + this

ROW_RULE_X = (17.9, 559.4)
ROW_RULE_GAP = 10.5  # rule centre = lowest baseline in the row + this

# ---- 7.5 payment terms box
BOX_GAP = 20.7  # box top = last row rule + this
BOX_X = (22.1, 580.9)
BOX_TITLE = (31.19, 24.75, BOLD, 15.01)  # x, baseline offset from box top, font, size
TERMS_X = 51.24
TERMS_MAX_X = 573.2
TERMS_FIRST_OFFSET = 43.95
TERMS_STEP = 24.01
TERMS_SIZE = 12.0
TERMS_MIN_SIZE = 10.0
TERMS_SHRINK_STEP = 0.05
TERMS_WRAP_STEP = 16.0
TERMS_DOT_X = 40.2
TERMS_DOT_D = 3.8
TERMS_DOT_RISE = 4.15
BOX_BOTTOM_GAP = 13.4  # box bottom = last line baseline + this
SUMMARY_GAP = 8.0  # payment summary: RECIEVABLES box top = PAYMENT TERMS box bottom + this
# The payment summary's boxes are tighter than the reference's payment-terms box (as on the
# owner's mock-up), so they usually fit under the items on page 1. Same x positions.
# (title baseline offset, title size, first line offset, line step, size, min size, wrap step,
#  dot diameter, dot rise, bottom gap)
BOX_METRICS = (24.75, 15.01, TERMS_FIRST_OFFSET, TERMS_STEP, TERMS_SIZE, TERMS_MIN_SIZE, TERMS_WRAP_STEP, TERMS_DOT_D, TERMS_DOT_RISE, BOX_BOTTOM_GAP)
SUMMARY_METRICS = (20.0, 13.5, 37.0, 18.0, 10.5, 9.0, 13.5, 3.3, 3.6, 10.5)

# ---- 7.6 totals, saving and footer (last page)
TOTAL_LABEL = (434.48, 703.89, BOLD, 12.70, "TOTAL:")
TOTAL_LABEL_RIGHT = 481.62  # right edge of "TOTAL:"; the GST label aligns its colon here
TOTAL_VALUE = (536.93, 703.80, REGULAR, 12.70)  # right edge
GST_LIFT = 16.0  # With GST billing, TOTAL moves up this much per tax row and the rows take its place
SUB_PILL = (374.9, 559.4, 710.3, 744.1)  # x0, x1, top, bottom
SUB_LABEL = (382.45, 733.27, REGULAR, 16.97, "SUB TOTAL :")
SUB_VALUE = (547.58, 733.72, REGULAR, 14.95)  # right edge
SUB_VALUE_MIN_X = 490.0
SUB_VALUE_MIN_SIZE = 11.0

SAVING_X = 17.89
SAVING_LINES_Y = (744.38, 753.16)
SAVING_SIZE = 7.52
SAVING_AMOUNT = (28.50, 778.09, BOLD, 17.91)
APPROX = (1.66, 774.24, REGULAR, 7.52, "APPROX")  # gap after the amount, baseline, font, size, text

THANKS = (14.45, 797.51, REGULAR, 7.97)
CONTACT = (14.45, 807.25, REGULAR, 6.84)
EMAIL_RULE_Y = (807.6, 808.1)
ADVANCE_NOTE = (14.45, 817.17, REGULAR, 5.13)
COLOUR_NOTE = (14.62, 825.37, REGULAR, 5.13)
LATE_NOTE = (169.70, 825.37, REGULAR, 5.13)
TERMS_NOTE = (14.62, 833.66, REGULAR, 5.13)
GST_NOTE = (169.26, 833.74, REGULAR, 5.69)

# ---- 7.7 pagination
ROW_RULE_LIMIT = 800.0  # a row whose rule would fall below this moves to a new page
BOX_BOTTOM_LIMIT = 684.0  # less GST_LIFT per GST row (668 with one)
CONT_BOX_TOP = 40.0
CONT_TABLE_PILL_Y = (40.0, 67.5)
CONT_BILL = (28.55, 28.0, REGULAR, 9.0)
PAGE_NUMBER = (580.9, 834.0, REGULAR, 6.0)  # right edge


@lru_cache(maxsize=1)
def register_fonts() -> None:
    for name, file in FONT_FILES.items():
        path = FONT_DIR / file
        if not path.exists():
            raise FileNotFoundError(
                f"Font {path} is missing. Download Montserrat-Regular.ttf and Montserrat-Bold.ttf "
                "from github.com/JulietaUla/Montserrat (fonts/ttf/) into backend/assets/fonts/."
            )
        pdfmetrics.registerFont(TTFont(name, str(path)))


def width(text: str, font: str, size: float) -> float:
    register_fonts()
    return pdfmetrics.stringWidth(text, font, size)
