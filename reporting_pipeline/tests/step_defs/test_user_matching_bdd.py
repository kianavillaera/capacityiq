"""BDD step definitions for user_matching.feature."""

import sys
from pathlib import Path

import pandas as pd
import pytest
from pytest_bdd import given, when, then, scenarios

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.mappings import normalise_name, normalise_uid, build_user_mapping, match_users
from src.transformations import clean_replicon, clean_servicenow

scenarios("../features/user_matching.feature")


class Ctx:
    rep_users: pd.DataFrame  = None
    sn_users: pd.DataFrame   = None
    mapping: pd.DataFrame    = None
    approved: pd.DataFrame   = None


@pytest.fixture
def ctx():
    return Ctx()


def _rep_users(name: str) -> pd.DataFrame:
    return pd.DataFrame({
        "username":    [name],
        "employee_id": ["E001"],
        "norm_name":   [normalise_name(name)],
    })


def _sn_users(name: str, uid: str) -> pd.DataFrame:
    return pd.DataFrame({
        "sn_user":   [name],
        "sn_user_id":[uid],
        "norm_name": [normalise_name(name)],
        "norm_uid":  [normalise_uid(uid)],
    })


@given('a Replicon user named "John Smith"')
def rep_john(ctx):
    ctx.rep_users = _rep_users("John Smith")


@given('a Replicon user named "Smith, John"')
def rep_smith_john(ctx):
    ctx.rep_users = _rep_users("Smith, John")


@given('a Replicon user named "ZZZNOBODY XYZABC"')
def rep_nobody(ctx):
    ctx.rep_users = _rep_users("ZZZNOBODY XYZABC")


@given('a ServiceNow user named "John Smith" with ID "jsmith"')
def sn_john(ctx):
    ctx.sn_users = _sn_users("John Smith", "jsmith")


@given("no matching ServiceNow user")
def sn_empty(ctx):
    ctx.sn_users = _sn_users("Alice Totally Different", "atd123")


@given("an approved user mapping with a manual correction")
def approved_mapping(ctx):
    ctx.rep_users = _rep_users("Some User")
    ctx.sn_users  = _sn_users("Some User", "suser")
    ctx.approved  = pd.DataFrame({
        "replicon_username":    ["Some User"],
        "servicenow_user_id":   ["manual_override"],
        "match_status":         ["auto_accepted"],
        "replicon_employee_id": ["E999"],
        "review_required":      [False],
    })


@when("I match users")
def do_match(ctx):
    ctx.mapping = build_user_mapping(ctx.rep_users, ctx.sn_users)


@when("I run user matching with the approved mapping")
def do_match_with_approved(ctx):
    from src.mappings import _resolve_mapping
    ctx.mapping, _ = _resolve_mapping(ctx.rep_users, ctx.sn_users, ctx.approved, 0.80, 0.70)


@then("the match status is auto_accepted")
def status_auto_accepted(ctx):
    assert ctx.mapping.iloc[0]["match_status"] == "auto_accepted"


@then("the match method is exact_name")
def method_exact_name(ctx):
    assert ctx.mapping.iloc[0]["match_method"] == "exact_name"


@then("the match status is no_match or rejected")
def status_no_match(ctx):
    status = ctx.mapping.iloc[0]["match_status"]
    assert status in ("no_match", "rejected"), f"Unexpected status: {status}"


@then("the corrected entry takes precedence")
def corrected_entry(ctx):
    row = ctx.mapping[ctx.mapping["replicon_username"] == "Some User"].iloc[0]
    assert row["servicenow_user_id"] == "manual_override"
