"""Excel export functions for the pipeline."""

import io
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def to_excel_bytes(results: dict) -> bytes:
    """Serialise reconciliation results to an in-memory Excel workbook (detail + by_user + monthly sheets)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        results["recon_table"].to_excel(writer, sheet_name="detail", index=False)
        results["recon_by_user"].to_excel(writer, sheet_name="by_user", index=False)
        for month, df in results["recon_by_month"].items():
            df.to_excel(writer, sheet_name=month, index=False)
    return buf.getvalue()

def export_reconciliation(results: dict, output_dir: Path, timestamp: str) -> dict:
    """Write reconciliation, exception report, user mapping, and summary to disk."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {}

    recon_path = output_dir / f"reconciliation_{timestamp}.xlsx"
    recon_path.write_bytes(to_excel_bytes(results))
    logger.info("Wrote reconciliation workbook: %s", recon_path)
    paths["reconciliation"] = recon_path

    exc_path = output_dir / f"exception_report_{timestamp}.xlsx"
    _df_to_excel(results["exception_report"], exc_path)
    logger.info("Wrote exception report: %s", exc_path)
    paths["exception_report"] = exc_path

    map_path = output_dir / f"user_mapping_{timestamp}.xlsx"
    _df_to_excel(results["user_mapping"], map_path)
    logger.info("Wrote user mapping: %s", map_path)
    paths["user_mapping"] = map_path

    sum_path = output_dir / f"summary_{timestamp}.xlsx"
    _df_to_excel(results["summary"], sum_path)
    logger.info("Wrote summary: %s", sum_path)
    paths["summary"] = sum_path

    return paths

def export_fte_workbook(fte_results: dict, output_path: Path) -> None:
    """Write the Power BI FTE workbook with all standard sheets."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        fte_results["tech_weekly_no_gen"].to_excel(writer, sheet_name="tech_weekly_fte", index=False)
        fte_results["graph1"].to_excel(writer, sheet_name="graph1_total_fte", index=False)
        fte_results["graph2"].to_excel(writer, sheet_name="graph2_task_fte", index=False)
        fte_results["weekly"].to_excel(writer, sheet_name="weekly_breakdown", index=False)
        fte_results["pivot"].to_excel(writer, sheet_name="category_weekly_pivot")
        fte_results["tech_weekly_spec_no_gen"].to_excel(
            writer, sheet_name="tech_weekly_fte_by_spec", index=False
        )
        fte_results["tech_weekly"].to_excel(writer, sheet_name="tech_weekly_fte_gen", index=False)
        fte_results["tech_weekly_spec"].to_excel(
            writer, sheet_name="tech_weekly_fte_by_spec_gen", index=False
        )

    logger.info("FTE workbook written: %s", output_path)

def export_timecard_data(df: pd.DataFrame, output_path: Path,
                         oncall_df: "pd.DataFrame | None" = None) -> None:
    """Export time-card data with two sheets: with_gen and without_gen.

    If oncall_df is supplied it is saved to a third 'oncall' sheet so the
    compliance pipeline can track hours_oncall without reading raw XLS files.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="with_gen", index=False)
        df[~df["is_gen"]].to_excel(writer, sheet_name="without_gen", index=False)
        if oncall_df is not None and not oncall_df.empty:
            oncall_df.to_excel(writer, sheet_name="oncall", index=False)

    logger.info(
        "Timecard data written: %s  (with_gen=%d  without_gen=%d  oncall=%d)",
        output_path, len(df), (~df["is_gen"]).sum(),
        len(oncall_df) if oncall_df is not None else 0,
    )

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Serialise a single DataFrame to in-memory Excel bytes."""
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()

def _df_to_excel(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
