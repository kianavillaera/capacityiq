"""BDD step definitions for data_quality.feature."""

import sys
from pathlib import Path

import pandas as pd
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.transformations import clean_replicon, clean_servicenow
from src.validators import (
    ValidationError,
    validate_no_duplicate_keys,
    validate_not_empty,
    validate_replicon_columns,
)

scenarios("../features/data_quality.feature")


class Ctx:
    raw: pd.DataFrame = None
    cleaned: pd.DataFrame = None
    exc: Exception = None


@pytest.fixture
def ctx():
    return Ctx()


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("a Replicon entry with blank hours")
def rep_blank_hours(ctx):
    ctx.raw = pd.DataFrame(
        {
            "Entry Date": ["01.06.2026"],
            "User Name": ["J Smith"],
            "Employee ID": ["E1"],
            "Project Code": ["P"],
            "Task Code": ["T"],
            "Hours": [""],
        }
    )


@given('a Replicon entry with date "not-a-date"')
def rep_bad_date(ctx):
    ctx.raw = pd.DataFrame(
        {
            "Entry Date": ["not-a-date"],
            "User Name": ["J Smith"],
            "Employee ID": ["E1"],
            "Project Code": ["P"],
            "Task Code": ["T"],
            "Hours": ["8"],
        }
    )


@given('a ServiceNow row with user ID "  jsmith  "')
def sn_whitespace_uid(ctx):
    ctx.raw = pd.DataFrame(
        {
            "Date": ["2026-06-01"],
            "User": ["J Smith"],
            "User ID": ["  jsmith  "],
            "Project ID": ["T"],
            "Time worked": [8],
            "_sheet": ["S1"],
        }
    )


@given("a DataFrame missing the Task Code column")
def df_missing_task_code(ctx):
    ctx.raw = pd.DataFrame({"Entry Date": ["01.06.2026"], "User Name": ["J Smith"]})


@given("an empty DataFrame named Replicon")
def empty_df(ctx):
    ctx.raw = pd.DataFrame()


@given("two Replicon rows with identical date, user, and task code")
def two_duplicate_rows(ctx):
    row = {
        "Entry Date": "01.06.2026",
        "User Name": "J Smith",
        "Employee ID": "E1",
        "Project Code": "P",
        "Task Code": "T",
        "Hours": "4",
    }
    ctx.raw = pd.DataFrame([row, row])


@given('a Replicon entry with Employee ID "E001.0"')
def rep_trailing_zero(ctx):
    ctx.raw = pd.DataFrame(
        {
            "Entry Date": ["01.06.2026"],
            "User Name": ["J Smith"],
            "Employee ID": ["E001.0"],
            "Project Code": ["P"],
            "Task Code": ["T"],
            "Hours": ["8"],
        }
    )


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the data is cleaned")
def clean_data(ctx):
    if "User ID" in (ctx.raw.columns if ctx.raw is not None else []):
        ctx.cleaned = clean_servicenow(ctx.raw)
    else:
        ctx.cleaned = clean_replicon(ctx.raw)


@when("I validate Replicon columns")
def validate_columns(ctx):
    try:
        validate_replicon_columns(ctx.raw)
    except ValidationError as e:
        ctx.exc = e


@when("I check it is not empty")
def validate_empty(ctx):
    try:
        validate_not_empty(ctx.raw, "Replicon")
    except ValidationError as e:
        ctx.exc = e


@when("I check for duplicate keys")
def check_duplicates(ctx, caplog):
    ctx.cleaned = clean_replicon(ctx.raw)
    import logging

    with caplog.at_level(logging.WARNING):
        validate_no_duplicate_keys(ctx.cleaned, ["date", "username", "task_code"], "Replicon")
    ctx._caplog = caplog


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the hours value is 0.0")
def hours_zero(ctx):
    assert ctx.cleaned["hours"].iloc[0] == 0.0


@then("the date value is NaT")
def date_nat(ctx):
    assert pd.isna(ctx.cleaned["date"].iloc[0])


@then(parsers.parse('the user ID is "{uid}"'))
def user_id_stripped(ctx, uid):
    assert ctx.cleaned["sn_user_id"].iloc[0] == uid


@then("a ValidationError is raised mentioning Task Code")
def validation_error_task_code(ctx):
    assert ctx.exc is not None
    assert "Task Code" in str(ctx.exc)


@then("a ValidationError is raised")
def validation_error(ctx):
    assert ctx.exc is not None


@then("a warning is logged")
def warning_logged(ctx):
    assert any("duplicate" in r.message.lower() for r in ctx._caplog.records)


@then('the employee_id is "E001"')
def employee_id_stripped(ctx):
    assert ctx.cleaned["employee_id"].iloc[0] == "E001"
