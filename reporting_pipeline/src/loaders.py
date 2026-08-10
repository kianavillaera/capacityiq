"""Data loaders. Returns uncleaned DataFrames for the pipeline."""

import base64
import io
import logging
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _prep_replicon(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    if "Hours Worked" in df.columns and "Hours" not in df.columns:
        df = df.rename(columns={"Hours Worked": "Hours"})
    # Some exports only set User Name on the first row per user (merged-cell style).
    if "User Name" in df.columns:
        df["User Name"] = df["User Name"].ffill()
    df["_source_file"] = source_name
    return df


def load_replicon_dir(directory: str | Path) -> pd.DataFrame:
    directory = Path(directory)
    paths = sorted(
        p for p in directory.iterdir() if p.suffix in (".csv", ".xlsx") and ":" not in p.name
    )
    if not paths:
        raise ValueError(f"No CSV or XLSX files found in: {directory}")
    frames = [
        _prep_replicon(
            pd.read_csv(p, dtype=str) if p.suffix == ".csv" else pd.read_excel(p, dtype=str),
            p.name,
        )
        for p in paths
    ]
    result = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d Replicon rows from %d file(s)", len(result), len(paths))
    return result


def load_replicon_bytes(file_bytes_list: list[tuple[str, bytes]]) -> pd.DataFrame:
    frames = [
        _prep_replicon(pd.read_csv(io.BytesIO(data), dtype=str), name)
        for name, data in file_bytes_list
    ]
    result = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d Replicon rows from %d file(s)", len(result), len(frames))
    return result


def load_timecard_files(paths: Sequence[str | Path]) -> pd.DataFrame:
    if not paths:
        raise ValueError("At least one time-card file path is required.")
    frames: list[pd.DataFrame] = []
    for p in paths:
        p = Path(p)
        engine = "xlrd" if p.suffix == ".xls" else None
        with pd.ExcelFile(p, engine=engine) as xl:
            frames.extend(xl.parse(s).assign(_sheet=s) for s in xl.sheet_names)
    result = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d ServiceNow rows from %d file(s)", len(result), len(paths))
    return result


def load_timecard_bytes(file_bytes: bytes) -> pd.DataFrame:
    with pd.ExcelFile(io.BytesIO(file_bytes)) as xl:
        return pd.concat([xl.parse(s).assign(_sheet=s) for s in xl.sheet_names], ignore_index=True)


def load_resources(path: str | Path, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name)
    logger.info("Loaded %d resources from %s", len(df), Path(path).name)
    return df


def load_approved_mapping(path: str | Path) -> "pd.DataFrame | None":
    path = Path(path)
    if not path.exists():
        return None
    df = pd.read_excel(path)
    logger.info("Loaded approved mapping from %s (%d rows)", path.name, len(df))
    return df


def _open_excel_sheets(p: Path) -> dict:
    """Open an Excel file returning {sheet_name: DataFrame}. Handles .xls files
    that are base64-encoded OLE2 (a known ServiceNow export quirk)."""
    if p.suffix.lower() == ".xls":
        with open(p, "rb") as f:
            raw = f.read(8)
        # OLE2 magic starts with D0 CF; if missing, try base64 decode
        if raw[:2] != b"\xd0\xcf":
            try:
                decoded = base64.b64decode(open(p, "rb").read())
                return pd.read_excel(io.BytesIO(decoded), sheet_name=None, engine="xlrd")
            except Exception:
                pass
        try:
            return pd.read_excel(p, sheet_name=None, engine="xlrd")
        except Exception:
            return pd.read_excel(p, sheet_name=None, engine="openpyxl")
    return pd.read_excel(p, sheet_name=None)


def load_timecard_multi(paths: Sequence[str | Path]) -> pd.DataFrame:
    """Load multiple time-card files for the FTE pipeline. Adds week_start column."""
    frames = []
    for p in paths:
        p = Path(p)
        sheets = _open_excel_sheets(p)
        df = pd.concat(sheets.values(), ignore_index=True)
        df["_source_file"] = p.name
        frames.append(df)
    result = pd.concat(frames, ignore_index=True)
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["week_start"] = (
        result["Date"] - pd.to_timedelta(result["Date"].dt.weekday, unit="D")
    ).dt.normalize()
    return result
