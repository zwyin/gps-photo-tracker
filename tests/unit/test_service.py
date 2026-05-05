"""Tests for CancellationToken and GPSTaggingService."""

import time
from pathlib import Path

import pytest

from gps_photo_tracker.core.exif_writer import EXIFWriter
from gps_photo_tracker.core.file_provider import FileProvider
from gps_photo_tracker.core.gpx_parser import GPXParser
from gps_photo_tracker.core.models import (
    BatchResult,
    MatcherConfig,
    ProcessMode,
    ProcessOptions,
    ProgressPhase,
    ProgressUpdate,
    RejectReason,
)
from gps_photo_tracker.service.cancel_token import CancellationToken
from gps_photo_tracker.service.tagging_service import GPSTaggingService


# ── CancellationToken tests ────────────────────────────────

class TestCancellationToken:

    def test_initial_state(self):
        token = CancellationToken()
        assert not token.is_cancelled

    def test_cancel(self):
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled

    def test_cancel_idempotent(self):
        token = CancellationToken()
        token.cancel()
        token.cancel()
        assert token.is_cancelled


# ── GPSTaggingService scan tests ──────────────────────────

class TestScanGPX:

    def test_scan_gpx(self, tmp_path):
        import textwrap
        gpx_content = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:05:00Z</time><ele>110</ele></trkpt>
          </trkseg></trk>
        </gpx>
        """)
        (tmp_path / "track.gpx").write_text(gpx_content)

        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        assert len(segments) == 1
        assert len(segments[0].points) == 2

    def test_scan_gpx_empty_dir(self, tmp_path):
        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        assert segments == []


class TestScanPhotos:

    def test_scan_photos(self, tmp_path):
        from PIL import Image
        import piexif

        # Create a JPEG with EXIF datetime
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:02:00"}}
        img.save(tmp_path / "photo.jpg", "JPEG", exif=piexif.dump(exif))

        service = GPSTaggingService()
        photos = service.scan_photos(tmp_path)
        assert len(photos) == 1
        assert photos[0].filename == "photo.jpg"
        assert photos[0].timestamp is not None

    def test_scan_photos_no_exif(self, tmp_path):
        from PIL import Image
        img = Image.new("RGB", (10, 10))
        img.save(tmp_path / "photo.jpg", "JPEG")

        service = GPSTaggingService()
        photos = service.scan_photos(tmp_path)
        assert len(photos) == 1
        assert photos[0].timestamp is None

    def test_scan_photos_empty_dir(self, tmp_path):
        service = GPSTaggingService()
        photos = service.scan_photos(tmp_path)
        assert photos == []


# ── GPSTaggingService preview tests ──────────────────────

class TestPreview:

    def _setup_gpx_and_photos(self, tmp_path):
        import textwrap
        from PIL import Image
        import piexif

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>
          </trkseg></trk>
        </gpx>
        """)
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(tmp_path / "photo.jpg", "JPEG", exif=piexif.dump(exif))

    def test_preview_basic(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)
        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)

        result = service.preview(segments, photos, MatcherConfig())
        assert isinstance(result, BatchResult)
        assert result.total == 1
        assert result.matched >= 0

    def test_preview_with_progress(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)
        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)

        progress_calls = []
        def on_progress(update: ProgressUpdate):
            progress_calls.append(update)

        service.preview(segments, photos, MatcherConfig(), on_progress=on_progress)
        assert len(progress_calls) > 0
        assert progress_calls[0].phase == ProgressPhase.MATCHING

    def test_preview_with_photo_callback(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)
        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)

        results = []
        def on_photo(r):
            results.append(r)

        service.preview(segments, photos, MatcherConfig(), on_photo_processed=on_photo)
        assert len(results) == 1


# ── GPSTaggingService process tests ──────────────────────

class TestProcess:

    def _setup_gpx_and_photos(self, tmp_path):
        import textwrap
        from PIL import Image
        import piexif

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>
          </trkseg></trk>
        </gpx>
        """)
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(tmp_path / "photo.jpg", "JPEG", exif=piexif.dump(exif))

    def test_process_copy_mode(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)
        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        result = service.process(segments, photos, MatcherConfig(), options)
        assert result.total == 1
        assert result.matched >= 0
        # Output file should exist
        assert (output / "photo.jpg").exists()

    def test_process_overwrite_mode(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)

        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
        options = ProcessOptions(mode=ProcessMode.OVERWRITE)

        result = service.process(segments, photos, MatcherConfig(), options)
        assert result.total == 1

    def test_process_preview_mode_no_write(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)

        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
        options = ProcessOptions(mode=ProcessMode.PREVIEW)

        result = service.process(segments, photos, MatcherConfig(), options)
        assert result.total == 1
        assert result.skipped == 0  # preview doesn't write
        assert result.overwritten == 0


# ── Cancel tests ─────────────────────────────────────────

class TestCancel:

    def test_cancel_stops_processing(self, tmp_path):
        import textwrap
        from PIL import Image
        import piexif

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>
          </trkseg></trk>
        </gpx>
        """)
        (tmp_path / "track.gpx").write_text(gpx)

        # Create 5 photos
        for i in range(5):
            img = Image.new("RGB", (10, 10))
            exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: f"2026:02:17 08:0{i}:00".encode()}}
            img.save(tmp_path / f"photo{i}.jpg", "JPEG", exif=piexif.dump(exif))

        service = GPSTaggingService()
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
        token = CancellationToken()

        # Cancel after first photo
        count = [0]
        def on_photo(r):
            count[0] += 1
            if count[0] == 1:
                token.cancel()

        result = service.preview(
            segments, photos, MatcherConfig(),
            on_photo_processed=on_photo,
            cancel=token,
        )
        # Cancelled: processed fewer than total
        assert count[0] < len(photos)
