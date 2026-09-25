from decimal import Decimal

import pytest

from app.loader import build_catalogue, load, read_config, read_workbook
from app.quote import QuoteInput, calculate
from app.settings import get_settings

RIGID_TB = "rigid_boxes/3x3x2-in/top-bottom"


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def sheet(settings):
    """(rows, flag_status, config) read once; tests copy before changing them."""
    rows, flags = read_workbook(settings.data_file)
    return rows, flags, read_config(settings.config_file)


@pytest.fixture(scope="session")
def catalogue(settings):
    return load(settings.data_file, settings.config_file)


@pytest.fixture
def rebuild(sheet):
    def _rebuild(rows=None, flags=None, config=None):
        base_rows, base_flags, base_config = sheet
        return build_catalogue(
            list(base_rows if rows is None else rows),
            dict(base_flags if flags is None else flags),
            base_config if config is None else config,
        )

    return _rebuild


@pytest.fixture
def quote(catalogue):
    def _quote(cat=None, **kwargs):
        kwargs["quantity"] = Decimal(str(kwargs["quantity"]))
        return calculate(cat or catalogue, QuoteInput(**kwargs))

    return _quote


def codes(result) -> list[str]:
    return [w["code"] for w in result["data"]["warnings"]]
