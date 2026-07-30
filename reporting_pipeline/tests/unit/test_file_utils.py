"""Unit tests for rotate_to_history and publish_to_sharepoint (added this session)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.utils import publish_to_sharepoint, rotate_to_history


class TestRotateToHistory:
    def test_existing_file_moved_to_history_subdir(self, tmp_path):
        f = tmp_path / "report.xlsx"
        f.write_bytes(b"data")
        rotate_to_history(f, timestamp="20260101_120000")
        assert not f.exists()
        assert (tmp_path / "history" / "report_20260101_120000.xlsx").exists()

    def test_missing_file_is_noop(self, tmp_path):
        rotate_to_history(tmp_path / "nonexistent.xlsx", timestamp="20260101_120000")
        # no exception, no history dir created
        assert not (tmp_path / "history").exists()

    def test_history_dir_created_when_absent(self, tmp_path):
        f = tmp_path / "x.xlsx"
        f.write_bytes(b"x")
        rotate_to_history(f, timestamp="20260101_120000")
        assert (tmp_path / "history").is_dir()

    def test_archived_name_contains_stem_and_timestamp(self, tmp_path):
        f = tmp_path / "compliance_Jun-Jul_2026.xlsx"
        f.write_bytes(b"x")
        rotate_to_history(f, timestamp="20260730_103828")
        archived = tmp_path / "history" / "compliance_Jun-Jul_2026_20260730_103828.xlsx"
        assert archived.exists()

    def test_preserves_file_content(self, tmp_path):
        content = b"spreadsheet content"
        f = tmp_path / "out.xlsx"
        f.write_bytes(content)
        rotate_to_history(f, timestamp="20260101_120000")
        archived = next((tmp_path / "history").glob("*.xlsx"))
        assert archived.read_bytes() == content


class TestPublishToSharepoint:
    def test_copies_file_to_destination(self, tmp_path):
        src = tmp_path / "src" / "report.xlsx"
        src.parent.mkdir()
        src.write_bytes(b"content")
        sp_dir = tmp_path / "sp"
        sp_dir.mkdir()
        result = publish_to_sharepoint(src, sp_dir, timestamp="20260101_120000")
        assert result == sp_dir / "report.xlsx"
        assert (sp_dir / "report.xlsx").read_bytes() == b"content"

    def test_rotates_existing_sharepoint_copy(self, tmp_path):
        src = tmp_path / "src" / "report.xlsx"
        src.parent.mkdir()
        src.write_bytes(b"new")
        sp_dir = tmp_path / "sp"
        sp_dir.mkdir()
        (sp_dir / "report.xlsx").write_bytes(b"old")
        publish_to_sharepoint(src, sp_dir, timestamp="20260101_120000")
        assert (sp_dir / "report.xlsx").read_bytes() == b"new"
        assert (sp_dir / "history" / "report_20260101_120000.xlsx").read_bytes() == b"old"

    def test_returns_none_when_dir_is_none(self, tmp_path):
        src = tmp_path / "report.xlsx"
        src.write_bytes(b"x")
        assert publish_to_sharepoint(src, None) is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        src = tmp_path / "report.xlsx"
        src.write_bytes(b"x")
        result = publish_to_sharepoint(src, tmp_path / "nonexistent_sp_dir")
        assert result is None

    def test_returns_none_on_oserror(self, tmp_path, monkeypatch):
        import shutil

        src = tmp_path / "src" / "report.xlsx"
        src.parent.mkdir()
        src.write_bytes(b"x")
        sp_dir = tmp_path / "sp"
        sp_dir.mkdir()
        monkeypatch.setattr(shutil, "copy2", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
        result = publish_to_sharepoint(src, sp_dir, timestamp="ts")
        assert result is None
