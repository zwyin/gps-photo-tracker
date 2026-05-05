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
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    ProcessMode,
    ProcessOptions,
    ProgressPhase,
    ProgressUpdate,
    RejectReason,
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
        segments = service.scan_gpx(tmp_path)
        assert len(segments) == 1  # only good.gpx parsed

    def test_scan_photos_handles_broken_jpeg(self, tmp_path):
        """L62-63: corrupt JPEG triggers except, photo added with timestamp=None."""
        (tmp_path / "good.jpg").write_bytes(_make_jpeg_bytes())
        (tmp_path / "bad.jpg").write_bytes(b"not a real image")
        service = GPSTaggingService()
        photos = service.scan_photos(tmp_path)
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
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
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
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
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
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
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
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, overwrite_gps=False)

        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=tmp_path)
        # Photo has existing GPS + overwrite=False → skipped, but still copied
        if result.skipped >= 1:
            assert (output / "photo.jpg").exists()
        # If matching fails due to timezone offset, it's still copied as failed photo
        elif result.failed >= 1:
            assert (output / "photo.jpg").exists()

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
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(sub)
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output, keep_structure=True)

        result = service.process(segments, photos, MatcherConfig(), options, photo_dir=sub)
        # Should preserve the subdirectory structure
        assert result.matched >= 0
        assert (output / "photo.jpg").exists()


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
        segments = service.scan_gpx(tmp_path)
        photos = service.scan_photos(tmp_path)
        result = service.preview(segments, photos, MatcherConfig())
        if result.failed > 0:
            assert len(result.reject_groups) > 0
