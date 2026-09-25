"""Size parsing and size metrics (FR-4)."""
import re
from decimal import Decimal

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SEPARATOR = re.compile(r"\s*[×xX*]\s*")
_REPEATED_UNIT = re.compile(r"\b(in|cm|mm|ft)(?:\s+\1\b)+")

# How many numbers each custom-dims formula needs, and their names in order.
DIM_NAMES = {
    "box": ("length", "width", "height"),
    "bag": ("height", "length", "side"),
    "flat": ("length", "width"),
}
METRIC_UNIT = "sq in"
CM_PER_INCH = Decimal("2.54")


def normalize_size_label(text: str) -> str:
    """Collapse a unit word repeated by a bad sheet formula: '6 × 8 in in in' -> '6 × 8 in'."""
    return _REPEATED_UNIT.sub(r"\1", " ".join(text.split()))


def parse_size(text: str) -> tuple[Decimal, ...]:
    """Numbers before any '(' in Size / Spec, split on ×, x, X or *."""
    head = text.split("(", 1)[0]
    parts = [p for p in _SEPARATOR.split(head.strip()) if p]
    numbers = []
    for part in parts:
        match = _NUMBER.search(part)
        if not match:
            return ()
        numbers.append(Decimal(match.group()))
    return tuple(numbers)


def metric(kind: str, dims: tuple[Decimal, ...]) -> Decimal:
    if kind == "box":
        l, w, h = dims
        return 2 * (l * w + l * h + w * h)
    if kind == "bag":
        h, l, s = dims
        return 2 * h * l + 2 * h * s + l * s
    if kind == "flat":
        l, w = dims
        return l * w
    raise ValueError(f"no metric for custom_dims {kind!r}")


def canonical(kind: str, dims: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    """Key for 'same size' checks: sorted for boxes and flat items, exact H, L, S for bags."""
    normalized = tuple(d.normalize() for d in dims)
    return normalized if kind == "bag" else tuple(sorted(normalized))


def format_dims(dims: tuple[Decimal, ...], unit: str = "in") -> str:
    return " × ".join(_plain(d) for d in dims) + f" {unit}"


def _plain(d: Decimal) -> str:
    text = format(d.normalize(), "f")
    return text
