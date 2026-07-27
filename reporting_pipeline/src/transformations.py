"""Data cleaning and type coercion. Inputs are raw DataFrames; outputs are ready for processing."""

import logging
import unicodedata

import pandas as pd

logger = logging.getLogger(__name__)


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()


def clean_replicon(df: pd.DataFrame) -> pd.DataFrame:
    if "_source_file" not in df.columns:
        df = df.copy()
        df["_source_file"] = "unknown"

    df = df.dropna(subset=["Entry Date", "User Name"]).copy()
    df = df.rename(columns={
        "Entry Date": "date", "User Name": "username", "Employee ID": "employee_id",
        "Project Code": "project_code", "Task Code": "task_code", "Hours": "hours",
    })
    df["date"] = pd.to_datetime(df["date"], format="%d.%m.%Y", errors="coerce")
    # Blank hours = submitted entry with no hours logged.
    df["hours"] = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0)
    df["employee_id"] = (
        df["employee_id"].astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
        .replace("nan", None)
    )
    logger.info("Replicon cleaned: %d rows, %d users, %.1f h", len(df), df["username"].nunique(), df["hours"].sum())
    return df[["date", "username", "employee_id", "project_code", "task_code", "hours", "_source_file"]]


def clean_servicenow(df: pd.DataFrame) -> pd.DataFrame:
    if "_sheet" not in df.columns:
        df = df.copy()
        df["_sheet"] = "unknown"

    df = df.rename(columns={
        "Date": "date", "User": "sn_user", "User ID": "sn_user_id",
        "Project ID": "task_code", "Time worked": "hours",
    })
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["hours"] = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0)
    df["sn_user_id"] = df["sn_user_id"].astype(str).str.strip()
    df["sn_user"] = df["sn_user"].astype(str).str.strip()
    df["task_code"] = df["task_code"].astype(str).str.strip()
    logger.info("SN cleaned: %d rows, %d users, %.1f h", len(df), df["sn_user_id"].nunique(), df["hours"].sum())
    return df[["date", "sn_user", "sn_user_id", "task_code", "hours", "_sheet"]]


def clean_timecard_for_attendance(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into (regular, on-call). On-call = 'On-Call' in Rate type."""
    from src.mappings import normalise_name

    df = df.drop_duplicates(keep="last").copy()
    df["Time worked"] = pd.to_numeric(df["Time worked"], errors="coerce").fillna(0)
    df["is_gen"] = df["Task"].astype(str).str.startswith("GEN")

    is_oncall = df["Rate type"].astype(str).str.contains("On-Call", case=False, na=False)
    tc, tc_oncall = df[~is_oncall].copy(), df[is_oncall].copy()

    for frame in (tc, tc_oncall):
        if "User ID" in frame.columns:
            frame["_uid"] = frame["User ID"].str.strip().str.lower()
        if "User" in frame.columns:
            frame["_norm"] = frame["User"].map(lambda n: normalise_name(_ascii(n)))

    logger.info("Timecard: %d rows, %d on-call", len(tc), len(tc_oncall))
    return tc, tc_oncall


def clean_resources(df: pd.DataFrame, uid_overrides: dict | None = None) -> pd.DataFrame:
    from src.mappings import normalise_name

    df = df.copy()
    df["Name"] = df["Name"].astype(str).str.strip()
    df["_uid"] = df["Email"].str.extract(r"^([^@]+)@", expand=False).str.lower()
    df["_norm"] = df["Name"].map(lambda n: normalise_name(_ascii(n)))
    df["tc_uid"] = None
    logger.info("Resources: %d roster members", len(df))
    return df
