"""
Shared fixtures for the entire test suite.
All test files import from here via pytest's automatic conftest discovery.
"""

import io
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Raw-data builders
# ---------------------------------------------------------------------------

REPLICON_DEFAULTS = {
    "Entry Date":  "01.06.2026",
    "User Name":   "John Smith",
    "Employee ID": "E001",
    "Project Code": "PRJ",
    "Task Code":   "TASK-001",
    "Hours":       "8",
}

SN_DEFAULTS = {
    "Date":        "2026-06-01",
    "User":        "John Smith",
    "User ID":     "jsmith",
    "Project ID":  "TASK-001",
    "Time worked": 8,
    "_sheet":      "Sheet1",
}


def make_replicon(*overrides: dict) -> pd.DataFrame:
    """Return a raw Replicon DataFrame. Pass dicts to override defaults per row."""
    rows = [{**REPLICON_DEFAULTS, **o} for o in overrides] if overrides else [REPLICON_DEFAULTS.copy()]
    return pd.DataFrame(rows)


def make_sn(*overrides: dict) -> pd.DataFrame:
    rows = [{**SN_DEFAULTS, **o} for o in overrides] if overrides else [SN_DEFAULTS.copy()]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def replicon_raw():
    return make_replicon()


@pytest.fixture
def sn_raw():
    return make_sn()


@pytest.fixture
def matched_replicon_and_sn():
    """One Replicon entry and one matching SN entry — expect zero variance."""
    return make_replicon(), make_sn()


@pytest.fixture
def reconciliation_result(matched_replicon_and_sn):
    from src.reconciliation import run
    rep, sn = matched_replicon_and_sn
    return run(rep, sn)


@pytest.fixture
def excel_bytes_factory():
    """Return a helper that serialises a DataFrame to in-memory Excel bytes."""
    def _factory(df: pd.DataFrame) -> bytes:
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        return buf.getvalue()
    return _factory
