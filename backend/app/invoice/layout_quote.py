"""Positions, sizes and fonts on the quotation (docs/templates/quotation.pdf).

Measured from the template the same way as layout.py (points from the top-left, y = baseline
for text). The band, Date line, Ship To and From blocks are the invoice's (layout.py); this
file holds only what the quotation does differently. Item rows use the invoice's row layout
(paginate.layout_row) with the quotation's columns.
"""
from . import layout as L

BAND_IMAGE = L.ASSETS / "quotation" / "quotation_band.png"  # the invoice band with the pill left blank

# ---- title in the band's pill. The template's Agrandir isn't available: Montserrat, shrunk to fit.
TITLE_CENTER_X = 296.3  # pill centre: (213.0 + 379.6) / 2
TITLE_BASELINE = 61.59
TITLE_FONT = L.BOLD  # closest bundled weight to Agrandir GrandMedium
TITLE_SIZE = 24.01
TITLE_MAX_W = 140.0  # inside the pill's straight part, clear of its round ends
TITLE_CHAR_SPACE = 0.8  # Agrandir GrandMedium is a wide face; open the letters up a little

# ---- Date and Quote No lines (template: "Date   01 OCT 2026", "Bill No : 01")
NUMBER_PREFIX = ": "
NUMBER_GAP = 73.49 - 67.62  # the template's gap between "Bill No" and its colon

# ---- table header pill and labels (label, x or centre, baseline offset from the pill top, size, align)
TABLE_PILL_X = (24.9, 556.1)
TABLE_PILL_Y = (290.4, 317.9)
LABEL_SIZE_SMALL = 8.15
TABLE_LABELS = {
    "item": (46.30, 308.57 - 290.4, 10.11, "left"),
    "quantity": (284.70, 306.36 - 290.4, 10.38, "left"),
    "subtotal": (495.27, 305.20 - 290.4, 9.13, "left"),
}
# Two-line labels: centre x, first and second baselines (offsets from the pill top), size.
MARKET_LABEL = (385.8, 303.16 - 290.4, 310.62 - 290.4, LABEL_SIZE_SMALL)
DISCOUNTED_LABEL = (453.0, 300.58 - 290.4, 308.05 - 290.4, LABEL_SIZE_SMALL)

# ---- item rows (paginate.Columns): the template's first title baseline is 345.01
FIRST_ROW_TOP = 345.01 - L.TITLE_OFFSET
TITLE_X = 37.57
QTY_CENTER = 308.6
REF_PRICE_CENTER = 385.8
PRICE_CENTER = 453.0
SUBTOTAL_CENTER = 519.6
NOTE_X = 336.0  # a note sits in the market-price column, clear of the quantity
NOTE_MAX_X = 428.0
TITLE_MAX_X = 278.0
ROW_RULE_X = (22.5, 563.8)
EMPTY_CELL = "--"  # a row with no market price shows this, as on the template

# ---- totals (right edges as on the invoice, moved with the template's pill)
TOTAL_LABEL = (425.25, 588.63, L.BOLD, 12.70, "TOTAL:")
TOTAL_VALUE = (527.6, 588.54, L.REGULAR, 12.70)  # right edge
SUB_PILL = (365.7, 550.1, 598.2, 632.0)  # x0, x1, top, bottom
SUB_LABEL = (372.99, 621.97, L.REGULAR, 17.0, "SUB TOTAL :")
SUB_VALUE = (538.3, 621.97, L.REGULAR, 14.95)  # right edge
SUB_VALUE_MIN_X = 481.0
SUB_VALUE_MIN_SIZE = 11.0

# The template's UPI block (QR and details), its two payment notes and its GST note are left off: a
# quotation carries no payment or tax details.

# ---- saving block and footer (smaller than the invoice's on this template)
SAVING_X = 14.49
SAVING_LINES_Y = (754.33, 761.66)
SAVING_SIZE = 6.28
SAVING_AMOUNT = (42.28, 782.46, L.BOLD, 14.94)
APPROX = (6.3, 779.24, L.REGULAR, 6.27, "APPROX")  # gap after the amount, baseline, font, size, text

THANKS = (11.62, 798.65, L.REGULAR, 6.65)
CONTACT = (11.62, 806.78, L.REGULAR, 5.70)
EMAIL_RULE_Y = (807.1, 807.5)
COLOUR_NOTE = (11.75, 821.89, L.REGULAR, 4.28)
TERMS_NOTE = (11.75, 828.81, L.REGULAR, 4.28)

# ---- pagination
ROW_RULE_LIMIT = 800.0  # pages before the last
LAST_ROW_RULE_LIMIT = 570.0  # the last page's rows end above TOTAL
CONT_TABLE_PILL_TOP = 40.0
CONT_ROW_TOP = CONT_TABLE_PILL_TOP + (TABLE_PILL_Y[1] - TABLE_PILL_Y[0])
