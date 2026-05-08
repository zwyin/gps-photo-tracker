"""Logging system with 4 log files for GPS Photo Tracker."""

import logging
from pathlib import Path

from gps_photo_tracker.core.models import GPSInfo, MatchResult, PhotoInfo


class OperationLogger:
    """Structured logger with separate files for operations, matches, writes, errors."""

    def __init__(self, log_dir: Path):
        log_dir.mkdir(parents=True, exist_ok=True)
        self._ops = self._make_logger("gps_ops", log_dir / "operations.log")
        self._matches = self._make_logger("gps_matches", log_dir / "matches.log")
        self._writes = self._make_logger("gps_writes", log_dir / "writes.log")
        self._errors = self._make_logger("gps_errors", log_dir / "errors.log")

    @staticmethod
    def _make_logger(name: str, path: Path) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            fh = logging.FileHandler(path, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            ))
            logger.addHandler(fh)
        return logger

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

    def log_error(self, context: str, error: Exception):
        self._errors.error(f"{context}: {type(error).__name__}: {error}")

    def cleanup_old_logs(self, retention_days: int = 30) -> None:
        """Delete log files older than retention_days."""
        import time
        if not self._errors.handlers:
            return
        log_dir = Path(self._errors.handlers[0].baseFilename).parent
        cutoff = time.time() - retention_days * 86400
        for log_file in log_dir.glob("*.log"):
            if log_file.stat().st_mtime < cutoff:
                # Close file handlers referencing this file before unlinking (Windows)
                for logger in (self._ops, self._matches, self._writes, self._errors):
                    for handler in list(logger.handlers):
                        if hasattr(handler, 'baseFilename') and handler.baseFilename == str(log_file):
                            handler.close()
                            logger.removeHandler(handler)
                log_file.unlink()

    def log_operation_start(self, params: dict):
        self._ops.info(f"START | params={params}")

    def log_operation_end(self, stats: dict):
        self._ops.info(f"END | stats={stats}")
