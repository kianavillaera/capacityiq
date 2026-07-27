"""Tests for Excel exporters."""

import io
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exporters import to_excel_bytes, df_to_excel_bytes
from tests.conftest import make_replicon, make_sn


def _run_recon():
    from src.reconciliation import run
    return run(make_replicon(), make_sn())


class TestToExcelBytes:
    def test_returns_bytes(self):
        result = _run_recon()
        assert isinstance(to_excel_bytes(result), bytes)

    def test_bytes_non_empty(self):
        result = _run_recon()
        assert len(to_excel_bytes(result)) > 0

    def test_has_detail_sheet(self):
        wb_bytes = to_excel_bytes(_run_recon())
        xl = pd.ExcelFile(io.BytesIO(wb_bytes))
        assert "detail" in xl.sheet_names

    def test_has_by_user_sheet(self):
        wb_bytes = to_excel_bytes(_run_recon())
        xl = pd.ExcelFile(io.BytesIO(wb_bytes))
        assert "by_user" in xl.sheet_names

    def test_has_monthly_sheet(self):
        wb_bytes = to_excel_bytes(_run_recon())
        xl = pd.ExcelFile(io.BytesIO(wb_bytes))
        monthly = [s for s in xl.sheet_names if s not in ("detail", "by_user")]
        assert len(monthly) >= 1

    def test_detail_has_required_columns(self):
        wb_bytes = to_excel_bytes(_run_recon())
        detail = pd.read_excel(io.BytesIO(wb_bytes), sheet_name="detail")
        required = {"date", "user_id", "task_code", "hours_replicon", "hours_servicenow", "variance"}
        assert required.issubset(detail.columns)

    def test_variance_formula_correct(self):
        wb_bytes = to_excel_bytes(_run_recon())
        detail = pd.read_excel(io.BytesIO(wb_bytes), sheet_name="detail")
        # variance = hours_servicenow - hours_replicon
        computed = (detail["hours_servicenow"] - detail["hours_replicon"]).round(4)
        stored   = detail["variance"].round(4)
        assert (computed == stored).all()

    def test_hours_tieout_between_detail_and_by_user(self):
        wb_bytes = to_excel_bytes(_run_recon())
        xl = pd.ExcelFile(io.BytesIO(wb_bytes))
        detail  = xl.parse("detail")
        by_user = xl.parse("by_user")
        assert abs(detail["hours_replicon"].sum() - by_user["hours_replicon"].sum()) < 0.01


class TestDfToExcelBytes:
    def test_returns_bytes(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = df_to_excel_bytes(df)
        assert isinstance(result, bytes)

    def test_roundtrips_dataframe(self):
        df = pd.DataFrame({"x": [10, 20], "y": ["a", "b"]})
        roundtrip = pd.read_excel(io.BytesIO(df_to_excel_bytes(df)))
        assert list(roundtrip.columns) == list(df.columns)
        assert len(roundtrip) == len(df)


class TestExportReconciliation:
    def test_writes_four_output_files(self, tmp_path):
        from src.exporters import export_reconciliation
        result = _run_recon()
        paths = export_reconciliation(result, tmp_path, "20260101_120000")
        assert len(paths) == 4
        for path in paths.values():
            assert path.exists()
            assert path.stat().st_size > 0

    def test_reconciliation_file_has_correct_sheets(self, tmp_path):
        from src.exporters import export_reconciliation
        result = _run_recon()
        paths = export_reconciliation(result, tmp_path, "20260101_120001")
        xl = pd.ExcelFile(paths["reconciliation"])
        assert "detail" in xl.sheet_names
        assert "by_user" in xl.sheet_names

    def test_exception_report_file_readable(self, tmp_path):
        from src.exporters import export_reconciliation
        result = _run_recon()
        paths = export_reconciliation(result, tmp_path, "20260101_120002")
        df = pd.read_excel(paths["exception_report"])
        assert isinstance(df, pd.DataFrame)

    def test_creates_output_dir_if_missing(self, tmp_path):
        from src.exporters import export_reconciliation
        subdir = tmp_path / "new" / "nested"
        result = _run_recon()
        export_reconciliation(result, subdir, "20260101_120003")
        assert subdir.exists()
