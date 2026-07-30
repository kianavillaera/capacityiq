"""Unit tests for pipeline helper functions added in the auto-detect / history-rotation feature set."""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.pipeline import _auto_sub_periods, _last_complete_week_end


class TestAutoSubPeriods:
    def test_two_months_returns_two_entries(self):
        result = _auto_sub_periods(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-26"))
        assert len(result) == 2

    def test_june_starts_on_first_monday_at_or_after_june_1(self):
        result = _auto_sub_periods(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-26"))
        label, sp_start, sp_end = result[0]
        assert label == "Jun 2026"
        # Jun 1 2026 is a Monday — starts on Jun 1
        assert sp_start.date() == date(2026, 6, 1)
        assert sp_start.weekday() == 0  # Monday

    def test_june_ends_on_sunday_before_first_monday_of_july(self):
        result = _auto_sub_periods(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-26"))
        _, _, sp_end = result[0]
        assert sp_end.date() == date(2026, 7, 5)  # Sunday before Jul 6
        assert sp_end.weekday() == 6  # Sunday

    def test_july_starts_on_first_monday_of_july(self):
        result = _auto_sub_periods(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-26"))
        label, sp_start, sp_end = result[1]
        assert label == "Jul 2026"
        assert sp_start.date() == date(2026, 7, 6)  # first Monday of July
        assert sp_start.weekday() == 0

    def test_july_ends_at_month_end(self):
        result = _auto_sub_periods(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-26"))
        _, _, sp_end = result[1]
        assert sp_end.date() == date(2026, 7, 26)

    def test_single_month_returns_empty(self):
        result = _auto_sub_periods(pd.Timestamp("2026-07-06"), pd.Timestamp("2026-07-26"))
        assert result == []

    def test_three_months_returns_three_entries(self):
        result = _auto_sub_periods(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-08-31"))
        assert len(result) == 3
        labels = [r[0] for r in result]
        assert labels == ["Jun 2026", "Jul 2026", "Aug 2026"]

    def test_sub_periods_do_not_overlap(self):
        result = _auto_sub_periods(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-26"))
        _, _, end0 = result[0]
        _, start1, _ = result[1]
        assert end0 < start1

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="month_end.*must be >="):
            _auto_sub_periods(pd.Timestamp("2026-07-01"), pd.Timestamp("2026-06-01"))


class TestLastCompleteWeekEnd:
    def _make_tc(self, week_users: dict[str, int]) -> pd.DataFrame:
        """Build a minimal timecard frame where each key is a week_start date string
        and value is the number of distinct users that week (8h each)."""
        rows = []
        for ws_str, n_users in week_users.items():
            ws = pd.Timestamp(ws_str)
            for i in range(n_users):
                for day in range(5):
                    rows.append(
                        {
                            "Date": ws + pd.Timedelta(days=day),
                            "User ID": f"user{i:03d}",
                            "Time worked": 8.0,
                        }
                    )
        return pd.DataFrame(rows)

    def test_returns_sunday_of_last_full_week(self):
        tc = self._make_tc(
            {
                "2026-06-01": 90,
                "2026-06-08": 90,
                "2026-06-15": 90,
            }
        )
        result = _last_complete_week_end(tc)
        assert result.weekday() == 6  # Sunday
        assert result.date() == date(2026, 6, 21)

    def test_drops_sparse_trailing_week(self):
        tc = self._make_tc(
            {
                "2026-06-01": 90,
                "2026-06-08": 90,
                "2026-06-15": 90,
                "2026-06-22": 10,  # sparse — below 50% of 90
            }
        )
        result = _last_complete_week_end(tc)
        # Jun 22 week should be dropped; last complete = Jun 15 → Jun 21
        assert result.date() == date(2026, 6, 21)

    def test_single_week_returns_its_sunday(self):
        tc = self._make_tc({"2026-06-01": 5})
        result = _last_complete_week_end(tc)
        assert result.weekday() == 6
        assert result.date() == date(2026, 6, 7)

    def test_all_sparse_returns_first_week_sunday(self):
        # When everything is sparse the function falls back to the first week
        tc = self._make_tc({"2026-06-01": 2, "2026-06-08": 1})
        result = _last_complete_week_end(tc)
        assert result.weekday() == 6

    def test_empty_dataframe_raises(self):
        with pytest.raises(Exception):
            _last_complete_week_end(pd.DataFrame(columns=["Date", "User ID", "Time worked"]))
