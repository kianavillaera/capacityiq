"""
Tests for transformation and cleaning functions.
"""

import pandas as pd

from src.transformations import clean_replicon, clean_servicenow

# ── clean_replicon ────────────────────────────────────────────────────────────


class TestCleanReplicon:
    def _make_raw(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Entry Date": ["01.06.2026", "02.06.2026", "invalid"],
                "User Name": ["John Smith", "Jane Doe", "Ghost User"],
                "Employee ID": ["EMP001", "EMP002.0", None],
                "Project Code": ["PRJ01", "PRJ01", "PRJ02"],
                "Task Code": ["T001", "T002", "T003"],
                "Hours": ["8", "", "7.5"],
                "_source_file": ["test.csv", "test.csv", "test.csv"],
            }
        )

    def test_returns_expected_columns(self):
        result = clean_replicon(self._make_raw())
        expected = {
            "date",
            "username",
            "employee_id",
            "project_code",
            "task_code",
            "hours",
            "_source_file",
        }
        assert set(result.columns) == expected

    def test_date_parsed_correctly(self):
        result = clean_replicon(self._make_raw())
        assert result.iloc[0]["date"] == pd.Timestamp("2026-06-01")

    def test_invalid_date_becomes_nat(self):
        result = clean_replicon(self._make_raw())
        assert pd.isna(result.iloc[2]["date"])

    def test_blank_hours_become_zero(self):
        result = clean_replicon(self._make_raw())
        # Row with empty string hours should become 0
        assert result.iloc[1]["hours"] == 0.0

    def test_employee_id_dot_zero_stripped(self):
        result = clean_replicon(self._make_raw())
        assert result.iloc[1]["employee_id"] == "EMP002"

    def test_null_employee_id_becomes_none(self):
        result = clean_replicon(self._make_raw())
        # Pandas stores None/NaN in object columns as np.nan, not Python None
        assert pd.isna(result.iloc[2]["employee_id"])

    def test_drops_rows_without_entry_date_or_username(self):
        raw = pd.DataFrame(
            {
                "Entry Date": [None, "01.06.2026"],
                "User Name": ["John", None],
                "Employee ID": ["E1", "E2"],
                "Project Code": ["P1", "P2"],
                "Task Code": ["T1", "T2"],
                "Hours": ["8", "8"],
            }
        )
        result = clean_replicon(raw)
        assert len(result) == 0  # both rows are dropped


# ── clean_resources ───────────────────────────────────────────────────────────


class TestCleanResources:
    from src.transformations import clean_resources

    def _make_resources(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Name": ["Smith, John", "García, Ana"],
                "Email": ["jsmith@example.com", "agarcia@example.com"],
            }
        )

    def test_adds_uid_column(self):
        from src.transformations import clean_resources

        result = clean_resources(self._make_resources())
        assert "_uid" in result.columns

    def test_uid_is_email_prefix_lowercased(self):
        from src.transformations import clean_resources

        result = clean_resources(self._make_resources())
        assert result["_uid"].tolist() == ["jsmith", "agarcia"]

    def test_adds_norm_column(self):
        from src.transformations import clean_resources

        result = clean_resources(self._make_resources())
        assert "_norm" in result.columns

    def test_norm_handles_last_first_format(self):
        from src.transformations import clean_resources

        result = clean_resources(self._make_resources())
        assert result["_norm"].iloc[0] == "john smith"

    def test_norm_handles_unicode(self):
        from src.transformations import clean_resources

        result = clean_resources(self._make_resources())
        assert result["_norm"].iloc[1] == "ana garcia"

    def test_tc_uid_initialised_to_none(self):
        from src.transformations import clean_resources

        result = clean_resources(self._make_resources())
        assert result["tc_uid"].isna().all()

    def test_does_not_mutate_input(self):
        from src.transformations import clean_resources

        original = self._make_resources()
        original_cols = set(original.columns)
        clean_resources(original)
        assert set(original.columns) == original_cols


# ── _ascii ────────────────────────────────────────────────────────────────────


class TestAscii:
    def test_strips_accents(self):
        from src.transformations import _ascii

        assert _ascii("García") == "Garcia"

    def test_strips_umlaut(self):
        from src.transformations import _ascii

        assert _ascii("Müller") == "Muller"

    def test_passthrough_ascii(self):
        from src.transformations import _ascii

        assert _ascii("John Smith") == "John Smith"

    def test_handles_non_string(self):
        from src.transformations import _ascii

        assert _ascii(123) == "123"


# ── clean_servicenow ──────────────────────────────────────────────────────────


class TestCleanServiceNow:
    def _make_raw(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Date": ["2026-06-01", "2026-06-02"],
                "User": ["John Smith", "Jane Doe"],
                "User ID": [" jsmith ", "jdoe"],
                "Project ID": ["T001", "T002"],
                "Time worked": ["8", None],
                "_sheet": ["Sheet1", "Sheet1"],
            }
        )

    def test_returns_expected_columns(self):
        result = clean_servicenow(self._make_raw())
        expected = {"date", "sn_user", "sn_user_id", "task_code", "hours", "_sheet"}
        assert set(result.columns) == expected

    def test_date_parsed(self):
        result = clean_servicenow(self._make_raw())
        assert result.iloc[0]["date"] == pd.Timestamp("2026-06-01")

    def test_user_id_stripped(self):
        result = clean_servicenow(self._make_raw())
        assert result.iloc[0]["sn_user_id"] == "jsmith"

    def test_null_hours_become_zero(self):
        result = clean_servicenow(self._make_raw())
        assert result.iloc[1]["hours"] == 0.0

    def test_missing_sheet_column_filled(self):
        raw = self._make_raw().drop(columns=["_sheet"])
        result = clean_servicenow(raw)
        assert result["_sheet"].iloc[0] == "unknown"
