"""In-memory catalogue: Category -> Product -> Item -> Tiers."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Addon:
    id: str
    name: str
    price: Decimal | None  # None = taken from the sheet (sample charge)
    basis: str  # per_unit | per_order
    from_sheet: bool = False


@dataclass(frozen=True)
class Tier:
    qty_from: int
    label: str
    price: Decimal
    flags: tuple[str, ...]
    row: int


@dataclass
class Item:
    id: str
    product_id: str
    size: str
    option_1: str | None
    option_2: str | None
    tiers: list[Tier]
    production_time: str
    unit: str
    dims: tuple[Decimal, ...] | None = None
    metric: Decimal | None = None
    sample_charge: Decimal | None = None

    @property
    def breakpoints(self) -> list[int]:
        return [t.qty_from for t in self.tiers]

    def option(self, key: str) -> str | None:
        return {"option_1": self.option_1, "option_2": self.option_2}[key]


@dataclass
class Product:
    id: str
    name: str  # exactly as in the sheet
    display_name: str
    category: str
    sale_unit: str
    yield_factor: int
    micro_uom: str | None
    micro_unit: str | None
    micro_approx: bool
    custom_dims: str
    anchor_group: str | None
    anchor_match: list[str]
    below_min_policy: str
    max_qty: int | None
    custom_surcharge_pct: Decimal
    custom_round_step: Decimal
    gst_rate: Decimal
    flagged_price_policy: str
    suggest_more: bool
    size_label: str
    option_labels: dict[str, str]
    addons: list[Addon]
    notes: list[str]
    items: list[Item] = field(default_factory=list)

    @property
    def supports_custom(self) -> bool:
        return self.custom_dims in ("box", "bag", "flat")


@dataclass
class Catalogue:
    products: dict[str, Product]
    items: dict[str, Item]
    categories: list[str]
    flag_status: dict[str, str]
    sample_rows: int
    tier_rows: int
    warnings: list[str]
    show_invoice_billing: bool
    loaded_at: datetime
    source_file: str

    def product(self, product_id: str) -> Product | None:
        return self.products.get(product_id)

    def item(self, item_id: str) -> Item | None:
        return self.items.get(item_id)

    def open_flags(self, flags: tuple[str, ...]) -> list[str]:
        return [f for f in flags if self.flag_status.get(f, "").strip().lower() == "open"]

    def anchor_pool(self, product: Product, options: dict[str, str | None]) -> list[Item]:
        """Every item in the product's anchor group with the same anchor_match option values."""
        group = product.anchor_group or product.id
        members = [p for p in self.products.values() if (p.anchor_group or p.id) == group]
        return [
            item
            for p in members
            for item in p.items
            if all((item.option(key) or None) == (options.get(key) or None) for key in product.anchor_match)
        ]

    @property
    def open_flag_count(self) -> int:
        return sum(1 for s in self.flag_status.values() if s.strip().lower() == "open")
