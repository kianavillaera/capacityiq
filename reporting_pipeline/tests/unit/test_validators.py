"""
Tests for validation functions.
"""

import pandas as pd
import pytest

from src.validators import (
    ValidationError,
    validate_no_duplicate_keys,
    validate_not_empty,
    validate_replicon_columns,
    validate_replicon_dates,
    validate_servicenow_columns,
)

# ── validate_not_empty ────────────────────────────────────────────────────────


class TestValidateNotEmpty:
    def test_passes_for_non_empty(self):
        df = pd.DataFrame({"a": [1, 2]})
        validate_not_empty(df, "test")  # should not raise

    def test_raises_for_empty(self):
        with pytest.raises(ValidationError, match="empty"):
            validate_not_empty(pd.DataFrame(), "test")


# ── validate_replicon_columns ─────────────────────────────────────────────────


class TestValidateRepliconColumns:
    def _make_valid(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Entry Date": ["01.06.2026"],
                "User Name": ["John"],
                "Task Code": ["T001"],
            }
        )

    def test_passes_with_required_columns(self):
        validate_replicon_columns(self._make_valid())

    def test_raises_for_missing_column(self):
        df = self._make_valid().drop(columns=["Task Code"])
        with pytest.raises(ValidationError, match="Task Code"):
            validate_replicon_columns(df)


# ── validate_servicenow_columns ───────────────────────────────────────────────


class TestValidateServiceNowColumns:
    def _make_valid(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Date": ["01/06/2026"],
                "User": ["John"],
                "User ID": ["jsmith"],
                "Project ID": ["T001"],
                "Time worked": [8],
            }
        )

    def test_passes_with_required_columns(self):
        validate_servicenow_columns(self._make_valid())

    def test_raises_for_missing_column(self):
        df = self._make_valid().drop(columns=["User ID"])
        with pytest.raises(ValidationError, match="User ID"):
            validate_servicenow_columns(df)


# ── validate_replicon_dates ───────────────────────────────────────────────────


class TestValidateRepliconDates:
    def test_no_warning_for_valid_dates(self, caplog):
        import logging

        df = pd.DataFrame({"date": pd.to_datetime(["2026-06-01", "2026-06-02"])})
        with caplog.at_level(logging.WARNING):
            validate_replicon_dates(df)
        assert "unparseable" not in caplog.text.lower()

    def test_warns_for_invalid_dates(self, caplog):
        import logging

        df = pd.DataFrame({"date": [pd.NaT, pd.Timestamp("2026-06-01")]})
        with caplog.at_level(logging.WARNING):
            validate_replicon_dates(df)
        assert "1 Replicon rows have unparseable" in caplog.text


# ── validate_no_duplicate_keys ────────────────────────────────────────────────


class TestValidateNoDuplicateKeys:
    def test_no_warning_for_unique_keys(self, caplog):
        import logging

        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        with caplog.at_level(logging.WARNING):
            validate_no_duplicate_keys(df, ["a"], "test")
        assert "duplicate" not in caplog.text.lower()

    def test_warns_for_duplicate_keys(self, caplog):
        import logging

        df = pd.DataFrame({"a": [1, 1], "b": [3, 4]})
        with caplog.at_level(logging.WARNING):
            validate_no_duplicate_keys(df, ["a"], "test")
        assert "duplicate" in caplog.text.lower()


class TestValidationErrorMessages:
    def test_missing_columns_error_mentions_column_name(self):
        df = pd.DataFrame({"Entry Date": ["01.06.2026"], "User Name": ["J"]})
        with pytest.raises(ValidationError, match="Task Code"):
            validate_replicon_columns(df)

    def test_missing_columns_error_shows_found_columns(self):
        df = pd.DataFrame({"Entry Date": ["d"], "User Name": ["u"]})
        with pytest.raises(ValidationError, match="Found"):
            validate_replicon_columns(df)

    def test_empty_error_includes_dataset_name(self):
        from src.validators import validate_not_empty

        with pytest.raises(ValidationError, match="Replicon"):
            validate_not_empty(pd.DataFrame(), "Replicon")

    def test_missing_file_error_includes_path(self):
        from pathlib import Path

        from src.validators import validate_files_exist

        with pytest.raises(ValidationError, match="/nonexistent/path.xlsx"):
            validate_files_exist([Path("/nonexistent/path.xlsx")])

    def test_empty_directory_error_includes_path(self, tmp_path):
        from src.validators import validate_directory_not_empty

        with pytest.raises(ValidationError, match=str(tmp_path)):
            validate_directory_not_empty(tmp_path)

    def test_user_mapping_missing_columns_raises(self):
        from src.validators import validate_user_mapping_columns

        df = pd.DataFrame({"replicon_username": ["u"]})
        with pytest.raises(ValidationError):
            validate_user_mapping_columns(df)
