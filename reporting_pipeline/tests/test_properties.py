"""Hypothesis property tests for pure transform functions."""

import sys
from pathlib import Path

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mappings import normalise_name, normalise_uid
from src.transformations import clean_replicon

# ── normalise_name ────────────────────────────────────────────────────────────


@given(st.text(min_size=0, max_size=50))
@settings(max_examples=200)
def test_normalise_name_always_returns_str(s):
    result = normalise_name(s)
    assert isinstance(result, str)


@given(st.text(min_size=0, max_size=50))
@settings(max_examples=200)
def test_normalise_name_is_lowercase(s):
    assert normalise_name(s) == normalise_name(s).lower()


@given(st.text(min_size=0, max_size=50))
@settings(max_examples=200)
def test_normalise_name_idempotent(s):
    once = normalise_name(s)
    twice = normalise_name(once)
    assert once == twice


# ── normalise_uid ─────────────────────────────────────────────────────────────


@given(st.text(min_size=0, max_size=50))
@settings(max_examples=200)
def test_normalise_uid_always_returns_str(s):
    assert isinstance(normalise_uid(s), str)


@given(st.text(min_size=0, max_size=50))
@settings(max_examples=200)
def test_normalise_uid_no_at_sign_in_output(s):
    assert "@" not in normalise_uid(s)


@given(st.text(min_size=0, max_size=50))
@settings(max_examples=200)
def test_normalise_uid_idempotent(s):
    once = normalise_uid(s)
    twice = normalise_uid(once)
    assert once == twice


# ── clean_replicon aggregate invariants ──────────────────────────────────────


@given(
    hours=st.lists(
        st.one_of(
            st.floats(min_value=0, max_value=24, allow_nan=False),
            st.just(""),
        ),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=100)
def test_clean_replicon_hours_always_non_negative(hours):
    raw = pd.DataFrame(
        {
            "Entry Date": ["01.06.2026"] * len(hours),
            "User Name": ["Alice"] * len(hours),
            "Employee ID": ["E001"] * len(hours),
            "Project Code": ["P"] * len(hours),
            "Task Code": ["T"] * len(hours),
            "Hours": [str(h) if h != "" else "" for h in hours],
            "_source_file": ["f.csv"] * len(hours),
        }
    )
    result = clean_replicon(raw)
    assert (result["hours"] >= 0).all()


@given(n=st.integers(min_value=1, max_value=20))
@settings(max_examples=50)
def test_clean_replicon_row_count_not_inflated(n):
    """clean_replicon must not increase row count."""
    raw = pd.DataFrame(
        {
            "Entry Date": ["01.06.2026"] * n,
            "User Name": ["Alice"] * n,
            "Employee ID": ["E001"] * n,
            "Project Code": ["P"] * n,
            "Task Code": ["T"] * n,
            "Hours": ["8"] * n,
            "_source_file": ["f.csv"] * n,
        }
    )
    result = clean_replicon(raw)
    # Rows can only stay the same or decrease (invalid dates dropped), never increase
    assert len(result) <= n
