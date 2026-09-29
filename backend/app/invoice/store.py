"""Invoice storage (BRD-cart-invoice 8.2): SQLAlchemy, SQLite by default, Postgres via DATABASE_URL."""
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import JSON, Date, DateTime, Integer, Numeric, String, create_engine, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..settings import ROOT

AMOUNT = Numeric(12, 2, asdecimal=True)


class Base(DeclarativeBase):
    pass


class InvoiceRow(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_no: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    billing_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Copy of customer.business_name so the Invoices page can search without reading JSON.
    business_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    customer: Mapped[dict] = mapped_column(JSON, nullable=False)
    lines: Mapped[list] = mapped_column(JSON, nullable=False)
    payments: Mapped[list] = mapped_column(JSON, nullable=False)
    saving_amount: Mapped[Decimal | None] = mapped_column(AMOUNT, nullable=True)
    total: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    gst_amount: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    payable: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    received: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvoiceEvent(Base):
    __tablename__ = "invoice_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
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
        self.engine: Engine = create_engine(url, **kwargs)
        self.is_sqlite = url.startswith("sqlite")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def next_bill_no(self, session: Session, start: int) -> int:
        highest = session.scalar(select(func.max(InvoiceRow.bill_no)))
        return start if highest is None else max(highest + 1, start)

    def get(self, session: Session, bill_no: int) -> InvoiceRow | None:
        return session.scalar(select(InvoiceRow).where(InvoiceRow.bill_no == bill_no))

    def exists(self, session: Session, bill_no: int) -> bool:
        return session.scalar(select(InvoiceRow.id).where(InvoiceRow.bill_no == bill_no)) is not None

    def add_event(self, session: Session, bill_no: int, event: str, detail: dict) -> None:
        session.add(InvoiceEvent(bill_no=bill_no, event=event, at=utcnow(), detail=detail))

    def events(self, session: Session, bill_no: int) -> list[InvoiceEvent]:
        return list(session.scalars(select(InvoiceEvent).where(InvoiceEvent.bill_no == bill_no).order_by(InvoiceEvent.id)))

    def search(
        self, session: Session, q: str | None, status: str | None, limit: int, offset: int
    ) -> tuple[list[InvoiceRow], int]:
        query = select(InvoiceRow)
        if q:
            term = q.strip()
            conds = [func.lower(InvoiceRow.business_name).contains(term.lower(), autoescape=True)]
            if term.isdigit():
                conds.append(InvoiceRow.bill_no == int(term))
            query = query.where(or_(*conds))
        if status:
            query = query.where(InvoiceRow.status == status)
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = session.scalars(query.order_by(InvoiceRow.bill_no.desc()).limit(limit).offset(offset))
        return list(rows), total
