"""
Tests for data loaders.
"""

import io
import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure reporting_pipeline/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.loaders import (
    load_replicon_bytes,
    load_timecard_bytes,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

REPLICON_CSV = (
    "Entry Date,User Name,Employee ID,Project Code,Task Code,Hours\n"
    "01.06.2026,John Smith,EMP001,PRJ01,TASK-001,8\n"
    "02.06.2026,Jane Doe,EMP002,PRJ01,TASK-002,7.5\n"
)


def _replicon_bytes() -> bytes:
    return REPLICON_CSV.encode("utf-8")


def _make_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestLoadRepliconBytes:
    def test_returns_dataframe(self):
        result = load_replicon_bytes([("test.csv", _replicon_bytes())])
        assert isinstance(result, pd.DataFrame)

    def test_has_source_file_column(self):
        result = load_replicon_bytes([("test.csv", _replicon_bytes())])
        assert "_source_file" in result.columns

    def test_correct_row_count(self):
        result = load_replicon_bytes([("test.csv", _replicon_bytes())])
        assert len(result) == 2

    def test_multiple_files_concatenated(self):
        data = [("file1.csv", _replicon_bytes()), ("file2.csv", _replicon_bytes())]
        result = load_replicon_bytes(data)
        assert len(result) == 4

    def test_hours_worked_renamed_to_hours(self):
        csv = "Entry Date,User Name,Employee ID,Project Code,Task Code,Hours Worked\n01.06.2026,John,E1,P1,T1,8\n"
        result = load_replicon_bytes([("test.csv", csv.encode())])
        assert "Hours" in result.columns


class TestLoadTimecardBytes:
    def _make_sn_excel(self) -> bytes:
        df = pd.DataFrame({
            "Date": ["01/06/2026"],
            "User": ["John Smith"],
            "User ID": ["jsmith"],
            "Project ID": ["TASK-001"],
            "Time worked": [8],
        })
        return _make_excel_bytes(df)

    def test_returns_dataframe(self):
        result = load_timecard_bytes(self._make_sn_excel())
        assert isinstance(result, pd.DataFrame)

    def test_has_sheet_column(self):
        result = load_timecard_bytes(self._make_sn_excel())
        assert "_sheet" in result.columns

    def test_correct_row_count(self):
        result = load_timecard_bytes(self._make_sn_excel())
        assert len(result) == 1


class TestLoadTimecardFiles:
    def test_raises_for_empty_paths(self):
        from src.loaders import load_timecard_files
        with pytest.raises(ValueError, match="required"):
            load_timecard_files([])


class TestLoadRepliconDir:
    def test_raises_for_empty_directory(self, tmp_path):
        from src.loaders import load_replicon_dir
        with pytest.raises(ValueError, match="No CSV or XLSX"):
            load_replicon_dir(tmp_path)

    def test_raises_for_missing_directory(self, tmp_path):
        from src.loaders import load_replicon_dir
        with pytest.raises((ValueError, FileNotFoundError, OSError)):
            load_replicon_dir(tmp_path / "nonexistent")

    def test_loads_csv_from_directory(self, tmp_path):
        import csv
        from src.loaders import load_replicon_dir
        csvfile = tmp_path / "rep.csv"
        csvfile.write_text(
            "Entry Date,User Name,Employee ID,Project Code,Task Code,Hours\n"
            "01.06.2026,John,E1,P1,T1,8\n"
        )
        result = load_replicon_dir(tmp_path)
        assert len(result) == 1
        assert result["_source_file"].iloc[0] == "rep.csv"

    def test_ffills_user_name_in_merged_cell_format(self, tmp_path):
        from src.loaders import load_replicon_dir
        csvfile = tmp_path / "rep.csv"
        csvfile.write_text(
            "Entry Date,User Name,Employee ID,Project Code,Task Code,Hours\n"
            "01.06.2026,John Smith,E1,P1,T1,8\n"
            "02.06.2026,,E1,P1,T2,4\n"  # blank User Name (merged-cell style)
        )
        result = load_replicon_dir(tmp_path)
        assert result["User Name"].iloc[1] == "John Smith"


class TestLoadApprovedMapping:
    def test_returns_none_when_file_missing(self, tmp_path):
        from src.loaders import load_approved_mapping
        result = load_approved_mapping(tmp_path / "nonexistent.xlsx")
        assert result is None
