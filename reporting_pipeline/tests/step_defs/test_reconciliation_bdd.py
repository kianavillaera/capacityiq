"""BDD step definitions for reconciliation.feature."""

import sys
from pathlib import Path

import pandas as pd
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.reconciliation import run
from tests.conftest import make_replicon, make_sn

scenarios("../features/reconciliation.feature")


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


class Ctx:
    rep: pd.DataFrame = None
    sn: pd.DataFrame = None
    result: dict = None


@pytest.fixture
def ctx():
    return Ctx()


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("a Replicon entry with 8 hours on task TASK-001 for user jsmith")
def replicon_8h(ctx):
    ctx.rep = make_replicon({"Hours": "8", "Task Code": "TASK-001"})


@given("a ServiceNow entry with 8 hours on task TASK-001 for user jsmith")
def sn_8h(ctx):
    ctx.sn = make_sn({"Time worked": 8, "Project ID": "TASK-001", "User ID": "jsmith"})


@given("no Replicon entry for task TASK-001")
def replicon_empty_task(ctx):
    # Replicon needs TASK-001 in its task-code set for SN scoping to include the SN row.
    # Use a zero-hours entry on a different date so the SN June-02 entry generates missing_in_replicon.
    ctx.rep = make_replicon({"Entry Date": "01.06.2026", "Task Code": "TASK-001", "Hours": ""})


@given("a ServiceNow entry with 5 hours on task TASK-001 for user jsmith")
def sn_5h_task(ctx):
    # Same date as Replicon so it falls within the date window
    ctx.sn = make_sn(
        {"Time worked": 5, "Project ID": "TASK-001", "User ID": "jsmith", "Date": "2026-06-01"}
    )


@given("a Replicon entry with 8 hours on task TASK-001 for user jsmith", target_fixture="ctx")
def replicon_8h_no_sn(ctx):
    ctx.rep = make_replicon({"Hours": "8", "Task Code": "TASK-001"})
    return ctx


@given("no ServiceNow entry for that task")
def sn_different_task(ctx):
    ctx.sn = make_sn({"Project ID": "DIFFERENT"})


@given("a Replicon entry with 8 hours for user jsmith")
def replicon_8h_user(ctx):
    ctx.rep = make_replicon({"Hours": "8"})


@given("a ServiceNow entry with 6 hours for user jsmith")
def sn_6h_user(ctx):
    ctx.sn = make_sn({"Time worked": 6})


@given("Replicon entries totalling 12 hours across two tasks")
def replicon_12h_two_tasks(ctx):
    ctx.rep = make_replicon(
        {"Hours": "8", "Task Code": "T1"},
        {"Hours": "4", "Task Code": "T2"},
    )
    ctx.sn = make_sn()


@given("a Replicon entry dated 2026-06-01")
def replicon_june(ctx):
    ctx.rep = make_replicon({"Entry Date": "01.06.2026"})


@given("a ServiceNow entry dated 2025-01-01 for the same user and task")
def sn_old_date(ctx):
    ctx.sn = make_sn({"Date": "2025-01-01"})


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I run reconciliation")
def run_recon(ctx):
    if ctx.rep is None:
        ctx.rep = make_replicon()
    if ctx.sn is None:
        ctx.sn = make_sn()
    ctx.result = run(ctx.rep, ctx.sn)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the net variance is 0")
def net_variance_zero(ctx):
    s = ctx.result["summary"].set_index("metric")["value"]
    assert float(s["net_variance"]) == 0.0


@then(parsers.parse("the exception type is {exc_type}"))
def check_exception_type(ctx, exc_type):
    exc = ctx.result["exception_report"]
    assert not exc.empty, "Expected exceptions but none found"
    assert exc_type in exc["exception_type"].values


@then(parsers.parse("the variance is {value:g}"))
def check_variance(ctx, value):
    exc = ctx.result["exception_report"]
    assert not exc.empty
    assert any(abs(v - value) < 0.01 for v in exc["variance"])


@then("Replicon hours before aggregation equals hours after aggregation")
def replicon_tieout(ctx):
    before = ctx.result["replicon"]["hours"].sum()
    after = ctx.result["replicon_agg"]["hours_replicon"].sum()
    assert abs(before - after) < 0.01


@then("the ServiceNow row is excluded from the comparison")
def sn_excluded(ctx):
    s = ctx.result["summary"].set_index("metric")["value"]
    assert int(s["total_servicenow_rows_in_window"]) == 0
