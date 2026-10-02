"""A throwaway Postgres schema for the tests that need real Postgres (row locks, migrations).

Set TEST_DATABASE_URL to a database you don't mind tests writing to (a local Postgres, or a
spare Neon branch; never production). Each test gets its own schema, dropped afterwards.
Without it those tests are skipped.
"""
import importlib.util
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()
needs_postgres = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")

# backend/scripts/migrate.py, loaded as a module (scripts/ isn't a package).
_spec = importlib.util.spec_from_file_location("migrate", Path(__file__).parents[1] / "scripts" / "migrate.py")
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)


def _plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1).replace("postgres://", "postgresql://", 1)


def with_schema(url: str, schema: str) -> str:
    """The URL with every connection's search_path set to `schema`."""
    sep = "&" if "?" in url else "?"
    return f"{_plain(url)}{sep}options={quote(f'-csearch_path={schema}')}"


@contextmanager
def temp_schema():
    """A URL whose unqualified tables live in a fresh, empty schema, dropped afterwards."""
    schema = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_plain(TEST_DATABASE_URL), autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    try:
        yield with_schema(TEST_DATABASE_URL, schema)
    finally:
        with psycopg.connect(_plain(TEST_DATABASE_URL), autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def pg_url():
    with temp_schema() as url:
        yield url
