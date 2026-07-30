"""Logging setup, timing utilities, and file-rotation helpers."""

import logging
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    if log_dir is not None:
        from logging.handlers import RotatingFileHandler
        from datetime import datetime
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)
        root.info("Log file: %s", log_file)

    return root


@contextmanager
def timer(label: str, logger: logging.Logger | None = None):
    _log = logger or logging.getLogger(__name__)
    start = time.perf_counter()
    _log.info("Starting: %s", label)
    try:
        yield
    finally:
        _log.info("Done: %s (%.2f s)", label, time.perf_counter() - start)


def rotate_to_history(path: Path, timestamp: str | None = None) -> None:
    """If *path* exists, move it to a ``history/`` subfolder with a timestamp suffix.

    This lets output files keep a fixed name (for Power BI refresh) while
    preserving every previous version in the history folder.

    Example::

        before: outputs/reports/compliance_Jun-Jul_2026.xlsx
        after:  outputs/reports/history/compliance_Jun-Jul_2026_20260730_103828.xlsx
                outputs/reports/compliance_Jun-Jul_2026.xlsx   ← new file written here
    """
    path = Path(path)
    if not path.exists():
        return
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    history_dir = path.parent / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    dest = history_dir / f"{path.stem}_{ts}{path.suffix}"
    path.rename(dest)
    logger.info("Archived to history: %s → history/%s", path.name, dest.name)


def publish_to_sharepoint(local_path: Path,
                           sharepoint_dir: "Path | None",
                           timestamp: str | None = None) -> "Path | None":
    """Copy *local_path* to *sharepoint_dir*, archiving any existing file first.

    Applies the same history-rotation logic as :func:`rotate_to_history` so
    the SharePoint folder always contains the latest file under a fixed name
    while previous versions are preserved in ``sharepoint_dir/history/``.

    Returns the destination path on success, or ``None`` if *sharepoint_dir*
    is not configured or not accessible (logged as a warning, never raises).
    """
    import shutil

    if not sharepoint_dir:
        return None
    sharepoint_dir = Path(sharepoint_dir)
    if not sharepoint_dir.exists():
        logger.warning(
            "SharePoint dir not accessible — skipping publish: %s", sharepoint_dir
        )
        return None

    dest = sharepoint_dir / Path(local_path).name
    rotate_to_history(dest, timestamp)          # archive old copy first

    try:
        shutil.copy2(local_path, dest)
        logger.info("Published to SharePoint: %s", dest)
        return dest
    except Exception as exc:
        logger.warning("SharePoint publish failed (%s): %s", exc, dest)
        return None
