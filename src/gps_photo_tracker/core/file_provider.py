"""File system abstraction with retry support for network disks."""

import shutil
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from gps_photo_tracker.core.models import (
    DiskFullError,
    FileAccessError,
    NetworkTimeoutError,
    PermissionDeniedError,
)

_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((OSError, TimeoutError)),
    reraise=True,
)


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
        """Copy file, creating destination directory if needed."""
        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except PermissionError as e:
            raise PermissionDeniedError(str(e)) from e
        except OSError as e:
            if e.errno == 28:  # No space left on device
                raise DiskFullError(str(e)) from e
            raise
