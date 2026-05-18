"""Tests for FileProvider."""

import pytest
from pathlib import Path
from unittest.mock import patch

from gps_photo_tracker.core.file_provider import FileProvider, _COPY_TIMEOUT
from gps_photo_tracker.core.models import FileAccessError, NetworkTimeoutError, PermissionDeniedError


class TestListPhotos:

    def test_finds_jpg_files(self, tmp_path):
        (tmp_path / "photo1.jpg").write_bytes(b"fake")
        (tmp_path / "photo2.jpeg").write_bytes(b"fake")
        (tmp_path / "readme.txt").write_bytes(b"fake")

        provider = FileProvider()
        photos = provider.list_photos(tmp_path)

        names = {p.name for p in photos}
        assert names == {"photo1.jpg", "photo2.jpeg"}

    def test_recursive_search(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (tmp_path / "top.jpg").write_bytes(b"fake")
        (sub / "nested.jpg").write_bytes(b"fake")

        provider = FileProvider()
        photos = provider.list_photos(tmp_path)

        assert len(photos) == 2

    def test_case_insensitive_extension(self, tmp_path):
        (tmp_path / "photo.JPG").write_bytes(b"fake")
        (tmp_path / "photo.Jpeg").write_bytes(b"fake")

        provider = FileProvider()
        photos = provider.list_photos(tmp_path)

        assert len(photos) == 2

    def test_empty_directory(self, tmp_path):
        provider = FileProvider()
        assert provider.list_photos(tmp_path) == []

    def test_skips_nonexistent_directory(self):
        provider = FileProvider()
        with pytest.raises(FileAccessError):
            provider.list_photos(Path("/nonexistent/dir"))


class TestListGPX:

    def test_finds_gpx_files(self, tmp_path):
        (tmp_path / "track1.gpx").write_text("<gpx/>")
        (tmp_path / "track2.GPX").write_text("<gpx/>")
        (tmp_path / "photo.jpg").write_bytes(b"fake")

        provider = FileProvider()
        gpx_files = provider.list_gpx(tmp_path)

        names = {p.name for p in gpx_files}
        assert names == {"track1.gpx", "track2.GPX"}

    def test_non_recursive(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (tmp_path / "top.gpx").write_text("<gpx/>")
        (sub / "nested.gpx").write_text("<gpx/>")

        provider = FileProvider()
        gpx_files = provider.list_gpx(tmp_path)

        assert len(gpx_files) == 1
        assert gpx_files[0].name == "top.gpx"

    def test_empty_directory(self, tmp_path):
        provider = FileProvider()
        assert provider.list_gpx(tmp_path) == []


class TestCopyFile:

    def test_basic_copy(self, tmp_path):
        src = tmp_path / "src.jpg"
        dst = tmp_path / "out" / "dst.jpg"
        src.write_bytes(b"image data")

        provider = FileProvider()
        provider.copy_file(src, dst)

        assert dst.exists()
        assert dst.read_bytes() == b"image data"

    def test_creates_destination_directory(self, tmp_path):
        src = tmp_path / "src.jpg"
        dst = tmp_path / "deep" / "nested" / "dir" / "dst.jpg"
        src.write_bytes(b"data")

        provider = FileProvider()
        provider.copy_file(src, dst)

        assert dst.exists()

    def test_source_not_exists(self, tmp_path):
        dst = tmp_path / "dst.jpg"

        provider = FileProvider()
        with pytest.raises(FileAccessError):
            provider.copy_file(Path("/nonexistent.jpg"), dst)

    def test_preserves_content(self, tmp_path):
        src = tmp_path / "src.jpg"
        dst = tmp_path / "dst.jpg"
        content = b"\xff\xd8\xff\xe0" + b"x" * 1000  # JPEG-like header
        src.write_bytes(content)

        provider = FileProvider()
        provider.copy_file(src, dst)

        assert dst.read_bytes() == content


class TestCopyTimeout:
    """Network disk timeout handling."""

    def test_timeout_raises_network_timeout_error(self, tmp_path):
        """Hanging copy raises NetworkTimeoutError."""
        src = tmp_path / "src.jpg"
        dst = tmp_path / "dst.jpg"
        src.write_bytes(b"data")

        provider = FileProvider()

        # Mock shutil.copy2 to simulate a hang (sleep longer than timeout)
        import shutil
        original_copy2 = shutil.copy2
        def slow_copy(*args, **kwargs):
            import time
            time.sleep(_COPY_TIMEOUT + 5)

        with patch("gps_photo_tracker.core.file_provider.shutil.copy2", side_effect=slow_copy):
            with pytest.raises(NetworkTimeoutError):
                provider.copy_file(src, dst)

    def test_normal_copy_completes_within_timeout(self, tmp_path):
        """Normal copy completes without timeout."""
        src = tmp_path / "src.jpg"
        dst = tmp_path / "dst.jpg"
        src.write_bytes(b"data")

        provider = FileProvider()
        provider.copy_file(src, dst)
        assert dst.exists()

    def test_permission_error_wrapped(self, tmp_path):
        """PermissionError is wrapped in PermissionDeniedError."""
        src = tmp_path / "src.jpg"
        dst = tmp_path / "dst.jpg"
        src.write_bytes(b"data")

        provider = FileProvider()
        with patch("gps_photo_tracker.core.file_provider.shutil.copy2", side_effect=PermissionError("denied")):
            with pytest.raises(PermissionDeniedError):
                provider.copy_file(src, dst)

    def test_retry_on_oserror(self, tmp_path):
        """OSError triggers retry (3 attempts)."""
        src = tmp_path / "src.jpg"
        dst = tmp_path / "dst.jpg"
        src.write_bytes(b"data")

        call_count = [0]
        import shutil
        original_copy2 = shutil.copy2

        def flaky_copy(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise OSError("Network error")
            return original_copy2(*args, **kwargs)

        provider = FileProvider()
        with patch("gps_photo_tracker.core.file_provider.shutil.copy2", side_effect=flaky_copy):
            provider.copy_file(src, dst)

        assert call_count[0] == 3
        assert dst.exists()


class TestListGPXNotFound:

    def test_nonexistent_directory_raises(self):
        provider = FileProvider()
        with pytest.raises(FileAccessError):
            provider.list_gpx(Path("/nonexistent/dir"))


class TestListTracks:

    def test_finds_track_files(self, tmp_path):
        (tmp_path / "a.gpx").write_text("gpx")
        (tmp_path / "b.kml").write_text("kml")
        (tmp_path / "c.tcx").write_text("tcx")
        (tmp_path / "d.txt").write_text("skip")

        provider = FileProvider()
        tracks = provider.list_tracks(tmp_path)
        names = {p.name for p in tracks}
        assert names == {"a.gpx", "b.kml", "c.tcx"}

    def test_nonexistent_directory_raises(self):
        provider = FileProvider()
        with pytest.raises(FileAccessError):
            provider.list_tracks(Path("/nonexistent/dir"))


class TestCopyDiskFull:

    def test_disk_full_error_wrapped(self, tmp_path):
        from gps_photo_tracker.core.models import DiskFullError

        src = tmp_path / "src.jpg"
        dst = tmp_path / "dst.jpg"
        src.write_bytes(b"data")

        err = OSError("No space left on device")
        err.errno = 28
        provider = FileProvider()
        with patch("gps_photo_tracker.core.file_provider.shutil.copy2", side_effect=err):
            with pytest.raises(DiskFullError):
                provider.copy_file(src, dst)
