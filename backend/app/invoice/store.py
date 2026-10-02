"""Invoice storage (BRD-cart-invoice 8.2): SQLAlchemy, SQLite by default, Postgres via DATABASE_URL.

Three number series, one table each, so each keeps its own unique bill numbers:
`invoices` (Non-GST invoices, plus every invoice saved before the series existed),
`gst_invoices` and `quotations`. `document_counters` remembers the highest number each series
has ever issued, so a deleted number is never handed out again.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import JSON, Date, DateTime, Integer, Numeric, String, create_engine, delete, func, inspect, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..designers import schema as designer_schema
from ..settings import ROOT

AMOUNT = Numeric(12, 2, asdecimal=True)
SERIES = ("non_gst", "gst", "quotation")


class Base(DeclarativeBase):
    pass


class _Document:
    """Columns every series stores. Rows are rendered from these, never re-priced."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_no: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    billing_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Copy of the customer's (or GST buyer's) name so the Invoices page can search without reading JSON.
    business_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    customer: Mapped[dict] = mapped_column(JSON, nullable=False)
    lines: Mapped[list] = mapped_column(JSON, nullable=False)
    payments: Mapped[list] = mapped_column(JSON, nullable=False)
    saving_amount: Mapped[Decimal | None] = mapped_column(AMOUNT, nullable=True)
    total: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    gst_amount: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    # Legacy With GST billing: {"option": "cgst_sgst_9_9", "taxes": [{"name", "rate", "amount"}, ...]}.
    # GST invoices: {"option": "<slab key>", "taxes": [CGST, UGST, IGST]}. Null otherwise.
    gst: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payable: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    # Percent due before printing: 100 = pay in full; less = split, the rest before dispatch.
    # Null on rows saved before it was chosen per invoice: those used config advance_pct (80).
    advance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2, asdecimal=True), nullable=True)
    received: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvoiceRow(_Document, Base):
    """Non-GST invoices (the Printevr invoice), and all invoices saved before the series split."""

    __tablename__ = "invoices"
    # Who generated the invoice, on rows saved while it was asked for. Kept, never printed.
    salesperson: Mapped[str | None] = mapped_column(String(100), nullable=True)


class GstInvoiceRow(_Document, Base):
    __tablename__ = "gst_invoices"
    # Buyer, consignee and transport fields as printed (models.GstDetails).
    details: Mapped[dict] = mapped_column(JSON, nullable=False)


class QuotationRow(_Document, Base):
    __tablename__ = "quotations"


ROW_CLASSES: dict[str, type] = {"non_gst": InvoiceRow, "gst": GstInvoiceRow, "quotation": QuotationRow}


class DocumentCounter(Base):
    """The highest number a series has issued. Only goes up."""

    __tablename__ = "document_counters"

    series: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_no: Mapped[int] = mapped_column(Integer, nullable=False)


class InvoiceEvent(Base):
    __tablename__ = "invoice_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Null on events written before the series existed: those are Non-GST invoices.
    series: Mapped[str | None] = mapped_column(String(16), nullable=True)
    event: Mapped[str] = mapped_column(String(20), nullable=False)  # created | payment_added | downloaded
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False)  # version and amounts; never customer details


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_url(url: str) -> str:
    """Relative SQLite paths resolve against the repo root; postgres:// URLs use psycopg 3."""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////") and url != "sqlite:///:memory:":
        rel = url[len("sqlite:///") :]
        path = Path(rel)
        if not path.is_absolute() and not (len(rel) > 1 and rel[1] == ":"):
            path = (ROOT / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        url = "sqlite:///" + path.as_posix()
    elif url.startswith("sqlite:////"):
        Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
    return url


class Store:
    def __init__(self, url: str):
        url = normalize_url(url)
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        else:
            # No server-side prepared statements: they don't survive a transaction-mode
            # pooler (Neon's -pooler host, PgBouncer), which DATABASE_URL should point at.
            kwargs["connect_args"] = {"prepare_threshold": None}
        self.engine: Engine = create_engine(url, **kwargs)
        self.is_sqlite = url.startswith("sqlite")
        Base.metadata.create_all(self.engine)
        self._add_missing_columns()
        self.session = sessionmaker(self.engine, expire_on_commit=False)
        self._designers_ready = False

    def designers_available(self) -> bool:
        """Whether the Designer Assignment tables exist (on Postgres: the migrations have run)."""
        if not self._designers_ready:
            self._designers_ready = designer_schema.prepare(self.engine)
        return self._designers_ready

    def _add_missing_columns(self) -> None:
        """create_all() doesn't alter existing tables: add columns introduced since (all nullable)."""
        added = {
            InvoiceRow.__tablename__: {"gst": "JSON", "salesperson": "VARCHAR(100)", "advance_pct": "NUMERIC(5,2)"},
            GstInvoiceRow.__tablename__: {"advance_pct": "NUMERIC(5,2)"},
            QuotationRow.__tablename__: {"advance_pct": "NUMERIC(5,2)"},
            InvoiceEvent.__tablename__: {"series": "VARCHAR(16)"},
        }
        for table, columns in added.items():
            have = {c["name"] for c in inspect(self.engine).get_columns(table)}
            for name, sql_type in columns.items():
                if name not in have:
                    with self.engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))

    @staticmethod
    def row_class(series: str) -> type:
        return ROW_CLASSES[series]

    def next_bill_no(self, session: Session, start: int, series: str = "non_gst") -> int:
        """One more than the highest number this series has issued (saved or since deleted)."""
        row = self.row_class(series)
        highest = session.scalar(select(func.max(row.bill_no)))
        counter = session.get(DocumentCounter, series)
        issued = max(highest or 0, counter.last_no if counter else 0)
        return max(issued + 1, start)

    def mark_issued(self, session: Session, series: str, bill_no: int) -> None:
        counter = session.get(DocumentCounter, series)
        if counter is None:
            session.add(DocumentCounter(series=series, last_no=bill_no))
        elif bill_no > counter.last_no:
            counter.last_no = bill_no

    def get(self, session: Session, bill_no: int, series: str = "non_gst"):
        row = self.row_class(series)
        return session.scalar(select(row).where(row.bill_no == bill_no))

    def delete(self, session: Session, row, series: str = "non_gst") -> None:
        session.execute(delete(InvoiceEvent).where(InvoiceEvent.bill_no == row.bill_no, self._series_is(series)))
        session.delete(row)

    def exists(self, session: Session, bill_no: int, series: str = "non_gst") -> bool:
        row = self.row_class(series)
        return session.scalar(select(row.id).where(row.bill_no == bill_no)) is not None

    def add_event(self, session: Session, bill_no: int, event: str, detail: dict, series: str = "non_gst") -> None:
        session.add(InvoiceEvent(bill_no=bill_no, series=series, event=event, at=utcnow(), detail=detail))

    @staticmethod
    def _series_is(series: str):
        if series == "non_gst":
            return or_(InvoiceEvent.series == series, InvoiceEvent.series.is_(None))
        return InvoiceEvent.series == series

    def events(self, session: Session, bill_no: int, series: str = "non_gst") -> list[InvoiceEvent]:
        query = select(InvoiceEvent).where(InvoiceEvent.bill_no == bill_no, self._series_is(series))
        return list(session.scalars(query.order_by(InvoiceEvent.id)))

    def search(
        self, session: Session, q: str | None, status: str | None, limit: int, offset: int, series: str = "non_gst"
    ) -> tuple[list, int]:
        row = self.row_class(series)
        query = select(row)
        if q:
            term = q.strip()
            conds = [func.lower(row.business_name).contains(term.lower(), autoescape=True)]
            if term.isdigit():
                conds.append(row.bill_no == int(term))
            query = query.where(or_(*conds))
        if status:
            query = query.where(row.status == status)
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = session.scalars(query.order_by(row.bill_no.desc()).limit(limit).offset(offset))
        return list(rows), total
