"""Acceptance 2: invoices arriving at the same moment still alternate, with no skips or repeats.

Real Postgres only (SQLite has no row locks); set TEST_DATABASE_URL. Each thread is its own
connection and transaction, like separate serverless instances; a barrier releases them together.
"""
import threading
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.designers import service
from app.designers.models import Designer, DesignJob, JobStatusHistory, RotationState
from app.invoice.store import Store

from .pg import migrate, needs_postgres, pg_url  # noqa: F401  (fixture)

pytestmark = needs_postgres
N = 10


@pytest.fixture
def store(pg_url):
    migrate.migrate(pg_url, out=lambda _: None)
    s = Store(pg_url)
    assert s.designers_available()
    yield s
    s.engine.dispose()


def run_together(store: Store, bill_nos: list[int]) -> list[Exception]:
    barrier = threading.Barrier(len(bill_nos))
    errors: list[Exception] = []

    def go(bill_no: int):
        try:
            with store.session() as s:
                barrier.wait()
                service.ensure_job(s, "non_gst", bill_no, f"Customer {bill_no}", Decimal("100.00"), "Box ×1")
                s.commit()
        except Exception as exc:  # collected, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(n,)) for n in bill_nos]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    return errors


def test_ten_at_once_alternate_perfectly(store):
    assert run_together(store, list(range(1, N + 1))) == []
    with store.session() as s:
        names = {d.id: d.name for d in s.scalars(select(Designer))}
        jobs = list(s.scalars(select(DesignJob).order_by(DesignJob.assignment_seq)))
        assert [j.assignment_seq for j in jobs] == list(range(1, N + 1))  # no gaps, no repeats
        assert [names[j.designer_id] for j in jobs] == ["Namit", "Ajendra"] * (N // 2)
        assert len({j.bill_no for j in jobs}) == N
        # Assignment times follow the order the lock was granted.
        assert [j.assigned_at for j in jobs] == sorted(j.assigned_at for j in jobs)
        state = s.get(RotationState, 1)
        assert (state.seq, state.last_order) == (N, 2)
        assert len(list(s.scalars(select(JobStatusHistory)))) == N


def test_same_invoice_at_once_makes_one_job(store):
    errors = run_together(store, [7] * N)
    # Losers either found the winner's job under the lock, or hit the unique constraint.
    assert all("design_jobs_invoice_unique" in str(e) for e in errors), errors
    with store.session() as s:
        assert len(list(s.scalars(select(DesignJob)))) == 1
        assert s.get(RotationState, 1).seq == 1
