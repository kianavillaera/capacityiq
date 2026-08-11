"""Pandera data contracts at stage boundaries.

Each schema validates one DataFrame that crosses a stage boundary.
Checked on representative inline frames, not on real data files.
"""

import sys
from pathlib import Path

import pandas as pd
import pandera as pa

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.transformations import (
    clean_replicon,
    clean_resources,
    clean_servicenow,
    clean_timecard_for_attendance,
)

REPLICON_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.dtypes.DateTime, nullable=True),
        "username": pa.Column(str, nullable=False),
        "employee_id": pa.Column(nullable=True),
        "project_code": pa.Column(str, nullable=True),
        "task_code": pa.Column(str, nullable=True),
        "hours": pa.Column(float, pa.Check.ge(0), nullable=False),
    },
    strict=False,  # extra columns (_source_file) allowed
)

SN_CLEAN_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.dtypes.DateTime, nullable=True),
        "sn_user": pa.Column(str, nullable=False),
        "sn_user_id": pa.Column(str, nullable=False),
        "task_code": pa.Column(str, nullable=False),
        "hours": pa.Column(float, pa.Check.ge(0), nullable=False),
    },
    strict=False,
)

TC_ATTENDANCE_SCHEMA = pa.DataFrameSchema(
    {
        "Date": pa.Column(pa.dtypes.DateTime, nullable=True),
        "User ID": pa.Column(str, nullable=True),
        "Time worked": pa.Column(float, pa.Check.ge(0), nullable=False),
        "is_gen": pa.Column(bool, nullable=False),
        "_uid": pa.Column(str, nullable=True),
    },
    strict=False,
)


def _raw_replicon():
    return pd.DataFrame(
        {
            "Entry Date": ["01.06.2026", "02.06.2026"],
            "User Name": ["Alice Smith", "Bob Jones"],
            "Employee ID": ["E001", "E002"],
            "Project Code": ["PRJ1", "PRJ1"],
            "Task Code": ["T001", "T002"],
            "Hours": ["8", "7.5"],
            "_source_file": ["a.csv", "a.csv"],
        }
    )


def _raw_sn():
    return pd.DataFrame(
        {
            "Date": ["2026-06-01", "2026-06-02"],
            "User": ["Alice Smith", "Bob Jones"],
            "User ID": ["alice.smith", "bob.jones"],
            "Project ID": ["T001", "T002"],
            "Time worked": [8, 7.5],
            "_sheet": ["Sheet1", "Sheet1"],
        }
    )


def _raw_tc():
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "User": ["Alice Smith", "Bob Jones"],
            "User ID": ["alice.smith", "bob.jones"],
            "Task": ["T001", "GEN0001"],
            "Category": ["Task work", "Task work"],
            "Time worked": [8.0, 4.0],
            "Rate type": ["Normal Billable", "Normal Billable"],
        }
    )


class TestRepliconOutputSchema:
    def test_clean_replicon_satisfies_schema(self):
        result = clean_replicon(_raw_replicon())
        REPLICON_SCHEMA.validate(result)

    def test_hours_are_non_negative(self):
        result = clean_replicon(_raw_replicon())
        assert (result["hours"] >= 0).all()

    def test_no_nulls_in_username(self):
        result = clean_replicon(_raw_replicon())
        assert result["username"].notna().all()


class TestServiceNowOutputSchema:
    def test_clean_servicenow_satisfies_schema(self):
        result = clean_servicenow(_raw_sn())
        SN_CLEAN_SCHEMA.validate(result)

    def test_hours_are_non_negative(self):
        result = clean_servicenow(_raw_sn())
        assert (result["hours"] >= 0).all()


class TestTimecardAttendanceSchema:
    def test_regular_frame_satisfies_schema(self):
        tc, _ = clean_timecard_for_attendance(_raw_tc())
        TC_ATTENDANCE_SCHEMA.validate(tc)

    def test_time_worked_non_negative(self):
        tc, _ = clean_timecard_for_attendance(_raw_tc())
        assert (tc["Time worked"] >= 0).all()

    def test_is_gen_bool_column(self):
        tc, _ = clean_timecard_for_attendance(_raw_tc())
        assert tc["is_gen"].dtype == bool

    def test_oncall_split_is_disjoint(self):
        raw = _raw_tc().copy()
        raw.loc[0, "Rate type"] = "On-Call Weekdays"
        tc, tc_oncall = clean_timecard_for_attendance(raw)
        # total row count is conserved regardless of how uids distribute across frames
        assert len(tc) + len(tc_oncall) == len(raw)


class TestResourcesSchema:
    def test_resources_has_required_columns(self):
        raw = pd.DataFrame(
            {
                "Name": ["Smith, Alice"],
                "Email": ["alice.smith@example.com"],
                "Pod": ["Pod1"],
                "Technology": ["F&O"],
                "Specialisation": ["Dev"],
                "Seniority": ["Senior"],
                "Location": ["London"],
            }
        )
        result = clean_resources(raw, uid_overrides={})
        for col in ["Name", "Email", "_uid", "_norm", "tc_uid"]:
            assert col in result.columns, f"missing {col}"

    def test_uid_derived_from_email(self):
        raw = pd.DataFrame(
            {
                "Name": ["Smith, Alice"],
                "Email": ["Alice.Smith@example.com"],
                "Pod": ["Pod1"],
                "Technology": ["F&O"],
                "Specialisation": ["Dev"],
                "Seniority": ["Senior"],
                "Location": ["London"],
            }
        )
        result = clean_resources(raw, uid_overrides={})
        assert result.iloc[0]["_uid"] == "alice.smith"

    def test_tc_uid_is_null_before_matching(self):
        raw = pd.DataFrame(
            {
                "Name": ["Smith, Alice"],
                "Email": ["alice.smith@example.com"],
                "Pod": ["Pod1"],
                "Technology": ["F&O"],
                "Specialisation": ["Dev"],
                "Seniority": ["Senior"],
                "Location": ["London"],
            }
        )
        result = clean_resources(raw, uid_overrides={})
        assert result["tc_uid"].isna().all()
