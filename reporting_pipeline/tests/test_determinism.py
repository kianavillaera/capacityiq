"""Determinism: two runs on the same input produce identical outputs."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mappings import build_user_mapping, normalise_name, normalise_uid
from src.pipeline import _auto_sub_periods, _last_complete_week_end
from src.transformations import clean_replicon, clean_servicenow, clean_timecard_for_attendance


def _replicon_raw():
    return pd.DataFrame(
        {
            "Entry Date": ["01.06.2026", "02.06.2026", "03.06.2026"],
            "User Name": ["Alice Smith", "Bob Jones", "Carol White"],
            "Employee ID": ["E001", "E002", "E003"],
            "Project Code": ["P1", "P1", "P2"],
            "Task Code": ["T001", "T002", "T003"],
            "Hours": ["8", "7.5", "6"],
            "_source_file": ["a.csv", "a.csv", "a.csv"],
        }
    )


def _sn_raw():
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


def _tc_raw():
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-08", "2026-06-09"]),
            "User ID": ["alice.smith", "bob.jones", "alice.smith", "bob.jones"],
            "User": ["Alice Smith", "Bob Jones", "Alice Smith", "Bob Jones"],
            "Task": ["T001", "T002", "T001", "GEN0001"],
            "Category": ["Task work", "Task work", "Task work", "Task work"],
            "Time worked": [8.0, 7.5, 8.0, 4.0],
            "Rate type": ["Normal Billable"] * 4,
        }
    )


class TestDeterminism:
    def test_clean_replicon_deterministic(self):
        raw = _replicon_raw()
        assert clean_replicon(raw).equals(clean_replicon(raw))

    def test_clean_servicenow_deterministic(self):
        raw = _sn_raw()
        assert clean_servicenow(raw).equals(clean_servicenow(raw))

    def test_clean_timecard_deterministic(self):
        tc1, oc1 = clean_timecard_for_attendance(_tc_raw())
        tc2, oc2 = clean_timecard_for_attendance(_tc_raw())
        assert tc1.reset_index(drop=True).equals(tc2.reset_index(drop=True))

    def test_build_user_mapping_deterministic(self):
        rep = clean_replicon(_replicon_raw())
        sn = clean_servicenow(_sn_raw())

        # Mirror _user_tables(): keep sn_user_id, add norm_* alongside it.
        def _sn_df():
            return sn[["sn_user", "sn_user_id"]].assign(
                norm_name=sn["sn_user"].map(normalise_name),
                norm_uid=sn["sn_user_id"].map(normalise_uid),
            )

        def _rep_df():
            return rep[["username", "employee_id"]].assign(
                norm_name=rep["username"].map(normalise_name),
                norm_uid=rep["username"].map(normalise_uid),
            )

        m1 = build_user_mapping(_rep_df(), _sn_df())
        m2 = build_user_mapping(_rep_df(), _sn_df())
        assert m1.reset_index(drop=True).equals(m2.reset_index(drop=True))

    def test_auto_sub_periods_deterministic(self):
        r1 = _auto_sub_periods(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-26"))
        r2 = _auto_sub_periods(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-26"))
        assert r1 == r2

    def test_last_complete_week_end_deterministic(self):
        tc = _tc_raw()
        assert _last_complete_week_end(tc) == _last_complete_week_end(tc)
