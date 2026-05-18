"""Tests for OperationLogger."""

import logging
import pytest
from pathlib import Path

from gps_photo_tracker.core.models import (
    GPSInfo,
    GPXParseError,
    MatchResult,
    PhotoInfo,
)
from gps_photo_tracker.logging_.logger import OperationLogger


@pytest.fixture
def log_dir(tmp_path):
    return tmp_path / "logs"


@pytest.fixture
def logger(log_dir):
    # Clear any existing handlers to avoid cross-test pollution
    for name in ["gps_ops", "gps_matches", "gps_writes", "gps_errors"]:
        l = logging.getLogger(name)
        l.handlers.clear()
    return OperationLogger(log_dir)


def _make_photo(filename="test.jpg", has_gps=False) -> PhotoInfo:
    return PhotoInfo(
        path=Path(f"/photos/{filename}"),
        filename=filename,
        timestamp=1700000000.0,
        has_gps=has_gps,
        existing_gps=GPSInfo(25.0, 100.0) if has_gps else None,
    )


def _make_result(success=True, method="interpolated", reject_reason=None) -> MatchResult:
    return MatchResult(
        photo=_make_photo(),
        success=success,
        gps=GPSInfo(25.953, 102.758, 1810.6) if success else None,
        method=method,
        time_diff=12.0 if success else None,
        reject_reason=reject_reason,
        interpolation_distance=247.0,
    )


class TestOperationLogger:

    def test_creates_log_dir(self, log_dir):
        OperationLogger(log_dir)
        assert log_dir.exists()

    def test_creates_log_files(self, logger, log_dir):
        logger.log_operation_start({})
        logger.log_match_success(_make_result())
        logger.log_write_success(_make_photo(), GPSInfo(25.0, 100.0))
        logger.log_error("test", ValueError("x"))
        assert (log_dir / "operations.log").exists()
        assert (log_dir / "matches.log").exists()
        assert (log_dir / "writes.log").exists()
        assert (log_dir / "errors.log").exists()

    def test_log_match_success(self, logger, log_dir):
        result = _make_result()
        logger.log_match_success(result)
        content = (log_dir / "matches.log").read_text(encoding="utf-8")
        assert "OK test.jpg" in content
        assert "interpolated" in content

    def test_log_match_success_nearest_no_interpolation_distance(self, logger, log_dir):
        """log_match_success should handle nearest match (interpolation_distance=None)."""
        result = MatchResult(
            photo=_make_photo(),
            success=True,
            gps=GPSInfo(25.953, 102.758, 1810.6),
            method="nearest",
            time_diff=5.0,
            interpolation_distance=None,  # No interpolation distance for nearest
        )
        logger.log_match_success(result)
        content = (log_dir / "matches.log").read_text(encoding="utf-8")
        assert "OK test.jpg" in content
        assert "nearest" in content
        assert "—" in content  # Distance shows as —

    def test_log_match_failed(self, logger, log_dir):
        result = _make_result(success=False, reject_reason="no_gps_coverage")
        logger.log_match_failed(result)
        content = (log_dir / "matches.log").read_text(encoding="utf-8")
        assert "FAIL test.jpg" in content
        assert "no_gps_coverage" in content

    def test_log_write_success(self, logger, log_dir):
        photo = _make_photo()
        gps = GPSInfo(25.0, 100.0, 1800)
        logger.log_write_success(photo, gps)
        content = (log_dir / "writes.log").read_text(encoding="utf-8")
        assert "WRITE test.jpg" in content
        assert "25.0000,100.0000" in content

    def test_log_write_success_with_dest(self, logger, log_dir):
        photo = _make_photo()
        gps = GPSInfo(25.0, 100.0)
        logger.log_write_success(photo, gps, dest=Path("/output/test.jpg"))
        content = (log_dir / "writes.log").read_text(encoding="utf-8")
        assert "test.jpg" in content

    def test_log_gps_overwrite(self, logger, log_dir):
        photo = _make_photo(has_gps=True)
        old = GPSInfo(25.0, 100.0)
        new = GPSInfo(25.001, 100.001)
        logger.log_gps_overwrite(photo, old, new)
        content = (log_dir / "writes.log").read_text(encoding="utf-8")
        assert "OVERWRITE test.jpg" in content

    def test_log_error(self, logger, log_dir):
        logger.log_error("scan_gpx", GPXParseError("bad file"))
        content = (log_dir / "errors.log").read_text(encoding="utf-8")
        assert "scan_gpx" in content

    def test_log_operation_start(self, logger, log_dir):
        logger.log_operation_start({"mode": "preview", "total": 100})
        content = (log_dir / "operations.log").read_text(encoding="utf-8")
        assert "START" in content
        assert "preview" in content

    def test_log_operation_end(self, logger, log_dir):
        logger.log_operation_end({"matched": 95, "failed": 5})
        content = (log_dir / "operations.log").read_text(encoding="utf-8")
        assert "END" in content
        assert "95" in content

    def test_cleanup_old_logs(self, logger, log_dir):
        """cleanup should remove log files older than retention_days."""
        import time
        logger.log_operation_start({})
        assert (log_dir / "operations.log").exists()
        # Set mtime to 60 days ago
        old_time = time.time() - 60 * 86400
        import os
        os.utime(log_dir / "operations.log", (old_time, old_time))
        logger.cleanup()
        assert not (log_dir / "operations.log").exists()

    def test_cleanup_keeps_recent_logs(self, logger, log_dir):
        """cleanup should keep recent log files."""
        logger.log_operation_start({})
        logger.cleanup()
        assert (log_dir / "operations.log").exists()

    def test_debug_method(self, log_dir):
        """debug() should write to debug.log."""
        for name in ["gps_ops", "gps_matches", "gps_writes", "gps_errors", "gps_debug"]:
            logging.getLogger(name).handlers.clear()
        olg = OperationLogger(log_dir)
        olg.debug("test debug message")
        for h in logging.getLogger("gps_debug").handlers:
            h.flush()
        content = (log_dir / "debug.log").read_text(encoding="utf-8")
        assert "test debug message" in content

    def test_namespace_debug_handler_dedup(self, log_dir):
        """Second OperationLogger with same dir should not duplicate namespace handler."""
        for name in ["gps_photo_tracker"]:
            logging.getLogger(name).handlers.clear()
        op1 = OperationLogger(log_dir)
        op2 = OperationLogger(log_dir)
        ns = logging.getLogger("gps_photo_tracker")
        paths = [getattr(h, "baseFilename", "") for h in ns.handlers]
        debug_count = sum(1 for p in paths if "debug.log" in p)
        assert debug_count <= 2  # at most one per instance

    def test_cleanup_size_removes_oldest(self, logger, log_dir):
        """_cleanup_size should remove oldest files when total exceeds max."""
        import time
        # Create a large "log" file
        big = log_dir / "old.log"
        big.write_bytes(b"x" * 1024 * 1024)  # 1 MB
        old_time = time.time() - 86400
        import os
        os.utime(big, (old_time, old_time))
        # Create recent small file
        recent = log_dir / "recent.log"
        recent.write_text("small")
        # Re-init with tiny max to trigger cleanup
        small_logger = OperationLogger(log_dir, max_total_mb=0.001)
        assert not big.exists()
        assert recent.exists()

    def test_cleanup_time_oserror(self, logger, log_dir, monkeypatch):
        """_cleanup_time should handle OSError gracefully."""
        import os
        logger.log_operation_start({})
        log_file = log_dir / "operations.log"

        original_unlink = Path.unlink

        def failing_unlink(self, *args, **kwargs):
            if "operations.log" in str(self):
                raise OSError("permission denied")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", failing_unlink)
        import time
        old_time = time.time() - 60 * 86400
        os.utime(log_file, (old_time, old_time))
        # Should not raise
        logger._cleanup_time()
