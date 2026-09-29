"""Row and payment-box measurement and page breaking (BRD-cart-invoice 7.4, 7.5, 7.7).

Pure apart from font metrics. Everything is laid out as drawing ops in top-left page
coordinates (y = baseline for text); render.py turns them into ReportLab calls.
"""
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal

from . import fmt
from . import layout as L
from .money import line_subtotal
from .terms import Run

# ---------------------------------------------------------------- drawing ops


@dataclass(frozen=True)
class Text:
    x: float
    y: float  # baseline
    text: str
    font: str
    size: float
    align: str = "left"  # left | center | right (x is the anchor)
    char_space: float = 0.0  # extra space after each character (left-aligned text only)


@dataclass(frozen=True)
class Dot:
    cx: float
    cy: float
    d: float


@dataclass(frozen=True)
class Bar:
    """A filled black rectangle (rules and underlines)."""

    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(frozen=True)
class Pill:
    """Rounded rectangle, radius = half the height, white fill, black stroke."""

    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(frozen=True)
class Box:
    """Plain stroked rectangle (the payment box)."""

    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(frozen=True)
class Image:
    path: str
    x: float
    top: float
    w: float
    h: float


Op = Text | Dot | Bar | Pill | Box | Image


def shift(ops: list[Op], dy: float) -> list[Op]:
    out = []
    for op in ops:
        if isinstance(op, Text):
            out.append(replace(op, y=op.y + dy))
        elif isinstance(op, Dot):
            out.append(replace(op, cy=op.cy + dy))
        elif isinstance(op, Image):
            out.append(replace(op, top=op.top + dy))
        else:
            out.append(replace(op, top=op.top + dy, bottom=op.bottom + dy))
    return out


def rule(y_center: float, x0: float, x1: float, height: float = L.RULE_H) -> Bar:
    return Bar(x0, x1, y_center - height / 2, y_center + height / 2)


# ---------------------------------------------------------------- text fitting


def shrink_to_fit(text: str, font: str, size: float, min_size: float, step: float, max_width: float) -> float | None:
    """Largest size (in `step`s down from `size`) at which the text fits; None if not even at min_size."""
    s = size
    while True:
        if L.width(text, font, s) <= max_width + 1e-6:
            return s
        if s - step < min_size - 1e-9:
            return None
        s = round(s - step, 4)


_SPACES = re.compile(r"( +)")


def wrap_runs(
    runs: list[tuple[str, str]], size: float, x_first: float, x_cont: float, max_x: float
) -> list[list[tuple[float, str, str]]]:
    """Greedy word wrap of (text, font) runs. Returns lines of (x, text, font) pieces.

    Spaces that fall at a line break are dropped; a word wider than a whole line is split
    between characters. Adjacent pieces in the same font are merged (widths are additive,
    since ReportLab doesn't kern).
    """
    pieces: list[tuple[str, str, bool]] = []
    for text, font in runs:
        for part in _SPACES.split(text):
            if part:
                pieces.append((part, font, part[0] == " "))

    lines: list[list[tuple[float, str, str]]] = [[]]
    x = x_first
    pending: list[tuple[str, str]] = []

    def new_line():
        nonlocal x
        lines.append([])
        x = x_cont

    for text, font, is_space in pieces:
        if is_space:
            pending.append((text, font))
            continue
        w = L.width(text, font, size)
        space_w = sum(L.width(t, f, size) for t, f in pending) if lines[-1] else 0.0
        if lines[-1] and x + space_w + w > max_x + 1e-6:
            new_line()
            space_w = 0.0
        if lines[-1]:
            for t, f in pending:
                lines[-1].append((x, t, f))
                x += L.width(t, f, size)
        pending = []
        if w > max_x - x + 1e-6:
            # A single word longer than the line: split it between characters.
            chunk = ""
            for ch in text:
                if chunk and x + L.width(chunk + ch, font, size) > max_x + 1e-6:
                    lines[-1].append((x, chunk, font))
                    new_line()
                    chunk = ""
                chunk += ch
            text, w = chunk, L.width(chunk, font, size)
        lines[-1].append((x, text, font))
        x += w
    return [_merge(line) for line in lines if line]


def _merge(line: list[tuple[float, str, str]]) -> list[tuple[float, str, str]]:
    merged: list[tuple[float, str, str]] = []
    for x, text, font in line:
        if merged and merged[-1][2] == font:
            px, ptext, _ = merged[-1]
            merged[-1] = (px, ptext + text, font)
        else:
            merged.append((x, text, font))
    # Trailing spaces carry no ink.
    if merged:
        x, text, font = merged[-1]
        merged[-1] = (x, text.rstrip(" ") or text, font)
    return merged


# ---------------------------------------------------------------- item rows


@dataclass
class RowLayout:
    """One item row laid out with its top at y = 0. `height` = offset of its rule."""

    ops: list[Op]
    height: float
    cells: dict = field(default_factory=dict)

    def at(self, top: float) -> list[Op]:
        return shift(self.ops, top)


def _spec_ops(spec, y: float) -> tuple[list[Op], float]:
    """One spec or customisation: dot, LABEL:- in bold, then the value. Returns (ops, last baseline)."""
    label = fmt.caps(spec.label) if spec.label else None
    value = fmt.caps(spec.value)
    size = L.SPEC_SIZE
    value_font = L.BOLD if (spec.emphasis and label) else L.REGULAR
    if label:
        label_text = f"{label}:-"
        label_w = L.width(label_text, L.BOLD, size)
        runs = [(label_text, L.BOLD), (" ", L.REGULAR), (value, value_font)]
        value_x = L.SPEC_X + label_w + L.width(" ", L.REGULAR, size)
        cont_x = value_x if label_w <= L.SPEC_WIDE_LABEL and value_x < L.SPEC_MAX_X - 20 else L.SPEC_X
    else:
        runs = [(value, L.REGULAR)]
        cont_x = L.SPEC_X
    lines = wrap_runs(runs, size, L.SPEC_X, cont_x, L.SPEC_MAX_X)
    ops: list[Op] = [Dot(L.SPEC_DOT_X, y - L.SPEC_DOT_RISE, L.SPEC_DOT_D)]
    for i, pieces in enumerate(lines):
        baseline = y + i * L.SPEC_STEP
        ops += [Text(x, baseline, text, font, size) for x, text, font in pieces]
    return ops, y + (len(lines) - 1) * L.SPEC_STEP


def fit_title(title: str) -> tuple[list[str], float]:
    text = fmt.caps(title)
    max_w = L.TITLE_MAX_X - L.TITLE_X
    size = shrink_to_fit(text, L.BOLD, L.TITLE_SIZE, L.TITLE_MIN_SIZE, L.TITLE_SHRINK_STEP, max_w)
    if size is not None:
        return [text], size
    size = L.TITLE_MIN_SIZE
    lines = wrap_runs([(text, L.BOLD)], size, L.TITLE_X, L.TITLE_X, L.TITLE_MAX_X)
    return ["".join(t for _, t, _ in line) for line in lines], size


def fit_note(text: str) -> tuple[list[str], float]:
    text = fmt.caps(text)
    max_w = L.NOTE_MAX_X - L.NOTE_X
    size = shrink_to_fit(text, L.BOLD, L.NOTE_SIZE, L.NOTE_MIN_SIZE, L.NOTE_SHRINK_STEP, max_w)
    if size is not None:
        return [text], size
    size = L.NOTE_MIN_SIZE
    lines = wrap_runs([(text, L.BOLD)], size, L.NOTE_X, L.NOTE_X, L.NOTE_MAX_X)
    return ["".join(t for _, t, _ in line) for line in lines], size


def layout_row(line, pad_unit_price: bool = True) -> RowLayout:
    """Section 7.4 for one cart line, with the row top at y = 0."""
    ops: list[Op] = []
    titles, title_size = fit_title(line.title)
    first_title = L.TITLE_OFFSET
    for i, t in enumerate(titles):
        ops.append(Text(L.TITLE_X, first_title + i * L.TITLE_LINE_STEP, t, L.BOLD, title_size))
    last_title = first_title + (len(titles) - 1) * L.TITLE_LINE_STEP
    lowest = last_title

    # Numbers
    nb = first_title + L.NUMBERS_OFFSET
    qty = Decimal(str(line.quantity))
    price = Decimal(str(line.unit_price))
    cells = {
        "quantity": fmt.quantity(qty),
        "unit": f"({fmt.caps(line.unit_label)})",
        "middle": None,
        "price": fmt.unit_price(price, pad_unit_price),
        "subtotal": fmt.amount(line_subtotal(qty, price)),
    }
    ops.append(Text(L.QTY_CENTER, nb, cells["quantity"], L.BOLD, L.NUM_SIZE, "center"))
    unit_y = nb + L.UNIT_LABEL_OFFSET
    ops.append(Text(L.QTY_CENTER, unit_y, cells["unit"], L.REGULAR, L.UNIT_LABEL_SIZE, "center"))
    lowest = max(lowest, unit_y)
    middle = line.middle
    if middle.kind == "note":
        note_lines, note_size = fit_note(middle.text)
        for i, t in enumerate(note_lines):
            y = nb + L.NOTE_OFFSET + i * L.NOTE_LINE_STEP
            ops.append(Text(L.NOTE_X, y, t, L.BOLD, note_size))
            lowest = max(lowest, y)
        cells["middle"] = " ".join(note_lines)
    elif middle.kind == "reference_price":
        cells["middle"] = fmt.unit_price(Decimal(str(middle.amount)), pad_unit_price)
        ops.append(Text(L.REF_PRICE_CENTER, nb, cells["middle"], L.REGULAR, L.NUM_SIZE, "center"))
    ops.append(Text(L.PRICE_CENTER, nb, cells["price"], L.REGULAR, L.NUM_SIZE, "center"))
    ops.append(Text(L.SUBTOTAL_CENTER, nb, cells["subtotal"], L.BOLD, L.NUM_SIZE, "center"))
    lowest = max(lowest, nb)

    # Specs, then customisations
    y = last_title + L.SPEC_FIRST_OFFSET
    last = None
    for spec in line.specs:
        spec_ops, last = _spec_ops(spec, y)
        ops += spec_ops
        y = last + L.SPEC_STEP
    if line.customisations:
        heading_y = (last + L.CUSTOMISATIONS_GAP) if last is not None else last_title + L.SPEC_FIRST_OFFSET
        ops.append(Text(L.CUSTOMISATIONS_X, heading_y, L.CUSTOMISATIONS_HEADING, L.BOLD, L.SPEC_SIZE))
        last = heading_y
        y = heading_y + L.SPEC_STEP
        for spec in line.customisations:
            spec_ops, last = _spec_ops(spec, y)
            ops += spec_ops
            y = last + L.SPEC_STEP
    if last is not None:
        lowest = max(lowest, last)

    rule_y = lowest + L.ROW_RULE_GAP
    ops.append(rule(rule_y, *L.ROW_RULE_X))
    return RowLayout(ops=ops, height=rule_y, cells=cells)


# ---------------------------------------------------------------- payment box


@dataclass
class BoxLayout:
    """Payment terms box with its top at y = 0."""

    ops: list[Op]
    height: float
    line_count: int

    def at(self, top: float) -> list[Op]:
        return shift(self.ops, top)


def layout_box(title: str, lines: list[list[Run]]) -> BoxLayout:
    x_title, title_offset, title_font, title_size = L.BOX_TITLE
    ops: list[Op] = [Text(x_title, title_offset, title, title_font, title_size)]
    max_w = L.TERMS_MAX_X - L.TERMS_X
    y = L.TERMS_FIRST_OFFSET
    last = y
    for runs in lines:
        font_runs = [(text, L.BOLD if bold else L.REGULAR) for text, bold in runs]
        plain = "".join(t for t, _ in runs)
        size = L.TERMS_SIZE
        while size - L.TERMS_SHRINK_STEP >= L.TERMS_MIN_SIZE - 1e-9 and _runs_width(font_runs, size) > max_w + 1e-6:
            size = round(size - L.TERMS_SHRINK_STEP, 4)
        ops.append(Dot(L.TERMS_DOT_X, y - L.TERMS_DOT_RISE, L.TERMS_DOT_D))
        wrapped = wrap_runs(font_runs, size, L.TERMS_X, L.TERMS_X, L.TERMS_MAX_X) if plain else [[]]
        for i, pieces in enumerate(wrapped):
            ops += [Text(x, y + i * L.TERMS_WRAP_STEP, t, f, size) for x, t, f in pieces]
        last = y + (len(wrapped) - 1) * L.TERMS_WRAP_STEP
        y = last + L.TERMS_STEP
    bottom = last + L.BOX_BOTTOM_GAP
    ops.insert(0, Box(L.BOX_X[0], L.BOX_X[1], 0.0, bottom))
    return BoxLayout(ops=ops, height=bottom, line_count=len(lines))


def _runs_width(runs: list[tuple[str, str]], size: float) -> float:
    return sum(L.width(t, f, size) for t, f in runs)


# ---------------------------------------------------------------- pages


@dataclass
class PagePlan:
    first: bool
    table_header: bool
    rows: list[tuple[int, float]] = field(default_factory=list)  # (row index, row top)
    header_top: float | None = None  # table header pill top on this page
    box_top: float | None = None


def paginate(row_heights: list[float], box_height: float, with_gst: bool) -> list[PagePlan]:
    """Place rows in order, never splitting one; then the payment box (7.7)."""
    pages = [PagePlan(first=True, table_header=True, header_top=L.TABLE_PILL_Y[0])]
    top = L.FIRST_ROW_TOP
    for index, height in enumerate(row_heights):
        if top + height > L.ROW_RULE_LIMIT and pages[-1].rows:
            pages.append(PagePlan(first=False, table_header=True, header_top=L.CONT_TABLE_PILL_Y[0]))
            top = L.CONT_ROW_TOP
        pages[-1].rows.append((index, top))
        top += height
    box_top = top + L.BOX_GAP
    limit = L.BOX_BOTTOM_LIMIT_GST if with_gst else L.BOX_BOTTOM_LIMIT
    if box_top + box_height > limit:
        pages.append(PagePlan(first=False, table_header=False))
        box_top = L.CONT_BOX_TOP
    pages[-1].box_top = box_top
    return pages
