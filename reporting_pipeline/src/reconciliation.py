"""Reconciliation engine. Compares Replicon and ServiceNow at date x user x task_code grain."""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.mappings import _user_tables, _resolve_mapping
from src.transformations import clean_replicon, clean_servicenow

logger = logging.getLogger(__name__)

def classify_exception(row: pd.Series) -> tuple:
    """Return (exception_type, possible_cause) for one reconciliation row, or (None, None)."""
    if row["match_status"] == "user_mapping_required":
        return "user_mapping_required", "User could not be matched between systems"
    if row["match_status"] in ("review_required", "rejected"):
        return "user_mapping_required", "Fuzzy match below auto-accept threshold"
    if row["hours_replicon"] == 0 and row["hours_servicenow"] > 0:
        return "missing_in_replicon", "Time in ServiceNow but absent from Replicon"
    if row["hours_servicenow"] == 0 and row["hours_replicon"] > 0:
        return "missing_in_servicenow", "Time in Replicon but absent from ServiceNow"
    if row["variance"] != 0:
        return "hours_mismatch", "Hours differ between systems"
    return None, None

def run(
    replicon_raw: pd.DataFrame,
    sn_raw: pd.DataFrame,
    approved_mapping: Optional[pd.DataFrame] = None,
    auto_accept: float = 0.80,
    review_low: float = 0.70,
) -> dict:
    """Run the full reconciliation pipeline and return a dict of result DataFrames.

    SN data is scoped to the Replicon date window, matched users, and matching
    task codes before aggregation. Variance = SN hours - Replicon hours.
    """
    logger.info("Reconciliation started.")

    replicon = clean_replicon(replicon_raw)
    sn = clean_servicenow(sn_raw)

    if replicon.empty:
        raise ValueError(
            "Replicon extract contains no usable rows after cleaning. "
            "Check date format (DD.MM.YYYY) and that Entry Date / User Name columns are present."
        )

    replicon_users, sn_users = _user_tables(replicon, sn)
    user_mapping, dup_sn = _resolve_mapping(
        replicon_users, sn_users, approved_mapping, auto_accept, review_low
    )

    replicon_min_date = replicon["date"].min()
    replicon_max_date = replicon["date"].max()

    sn_in_window = sn[
        (sn["date"] >= replicon_min_date) & (sn["date"] <= replicon_max_date)
    ].copy()
    sn_excluded_date = len(sn) - len(sn_in_window)

    _accepted = user_mapping[
        user_mapping["match_status"].isin(["auto_accepted", "manual_match"])
    ][["replicon_username", "servicenow_user_id", "replicon_employee_id", "review_required"]]

    _replicon_sn_ids = set(_accepted["servicenow_user_id"].dropna())
    sn_in_window = sn_in_window[sn_in_window["sn_user_id"].isin(_replicon_sn_ids)]
    sn_excluded_user = (len(sn) - sn_excluded_date) - len(sn_in_window)

    _replicon_task_codes = set(replicon["task_code"].dropna())
    sn_in_window = sn_in_window[sn_in_window["task_code"].isin(_replicon_task_codes)]
    sn_excluded_task = (len(sn) - sn_excluded_date - sn_excluded_user) - len(sn_in_window)

    logger.info(
        "ServiceNow scoped: %d rows in window (date=-%d  user=-%d  task=-%d)",
        len(sn_in_window),
        sn_excluded_date,
        sn_excluded_user,
        sn_excluded_task,
    )

    replicon_mapped = replicon.merge(
        _accepted.rename(columns={"replicon_username": "username"}),
        on="username",
        how="left",
    )
    replicon_agg = (
        replicon_mapped.groupby(
            ["date", "servicenow_user_id", "task_code"], dropna=False
        )["hours"]
        .sum()
        .reset_index()
        .rename(columns={"hours": "hours_replicon"})
    )
    sn_agg = (
        sn_in_window.groupby(
            ["date", "sn_user_id", "task_code"], dropna=False
        )["hours"]
        .sum()
        .reset_index()
        .rename(columns={"sn_user_id": "servicenow_user_id", "hours": "hours_servicenow"})
    )

    # Ensure the join key has a consistent dtype on both sides before the outer
    # merge. When no users match, replicon_agg gets float64 (NaN) while sn_agg
    # keeps object dtype, which causes a TypeError in pandas.
    replicon_agg["servicenow_user_id"] = replicon_agg["servicenow_user_id"].astype(object)
    sn_agg["servicenow_user_id"] = sn_agg["servicenow_user_id"].astype(object)

    recon = replicon_agg.merge(
        sn_agg, on=["date", "servicenow_user_id", "task_code"], how="outer"
    )
    if len(recon) > len(replicon_agg) + len(sn_agg):
        raise RuntimeError(
            f"MERGE CARDINALITY ERROR: {len(recon):,} rows from "
            f"{len(replicon_agg):,} + {len(sn_agg):,} inputs. "
            "Check for duplicate (date, user, task_code) keys."
        )

    recon["hours_replicon"] = recon["hours_replicon"].fillna(0.0)
    recon["hours_servicenow"] = recon["hours_servicenow"].fillna(0.0)
    recon["variance"] = recon["hours_servicenow"] - recon["hours_replicon"]

    _uid_info = (
        user_mapping[["servicenow_user_id", "replicon_username", "replicon_employee_id"]]
        .drop_duplicates(subset=["servicenow_user_id"])
        .rename(columns={"replicon_username": "username", "replicon_employee_id": "employee_id"})
    )
    recon = recon.merge(_uid_info, on="servicenow_user_id", how="left")

    _status_info = user_mapping[
        ["servicenow_user_id", "match_status", "review_required"]
    ].drop_duplicates(subset=["servicenow_user_id"])
    recon = recon.merge(_status_info, on="servicenow_user_id", how="left")
    recon["match_status"] = recon["match_status"].fillna("user_mapping_required")
    recon["review_required"] = recon["review_required"].fillna(True)

    recon_table = (
        recon[
            [
                "date", "servicenow_user_id", "username", "employee_id",
                "task_code", "hours_replicon", "hours_servicenow", "variance",
                "match_status", "review_required",
            ]
        ]
        .rename(columns={"servicenow_user_id": "user_id"})
        .sort_values(["date", "user_id", "task_code"])
        .reset_index(drop=True)
    )

    recon_by_user = (
        recon_table.groupby(
            ["user_id", "username", "employee_id", "match_status", "review_required"],
            dropna=False,
        )
        .agg(
            hours_replicon=("hours_replicon", "sum"),
            hours_servicenow=("hours_servicenow", "sum"),
        )
        .reset_index()
        .sort_values("user_id")
        .reset_index(drop=True)
    )
    recon_by_user["variance"] = recon_by_user["hours_servicenow"] - recon_by_user["hours_replicon"]

    months = sorted(recon_table["date"].dt.to_period("M").dropna().unique())
    recon_by_month: dict = {}
    for month in months:
        _rows = recon_table[recon_table["date"].dt.to_period("M") == month]
        _m = (
            _rows.groupby(["user_id", "username", "employee_id"], dropna=False)
            .agg(
                hours_replicon=("hours_replicon", "sum"),
                hours_servicenow=("hours_servicenow", "sum"),
            )
            .reset_index()
            .sort_values("user_id")
            .reset_index(drop=True)
        )
        _m["variance"] = _m["hours_servicenow"] - _m["hours_replicon"]
        recon_by_month[str(month)] = _m

    _exc = recon_table[
        (recon_table["variance"] != 0)
        | recon_table["match_status"].isin(["user_mapping_required", "review_required"])
    ].copy()
    if not _exc.empty:
        _exc[["exception_type", "possible_cause"]] = _exc.apply(
            lambda r: pd.Series(classify_exception(r)), axis=1
        )
    else:
        _exc["exception_type"] = pd.Series(dtype=object)
        _exc["possible_cause"] = pd.Series(dtype=object)
    _exc["percentage_difference"] = np.where(
        _exc["hours_replicon"] != 0,
        (_exc["variance"] / _exc["hours_replicon"] * 100).round(1),
        np.nan,
    )
    exception_report = _exc[
        [
            "date", "user_id", "username", "employee_id", "task_code",
            "hours_replicon", "hours_servicenow", "variance",
            "percentage_difference", "exception_type", "possible_cause",
        ]
    ].reset_index(drop=True)

    summary_data = {
        "replicon_window_start": str(replicon_min_date.date()),
        "replicon_window_end": str(replicon_max_date.date()),
        "total_replicon_rows_loaded": len(replicon_raw),
        "total_servicenow_rows_loaded": len(sn_raw),
        "total_servicenow_rows_in_window": len(sn_in_window),
        "total_servicenow_rows_excluded_by_date": sn_excluded_date,
        "total_servicenow_rows_excluded_by_user": sn_excluded_user,
        "total_servicenow_rows_excluded_by_task": sn_excluded_task,
        "total_replicon_hours_before_aggregation": round(replicon["hours"].sum(), 2),
        "total_servicenow_hours_in_window": round(sn_in_window["hours"].sum(), 2),
        "total_replicon_hours_after_aggregation": round(replicon_agg["hours_replicon"].sum(), 2),
        "total_servicenow_hours_after_aggregation": round(sn_agg["hours_servicenow"].sum(), 2),
        "total_users_matched": int(user_mapping["match_status"].eq("auto_accepted").sum()),
        "total_users_unmatched": int(
            user_mapping["match_status"].isin(["no_match", "rejected"]).sum()
        ),
        "total_duplicate_candidates": int(dup_sn.sum()) if not dup_sn.empty else 0,
        "total_records_compared": len(recon_table),
        "total_discrepancies": int((recon_table["variance"] != 0).sum()),
        "net_variance": round(recon_table["variance"].sum(), 2),
    }
    summary_df = (
        pd.Series(summary_data)
        .rename("value")
        .reset_index()
        .rename(columns={"index": "metric"})
    )

    logger.info(
        "Reconciliation complete: %d records compared, %d discrepancies, net variance %.2f h",
        len(recon_table),
        int((recon_table["variance"] != 0).sum()),
        recon_table["variance"].sum(),
    )

    return {
        "replicon": replicon,
        "sn": sn,
        "sn_in_window": sn_in_window,
        "user_mapping": user_mapping,
        "replicon_agg": replicon_agg,
        "sn_agg": sn_agg,
        "recon_table": recon_table,
        "recon_by_user": recon_by_user,
        "recon_by_month": recon_by_month,
        "exception_report": exception_report,
        "summary": summary_df,
        "replicon_min_date": replicon_min_date,
        "replicon_max_date": replicon_max_date,
        "sn_excluded_date": sn_excluded_date,
        "sn_excluded_user": sn_excluded_user,
        "sn_excluded_task": sn_excluded_task,
        "dup_sn": dup_sn,
    }
