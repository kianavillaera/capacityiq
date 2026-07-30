"""Tests for logging utilities."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import setup_logging, timer


class TestSetupLogging:
    def test_returns_logger(self):
        log = setup_logging()
        assert isinstance(log, logging.Logger)

    def test_console_handler_attached(self):
        log = setup_logging()
        assert any(isinstance(h, logging.StreamHandler) for h in log.handlers)

    def test_file_handler_created_when_log_dir_given(self, tmp_path):
        from logging.handlers import RotatingFileHandler

        log = setup_logging(log_dir=tmp_path)
        assert any(isinstance(h, RotatingFileHandler) for h in log.handlers)

    def test_log_file_exists_after_setup(self, tmp_path):
        setup_logging(log_dir=tmp_path)
        log_files = list(tmp_path.glob("pipeline_*.log"))
        assert len(log_files) == 1

    def test_calling_twice_does_not_duplicate_handlers(self):
        setup_logging()
        setup_logging()
        root = logging.getLogger()
        assert len(root.handlers) <= 2  # at most console + file


class TestTimer:
    def test_logs_start_and_end(self, caplog):
        with caplog.at_level(logging.INFO), timer("test_block"):
            pass
        messages = caplog.messages
        assert any("test_block" in m for m in messages)

    def test_yields_control(self):
        results = []
        with timer("x"):
            results.append(42)
        assert results == [42]

    def test_accepts_custom_logger(self, caplog):
        custom = logging.getLogger("custom_test")
        with caplog.at_level(logging.INFO, logger="custom_test"), timer("y", logger=custom):
            pass
        assert any("y" in m for m in caplog.messages)
