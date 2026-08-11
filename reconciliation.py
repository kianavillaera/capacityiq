import io
import re
from typing import Optional

import numpy as np
import pandas as pd

try:
    import jellyfish

    HAS_JELLYFISH = True
except ImportError:
    jellyfish = None
    HAS_JELLYFISH = False

try:
    from rapidfuzz import fuzz as _rf

    HAS_RAPIDFUZZ = True
except ImportError:
    _rf = None
    HAS_RAPIDFUZZ = False


def clean_replicon(df: pd.DataFrame) -> pd.DataFrame:
    if "_source_file" not in df.columns:
        df = df.copy()
        df["_source_file"] = "unknown"
    df = df.dropna(subset=["Entry Date", "User Name"]).copy()
    df = df.rename(
        columns={
            "Entry Date": "date",
            "User Name": "username",
            "Employee ID": "employee_id",
            "Project Code": "project_code",
            "Task Code": "task_code",
            "Hours": "hours",
        }
    )
    df["date"] = pd.to_datetime(df["date"], format="%d.%m.%Y", errors="coerce")
    # Blanks are submitted entries with no hours — treat as zero
    df["hours"] = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0)
    df["employee_id"] = (
        df["employee_id"]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
        .replace("nan", None)
    )
    return df[
        [
            "date",
            "username",
            "employee_id",
            "project_code",
            "task_code",
            "hours",
            "_source_file",
        ]
    ]


def clean_servicenow(df: pd.DataFrame) -> pd.DataFrame:
    if "_sheet" not in df.columns:
        df = df.copy()
        df["_sheet"] = "unknown"
    df = df.rename(
        columns={
            "Date": "date",
            "User": "sn_user",
            "User ID": "sn_user_id",
            "Project ID": "task_code",
            "Time worked": "hours",
        }
    )
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["hours"] = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0)
    df["sn_user_id"] = df["sn_user_id"].astype(str).str.strip()
    df["sn_user"] = df["sn_user"].astype(str).str.strip()
    df["task_code"] = df["task_code"].astype(str).str.strip()
    return df[["date", "sn_user", "sn_user_id", "task_code", "hours", "_sheet"]]


def normalise_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = re.sub(r"\(.*?\)", "", name)
    if "," in name:
        last, first = name.split(",", 1)
        name = first.strip() + " " + last.strip()
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def normalise_uid(uid: str) -> str:
    if not isinstance(uid, str):
        return ""
    uid = re.sub(r"@.*$", "", uid)
    uid = uid.lower().strip()
    uid = re.sub(r"[._\-]", " ", uid)
    uid = re.sub(r"\s+", " ", uid).strip()
    return uid


def _score_pair(a: str, b: str) -> tuple:
    jw = jellyfish.jaro_winkler_similarity(a, b) if HAS_JELLYFISH and jellyfish else 0.0
    ts = _rf.token_sort_ratio(a, b) / 100 if HAS_RAPIDFUZZ and _rf else 0.0
    tst = _rf.token_set_ratio(a, b) / 100 if HAS_RAPIDFUZZ and _rf else 0.0
    return jw, ts, tst


def _best_score(rep_norm: str, sn_norm: str, sn_uid: str) -> tuple:
    jw1, ts1, tst1 = _score_pair(rep_norm, sn_norm)
    jw2, ts2, tst2 = _score_pair(rep_norm, sn_uid)
    jw, ts, tst = max(jw1, jw2), max(ts1, ts2), max(tst1, tst2)
    if HAS_JELLYFISH and HAS_RAPIDFUZZ:
        final = 0.35 * jw + 0.30 * ts + 0.35 * tst
    elif HAS_JELLYFISH:
        final = jw
    elif HAS_RAPIDFUZZ:
        final = 0.5 * ts + 0.5 * tst
    else:
        final = 0.0
    return jw, ts, tst, final


def build_user_mapping(
    rep_df: pd.DataFrame,
    sn_df: pd.DataFrame,
    auto_accept: float = 0.80,
    review_low: float = 0.70,
) -> pd.DataFrame:
    sn_by_name = dict(zip(sn_df["norm_name"], sn_df["sn_user_id"]))
    sn_by_uid = dict(zip(sn_df["norm_uid"], sn_df["sn_user_id"]))

    rows = []
    for _, rep in rep_df.iterrows():
        rn = rep["norm_name"]
        record = dict(
            replicon_username=rep["username"],
            replicon_employee_id=rep["employee_id"],
            servicenow_user_id=None,
            servicenow_name=None,
            match_method="no_match",
            jaro_winkler_score=0.0,
            token_sort_score=0.0,
            token_set_score=0.0,
            final_score=0.0,
            review_required=True,
            match_status="no_match",
            notes="",
        )

        if rn in sn_by_name:
            uid = sn_by_name[rn]
            record.update(
                servicenow_user_id=uid,
                match_method="exact_name",
                jaro_winkler_score=1.0,
                token_sort_score=1.0,
                token_set_score=1.0,
                final_score=1.0,
                review_required=False,
                match_status="auto_accepted",
            )
        elif rn in sn_by_uid:
            uid = sn_by_uid[rn]
            record.update(
                servicenow_user_id=uid,
                match_method="exact_uid",
                jaro_winkler_score=1.0,
                token_sort_score=1.0,
                token_set_score=1.0,
                final_score=1.0,
                review_required=False,
                match_status="auto_accepted",
            )
        else:
            candidates = []
            for _, sn_row in sn_df.iterrows():
                jw, ts, tst, final = _best_score(
                    rn, sn_row["norm_name"], sn_row["norm_uid"]
                )
                if final >= review_low * 0.70:
                    candidates.append(
                        (final, jw, ts, tst, sn_row["sn_user_id"], sn_row["sn_user"])
                    )
            if candidates:
                candidates.sort(reverse=True)
                final, jw, ts, tst, uid, sn_name = candidates[0]
                if final >= auto_accept:
                    status, review, keep = "auto_accepted", False, True
                elif final >= review_low:
                    status, review, keep = "review_required", True, True
                else:
                    status, review, keep = "rejected", True, False
                    uid, sn_name = None, None
                record.update(
                    servicenow_user_id=uid if keep else None,
                    servicenow_name=sn_name if keep else None,
                    match_method="fuzzy",
                    jaro_winkler_score=round(jw, 4),
                    token_sort_score=round(ts, 4),
                    token_set_score=round(tst, 4),
                    final_score=round(final, 4),
                    review_required=review,
                    match_status=status,
                )

        if record["servicenow_user_id"] and not record["servicenow_name"]:
            _row = sn_df[sn_df["sn_user_id"] == record["servicenow_user_id"]]
            if not _row.empty:
                record["servicenow_name"] = _row.iloc[0]["sn_user"]
        rows.append(record)

    return pd.DataFrame(rows)


def _user_tables(replicon: pd.DataFrame, sn: pd.DataFrame) -> tuple:
    replicon_users = (
        replicon[["username", "employee_id"]]
        .drop_duplicates(subset=["username"])
        .reset_index(drop=True)
        .assign(norm_name=lambda d: d["username"].map(normalise_name))
    )
    sn_users = (
        sn[["sn_user", "sn_user_id"]]
        .drop_duplicates(subset=["sn_user_id"])
        .reset_index(drop=True)
        .assign(
            norm_name=lambda d: d["sn_user"].map(normalise_name),
            norm_uid=lambda d: d["sn_user_id"].map(normalise_uid),
        )
    )
    return replicon_users, sn_users


def _resolve_mapping(
    replicon_users: pd.DataFrame,
    sn_users: pd.DataFrame,
    approved: Optional[pd.DataFrame],
    auto_accept: float,
    review_low: float,
) -> tuple:
    if approved is not None:
        mapping = approved.copy()
        unmatched = replicon_users[
            ~replicon_users["username"].isin(set(mapping["replicon_username"]))
        ]
        if not unmatched.empty:
            mapping = pd.concat(
                [
                    mapping,
                    build_user_mapping(unmatched, sn_users, auto_accept, review_low),
                ],
                ignore_index=True,
            )
    else:
        mapping = build_user_mapping(replicon_users, sn_users, auto_accept, review_low)

    dup_sn = (
        mapping[mapping["servicenow_user_id"].notna()]
        .groupby("servicenow_user_id")["replicon_username"]
        .count()
        .loc[lambda x: x > 1]
    )
    if not dup_sn.empty:
        mapping.loc[mapping["servicenow_user_id"].isin(dup_sn.index), "notes"] = (
            "duplicate_user_candidate"
        )

    return mapping, dup_sn


def match_users(
    replicon: pd.DataFrame,
    sn: pd.DataFrame,
    approved: Optional[pd.DataFrame] = None,
    auto_accept: float = 0.80,
    review_low: float = 0.70,
) -> pd.DataFrame:
    replicon_users, sn_users = _user_tables(replicon, sn)
    mapping, _ = _resolve_mapping(
        replicon_users, sn_users, approved, auto_accept, review_low
    )
    return mapping


def classify_exception(row) -> tuple:
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
    ][
        [
            "replicon_username",
            "servicenow_user_id",
            "replicon_employee_id",
            "review_required",
        ]
    ]

    _replicon_sn_ids = set(_accepted["servicenow_user_id"].dropna())
    sn_in_window = sn_in_window[sn_in_window["sn_user_id"].isin(_replicon_sn_ids)]
    sn_excluded_user = (len(sn) - sn_excluded_date) - len(sn_in_window)

    _replicon_task_codes = set(replicon["task_code"].dropna())
    sn_in_window = sn_in_window[sn_in_window["task_code"].isin(_replicon_task_codes)]
    sn_excluded_task = (len(sn) - sn_excluded_date - sn_excluded_user) - len(
        sn_in_window
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
        sn_in_window.groupby(["date", "sn_user_id", "task_code"], dropna=False)["hours"]
        .sum()
        .reset_index()
        .rename(
            columns={"sn_user_id": "servicenow_user_id", "hours": "hours_servicenow"}
        )
    )

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
        user_mapping[
            ["servicenow_user_id", "replicon_username", "replicon_employee_id"]
        ]
        .drop_duplicates(subset=["servicenow_user_id"])
        .rename(
            columns={
                "replicon_username": "username",
                "replicon_employee_id": "employee_id",
            }
        )
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
                "date",
                "servicenow_user_id",
                "username",
                "employee_id",
                "task_code",
                "hours_replicon",
                "hours_servicenow",
                "variance",
                "match_status",
                "review_required",
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
    recon_by_user["variance"] = (
        recon_by_user["hours_servicenow"] - recon_by_user["hours_replicon"]
    )

    months = sorted(recon_table["date"].dt.to_period("M").dropna().unique())
    recon_by_month = {}
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
    _exc[["exception_type", "possible_cause"]] = _exc.apply(
        lambda r: pd.Series(classify_exception(r)), axis=1
    )
    _exc["percentage_difference"] = np.where(
        _exc["hours_replicon"] != 0,
        (_exc["variance"] / _exc["hours_replicon"] * 100).round(1),
        np.nan,
    )
    exception_report = _exc[
        [
            "date",
            "user_id",
            "username",
            "employee_id",
            "task_code",
            "hours_replicon",
            "hours_servicenow",
            "variance",
            "percentage_difference",
            "exception_type",
            "possible_cause",
        ]
    ].reset_index(drop=True)

    summary = {
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
        "total_replicon_hours_after_aggregation": round(
            replicon_agg["hours_replicon"].sum(), 2
        ),
        "total_servicenow_hours_after_aggregation": round(
            sn_agg["hours_servicenow"].sum(), 2
        ),
        "total_users_matched": int(
            user_mapping["match_status"].eq("auto_accepted").sum()
        ),
        "total_users_unmatched": int(
            user_mapping["match_status"].isin(["no_match", "rejected"]).sum()
        ),
        "total_duplicate_candidates": int(dup_sn.sum()) if not dup_sn.empty else 0,
        "total_records_compared": len(recon_table),
        "total_discrepancies": int((recon_table["variance"] != 0).sum()),
        "net_variance": round(recon_table["variance"].sum(), 2),
    }
    summary_df = (
        pd.Series(summary)
        .rename("value")
        .reset_index()
        .rename(columns={"index": "metric"})
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


def to_excel_bytes(results: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        results["recon_table"].to_excel(writer,   sheet_name="detail",  index=False)
        results["recon_by_user"].to_excel(writer, sheet_name="by_user", index=False)
        for month, df in results["recon_by_month"].items():
            df.to_excel(writer, sheet_name=month, index=False)
    return buf.getvalue()
