"""File system abstraction with retry support for network disks."""

import shutil
import threading
from pathlib import Path

from tenacity import retry, stop_after_attempt, stop_after_delay, wait_exponential, retry_if_exception_type

from gps_photo_tracker.core.models import (
    DiskFullError,
    FileAccessError,
    NetworkTimeoutError,
    PermissionDeniedError,
)

_RETRY = retry(
    stop=(stop_after_attempt(3) | stop_after_delay(90)),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((OSError, TimeoutError, NetworkTimeoutError)),
    reraise=True,
)

_COPY_TIMEOUT = 30  # seconds per copy attempt


class FileProvider:
    """File system operations with retry for network disks."""

    def list_photos(self, directory: Path) -> list[Path]:
        """Recursively find all JPEG files in directory."""
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        return sorted(
            p for p in directory.rglob("*")
            if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg")
        )

    def list_gpx(self, directory: Path) -> list[Path]:
        """Find all GPX files in directory (non-recursive)."""
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        return sorted(
            p for p in directory.iterdir()
            if p.is_file() and p.suffix.lower() == ".gpx"
        )

    @_RETRY
    def copy_file(self, src: Path, dst: Path) -> None:
        """Copy file with 30s timeout, creating destination directory if needed."""
        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)

        exc_holder = [None]

        def _do_copy():
            try:
                shutil.copy2(src, dst)
            except Exception as e:
                exc_holder[0] = e

        t = threading.Thread(target=_do_copy)
        t.start()
        t.join(timeout=_COPY_TIMEOUT)

        if t.is_alive():
            raise NetworkTimeoutError(
                f"Copy timed out after {_COPY_TIMEOUT}s: {src} -> {dst}"
            )

        if exc_holder[0] is not None:
            e = exc_holder[0]
            if isinstance(e, PermissionError):
                raise PermissionDeniedError(str(e)) from e
            if isinstance(e, OSError) and e.errno == 28:
                raise DiskFullError(str(e)) from e
            raise e
