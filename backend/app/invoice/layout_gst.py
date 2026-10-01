"""Positions, sizes and fonts on the GST invoice (docs/templates/gst_invoice.pdf, BASTTA format).

Measured from the template (points from the top-left, y = baseline for text). The template
sets most text in Open Sans Bold and Poppins, which aren't bundled: everything here uses the
bundled Montserrat at the template's sizes, centred on the template's columns so the wider
glyphs stay inside them, and shrunk where a run would cross its neighbour.
"""
from . import layout as L

REGULAR = L.REGULAR
BOLD = L.BOLD

# ---- header
COPY_LABEL = (298.2, 16.12, BOLD, 9.67)  # centre x ("ORIGINAL COPY")
SELLER_NAME = (22.13, 34.28, BOLD, 21.01)
SELLER_NAME_SKEW = 12.0  # the template's Poppins Black Italic, as a slanted bold
SELLER_LINES_X = 22.13
SELLER_LINES_Y = (45.09, 53.42, 61.76)
SELLER_LINES_SIZE = 6.0
DATE_LABEL = (443.79, 35.80, BOLD, 9.67)
DATE_GAP = 7.95  # label end to value
NUMBER_LABEL = (441.26, 50.37, BOLD, 9.67)
NUMBER_GAP = 7.70
HEADER_VALUE_MAX_X = 580.0

# ---- parties
BUYER_HEADING = (45.47, 88.04, BOLD, 7.22)
CONSIGNEE_HEADING = (365.54, 86.53, BOLD, 7.22)
PARTY_SIZE = 7.88
PARTY_MIN_SIZE = 6.0
PARTY_STEP = 10.0
BUYER_X = (45.47, 330.0)  # x, max x
BUYER_Y0 = 98.92
CONSIGNEE_X = (367.20, 580.0)
CONSIGNEE_Y0 = 86.53 + (BUYER_Y0 - 88.04)
PARTY_ADDRESS_LINES = 3

# ---- delivery and transport fields: key -> (x, baseline, size, max x)
FIELDS = {
    "delivery_terms": (45.47, 192.70, 7.01, 315.0),
    "payment_terms": (45.47, 202.05, 7.01, 315.0),
    "po_date": (45.47, 211.40, 7.01, 315.0),
    "gr_rr_no": (322.66, 191.91, 6.51, 445.0),
    "transport": (322.66, 200.59, 6.51, 445.0),
    "vehicle_no": (322.66, 209.26, 6.51, 445.0),
    "eway_bill_no": (322.66, 217.93, 6.51, 445.0),
    "station": (450.89, 200.14, 7.33, 585.0),
}
FIELD_MIN_SIZE = 5.0

# ---- dotted rule above the table
DOTS = (48.6, 541.9, 244.9)  # first x, last x, centre y
DOT_STEP = 1.5
DOT_D = 0.75

# ---- table header: key -> (centre x, baseline, size)
TABLE_LABELS = {
    "item": (66.2, 268.82, 10.48),
    "description": (138.74, 269.52, 10.97),
    "hsn": (265.31, 266.23, 9.82),
    "quantity": (338.08, 266.35, 9.82),
    "units": (407.07, 266.39, 9.82),
    "rate": (462.56, 266.26, 9.82),
    "amount": (516.27, 266.26, 9.82),
}
HEADER_RULE = (50.0, 537.1, 279.8, 280.5)  # x0, x1, top, bottom

# ---- item rows (offsets from the row's first title baseline)
FIRST_TITLE_Y = 298.41
SERIAL = (59.90, -1.12, BOLD, 10.48)  # x, offset, font, size: "1."
TITLE_X = 73.36
TITLE_MAX_X = 236.0
TITLE_SIZE = 7.64
TITLE_MIN_SIZE = 6.5
TITLE_STEP = 9.0
SPEC_X = 86.82
SPEC_MAX_X = 236.0
SPEC_SIZE = 6.29
SPEC_STEP = 7.6
SPEC_FIRST = 310.50 - 298.41  # first spec baseline below the last title line
NUMBERS_OFFSET = 298.85 - 298.41
NUM_FONT = (REGULAR, 8.17)
NUM_MIN_SIZE = 6.5
# key -> (centre x, max width)
NUM_COLUMNS = {
    "hsn": (271.31, 56.0),
    "quantity": (343.28, 58.0),
    "units": (414.53, 44.0),
    "rate": (464.66, 46.0),
    "amount": (526.11, 54.0),
}
ROW_GAP = 14.0  # next row's title baseline below this row's lowest baseline
TABLE_END_RULE = (82.6, 533.0, 22.7, 1.2)  # x0, x1, gap below the last baseline, thickness

# ---- totals: labels right-aligned on the colon, values right-aligned
TOTALS_LABEL_RIGHT = 453.04
TOTALS_VALUE_RIGHT = 530.3
TOTALS_FONT = (REGULAR, 9.67)
TOTALS_Y = {"sub_total": 471.87, "cgst": 491.03, "ugst": 506.78, "igst": 522.53, "after_tax": 536.72}
TOTAL_RULE_1 = (406.2, 543.1, 549.1, 550.6)
TOTAL_LABEL = (408.66, 564.07, BOLD, 12.9)
TOTAL_VALUE_RIGHT = 530.3
TOTAL_RULE_2 = (408.9, 542.6, 568.9, 570.7)

# ---- footer
BANK_X = 22.13
BANK_Y0 = 740.56
BANK_STEP = 9.45
BANK_FONT = (BOLD, 6.87)
TERMS_HEADING = (199.95, 757.07, BOLD, 6.37)
TERMS_RULE_Y = (757.6, 758.1)
TERMS_X = 199.95
TERMS_Y0 = 774.04
TERMS_STEP = 8.49
TERMS_SIZE = 6.37
TERMS_MAX_X = 396.0
CERTIFIED = (493.9, 791.02, BOLD, 6.07)  # centre x
CERTIFIED_MAX_W = 182.0
SIGNATORY = (494.97, 809.46, REGULAR, 12.0)  # centre x

# ---- pagination
LAST_PAGE_ROWS_END = 452.0  # rows on the last page end above SUB-TOTAL
PAGE_ROWS_END = 820.0  # pages before the last (no footer on them)
CONT_NUMBER = (22.13, 30.0, BOLD, 9.0)  # "INVOICE NO. 7 (continued)"
CONT_HEADER_SHIFT = 268.82 - 60.0  # table header moves up by this on continuation pages
