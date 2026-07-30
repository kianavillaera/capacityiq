"""Input validators. All raise ValidationError with an actionable message."""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REPLICON_REQUIRED_COLS = {"Entry Date", "User Name", "Task Code"}
SERVICENOW_REQUIRED_COLS = {"Date", "User", "User ID", "Project ID", "Time worked"}
USER_MAPPING_REQUIRED_COLS = {"replicon_username", "servicenow_user_id", "match_status"}


class ValidationError(Exception):
    pass


def validate_files_exist(paths: list[Path]) -> None:
    missing = [str(p) for p in paths if not Path(p).exists()]
    if missing:
        raise ValidationError("Missing files:\n  " + "\n  ".join(missing))


def validate_directory_not_empty(directory: Path, suffix_filter: tuple = (".csv", ".xlsx")) -> None:
    directory = Path(directory)
    if not directory.exists():
        raise ValidationError(f"Directory does not exist: {directory}")
    if not any(p.suffix in suffix_filter and ":" not in p.name for p in directory.iterdir()):
        raise ValidationError(f"No {'/'.join(suffix_filter)} files in: {directory}")


def validate_replicon_columns(df: pd.DataFrame) -> None:
    _check_columns(df, REPLICON_REQUIRED_COLS, "Replicon")


def validate_servicenow_columns(df: pd.DataFrame) -> None:
    _check_columns(df, SERVICENOW_REQUIRED_COLS, "ServiceNow")


def validate_user_mapping_columns(df: pd.DataFrame) -> None:
    _check_columns(df, USER_MAPPING_REQUIRED_COLS, "User Mapping")


def validate_not_empty(df: pd.DataFrame, name: str) -> None:
    if df.empty:
        raise ValidationError(f"'{name}' is empty after loading.")


def validate_replicon_dates(df: pd.DataFrame) -> None:
    bad = df["date"].isna().sum()
    if bad:
        logger.warning("%d Replicon rows have unparseable dates (expected DD.MM.YYYY).", bad)


def validate_no_duplicate_keys(df: pd.DataFrame, key_cols: list[str], name: str) -> None:
    dupes = df.duplicated(subset=key_cols).sum()
    if dupes:
        logger.warning(
            "%d duplicate rows in '%s' on %s. Hours will be summed.",
            dupes,
            name,
            key_cols,
        )


def _check_columns(df: pd.DataFrame, required: set, source_name: str) -> None:
    missing = required - set(df.columns)
    if missing:
        raise ValidationError(
            f"{source_name} missing columns: {sorted(missing)}\nFound: {sorted(df.columns.tolist())}"
        )
    logger.info("%s columns OK.", source_name)
