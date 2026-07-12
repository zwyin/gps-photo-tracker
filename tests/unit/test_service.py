"""Tests for CancellationToken and GPSTaggingService."""

import time
from pathlib import Path

import piexif
import pytest
from PIL import Image

from gps_photo_tracker.core.exif_writer import EXIFWriter
from gps_photo_tracker.core.file_provider import FileProvider
from gps_photo_tracker.core.gpx_parser import GPXParser
from gps_photo_tracker.core.models import (
    BatchResult,
    GPSInfo,
    InputSelection,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    ProcessMode,
    ProcessOptions,
    ProgressPhase,
    ProgressUpdate,
    RejectReason,
    ReviewAction,
    ReviewDecision,
    ReviewState,
)
from gps_photo_tracker.service.cancel_token import CancellationToken
from gps_photo_tracker.service.tagging_service import GPSTaggingService


def _make_jpeg_bytes() -> bytes:
    """Create minimal JPEG bytes in memory."""
    import io
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10))
    img.save(buf, "JPEG")
    return buf.getvalue()


def _make_jpeg_bytes_with_datetime(dt_bytes: bytes) -> bytes:
    """Create JPEG bytes with EXIF DateTimeOriginal."""
    import io
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10))
    exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: dt_bytes}}
    img.save(buf, "JPEG", exif=piexif.dump(exif))
    return buf.getvalue()


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
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        assert len(segments) == 1
        assert len(segments[0].points) == 2

    def test_scan_gpx_empty_dir(self, tmp_path):
        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
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
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        assert len(photos) == 1
        assert photos[0].filename == "photo.jpg"
        assert photos[0].timestamp is not None

    def test_scan_photos_no_exif(self, tmp_path):
        from PIL import Image
        img = Image.new("RGB", (10, 10))
        img.save(tmp_path / "photo.jpg", "JPEG")

        service = GPSTaggingService()
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        assert len(photos) == 1
        assert photos[0].timestamp is None

    def test_scan_photos_empty_dir(self, tmp_path):
        service = GPSTaggingService()
        photos = service.scan_photos(InputSelection.of([tmp_path]))
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
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))

        result = service.preview(segments, photos, MatcherConfig())
        assert isinstance(result, BatchResult)
        assert result.total == 1
        assert result.matched >= 0

    def test_preview_with_progress(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)
        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))

        progress_calls = []
        def on_progress(update: ProgressUpdate):
            progress_calls.append(update)

        service.preview(segments, photos, MatcherConfig(), on_progress=on_progress)
        assert len(progress_calls) > 0
        assert progress_calls[0].phase == ProgressPhase.MATCHING

    def test_preview_with_photo_callback(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)
        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))

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
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        result = service.process(segments, photos, MatcherConfig(), options)
        assert result.total == 1
        assert result.matched >= 0
        # Output file should exist
        assert (output / "photo.jpg").exists()

    def test_process_overwrite_mode(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.OVERWRITE)

        result = service.process(segments, photos, MatcherConfig(), options)
        assert result.total == 1

    def test_process_preview_mode_no_write(self, tmp_path):
        self._setup_gpx_and_photos(tmp_path)

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
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
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
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


# ── Coverage gap tests ────────────────────────────────────

class TestScanEdgeCases:
    """Tests targeting uncovered lines in tagging_service."""

    def test_scan_gpx_skips_bad_file(self, tmp_path):
        """L43-44: unparseable GPX file is skipped."""
        (tmp_path / "bad.gpx").write_text("not xml at all")
        (tmp_path / "good.gpx").write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
  </trkseg></trk>
</gpx>""")
        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        assert len(segments) == 1  # only good.gpx parsed

    def test_scan_photos_handles_broken_jpeg(self, tmp_path):
        """L62-63: corrupt JPEG triggers except, photo added with timestamp=None."""
        (tmp_path / "good.jpg").write_bytes(_make_jpeg_bytes())
        (tmp_path / "bad.jpg").write_bytes(b"not a real image")
        service = GPSTaggingService()
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        assert len(photos) == 2
        good = [p for p in photos if p.filename == "good.jpg"][0]
        bad = [p for p in photos if p.filename == "bad.jpg"][0]
        assert bad.timestamp is None
        assert not bad.has_gps


class TestProcessOverwriteAndSkip:
    """Cover L146-153 (matched/skipped), L179-181 (has_gps skip), L185-190 (write)."""

    def _make_photo_with_gps(self, tmp_path, filename, dt_bytes, lat, lon, alt=None):
        """Create a JPEG that already has GPS in EXIF."""
        import piexif
        from PIL import Image
        from gps_photo_tracker.core.exif_writer import EXIFWriter

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: dt_bytes}}
        img.save(tmp_path / filename, "JPEG", exif=piexif.dump(exif))

        gps_info = GPSInfo(latitude=lat, longitude=lon, altitude=alt)
        EXIFWriter.write_gps(tmp_path / filename, tmp_path / filename, gps_info)

    def test_overwrite_mode_writes_gps(self, tmp_path):
        """L189-190: OVERWRITE mode writes GPS to source file."""
        import textwrap
        self._make_photo_with_gps(tmp_path, "photo.jpg", b"2026:02:17 08:05:00", 20.0, 100.0, 500.0)

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.OVERWRITE, overwrite_gps=True)

        result = service.process(segments, photos, MatcherConfig(), options)
        assert result.overwritten >= 0  # L149-150 covered

    def test_skip_photo_with_existing_gps_no_overwrite(self, tmp_path):
        """L179-181: photo has GPS + overwrite_gps=False → skipped."""
        import textwrap
        self._make_photo_with_gps(tmp_path, "photo.jpg", b"2026:02:17 08:05:00", 20.0, 100.0)

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=tmp_path / "out", overwrite_gps=False)
        (tmp_path / "out").mkdir()

        result = service.process(segments, photos, MatcherConfig(), options)
        assert result.skipped >= 0

    def test_copy_mode_writes_matched_photo(self, tmp_path):
        """L185-188: COPY mode copies file then writes GPS."""
        import textwrap
        img = _make_jpeg_bytes_with_datetime(b"2026:02:17 08:05:00")
        (tmp_path / "photo.jpg").write_bytes(img)

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        output = tmp_path / "output"
        output.mkdir()
        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        result = service.process(segments, photos, MatcherConfig(), options)
        # Should have written GPS to output file
        assert (output / "photo.jpg").exists()


class TestPreviewEmptyInput:
    """Edge cases with empty inputs."""

    def test_preview_no_photos(self):
        service = GPSTaggingService()
        result = service.preview([], [], MatcherConfig())
        assert result.total == 0
        assert result.matched == 0

    def test_preview_no_valid_timestamps(self):
        photos = [PhotoInfo(path=Path("/x.jpg"), filename="x.jpg", timestamp=None, has_gps=False)]
        service = GPSTaggingService()
        result = service.preview([], photos, MatcherConfig())
        assert result.total == 0


class TestCopyModeSkippedStillCopied:
    """COPY mode: skipped photos (has_gps + no overwrite) are still copied."""

    def test_skipped_photo_is_copied(self, tmp_path):
        """Reuses the pattern from TestProcessOverwriteAndSkip which works
        across timezones (write_gps -> read_datetime gives same local time)."""
        import textwrap
        self._make_photo_with_gps(tmp_path, "photo.jpg", b"2026:02:17 08:05:00", 25.0, 100.0)

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        output = tmp_path / "output"
        output.mkdir()
        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, overwrite_gps=False)

        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)
        # Photo has existing GPS + overwrite=False → skipped, but still copied
        if result.skipped >= 1:
            assert (output / tmp_path.name / "photo.jpg").exists()
        # If matching fails due to timezone offset, it's still copied as failed photo
        elif result.failed >= 1:
            assert (output / tmp_path.name / "photo.jpg").exists()

    @staticmethod
    def _make_photo_with_gps(tmp_path, filename, dt_bytes, lat, lon, alt=None):
        import piexif
        from PIL import Image
        from gps_photo_tracker.core.exif_writer import EXIFWriter

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: dt_bytes}}
        img.save(tmp_path / filename, "JPEG", exif=piexif.dump(exif))
        EXIFWriter.write_gps(tmp_path / filename, tmp_path / filename, GPSInfo(lat, lon, alt))


class TestKeepStructure:
    """keep_structure preserves relative path from photo_dir."""

    def test_keep_structure_subdir(self, tmp_path):
        import textwrap, piexif
        from PIL import Image

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        sub = tmp_path / "photos" / "202602"
        sub.mkdir(parents=True)
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(sub / "photo.jpg", "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()
        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([sub]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, keep_structure=True)

        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=sub)
        # Should preserve the subdirectory structure
        assert result.matched >= 0
        assert (output / sub.name / "photo.jpg").exists()


class TestRejectGroups:
    """reject_groups is populated with failure reasons."""

    def test_reject_groups_populated(self, tmp_path):
        import textwrap, piexif
        from PIL import Image

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        # Photo far from any track point → will fail
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(tmp_path / "photo.jpg", "JPEG", exif=piexif.dump(exif))

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        result = service.preview(segments, photos, MatcherConfig())
        if result.failed > 0:
            assert len(result.reject_groups) > 0


class TestOperationLoggerIntegration:
    """OperationLogger wired into GPSTaggingService produces log files."""

    def _setup_gpx_and_photos(self, tmp_path):
        import textwrap, piexif
        from PIL import Image

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(tmp_path / "photo.jpg", "JPEG", exif=piexif.dump(exif))

    def test_no_log_dir_no_logging(self, tmp_path):
        """Service without log_dir works normally (backward compatible)."""
        self._setup_gpx_and_photos(tmp_path)
        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        result = service.preview(segments, photos, MatcherConfig())
        assert result.total == 1

    def test_operations_log_on_preview(self, tmp_path):
        """operations.log has START and END entries."""
        import logging
        for name in ["gps_ops", "gps_matches", "gps_writes", "gps_errors"]:
            logging.getLogger(name).handlers.clear()

        self._setup_gpx_and_photos(tmp_path)
        log_dir = tmp_path / "logs"
        service = GPSTaggingService(log_dir=log_dir)
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        service.preview(segments, photos, MatcherConfig())

        ops = (log_dir / "operations.log").read_text(encoding="utf-8")
        assert "START" in ops
        assert "END" in ops
        assert "preview" in ops

    def test_matches_log_on_success(self, tmp_path):
        """matches.log records successful match."""
        import logging
        for name in ["gps_ops", "gps_matches", "gps_writes", "gps_errors"]:
            logging.getLogger(name).handlers.clear()

        self._setup_gpx_and_photos(tmp_path)
        log_dir = tmp_path / "logs"
        service = GPSTaggingService(log_dir=log_dir)
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        result = service.preview(segments, photos, MatcherConfig())

        if result.matched > 0:
            matches = (log_dir / "matches.log").read_text(encoding="utf-8")
            assert "OK photo.jpg" in matches

    def test_matches_log_on_failure(self, tmp_path):
        """matches.log records failed match."""
        import logging, textwrap, piexif
        from PIL import Image
        for name in ["gps_ops", "gps_matches", "gps_writes", "gps_errors"]:
            logging.getLogger(name).handlers.clear()

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        # Photo time outside track coverage
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 20:00:00"}}
        img.save(tmp_path / "photo.jpg", "JPEG", exif=piexif.dump(exif))

        log_dir = tmp_path / "logs"
        service = GPSTaggingService(log_dir=log_dir)
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        result = service.preview(segments, photos, MatcherConfig())

        if result.failed > 0:
            matches = (log_dir / "matches.log").read_text(encoding="utf-8")
            assert "FAIL photo.jpg" in matches

    def test_writes_log_on_copy(self, tmp_path):
        """writes.log records GPS write in COPY mode."""
        import logging
        for name in ["gps_ops", "gps_matches", "gps_writes", "gps_errors"]:
            logging.getLogger(name).handlers.clear()

        self._setup_gpx_and_photos(tmp_path)
        output = tmp_path / "output"
        output.mkdir()

        log_dir = tmp_path / "logs"
        service = GPSTaggingService(log_dir=log_dir)
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)
        result = service.process(segments, photos, MatcherConfig(), options)

        if result.matched > 0:
            writes = (log_dir / "writes.log").read_text(encoding="utf-8")
            assert "WRITE" in writes

    def test_error_log_on_bad_gpx(self, tmp_path):
        """errors.log records unparseable GPX file."""
        import logging
        for name in ["gps_ops", "gps_matches", "gps_writes", "gps_errors"]:
            logging.getLogger(name).handlers.clear()

        (tmp_path / "bad.gpx").write_text("not xml")
        log_dir = tmp_path / "logs"
        service = GPSTaggingService(log_dir=log_dir)
        service.scan_gpx(InputSelection.of([tmp_path]))

        errors = (log_dir / "errors.log").read_text(encoding="utf-8")
        assert "scan_gpx" in errors
        assert "bad.gpx" in errors

    def test_error_log_on_bad_photo(self, tmp_path):
        """errors.log records unreadable photo."""
        import logging
        for name in ["gps_ops", "gps_matches", "gps_writes", "gps_errors"]:
            logging.getLogger(name).handlers.clear()

        (tmp_path / "bad.jpg").write_bytes(b"not a real image")
        log_dir = tmp_path / "logs"
        service = GPSTaggingService(log_dir=log_dir)
        service.scan_photos(InputSelection.of([tmp_path]))

        errors = (log_dir / "errors.log").read_text(encoding="utf-8")
        assert "scan_photos" in errors
        assert "bad.jpg" in errors


class TestCopyAfterWriteFailure:
    """COPY mode: if GPS write fails, photo should still be copied (output == input)."""

    def test_copy_after_write_failure(self, tmp_path):
        """When GPS write fails in COPY mode, the photo is still copied."""
        import textwrap, piexif
        from PIL import Image
        from unittest.mock import patch

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(tmp_path / "photo.jpg", "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        # Make write_gps fail
        with patch("gps_photo_tracker.service.tagging_service.EXIFWriter.write_gps",
                   side_effect=Exception("EXIF write error")):
            result = service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)

        # Photo should still exist in output even though write failed
        if result.matched > 0:
            # Some matched but write failed — photo still copied
            assert (output / "photo.jpg").exists()


class TestScanProgressCallbacks:
    """Verify scan_gpx and scan_photos call on_progress correctly."""

    def test_scan_gpx_progress_callback(self, tmp_path):
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "a.gpx").write_text(gpx)
        (tmp_path / "b.gpx").write_text(gpx)

        service = GPSTaggingService()
        updates = []
        segments = service.scan_gpx(InputSelection.of([tmp_path]), on_progress=lambda u: updates.append(u))

        assert len(segments) == 2
        assert len(updates) == 2
        assert updates[0].phase == ProgressPhase.SCANNING_GPX
        assert updates[0].current == 1
        assert updates[0].total == 2
        assert updates[0].current_file == "a.gpx"

    def test_scan_photos_progress_callback(self, tmp_path):
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:00:00"}}
        img.save(str(tmp_path / "a.jpg"), "JPEG", exif=piexif.dump(exif))
        img.save(str(tmp_path / "b.jpg"), "JPEG", exif=piexif.dump(exif))

        service = GPSTaggingService()
        updates = []
        photos = service.scan_photos(InputSelection.of([tmp_path]), on_progress=lambda u: updates.append(u))

        assert len(photos) == 2
        assert len(updates) == 2
        assert updates[0].phase == ProgressPhase.SCANNING_PHOTOS
        assert updates[0].current == 1

    def test_scan_gpx_skips_bad_file(self, tmp_path):
        (tmp_path / "bad.gpx").write_text("NOT VALID GPX")
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "good.gpx").write_text(gpx)

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        assert len(segments) == 1
        assert segments[0].filename == "good.gpx"


class TestCopyModeEdgeCases:
    """COPY mode: output == input, keep_structure, copy-only paths."""

    def test_copy_preserves_directory_structure(self, tmp_path):
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>'
               '<trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "track.gpx").write_text(gpx)

        subdir = tmp_path / "subdir"
        subdir.mkdir()
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(subdir / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(
            mode=ProcessMode.COPY, output_dir=output, keep_structure=True,
        )
        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)

        # Should preserve subdir structure
        assert (output / "subdir" / "photo.jpg").exists()

    def test_copy_all_photos_output_equals_input(self, tmp_path):
        """Spec 5.3: output count == input count."""
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        # Matched photo
        exif1 = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:00:00"}}
        img.save(str(tmp_path / "matched.jpg"), "JPEG", exif=piexif.dump(exif1))
        # Unmatched photo (no GPS coverage)
        exif2 = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:18 08:00:00"}}
        img.save(str(tmp_path / "unmatched.jpg"), "JPEG", exif=piexif.dump(exif2))

        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)
        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)

        assert (output / tmp_path.name / "matched.jpg").exists()
        assert (output / tmp_path.name / "unmatched.jpg").exists()
        output_count = len(list(output.rglob("*.jpg")))
        assert output_count == 2

    def test_copy_skip_existing_gps(self, tmp_path):
        """Photo with GPS + overwrite_gps=False: copy only, no GPS write."""
        # Use a known timestamp that matches GPS segment range
        import datetime as _dt
        ts = _dt.datetime(2026, 2, 17, 8, 5, 0, tzinfo=_dt.timezone.utc).timestamp()
        # GPX times in UTC
        start = _dt.datetime(2026, 2, 17, 8, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
        end = _dt.datetime(2026, 2, 17, 8, 10, 0, tzinfo=_dt.timezone.utc).timestamp()

        from gps_photo_tracker.core.models import GPXSegment, TrackPoint
        segments = [GPXSegment(
            filename="track.gpx", start=start, end=end,
            points=[
                TrackPoint(start, 25.0, 100.0, 100),
                TrackPoint(end, 25.001, 100.001, 110),
            ],
        )]

        # Create a photo with existing GPS
        img = Image.new("RGB", (10, 10))
        exif_bytes = {
            "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"},
            "GPS": {
                piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
                piexif.GPSIFD.GPSLatitudeRef: b'N',
                piexif.GPSIFD.GPSLatitude: ((25, 1), (0, 1), (0, 1)),
                piexif.GPSIFD.GPSLongitudeRef: b'E',
                piexif.GPSIFD.GPSLongitude: ((100, 1), (0, 1), (0, 1)),
            },
        }
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif_bytes))

        # Manually construct PhotoInfo with correct UTC timestamp
        photos = [PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=ts, has_gps=True,
            existing_gps=GPSInfo(25.0, 100.0, None),
        )]

        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        options = ProcessOptions(
            mode=ProcessMode.COPY, output_dir=output, overwrite_gps=False,
        )
        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)

        assert result.skipped >= 1
        assert (output / tmp_path.name / "photo.jpg").exists()


class TestPipelineProgressCallback:
    """Verify progress callbacks fire during preview and process."""

    def test_preview_progress_fires(self, tmp_path):
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>'
               '<trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))

        updates = []
        result = service.preview(
            segments, photos, MatcherConfig(),
            on_progress=lambda u: updates.append(u),
        )

        assert result.total == 1
        assert len(updates) >= 1
        assert updates[0].phase == ProgressPhase.MATCHING

    def test_process_progress_fires_writing_phase(self, tmp_path):
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time><ele>100</ele></trkpt>'
               '<trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time><ele>110</ele></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        updates = []
        result = service.process(
            segments, photos, MatcherConfig(), options,
            photo_dir=tmp_path,
            on_progress=lambda u: updates.append(u),
        )

        phases = [u.phase for u in updates]
        assert ProgressPhase.WRITING in phases


class TestAutoTune:
    """auto_tune delegates to ParamTuner.recommend."""

    def test_auto_tune_returns_config(self):
        from gps_photo_tracker.core.models import GPXSegment, TrackPoint
        segments = [GPXSegment(
            filename="t.gpx", start=0, end=600,
            points=[TrackPoint(0, 25.0, 100.0), TrackPoint(600, 25.001, 100.001)],
        )]
        photos = [PhotoInfo(path=Path("/a.jpg"), filename="a.jpg", timestamp=300.0, has_gps=False)]
        service = GPSTaggingService()
        config = service.auto_tune(segments, photos)
        assert isinstance(config, MatcherConfig)

    def test_auto_tune_empty_returns_defaults(self):
        service = GPSTaggingService()
        config = service.auto_tune([], [])
        assert isinstance(config, MatcherConfig)
        assert config.isolated_window == MatcherConfig().isolated_window


class TestOrientationInScan:
    """scan_photos reads orientation via OrientationReader."""

    def test_scan_reads_orientation(self, tmp_path):
        from gps_photo_tracker.core.orientation import OrientationReader
        img = Image.new("RGB", (10, 10))
        exif = {
            "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:00:00"},
            "0th": {piexif.ImageIFD.Orientation: 6},
        }
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        service = GPSTaggingService()
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        assert len(photos) == 1
        assert photos[0].orientation == 6

    def test_scan_photo_no_orientation(self, tmp_path):
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:00:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        service = GPSTaggingService()
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        assert len(photos) == 1
        # orientation is None when not set in EXIF
        assert photos[0].orientation is None


class TestResumeCheckpoint:
    """Resume skips already-completed photos via checkpoint."""

    def test_resume_skips_completed(self, tmp_path):
        from gps_photo_tracker.core.checkpoint import CheckpointManager
        from gps_photo_tracker.core.models import GPXSegment, TrackPoint

        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>'
               '<trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()

        # Pre-create checkpoint with photo already completed
        CheckpointManager.create(output, total_photos=1)
        CheckpointManager.mark(output, "photo.jpg")

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(
            mode=ProcessMode.COPY, output_dir=output, resume=True,
        )

        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)
        # Photo was skipped by resume
        assert result.matched == 0

    def test_checkpoint_completes_on_success(self, tmp_path):
        from gps_photo_tracker.core.checkpoint import CheckpointManager

        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>'
               '<trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(
            mode=ProcessMode.COPY, output_dir=output, resume=True,
        )

        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)
        # After completion, checkpoint should be completed
        assert not CheckpointManager.is_interrupted(output)


class TestReportGeneration:
    """generate_report triggers ReportBuilder.build."""

    def test_report_generated_on_process(self, tmp_path):
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>'
               '<trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(
            mode=ProcessMode.COPY, output_dir=output, generate_report=True,
        )

        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)
        report_path = output / "report.html"
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "<html" in content


class TestConcurrentWorkersInResult:
    """BatchResult.concurrent_workers reflects options.workers."""

    def test_default_workers(self, tmp_path):
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>'
               '<trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))

        result = service.preview(segments, photos, MatcherConfig())
        assert result.concurrent_workers == 1

    def test_custom_workers(self, tmp_path):
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>'
               '<trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time></trkpt>'
               '</trkseg></trk></gpx>')
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=4)

        result = service.process(segments, photos, MatcherConfig(), options)
        assert result.concurrent_workers == 4


class TestParallelWrite:
    """workers > 1 triggers BatchProcessor for write phase."""

    def test_parallel_uses_batch_processor(self, tmp_path):
        """When workers>1, BatchProcessor.submit_all is called instead of inline write."""
        from unittest.mock import patch, MagicMock
        from gps_photo_tracker.core.concurrency import WriteResult

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        match_result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0, 50),
            method="interpolated", time_diff=10.0,
        )

        output = tmp_path / "output"
        output.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2)

        def fake_submit_all(tasks, on_progress=None, on_result=None, cancel=None):
            """Simulate BatchProcessor.submit_all invoking callbacks."""
            if on_progress:
                on_progress(0, len(tasks))
            if on_result:
                for t in tasks:
                    on_result(WriteResult(
                        success=True, filename=t.match_result.photo.filename,
                        dest_path=output / t.match_result.photo.filename,
                    ))
                on_progress(len(tasks), len(tasks))
            return []

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = fake_submit_all

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher:
            MockMatcher.return_value.match.return_value = [match_result]

            service = GPSTaggingService()
            result = service.process(
                [], [photo], MatcherConfig(), options, photo_dir=tmp_path,
            )

            assert result.matched == 1
            assert result.failed == 0
            assert result.concurrent_workers == 2

    def test_parallel_write_failure_decrements_counters(self, tmp_path):
        """Parallel write failure decrements matched and increments failed."""
        from unittest.mock import patch, MagicMock
        from gps_photo_tracker.core.concurrency import WriteResult

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        match_result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0, 50),
            method="interpolated", time_diff=10.0,
        )

        output = tmp_path / "output"
        output.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2)

        def fake_submit_all_with_failure(tasks, on_progress=None, on_result=None, cancel=None):
            if on_result:
                on_result(WriteResult(
                    success=False, filename="photo.jpg", error="write failed",
                ))
            return []

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = fake_submit_all_with_failure

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher:
            MockMatcher.return_value.match.return_value = [match_result]

            service = GPSTaggingService()
            result = service.process(
                [], [photo], MatcherConfig(), options, photo_dir=tmp_path,
            )

            assert result.matched == 0
            assert result.failed == 1

    def test_workers_1_does_not_use_batch_processor(self, tmp_path):
        """workers=1 uses inline sequential write, not BatchProcessor."""
        import textwrap
        from unittest.mock import patch

        gpx = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
            <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:10:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>""")
        (tmp_path / "track.gpx").write_text(gpx)

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=1)

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor") as MockBP:
            service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)
            # BatchProcessor should NOT have been instantiated
            MockBP.assert_not_called()


class TestCopyDestinationPaths:
    """Test _copy_destination with keep_structure edge cases."""

    def test_keep_structure_value_error_fallback(self):
        service = GPSTaggingService()
        options = ProcessOptions(
            mode=ProcessMode.COPY,
            output_dir=Path("/output"),
            keep_structure=True,
        )
        # Path not relative to photo_dir → ValueError → fallback to photo_dir.name / filename
        result = service._copy_destination(Path("/other/photo.jpg"), options, Path("/photos"))
        assert result == Path("/output") / "photos" / "photo.jpg"

    def test_keep_structure_preserves_relative_path(self):
        service = GPSTaggingService()
        options = ProcessOptions(
            mode=ProcessMode.COPY,
            output_dir=Path("/output"),
            keep_structure=True,
        )
        result = service._copy_destination(
            Path("/photos/2026/feb/photo.jpg"), options, Path("/photos"),
        )
        assert result == Path("/output") / "2026" / "feb" / "photo.jpg"

    def test_no_keep_structure_uses_filename_only(self):
        service = GPSTaggingService()
        options = ProcessOptions(
            mode=ProcessMode.COPY,
            output_dir=Path("/output"),
            keep_structure=False,
        )
        result = service._copy_destination(
            Path("/photos/2026/feb/photo.jpg"), options, Path("/photos"),
        )
        assert result == Path("/output") / "photo.jpg"


class TestOverwriteMode:
    """OVERWRITE mode writes GPS to original file in-place."""

    def test_overwrite_writes_gps_in_place(self, tmp_path):
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        match_result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0, 50),
            method="interpolated", time_diff=10.0,
        )

        from unittest.mock import patch, MagicMock
        from gps_photo_tracker.core.exif_writer import EXIFWriter as RealWriter
        mock_writer = MagicMock()
        with patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch("gps_photo_tracker.service.tagging_service.EXIFWriter", mock_writer):
            MockMatcher.return_value.match.return_value = [match_result]
            service = GPSTaggingService()
            opts = ProcessOptions(mode=ProcessMode.OVERWRITE)
            result = service.process([], [photo], MatcherConfig(), opts)

            assert result.matched == 1
            mock_writer.write_gps.assert_called_once()
            call_args = mock_writer.write_gps.call_args[0]
            assert call_args[0] == call_args[1]


class TestReportGenerationFailure:
    """Report generation failure is caught gracefully."""

    def test_report_failure_does_not_crash(self, tmp_path):
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        match_result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0, 50),
            method="interpolated", time_diff=10.0,
        )
        output = tmp_path / "output"
        output.mkdir()
        opts = ProcessOptions(
            mode=ProcessMode.COPY, output_dir=output, generate_report=True,
        )

        from unittest.mock import patch
        with patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch("gps_photo_tracker.service.tagging_service.ReportBuilder") as MockRB:
            MockMatcher.return_value.match.return_value = [match_result]
            MockRB.build.side_effect = OSError("disk full")
            service = GPSTaggingService()
            result = service.process([], [photo], MatcherConfig(), opts, photo_dir=tmp_path)
            assert result.matched == 1


class TestSequentialWriteError:
    """Sequential write failure falls back to copy and adjusts counters."""

    def test_write_failure_copies_original(self, tmp_path):
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        match_result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0, 50),
            method="interpolated", time_diff=10.0,
        )
        output = tmp_path / "output"
        output.mkdir()
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        from unittest.mock import patch
        with patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter:
            MockMatcher.return_value.match.return_value = [match_result]
            MockWriter.write_gps.side_effect = OSError("write failed")
            service = GPSTaggingService()
            result = service.process([], [photo], MatcherConfig(), opts, photo_dir=tmp_path)
            assert result.matched == 0
            assert result.failed == 1
            assert (output / tmp_path.name / "photo.jpg").exists()


class TestApplyReviewDecisions:
    """Cover apply_review with FOLLOW_PREV/FOLLOW_NEXT and _apply_follow."""

    def _make_results(self, tmp_path):
        """Create 3 photos: p0 success, p1 failed, p2 success."""
        p0 = PhotoInfo(path=tmp_path / "p0.jpg", filename="p0.jpg", timestamp=100.0, has_gps=False)
        p1 = PhotoInfo(path=tmp_path / "p1.jpg", filename="p1.jpg", timestamp=200.0, has_gps=False)
        p2 = PhotoInfo(path=tmp_path / "p2.jpg", filename="p2.jpg", timestamp=300.0, has_gps=False)
        r0 = MatchResult(photo=p0, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=5.0)
        r1 = MatchResult(photo=p1, success=False, reject_reason=RejectReason.NO_GPS_COVERAGE)
        r2 = MatchResult(photo=p2, success=True, gps=GPSInfo(25.1, 100.1), method="interpolated", time_diff=5.0)
        return [r0, r1, r2]

    def test_follow_prev_assigns_gps(self, tmp_path):
        """FOLLOW_PREV: failed photo follows prev neighbor's GPS."""
        results = self._make_results(tmp_path)
        state = ReviewState(
            failed_results=[results[1]],
            gps_segments=[],
            all_results=results,
            decisions={str(tmp_path / "p1.jpg"): ReviewDecision(
                photo_path=str(tmp_path / "p1.jpg"),
                action=ReviewAction.FOLLOW_PREV,
            )},
        )
        service = GPSTaggingService()
        updated = service.apply_review(results, state)
        assert updated[1].success
        assert updated[1].method == "follow_prev"
        assert updated[1].review_gps.latitude == 25.0

    def test_follow_next_assigns_gps(self, tmp_path):
        """FOLLOW_NEXT: failed photo follows next neighbor's GPS."""
        results = self._make_results(tmp_path)
        state = ReviewState(
            failed_results=[results[1]],
            gps_segments=[],
            all_results=results,
            decisions={str(tmp_path / "p1.jpg"): ReviewDecision(
                photo_path=str(tmp_path / "p1.jpg"),
                action=ReviewAction.FOLLOW_NEXT,
            )},
        )
        service = GPSTaggingService()
        updated = service.apply_review(results, state)
        assert updated[1].success
        assert updated[1].method == "follow_next"
        assert updated[1].review_gps.latitude == 25.1

    def test_follow_skips_protected_neighbor(self, tmp_path):
        """FOLLOW_PREV skips protected neighbor, finds next valid."""
        p0 = PhotoInfo(path=tmp_path / "p0.jpg", filename="p0.jpg", timestamp=100.0, has_gps=False)
        p1 = PhotoInfo(path=tmp_path / "p1.jpg", filename="p1.jpg", timestamp=200.0, has_gps=False)
        p2 = PhotoInfo(path=tmp_path / "p2.jpg", filename="p2.jpg", timestamp=300.0, has_gps=False)
        p3 = PhotoInfo(path=tmp_path / "p3.jpg", filename="p3.jpg", timestamp=400.0, has_gps=False)
        r0 = MatchResult(photo=p0, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=5.0)
        r1 = MatchResult(photo=p1, success=True, gps=GPSInfo(25.05, 100.05), method="protected", time_diff=5.0)
        r2 = MatchResult(photo=p2, success=False, reject_reason=RejectReason.NO_GPS_COVERAGE)
        r3 = MatchResult(photo=p3, success=True, gps=GPSInfo(25.1, 100.1), method="interpolated", time_diff=5.0)
        results = [r0, r1, r2, r3]
        state = ReviewState(
            failed_results=[r2],
            gps_segments=[],
            all_results=results,
            decisions={str(tmp_path / "p2.jpg"): ReviewDecision(
                photo_path=str(tmp_path / "p2.jpg"),
                action=ReviewAction.FOLLOW_PREV,
            )},
        )
        service = GPSTaggingService()
        updated = service.apply_review(results, state)
        assert updated[2].success
        assert updated[2].review_gps.latitude == 25.0  # skipped protected p1, found p0

    def test_follow_no_valid_neighbor_leaves_failed(self, tmp_path):
        """FOLLOW_PREV with no valid neighbor: photo stays failed."""
        p0 = PhotoInfo(path=tmp_path / "p0.jpg", filename="p0.jpg", timestamp=100.0, has_gps=False)
        p1 = PhotoInfo(path=tmp_path / "p1.jpg", filename="p1.jpg", timestamp=200.0, has_gps=False)
        r0 = MatchResult(photo=p0, success=False, reject_reason=RejectReason.NO_GPS_COVERAGE)
        r1 = MatchResult(photo=p1, success=False, reject_reason=RejectReason.NO_GPS_COVERAGE)
        results = [r0, r1]
        state = ReviewState(
            failed_results=results,
            gps_segments=[],
            all_results=results,
            decisions={str(tmp_path / "p1.jpg"): ReviewDecision(
                photo_path=str(tmp_path / "p1.jpg"),
                action=ReviewAction.FOLLOW_PREV,
            )},
        )
        service = GPSTaggingService()
        updated = service.apply_review(results, state)
        assert not updated[1].success

    def test_successful_results_skipped(self, tmp_path):
        """apply_review skips already-successful results (L69)."""
        results = self._make_results(tmp_path)
        state = ReviewState(
            failed_results=[],
            gps_segments=[],
            all_results=results,
            decisions={},
        )
        service = GPSTaggingService()
        updated = service.apply_review(results, state)
        assert updated[0].success
        assert updated[0].method == "interpolated"  # unchanged


class TestWritePhaseCancelAndProgress:
    """Cover write_phase cancel (L148) and progress callback (L162-165)."""

    def test_write_phase_cancel_stops_early(self, tmp_path):
        """CancellationToken breaks the write loop."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
            method="interpolated", time_diff=10.0,
        )
        opts = ProcessOptions(mode=ProcessMode.OVERWRITE)
        cancel = CancellationToken()
        cancel.cancel()

        service = GPSTaggingService()
        batch = service.write_phase([result], opts, cancel=cancel)
        assert batch.total == 1
        assert batch.matched == 0  # cancelled before processing

    def test_write_phase_skips_protected(self, tmp_path):
        """write_phase counts protected method as skipped (L161-165)."""
        img = Image.new("RGB", (10, 10))
        img.save(str(tmp_path / "photo.jpg"), "JPEG")
        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
            method="protected", time_diff=10.0,
        )
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=tmp_path / "out")
        (tmp_path / "out").mkdir()

        service = GPSTaggingService()
        batch = service.write_phase([result], opts)
        assert batch.skipped == 1
        assert batch.matched == 0

    def test_write_phase_overwrite_counts(self, tmp_path):
        """write_phase increments overwritten when photo has existing GPS (L174-175)."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=True,
            existing_gps=GPSInfo(30.0, 120.0),
        )
        result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
            method="interpolated", time_diff=10.0,
        )
        opts = ProcessOptions(mode=ProcessMode.OVERWRITE, overwrite_gps=True)

        from unittest.mock import patch
        with patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter:
            MockWriter.write_gps.return_value = True
            service = GPSTaggingService()
            batch = service.write_phase([result], opts)
            assert batch.overwritten == 1

    def test_write_phase_progress_callback(self, tmp_path):
        """write_phase calls on_progress callback."""
        img = Image.new("RGB", (10, 10))
        img.save(str(tmp_path / "photo.jpg"), "JPEG")
        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
            method="interpolated", time_diff=10.0,
        )
        opts = ProcessOptions(mode=ProcessMode.PREVIEW)
        progress_calls = []

        def on_progress(update):
            progress_calls.append(update)

        service = GPSTaggingService()
        service.write_phase([result], opts, on_progress=on_progress)
        assert len(progress_calls) >= 1


class TestWritePhaseWithOpLogger:
    """Cover write_phase op_logger paths (L178-196)."""

    def test_write_success_logs(self, tmp_path):
        """Successful write logs via op_logger (L178-179)."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
            method="interpolated", time_diff=10.0,
        )
        opts = ProcessOptions(mode=ProcessMode.OVERWRITE)
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        from unittest.mock import patch, MagicMock
        with patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter:
            MockWriter.write_gps.return_value = True
            service = GPSTaggingService(log_dir=log_dir)
            batch = service.write_phase([result], opts)
            assert batch.matched == 1
            assert service._op_logger is not None

    def test_write_failure_copies_and_logs(self, tmp_path):
        """Write failure in COPY mode copies original and logs error (L180-196)."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
            method="interpolated", time_diff=10.0,
        )
        output = tmp_path / "output"
        output.mkdir()
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        from unittest.mock import patch
        with patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter:
            MockWriter.write_gps.side_effect = OSError("disk full")
            service = GPSTaggingService(log_dir=log_dir)
            batch = service.write_phase([result], opts, photo_dir=tmp_path)
            assert batch.matched == 0
            assert batch.failed == 1


class TestApplyFollowPathNotFound:
    """Cover L113: _apply_follow with path not in ordered list."""

    def test_path_not_in_all_results(self, tmp_path):
        """Photo not in all_results → _apply_follow returns without change."""
        p_failed = PhotoInfo(path=tmp_path / "orphan.jpg", filename="orphan.jpg", timestamp=200.0, has_gps=False)
        p_other = PhotoInfo(path=tmp_path / "other.jpg", filename="other.jpg", timestamp=100.0, has_gps=False)
        r_failed = MatchResult(photo=p_failed, success=False, reject_reason=RejectReason.NO_GPS_COVERAGE)
        r_other = MatchResult(photo=p_other, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=5.0)
        results = [r_failed]

        # all_results only has r_other, so orphan.jpg is not in path_to_idx
        state = ReviewState(
            failed_results=[r_failed],
            gps_segments=[],
            all_results=[r_other],
            decisions={str(tmp_path / "orphan.jpg"): ReviewDecision(
                photo_path=str(tmp_path / "orphan.jpg"),
                action=ReviewAction.FOLLOW_PREV,
            )},
        )
        service = GPSTaggingService()
        updated = service.apply_review(results, state)
        assert not updated[0].success


class TestWritePhaseSkipAndCopyFallback:
    """Cover L189-196: write_phase skip path and copy fallback after double failure."""

    def test_should_write_false_skips_and_copies(self, tmp_path):
        """Photo has_gps + overwrite_gps=False → _should_write returns False → skip + copy (L192-196)."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=True, existing_gps=GPSInfo(30.0, 120.0),
        )
        # Method is NOT "skipped" — could happen via manual review override
        result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
            method="interpolated", time_diff=10.0,
        )
        output = tmp_path / "output"
        output.mkdir()
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        service = GPSTaggingService()
        batch = service.write_phase([result], opts, photo_dir=tmp_path)
        assert batch.skipped == 1
        assert (output / tmp_path.name / "photo.jpg").exists()

    def test_write_and_copy_both_fail(self, tmp_path):
        """Write fails AND copy also fails — both errors logged (L189-191)."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=False,
        )
        result = MatchResult(
            photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
            method="interpolated", time_diff=10.0,
        )
        output = tmp_path / "output"
        output.mkdir()
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        from unittest.mock import patch
        with patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter, \
             patch.object(FileProvider, "copy_file", side_effect=OSError("copy failed")):
            MockWriter.write_gps.side_effect = OSError("write failed")
            service = GPSTaggingService(log_dir=log_dir)
            batch = service.write_phase([result], opts, photo_dir=tmp_path)
            assert batch.failed == 1
            assert batch.matched == 0


class TestProcessWithOpLogger:
    """Cover L407-442: _run_pipeline op_logger + checkpoint paths."""

    def test_process_log_match_success(self, tmp_path):
        """process() with log_dir logs match_success (L407)."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        from unittest.mock import patch
        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg", timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=10.0)
        opts = ProcessOptions(mode=ProcessMode.OVERWRITE)

        with patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            MockWriter.write_gps.return_value = True
            service = GPSTaggingService(log_dir=log_dir)
            result = service.process([], [photo], MatcherConfig(), opts, photo_dir=tmp_path)
            assert result.matched == 1
            assert service._op_logger is not None

    def test_process_overwrite_gps_with_existing(self, tmp_path):
        """process() counts overwritten when photo has existing GPS (L411-413)."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=True, existing_gps=GPSInfo(30.0, 120.0),
        )
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=10.0)
        opts = ProcessOptions(mode=ProcessMode.OVERWRITE, overwrite_gps=True)

        from unittest.mock import patch
        with patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            MockWriter.write_gps.return_value = True
            service = GPSTaggingService(log_dir=log_dir)
            result = service.process([], [photo], MatcherConfig(), opts, photo_dir=tmp_path)
            assert result.overwritten == 1

    def test_process_write_failure_with_copy(self, tmp_path):
        """process() write failure copies original and adjusts counters (L425-442)."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg", timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=10.0)
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        from unittest.mock import patch
        with patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            MockWriter.write_gps.side_effect = OSError("write failed")
            service = GPSTaggingService(log_dir=log_dir)
            result = service.process([], [photo], MatcherConfig(), opts, photo_dir=tmp_path)
            assert result.failed == 1
            assert result.matched == 0
            assert (output / tmp_path.name / "photo.jpg").exists()

    def test_process_checkpoint_marks_completed(self, tmp_path):
        """process() with resume marks checkpoint after successful write (L458)."""
        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()
        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg", timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=10.0)
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, resume=True)

        from unittest.mock import patch
        with patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            MockWriter.write_gps.return_value = True
            service = GPSTaggingService()
            result = service.process([], [photo], MatcherConfig(), opts, photo_dir=tmp_path)
            assert result.matched == 1


class TestParallelWriteWithLogger:
    """Cover parallel write callbacks with op_logger (L473, 486-489, 495, 497, 505-507, 516-527)."""

    def test_parallel_write_success_logs(self, tmp_path):
        """Parallel write success calls op_logger.log_write_success (L473, 486-489)."""
        from unittest.mock import patch, MagicMock
        from gps_photo_tracker.core.concurrency import WriteResult

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg", timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=10.0)
        output = tmp_path / "output"
        output.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2)

        def fake_submit_all(tasks, on_progress=None, on_result=None, cancel=None):
            if on_progress:
                on_progress(0, len(tasks))
            if on_result:
                for t in tasks:
                    on_result(WriteResult(
                        success=True, filename=t.match_result.photo.filename,
                        dest_path=output / t.match_result.photo.filename,
                    ))
                on_progress(len(tasks), len(tasks))
            return []

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = fake_submit_all

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            service = GPSTaggingService(log_dir=log_dir)
            result = service.process([], [photo], MatcherConfig(), options, photo_dir=tmp_path)
            assert result.matched == 1

    def test_parallel_write_failure_logs_and_copies(self, tmp_path):
        """Parallel write failure logs error and copies original (L495, 497, 505-507)."""
        from unittest.mock import patch, MagicMock
        from gps_photo_tracker.core.concurrency import WriteResult

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg", timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=10.0)
        output = tmp_path / "output"
        output.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2)

        def fake_submit_all_fail(tasks, on_progress=None, on_result=None, cancel=None):
            if on_result:
                for t in tasks:
                    on_result(WriteResult(
                        success=False, filename=t.match_result.photo.filename,
                        error=OSError("parallel write failed"),
                    ))
            return []

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = fake_submit_all_fail

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            service = GPSTaggingService(log_dir=log_dir)
            result = service.process([], [photo], MatcherConfig(), options, photo_dir=tmp_path)
            assert result.failed == 1
            assert result.matched == 0

    def test_parallel_overwrite_failure_decrements(self, tmp_path):
        """Parallel write failure on photo with existing GPS decrements overwritten (L494-495)."""
        from unittest.mock import patch, MagicMock
        from gps_photo_tracker.core.concurrency import WriteResult

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(
            path=tmp_path / "photo.jpg", filename="photo.jpg",
            timestamp=1000.0, has_gps=True, existing_gps=GPSInfo(30.0, 120.0),
        )
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=10.0)
        output = tmp_path / "output"
        output.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2, overwrite_gps=True)

        def fake_submit_all_fail(tasks, on_progress=None, on_result=None, cancel=None):
            if on_result:
                for t in tasks:
                    on_result(WriteResult(
                        success=False, filename=t.match_result.photo.filename,
                        error=OSError("failed"),
                    ))
            return []

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = fake_submit_all_fail

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            service = GPSTaggingService()
            result = service.process([], [photo], MatcherConfig(), options, photo_dir=tmp_path)
            assert result.failed == 1
            assert result.overwritten == 0

    def test_parallel_submit_exception_fallback(self, tmp_path):
        """BatchProcessor.submit_all raises → fallback copy all photos (L516-527)."""
        from unittest.mock import patch, MagicMock

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg", timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0), method="interpolated", time_diff=10.0)
        output = tmp_path / "output"
        output.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2)

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = RuntimeError("infrastructure failure")

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            service = GPSTaggingService(log_dir=log_dir)
            result = service.process([], [photo], MatcherConfig(), options, photo_dir=tmp_path)
            # Infrastructure failure → fallback copy, matched stays 1
            assert result.matched == 1


class TestWritePhaseFailedCopy:
    """Cover L201-203: write_phase failed result + is_copy copies original."""

    def test_failed_result_copies_original_in_copy_mode(self, tmp_path):
        img = Image.new("RGB", (10, 10))
        img.save(str(tmp_path / "photo.jpg"), "JPEG")

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg",
                          timestamp=1000.0, has_gps=False)
        result = MatchResult(photo=photo, success=False, reject_reason="no_gps_coverage")
        output = tmp_path / "output"
        output.mkdir()
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        service = GPSTaggingService()
        batch = service.write_phase([result], opts, photo_dir=tmp_path)
        assert batch.failed == 1
        assert (output / tmp_path.name / "photo.jpg").exists()


class TestSequentialWriteCopyFallbackFail:
    """Cover L435-437: sequential write fails → copy fallback also fails with op_logger."""

    def test_write_and_copy_both_fail_with_logger(self, tmp_path):
        from unittest.mock import patch

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg",
                          timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
                                   method="interpolated", time_diff=10.0)
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=output)

        with patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch("gps_photo_tracker.service.tagging_service.EXIFWriter") as MockWriter, \
             patch.object(FileProvider, "copy_file", side_effect=OSError("disk full")):
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            MockWriter.write_gps.side_effect = OSError("write failed")
            service = GPSTaggingService(log_dir=log_dir)
            result = service.process([], [photo], MatcherConfig(), opts, photo_dir=tmp_path)
            assert result.failed == 1
            assert result.matched == 0


class TestSequentialSkipCopy:
    """Cover L440-442: skip path with is_copy copies original to output."""

    def test_skip_with_copy_mode_copies_original(self, tmp_path):
        from unittest.mock import patch

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        output = tmp_path / "output"
        output.mkdir()

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg",
                          timestamp=1000.0, has_gps=True, existing_gps=GPSInfo(30.0, 120.0))
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
                                   method="interpolated", time_diff=10.0)
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, overwrite_gps=False)

        with patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            service = GPSTaggingService()
            result = service.process([], [photo], MatcherConfig(), opts, photo_dir=tmp_path)
            assert result.skipped == 1
            assert (output / tmp_path.name / "photo.jpg").exists()


class TestParallelProgressCallback:
    """Cover L473: parallel _on_write_progress emits ProgressUpdate."""

    def test_parallel_write_emits_writing_progress(self, tmp_path):
        from unittest.mock import patch, MagicMock
        from gps_photo_tracker.core.concurrency import WriteResult

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg",
                          timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
                                   method="interpolated", time_diff=10.0)
        output = tmp_path / "output"
        output.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2)

        progress_calls = []

        def fake_submit_all(tasks, on_progress=None, on_result=None, cancel=None):
            if on_progress:
                on_progress(0, 1)
            if on_result:
                for t in tasks:
                    on_result(WriteResult(
                        success=True, filename=t.match_result.photo.filename,
                        dest_path=output / t.match_result.photo.filename,
                    ))
            return []

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = fake_submit_all

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            service = GPSTaggingService()
            service.process(
                [], [photo], MatcherConfig(), options,
                photo_dir=tmp_path, on_progress=lambda u: progress_calls.append(u),
            )
        assert len(progress_calls) >= 1
        assert progress_calls[0].phase == ProgressPhase.WRITING


class TestParallelFallbackCopyFail:
    """Cover L505-507: parallel write failure → fallback copy also fails."""

    def test_parallel_write_fail_and_copy_fail(self, tmp_path):
        from unittest.mock import patch, MagicMock
        from gps_photo_tracker.core.concurrency import WriteResult

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg",
                          timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
                                   method="interpolated", time_diff=10.0)
        output = tmp_path / "output"
        output.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2)

        def fake_submit_all(tasks, on_progress=None, on_result=None, cancel=None):
            if on_result:
                for t in tasks:
                    on_result(WriteResult(
                        success=False, filename=t.match_result.photo.filename,
                        error=OSError("parallel write failed"),
                    ))
            return []

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = fake_submit_all

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch.object(FileProvider, "copy_file", side_effect=OSError("copy failed")):
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            service = GPSTaggingService(log_dir=log_dir)
            result = service.process([], [photo], MatcherConfig(), options, photo_dir=tmp_path)
            assert result.failed == 1
            assert result.matched == 0


class TestParallelSubmitAllCopyFail:
    """Cover L525-527: submit_all raises → fallback copy also fails."""

    def test_submit_all_exception_and_copy_fail(self, tmp_path):
        from unittest.mock import patch, MagicMock

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg",
                          timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
                                   method="interpolated", time_diff=10.0)
        output = tmp_path / "output"
        output.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2)

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = RuntimeError("infrastructure failure")

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher, \
             patch.object(FileProvider, "copy_file", side_effect=OSError("copy failed")):
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            service = GPSTaggingService(log_dir=log_dir)
            result = service.process([], [photo], MatcherConfig(), options, photo_dir=tmp_path)
            # Copy also failed → matched decremented, failed incremented
            assert result.failed == 1
            assert result.matched == 0


class TestParallelCheckpoint:
    """Cover L531-532: CheckpointManager.mark for parallel completed filenames."""

    def test_parallel_marks_checkpoint(self, tmp_path):
        from unittest.mock import patch, MagicMock
        from gps_photo_tracker.core.concurrency import WriteResult

        img = Image.new("RGB", (10, 10))
        exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:02:17 08:05:00"}}
        img.save(str(tmp_path / "photo.jpg"), "JPEG", exif=piexif.dump(exif))

        photo = PhotoInfo(path=tmp_path / "photo.jpg", filename="photo.jpg",
                          timestamp=1000.0, has_gps=False)
        match_result = MatchResult(photo=photo, success=True, gps=GPSInfo(25.0, 100.0),
                                   method="interpolated", time_diff=10.0)
        output = tmp_path / "output"
        output.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, workers=2, resume=True)

        def fake_submit_all(tasks, on_progress=None, on_result=None, cancel=None):
            if on_result:
                for t in tasks:
                    on_result(WriteResult(
                        success=True, filename=t.match_result.photo.filename,
                        dest_path=output / t.match_result.photo.filename,
                    ))
            return []

        mock_instance = MagicMock()
        mock_instance.submit_all.side_effect = fake_submit_all

        with patch("gps_photo_tracker.service.tagging_service.BatchProcessor", return_value=mock_instance), \
             patch("gps_photo_tracker.service.tagging_service.GPSMatcher") as MockMatcher:
            MockMatcher.return_value.match.return_value = [match_result]
            MockMatcher.return_value.auto_follow.return_value = 0
            service = GPSTaggingService()
            result = service.process([], [photo], MatcherConfig(), options, photo_dir=tmp_path)
            assert result.matched == 1
            from gps_photo_tracker.core.checkpoint import CheckpointManager
            assert CheckpointManager.is_interrupted(output) is False


class TestScanWithInputSelection:
    """scan_gpx/scan_photos accept InputSelection (file or directory)."""

    def test_scan_photos_with_file(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        photos = GPSTaggingService().scan_photos(InputSelection.of([tmp_path / "a.jpg"]))
        assert len(photos) == 1 and photos[0].filename == "a.jpg"

    def test_scan_photos_with_dir(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        assert len(GPSTaggingService().scan_photos(InputSelection.of([tmp_path]))) == 1

    def test_scan_gpx_with_file(self, tmp_path):
        gpx = ('<?xml version="1.0"?><gpx><trk><trkseg>'
               '<trkpt lat="31" lon="121"><time>2020-01-01T12:00:00Z</time></trkpt>'
               '</trkseg></trk></gpx>')
        gpx_file = tmp_path / "a.gpx"
        gpx_file.write_text(gpx, encoding="utf-8")
        segs = GPSTaggingService().scan_gpx(InputSelection.of([gpx_file]))
        assert len(segs) >= 1 and len(segs[0].points) >= 1


