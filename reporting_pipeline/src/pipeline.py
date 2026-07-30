"""End-to-end pipeline orchestrators."""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from config.settings import (
    AUTO_ACCEPT_THRESHOLD,
    REVIEW_LOW_THRESHOLD,
    HOURS_THRESHOLD_WEEKLY,
    HOURS_THRESHOLD_MONTHLY,
    HOURS_PER_FTE,
    FTE_BAND,
    TECH_MAP,
    TASK_CATEGORIES,
    UID_OVERRIDES,
    PARTIAL_HOURS_EXCEPTIONS,
    RESOURCES_SHEET,
    TIMESTAMP,
    REPORTS_DIR,
    EXPORTS_DIR,
)
from src import loaders, validators, transformations, reconciliation as recon_engine
from src import exporters, fte_prep, report_generator, mappings
from src.utils import timer, rotate_to_history

logger = logging.getLogger(__name__)


def _auto_sub_periods(month_start: pd.Timestamp, month_end: pd.Timestamp) -> list:
    """Auto-generate sub-periods per calendar month, aligned to ISO week boundaries.

    Each sub-period starts on the first Monday on or after the 1st of that
    calendar month, and ends on the Sunday before the first Monday of the next
    month (or on month_end for the last month).  No hardcoded dates required.

    Examples (Jun-Jul 2026)::

        ('Jun 2026', 2026-06-01, 2026-07-05)  # 5 full weeks
        ('Jul 2026', 2026-07-06, 2026-07-26)  # 3 full weeks
    """
    # Enumerate distinct calendar months between month_start and month_end
    m = pd.Timestamp(month_start.year, month_start.month, 1)
    months: list[pd.Timestamp] = []
    while m <= pd.Timestamp(month_end.year, month_end.month, 1):
        months.append(m)
        m = m + pd.DateOffset(months=1)

    if len(months) <= 1:
        return []  # single-month period — no sub-split needed

    sub_periods = []
    for i, m_first in enumerate(months):
        # First Monday on or after the 1st of this month
        days_fwd = (7 - m_first.weekday()) % 7
        sp_start = m_first + pd.Timedelta(days=days_fwd)
        if i == 0:
            sp_start = max(sp_start, month_start)

        if i < len(months) - 1:
            # Sunday before the first Monday of the next calendar month
            next_first = months[i + 1]
            days_fwd_next = (7 - next_first.weekday()) % 7
            sp_end = next_first + pd.Timedelta(days=days_fwd_next) - pd.Timedelta(days=1)
        else:
            sp_end = month_end

        if sp_start <= sp_end:
            label = m_first.strftime("%b %Y")   # e.g. 'Jun 2026'
            sub_periods.append((label, sp_start, sp_end))

    return sub_periods

def run_reconciliation_pipeline(
    replicon_dir: Path,
    timecard_paths: list[Path],
    output_dir: Path = REPORTS_DIR,
    approved_mapping_path: Optional[Path] = None,
    auto_accept: float = AUTO_ACCEPT_THRESHOLD,
    review_low: float = REVIEW_LOW_THRESHOLD,
    timestamp: str = TIMESTAMP,
) -> dict:
    logger.info("Reconciliation pipeline starting.")

    with timer("input validation", logger):
        validators.validate_directory_not_empty(replicon_dir)
        validators.validate_files_exist(timecard_paths)
        if approved_mapping_path and approved_mapping_path.exists():
            validators.validate_files_exist([approved_mapping_path])

    with timer("data loading", logger):
        replicon_raw = loaders.load_replicon_dir(replicon_dir)
        sn_raw = loaders.load_timecard_files(timecard_paths)
        approved_mapping = loaders.load_approved_mapping(approved_mapping_path) if approved_mapping_path else None

    with timer("column validation", logger):
        validators.validate_replicon_columns(replicon_raw)
        validators.validate_servicenow_columns(sn_raw)
        validators.validate_not_empty(replicon_raw, "Replicon")
        validators.validate_not_empty(sn_raw, "ServiceNow")
        if approved_mapping is not None:
            validators.validate_user_mapping_columns(approved_mapping)

    with timer("reconciliation", logger):
        results = recon_engine.run(
            replicon_raw,
            sn_raw,
            approved_mapping,
            auto_accept,
            review_low,
        )

    with timer("export", logger):
        output_paths = exporters.export_reconciliation(results, output_dir, timestamp)
        results["output_paths"] = output_paths

    logger.info("Reconciliation pipeline complete.")

    return results

def run_fte_pipeline(
    timecard_paths: list[Path],
    output_dir: Path = EXPORTS_DIR,
    ref_graph1_path: Optional[Path] = None,
    ref_graph2_path: Optional[Path] = None,
    timestamp: str = TIMESTAMP,
) -> dict:
    logger.info("FTE pipeline starting.")

    with timer("input validation", logger):
        validators.validate_files_exist(timecard_paths)

    with timer("data loading", logger):
        df_raw = loaders.load_timecard_multi(timecard_paths)

    # On-call rows are excluded from FTE totals but tracked in the source data.
    with timer("cleaning", logger):
        # Exclude pipeline-generated meta columns from dedup so rows from overlapping
        # extracts (same user/date/task but different _source_file) are collapsed.
        _meta = [c for c in ("_source_file", "_sheet") if c in df_raw.columns]
        df_raw = df_raw.drop_duplicates(subset=[c for c in df_raw.columns if c not in _meta], keep="last")
        is_oncall = df_raw["Rate type"].astype(str).str.contains("On-Call", case=False, na=False)
        df = df_raw[~is_oncall].copy()
        df["Time worked"] = pd.to_numeric(df["Time worked"], errors="coerce").fillna(0)
        df["is_gen"] = df["Task"].astype(str).str.startswith("GEN")
        logger.info("After dedup + on-call removal: %d rows", len(df))

    with timer("FTE aggregation", logger):
        fte_results = fte_prep.prepare_fte_data(
            df,
            hours_per_fte=HOURS_PER_FTE,
            fte_band=FTE_BAND,
            tech_map=TECH_MAP,
            task_categories=TASK_CATEGORIES,
        )

    with timer("reference validation", logger):
        fte_prep.validate_against_reference(
            fte_results["weekly"],
            ref_graph2_path,
            ref_graph1_path,
        )

    with timer("export", logger):
        output_dir = Path(output_dir)
        # Fixed filenames so Power BI can always refresh from the same path.
        # Previous files are moved to history/ before being overwritten.
        fte_output = output_dir / "powerbi_fte_weekly.xlsx"
        tc_output  = output_dir / "timecard_data.xlsx"

        rotate_to_history(fte_output, timestamp)
        rotate_to_history(tc_output,  timestamp)

        exporters.export_fte_workbook(fte_results, fte_output)
        exporters.export_timecard_data(df, tc_output)

        fte_results["output_paths"] = {
            "powerbi_fte": fte_output,
            "timecard_data": tc_output,
        }

    logger.info("FTE pipeline complete.")
    return fte_results

def run_weekly_attendance_pipeline(
    timecard_paths: list[Path],
    resources_path: Path,
    output_dir: Path = REPORTS_DIR,
    resources_sheet: str = RESOURCES_SHEET,
    hours_threshold: int = HOURS_THRESHOLD_WEEKLY,
    timestamp: str = TIMESTAMP,
) -> dict:
    logger.info("Weekly attendance pipeline starting.")

    with timer("input validation", logger):
        validators.validate_files_exist([*timecard_paths, resources_path])

    with timer("data loading", logger):
        tc_raw = loaders.load_timecard_multi(timecard_paths)
        resources_raw = loaders.load_resources(resources_path, resources_sheet)

    with timer("cleaning", logger):
        tc, tc_oncall = transformations.clean_timecard_for_attendance(tc_raw)
        resources = transformations.clean_resources(resources_raw, UID_OVERRIDES)

    week = tc["week_start"].max()
    tc_week = tc[tc["week_start"] == week]
    tc_oncall_week = tc_oncall[tc_oncall["week_start"] == week]

    logger.info("Analysing week: %s  (%d rows)", week.date(), len(tc_week))

    with timer("roster matching", logger):
        resources_matched = mappings.match_roster_to_timecard(resources, tc_week, UID_OVERRIDES)

    with timer("attendance computation", logger):
        roster, orphans, ghost, incomplete, full, day_cols = (
            report_generator.build_weekly_attendance(
                tc_week, tc_oncall_week, resources_matched, week, hours_threshold,
                partial_hours_exceptions=PARTIAL_HOURS_EXCEPTIONS,
            )
        )

    with timer("export", logger):
        output_path = output_dir / f"compliance_{week.date()}_{timestamp}.xlsx"
        report_generator.write_weekly_attendance_report(
            output_path, full, ghost, incomplete, orphans, day_cols, week, hours_threshold
        )

    logger.info("Weekly attendance pipeline complete: %s", output_path)

    return {
        "roster": roster,
        "ghost": ghost,
        "incomplete": incomplete,
        "full": full,
        "orphans": orphans,
        "day_cols": day_cols,
        "week": week,
        "output_path": output_path,
    }

def run_monthly_attendance_pipeline(
    timecard_data_path: Path,
    resources_path: Path,
    month_start: Optional[pd.Timestamp] = None,   # auto-detected if None
    month_end: Optional[pd.Timestamp] = None,     # auto-detected if None
    month_label: Optional[str] = None,            # auto-generated if None
    output_dir: Path = REPORTS_DIR,
    resources_sheet: str = RESOURCES_SHEET,
    hours_threshold: int = HOURS_THRESHOLD_WEEKLY,
    month_threshold: Optional[int] = None,        # auto-computed if None
    timestamp: str = TIMESTAMP,
    sub_periods: Optional[list] = None,  # list of (label, start_ts, end_ts); auto-generated if None
) -> dict:
    """Run the monthly attendance analysis. Reads from timecard_data.xlsx (FTE pipeline output).

    All date/period parameters are optional.  When omitted the pipeline inspects
    the timecard file and infers sensible defaults automatically:

    * ``month_start`` / ``month_end`` — full date range present in the file
    * ``month_label`` — derived from the months spanned (e.g. 'Jun-Jul 2026')
    * ``month_threshold`` — ``len(weeks) × hours_threshold``
    * ``sub_periods`` — one sub-period per calendar month, aligned to Mon-Sun week
      boundaries (e.g. Jun 1–Jul 5, Jul 6–Jul 26)
    """
    logger.info("Monthly attendance pipeline starting.")

    with timer("input validation", logger):
        validators.validate_files_exist([timecard_data_path, resources_path])

    with timer("data loading", logger):
        tc_raw = pd.read_excel(timecard_data_path, sheet_name="with_gen")
        tc_raw["Date"] = pd.to_datetime(tc_raw["Date"], errors="coerce")
        tc_raw["week_start"] = (
            tc_raw["Date"] - pd.to_timedelta(tc_raw["Date"].dt.weekday, unit="D")
        ).dt.normalize()
        tc_raw["Time worked"] = pd.to_numeric(tc_raw["Time worked"], errors="coerce").fillna(0)

        # ── Auto-detect period from data when not explicitly supplied ─────────
        _data_min = tc_raw["Date"].min().normalize()
        _data_max = tc_raw["Date"].max().normalize()

        if month_start is None:
            month_start = _data_min
        if month_end is None:
            month_end = _data_max
        if month_label is None:
            _s = month_start.strftime("%b")
            _e = month_end.strftime("%b %Y")
            month_label = _e if month_start.strftime("%b %Y") == _e else f"{_s}-{_e}"
        if sub_periods is None:
            sub_periods = _auto_sub_periods(month_start, month_end)
        # ─────────────────────────────────────────────────────────────────────

        logger.info("Monthly attendance pipeline: %s (%s → %s)",
                    month_label, month_start.date(), month_end.date())

        _meta_cols = [c for c in ("_source_file",) if c in tc_raw.columns]
        tc_raw = (
            tc_raw[(tc_raw["Date"] >= month_start) & (tc_raw["Date"] <= month_end)]
            .drop_duplicates(subset=[c for c in tc_raw.columns if c not in _meta_cols], keep="last")
            .reset_index(drop=True)
        )

        # Load on-call rows from the dedicated sheet if available (written by the
        # overlay/merge step). Gives hours_oncall visibility in the monthly report.
        try:
            oncall_raw = pd.read_excel(timecard_data_path, sheet_name="oncall")
            oncall_raw["Date"] = pd.to_datetime(oncall_raw["Date"], errors="coerce")
            oncall_raw["week_start"] = (
                oncall_raw["Date"] - pd.to_timedelta(oncall_raw["Date"].dt.weekday, unit="D")
            ).dt.normalize()
            oncall_raw["Time worked"] = pd.to_numeric(oncall_raw["Time worked"], errors="coerce").fillna(0)
            oncall_raw = oncall_raw[
                (oncall_raw["Date"] >= month_start) & (oncall_raw["Date"] <= month_end)
            ].reset_index(drop=True)
            logger.info("Loaded %d on-call rows from 'oncall' sheet.", len(oncall_raw))
        except Exception:
            oncall_raw = pd.DataFrame()
            logger.debug("No 'oncall' sheet in timecard file — hours_oncall will be 0.")

        resources_raw = loaders.load_resources(resources_path, resources_sheet)

    with timer("cleaning", logger):
        tc, tc_oncall_file = transformations.clean_timecard_for_attendance(tc_raw)
        # Prefer the dedicated oncall sheet; fall back to whatever clean_timecard extracted
        if not oncall_raw.empty:
            if "User ID" in oncall_raw.columns:
                oncall_raw["_uid"] = oncall_raw["User ID"].str.strip().str.lower()
            tc_oncall = oncall_raw
        else:
            tc_oncall = tc_oncall_file
        resources = transformations.clean_resources(resources_raw, UID_OVERRIDES)

    weeks = sorted(tc["week_start"].unique())

    # Auto-compute monthly threshold if not supplied
    if month_threshold is None:
        month_threshold = len(weeks) * hours_threshold

    logger.info("Analysis period: %s to %s (%d weeks, threshold=%dh)",
                month_start.date(), month_end.date(), len(weeks), month_threshold)

    with timer("roster matching", logger):
        resources_matched = mappings.match_roster_to_timecard(resources, tc, UID_OVERRIDES)

    with timer("attendance computation", logger):
        roster, orphans, ghost, incomplete, full, wk_cols = (
            report_generator.build_monthly_attendance(
                tc, tc_oncall, resources_matched, weeks, month_threshold, hours_threshold,
                partial_hours_exceptions=PARTIAL_HOURS_EXCEPTIONS,
            )
        )

        # Build per-week sub-rosters for the per-week sheets
        week_rosters = {}
        for w in weeks:
            tc_w = tc[tc["week_start"] == w]
            tc_w = tc_w[(tc_w["Date"] >= month_start) & (tc_w["Date"] <= month_end)]
            tc_oc_w = tc_oncall[
                (tc_oncall["week_start"] == w)
                & (tc_oncall["Date"] >= month_start)
                & (tc_oncall["Date"] <= month_end)
            ]

            if len(tc_w) == 0:
                continue

            res_w = mappings.match_roster_to_timecard(resources, tc_w, UID_OVERRIDES)
            week_dates = sorted(tc_w["Date"].dt.normalize().unique())
            day_cols_w = [d.strftime("%a %d/%m") for d in week_dates]

            roster_w, orphans_w, *_ = report_generator.build_weekly_attendance(
                tc_w, tc_oc_w if not tc_oc_w.empty else pd.DataFrame(columns=tc_oncall.columns),
                res_w, w, hours_threshold,
                partial_hours_exceptions=PARTIAL_HOURS_EXCEPTIONS,
            )
            week_rosters[w] = (roster_w, orphans_w, day_cols_w)

        # Build per-sub-period full rosters (e.g. June-only, July-only)
        sub_period_rosters = []
        for sp_label, sp_start, sp_end in (sub_periods or []):
            tc_sp    = tc[(tc["Date"] >= sp_start) & (tc["Date"] <= sp_end)]
            tc_oc_sp = tc_oncall[(tc_oncall["Date"] >= sp_start) & (tc_oncall["Date"] <= sp_end)]
            weeks_sp = sorted(tc_sp["week_start"].unique())
            if not weeks_sp:
                logger.warning("Sub-period %s: no data found, skipping.", sp_label)
                continue
            sp_thresh = len(weeks_sp) * hours_threshold
            res_sp = mappings.match_roster_to_timecard(resources, tc_sp, UID_OVERRIDES)
            _, _, _, _, full_sp, _ = report_generator.build_monthly_attendance(
                tc_sp, tc_oc_sp, res_sp, weeks_sp, sp_thresh, hours_threshold,
                partial_hours_exceptions=PARTIAL_HOURS_EXCEPTIONS,
            )
            sub_period_rosters.append((sp_label, full_sp, sp_thresh))
            logger.info(
                "Sub-period %s (%d wks, \u2265%dh): compliant=%d/%d",
                sp_label, len(weeks_sp), sp_thresh,
                int((full_sp["hours_logged"] >= sp_thresh).sum()), len(full_sp),
            )
        # Fixed filename so Power BI can always refresh from the same path.
        # The previous file is moved to history/ before being overwritten.
        label_safe  = month_label.replace(" ", "_").replace("/", "-")
        output_path = output_dir / f"compliance_{label_safe}.xlsx"
        rotate_to_history(output_path, timestamp)
        report_generator.write_monthly_attendance_report(
            output_path, full, ghost, incomplete, orphans, wk_cols,
            week_rosters, month_label, hours_threshold, month_threshold,
            sub_period_rosters=sub_period_rosters or None,
        )

    logger.info("Monthly attendance pipeline complete: %s", output_path)

    return {
        "roster": roster,
        "ghost": ghost,
        "incomplete": incomplete,
        "full": full,
        "orphans": orphans,
        "wk_cols": wk_cols,
        "week_rosters": week_rosters,
        "sub_period_rosters": sub_period_rosters,
        "output_path": output_path,
    }

def run_validation_only(
    replicon_dir: Path,
    timecard_paths: list[Path],
    approved_mapping_path: Optional[Path] = None,
) -> bool:
    """Validate all input files. Returns True if all checks pass, False otherwise."""
    logger.info("Running input validation only...")
    try:
        validators.validate_directory_not_empty(replicon_dir)
        validators.validate_files_exist(timecard_paths)
        if approved_mapping_path and approved_mapping_path.exists():
            validators.validate_files_exist([approved_mapping_path])

        replicon_raw = loaders.load_replicon_dir(replicon_dir)
        sn_raw = loaders.load_timecard_files(timecard_paths)

        validators.validate_replicon_columns(replicon_raw)
        validators.validate_servicenow_columns(sn_raw)
        validators.validate_not_empty(replicon_raw, "Replicon")
        validators.validate_not_empty(sn_raw, "ServiceNow")

        from src.transformations import clean_replicon, clean_servicenow
        replicon_clean = clean_replicon(replicon_raw)
        validators.validate_replicon_dates(replicon_clean)
        validators.validate_no_duplicate_keys(
            replicon_clean, ["date", "username", "task_code"], "Replicon"
        )

        logger.info("✅  All validation checks passed.")
        return True

    except validators.ValidationError as exc:
        logger.error("❌  Validation failed: %s", exc)
        return False
