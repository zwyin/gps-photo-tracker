"""Logging system with rotating log files for GPS Photo Tracker."""

import logging
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from gps_photo_tracker.core.models import GPSInfo, MatchResult, PhotoInfo

_DEFAULT_RETENTION_DAYS = 30
_DEFAULT_MAX_TOTAL_MB = 50


class OperationLogger:
    """Structured logger with separate rotating files for operations, matches, writes, debug, errors."""

    def __init__(self, log_dir: Path, retention_days: int = _DEFAULT_RETENTION_DAYS,
                 max_total_mb: float = _DEFAULT_MAX_TOTAL_MB):
        self._log_dir = log_dir
        self._retention_days = retention_days
        self._max_total_bytes = max_total_mb * 1024 * 1024
        log_dir.mkdir(parents=True, exist_ok=True)

        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        self._ops = self._make_logger("gps_ops", log_dir / "operations.log", fmt)
        self._matches = self._make_logger("gps_matches", log_dir / "matches.log", fmt)
        self._writes = self._make_logger("gps_writes", log_dir / "writes.log", fmt)
        self._debug = self._make_logger("gps_debug", log_dir / "debug.log", fmt, level=logging.DEBUG)
        self._errors = self._make_logger("gps_errors", log_dir / "errors.log", fmt)

        self.cleanup()

    def _make_logger(self, name: str, path: Path, fmt: logging.Formatter,
                     level: int = logging.INFO) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            fh = TimedRotatingFileHandler(
                str(path), when="D", interval=1,
                backupCount=self._retention_days, encoding="utf-8",
            )
            fh.setLevel(level)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        return logger

    # ── Match logging ────────────────────────────────────────

    def log_match_success(self, result: MatchResult):
        dist_str = f"{result.interpolation_distance:.0f}m" if result.interpolation_distance is not None else "—"
        self._matches.info(
            f"OK {result.photo.filename} | {result.method} | "
            f"GPS({result.gps.latitude:.4f},{result.gps.longitude:.4f}) | "
            f"时差:{result.time_diff:.1f}s | 距离:{dist_str}"
        )

    def log_match_failed(self, result: MatchResult):
        self._matches.warning(
            f"FAIL {result.photo.filename} | reason:{result.reject_reason}"
        )

    # ── Write logging ────────────────────────────────────────

    def log_write_success(self, photo: PhotoInfo, gps: GPSInfo, dest: Path = None):
        target = str(dest) if dest else str(photo.path)
        self._writes.info(
            f"WRITE {photo.filename} -> {target} | "
            f"GPS({gps.latitude:.4f},{gps.longitude:.4f}) alt:{gps.altitude}"
        )

    def log_gps_overwrite(self, photo: PhotoInfo, old: GPSInfo, new: GPSInfo):
        self._writes.warning(
            f"OVERWRITE {photo.filename} | "
            f"旧({old.latitude:.4f},{old.longitude:.4f}) -> "
            f"新({new.latitude:.4f},{new.longitude:.4f})"
        )

    # ── Debug logging ────────────────────────────────────────

    def debug(self, msg: str):
        self._debug.debug(msg)

    # ── Operation lifecycle ───────────────────────────────────

    def log_operation_start(self, params: dict):
        self._ops.info(f"START | params={params}")

    def log_operation_end(self, stats: dict):
        self._ops.info(f"END | stats={stats}")

    # ── Error logging ────────────────────────────────────────

    def log_error(self, context: str, error: Exception):
        self._errors.error(f"{context}: {type(error).__name__}: {error}")

    # ── Cleanup ──────────────────────────────────────────────

    def cleanup(self):
        self._cleanup_time()
        self._cleanup_size()

    def _cleanup_time(self):
        """Delete rotated log files older than retention_days."""
        cutoff = time.time() - self._retention_days * 86400
        for log_file in self._log_dir.glob("*.log*"):
            try:
                if log_file.stat().st_mtime < cutoff:
                    log_file.unlink()
            except OSError:
                pass

    def _cleanup_size(self):
        """Delete oldest log files when total exceeds max_total_bytes."""
        files = sorted(
            self._log_dir.glob("*.log*"),
            key=lambda f: f.stat().st_mtime,
        )
        total = sum(f.stat().st_size for f in files)
        for f in files:
            if total <= self._max_total_bytes:
                break
            size = f.stat().st_size
            try:
                f.unlink()
                total -= size
            except OSError:
                pass
