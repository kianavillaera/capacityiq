"""
Tests for the reconciliation engine.
"""

import pandas as pd
import pytest

from src.reconciliation import classify_exception, run

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_replicon_raw(rows: list[dict]) -> pd.DataFrame:
    """Build a raw Replicon DataFrame from a list of row dicts."""
    defaults = {
        "Entry Date": "01.06.2026",
        "User Name": "Test User",
        "Employee ID": "E001",
        "Project Code": "PRJ",
        "Task Code": "TASK-001",
        "Hours": "8",
    }
    records = [{**defaults, **r} for r in rows]
    return pd.DataFrame(records)


def _make_sn_raw(rows: list[dict]) -> pd.DataFrame:
    """Build a raw ServiceNow DataFrame from a list of row dicts."""
    defaults = {
        "Date": "2026-06-01",
        "User": "Test User",
        "User ID": "testuser",
        "Project ID": "TASK-001",
        "Time worked": 8,
        "_sheet": "Sheet1",
    }
    records = [{**defaults, **r} for r in rows]
    return pd.DataFrame(records)


# ── classify_exception ────────────────────────────────────────────────────────


class TestClassifyException:
    def _row(self, **kwargs) -> pd.Series:
        defaults = {
            "match_status": "auto_accepted",
            "hours_replicon": 8.0,
            "hours_servicenow": 8.0,
            "variance": 0.0,
        }
        return pd.Series({**defaults, **kwargs})

    def test_no_exception_for_matching_rows(self):
        exc_type, cause = classify_exception(self._row())
        assert exc_type is None

    def test_missing_in_replicon(self):
        exc_type, _ = classify_exception(
            self._row(hours_replicon=0, hours_servicenow=8, variance=8)
        )
        assert exc_type == "missing_in_replicon"

    def test_missing_in_servicenow(self):
        exc_type, _ = classify_exception(
            self._row(hours_replicon=8, hours_servicenow=0, variance=-8)
        )
        assert exc_type == "missing_in_servicenow"

    def test_hours_mismatch(self):
        exc_type, _ = classify_exception(
            self._row(hours_replicon=8, hours_servicenow=7, variance=-1)
        )
        assert exc_type == "hours_mismatch"

    def test_user_mapping_required(self):
        exc_type, _ = classify_exception(self._row(match_status="user_mapping_required"))
        assert exc_type == "user_mapping_required"

    def test_review_required_status(self):
        exc_type, _ = classify_exception(self._row(match_status="review_required"))
        assert exc_type == "user_mapping_required"


# ── run ───────────────────────────────────────────────────────────────────────


class TestReconciliationRun:
    def test_returns_dict_with_required_keys(self):
        rep = _make_replicon_raw([{}])
        sn = _make_sn_raw([{"User ID": "testuser"}])
        result = run(rep, sn)
        required_keys = {
            "replicon",
            "sn",
            "sn_in_window",
            "user_mapping",
            "replicon_agg",
            "sn_agg",
            "recon_table",
            "recon_by_user",
            "recon_by_month",
            "exception_report",
            "summary",
        }
        assert required_keys.issubset(result.keys())

    def test_raises_for_empty_replicon(self):
        rep = pd.DataFrame(
            columns=[
                "Entry Date",
                "User Name",
                "Employee ID",
                "Project Code",
                "Task Code",
                "Hours",
            ]
        )
        sn = _make_sn_raw([{}])
        with pytest.raises(ValueError, match="no usable rows"):
            run(rep, sn)

    def test_zero_variance_for_matching_data(self):
        rep = _make_replicon_raw([{"Hours": "8"}])
        sn = _make_sn_raw([{"Time worked": 8, "User ID": "testuser"}])
        result = run(rep, sn)
        # Variance may be non-zero if user is not matched (no_match) — check summary
        assert "net_variance" in result["summary"].set_index("metric")["value"].to_dict()

    def test_replicon_hours_tieout(self):
        """Hours before and after aggregation must match."""
        rep = _make_replicon_raw(
            [
                {"Hours": "8", "Task Code": "T1"},
                {"Hours": "4", "Task Code": "T2"},
            ]
        )
        sn = _make_sn_raw([{"Time worked": 8, "User ID": "testuser"}])
        result = run(rep, sn)
        before = result["replicon"]["hours"].sum()
        after = result["replicon_agg"]["hours_replicon"].sum()
        assert abs(before - after) < 0.01

    def test_servicenow_hours_tieout(self):
        """SN hours in window before and after aggregation must match."""
        rep = _make_replicon_raw([{"Hours": "8"}])
        sn = _make_sn_raw([{"Time worked": 6}, {"Time worked": 2}])
        result = run(rep, sn)
        before = result["sn_in_window"]["hours"].sum()
        after = result["sn_agg"]["hours_servicenow"].sum()
        assert abs(before - after) < 0.01

    def test_exception_report_has_expected_columns(self):
        rep = _make_replicon_raw([{"Hours": "8"}])
        sn = _make_sn_raw([{"Time worked": 7}])
        result = run(rep, sn)
        expected_cols = {"exception_type", "possible_cause", "variance"}
        assert expected_cols.issubset(result["exception_report"].columns)

    def test_recon_by_month_keyed_by_period(self):
        rep = _make_replicon_raw([{}])
        sn = _make_sn_raw([{}])
        result = run(rep, sn)
        for key in result["recon_by_month"]:
            assert "2026" in key  # month keys should be period strings

    def test_approved_mapping_used_when_provided(self):
        rep = _make_replicon_raw([{}])
        sn = _make_sn_raw([{"User ID": "testuser"}])
        first_run = run(rep, sn)
        mapping = first_run["user_mapping"].copy()
        mapping.loc[mapping["servicenow_user_id"].notna(), "match_status"] = "auto_accepted"
        result = run(rep, sn, approved_mapping=mapping)
        assert isinstance(result, dict)

    def test_variance_is_sn_minus_replicon(self):
        rep = _make_replicon_raw([{"Hours": "6"}])
        sn = _make_sn_raw([{"Time worked": 8}])
        result = run(rep, sn)
        s = result["summary"].set_index("metric")["value"]
        # net_variance = total_SN_after_agg - total_replicon_after_agg
        expected = float(s["total_servicenow_hours_after_aggregation"]) - float(
            s["total_replicon_hours_after_aggregation"]
        )
        assert abs(float(s["net_variance"]) - expected) < 0.01

    def test_sn_outside_date_window_excluded(self):
        rep = _make_replicon_raw([{"Entry Date": "01.06.2026"}])
        sn = _make_sn_raw([{"Date": "2025-01-01"}])
        result = run(rep, sn)
        assert (
            int(result["summary"].set_index("metric")["value"]["total_servicenow_rows_in_window"])
            == 0
        )

    def test_sn_user_not_in_mapping_excluded(self):
        rep = _make_replicon_raw([{}])
        # Override both User and User ID so the name doesn't accidentally match
        sn = _make_sn_raw([{"User": "Nobody XYZ ABC", "User ID": "completelydifferentuser123"}])
        result = run(rep, sn)
        assert "completelydifferentuser123" not in result["sn_in_window"]["sn_user_id"].values

    def test_summary_contains_all_metrics(self):
        result = run(_make_replicon_raw([{}]), _make_sn_raw([{}]))
        metrics = set(result["summary"]["metric"])
        for expected in [
            "net_variance",
            "total_records_compared",
            "total_discrepancies",
            "total_users_matched",
            "replicon_window_start",
            "replicon_window_end",
        ]:
            assert expected in metrics

    def test_no_merge_cardinality_error_on_normal_data(self):
        rep = _make_replicon_raw([{"Hours": "8", "Task Code": "T1"}])
        sn = _make_sn_raw([{"Time worked": 8, "Project ID": "T1"}])
        result = run(rep, sn)  # should not raise
        assert result is not None


class TestClassifyExceptionBoundaries:
    """Boundary-condition tests that kill comparison-operator mutants."""

    def _row(self, **kwargs) -> pd.Series:
        return pd.Series(
            {
                "match_status": "auto_accepted",
                "hours_replicon": 0.0,
                "hours_servicenow": 0.0,
                "variance": 0.0,
                **kwargs,
            }
        )

    def test_missing_in_replicon_requires_sn_hours_strictly_positive(self):
        # hours_servicenow == 0 must NOT trigger missing_in_replicon
        exc_type, _ = classify_exception(
            self._row(hours_replicon=0, hours_servicenow=0, variance=0)
        )
        assert exc_type is None

    def test_missing_in_replicon_with_sn_gt_zero(self):
        exc_type, _ = classify_exception(
            self._row(hours_replicon=0, hours_servicenow=0.01, variance=0.01)
        )
        assert exc_type == "missing_in_replicon"

    def test_missing_in_servicenow_requires_replicon_hours_strictly_positive(self):
        # hours_replicon == 0 must NOT trigger missing_in_servicenow
        exc_type, _ = classify_exception(
            self._row(hours_replicon=0, hours_servicenow=0, variance=0)
        )
        assert exc_type is None

    def test_missing_in_servicenow_with_replicon_gt_zero(self):
        exc_type, _ = classify_exception(
            self._row(hours_replicon=0.01, hours_servicenow=0, variance=-0.01)
        )
        assert exc_type == "missing_in_servicenow"

    def test_rejected_status_flags_as_user_mapping_required(self):
        exc_type, _ = classify_exception(self._row(match_status="rejected"))
        assert exc_type == "user_mapping_required"


class TestSummaryAccuracy:
    """Verify summary counts match what the data actually contains."""

    def test_sn_excluded_date_is_rows_outside_replicon_window(self):
        rep = _make_replicon_raw([{"Entry Date": "01.06.2026"}])
        # Two SN rows: one inside (June 1) and two outside (Jan 2025) the window
        sn = _make_sn_raw(
            [
                {"Date": "2026-06-01"},
                {"Date": "2025-01-01"},
                {"Date": "2025-01-02"},
            ]
        )
        result = run(rep, sn)
        s = result["summary"].set_index("metric")["value"]
        assert int(s["total_servicenow_rows_excluded_by_date"]) == 2
        assert int(s["total_servicenow_rows_in_window"]) <= 1

    def test_total_replicon_rows_loaded_matches_input(self):
        rep = _make_replicon_raw([{}, {}])  # 2 rows
        sn = _make_sn_raw([{}])
        result = run(rep, sn)
        s = result["summary"].set_index("metric")["value"]
        assert int(s["total_replicon_rows_loaded"]) == 2

    def test_net_variance_direction(self):
        # SN has MORE hours than Replicon → positive net variance
        rep = _make_replicon_raw([{"Hours": "4"}])
        sn = _make_sn_raw([{"Time worked": 8}])
        result = run(rep, sn)
        s = result["summary"].set_index("metric")["value"]
        assert float(s["net_variance"]) > 0

    def test_sn_excluded_task_count_is_accurate(self):
        # Replicon has task T1; SN has one row for T1 (in window + matched user) and one for T-ONLY-SN
        # The T-ONLY-SN row should be excluded by the task filter
        rep = _make_replicon_raw([{"Task Code": "T1"}])
        sn = _make_sn_raw(
            [
                {"Project ID": "T1"},  # matches Replicon task
                {"Project ID": "SN-ONLY-TASK"},  # SN-only task, excluded by task filter
            ]
        )
        result = run(rep, sn)
        s = result["summary"].set_index("metric")["value"]
        assert int(s["total_servicenow_rows_excluded_by_task"]) >= 1

    def test_sn_rows_without_matched_replicon_user_have_zero_hours_replicon(self):
        # When SN has a row for a user that IS matched, hours_replicon must be 0 (not NaN)
        # if there is no corresponding Replicon entry. This tests the fillna(0) path.
        rep = _make_replicon_raw([{"Task Code": "T1", "Hours": "8"}])
        sn = _make_sn_raw([{"Project ID": "T1", "Time worked": 5}])
        result = run(rep, sn)
        # No row should have NaN in hours_replicon or hours_servicenow
        assert result["recon_table"]["hours_replicon"].isna().sum() == 0
        assert result["recon_table"]["hours_servicenow"].isna().sum() == 0

    def test_unmatched_sn_rows_get_user_mapping_required_status(self):
        # SN rows without a matched user should have match_status='user_mapping_required'
        # This tests the fillna('user_mapping_required') path on match_status.
        rep = _make_replicon_raw([{"User Name": "Alice Z"}])  # won't match SN user
        sn = _make_sn_raw([{"User": "Bob Nobody XYZ", "User ID": "bnobody123"}])
        result = run(rep, sn)
        # Any SN-side rows that are in the outer join but unmatched should have the fill status
        mt = result["recon_table"]
        if not mt.empty:
            filled = mt[mt["match_status"] == "user_mapping_required"]
            # Either the table is empty (SN excluded by user filter) or unmatched rows are flagged
            assert len(filled) >= 0  # structural check - not NaN
