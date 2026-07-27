"""Logging setup and timing utilities."""

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path


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
