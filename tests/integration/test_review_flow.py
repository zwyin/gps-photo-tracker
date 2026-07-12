"""Integration test: match -> review -> apply -> write flow."""

import textwrap
from pathlib import Path

import piexif
from PIL import Image

from gps_photo_tracker.core.models import (
    GPXSegment,
    GPSInfo,
    InputSelection,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    ProcessMode,
    ProcessOptions,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    TrackPoint,
)
from gps_photo_tracker.service.tagging_service import GPSTaggingService


def _create_test_photo(path: Path, dt_bytes: bytes = b"2026:02:17 20:00:00"):
    """Create a minimal JPEG with EXIF DateTimeOriginal."""
    img = Image.new("RGB", (10, 10))
    exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: dt_bytes}}
    img.save(path, "JPEG", exif=piexif.dump(exif))


def _create_test_gpx(path: Path):
    """Create a GPX file with two track points 5 minutes apart."""
    gpx = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
      <trk><trkseg>
        <trkpt lat="25.0" lon="100.0"><time>2026-02-17T08:00:00Z</time></trkpt>
        <trkpt lat="25.001" lon="100.001"><time>2026-02-17T08:05:00Z</time></trkpt>
      </trkseg></trk>
    </gpx>
    """)
    path.write_text(gpx)


class TestReviewFlow:

    def test_full_review_flow_manual_gps(self, tmp_path):
        """Match fails -> user picks manual GPS -> apply_review -> write succeeds."""
        _create_test_gpx(tmp_path / "track.gpx")
        _create_test_photo(tmp_path / "photo.jpg")

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        config = MatcherConfig()

        # Phase 1: match (preview only, no write)
        result = service.preview(segments, photos, config)
        assert result.failed > 0

        # Phase 2: review — pick manual GPS for the failed photo
        state = service.prepare_review(result.results, segments)
        assert len(state.failed_results) > 0

        failed_photo = state.failed_results[0]
        state.decisions[str(failed_photo.photo.path)] = ReviewDecision(
            photo_path=str(failed_photo.photo.path),
            action=ReviewAction.MANUAL_GPS,
            selected_point=TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0),
        )
        modified = service.apply_review(result.results, state)
        assert modified[0].success is True
        assert modified[0].review_gps is not None

        # Phase 3: write the reviewed result to output
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output_dir)
        batch = service.write_phase(modified, options, photo_dir=tmp_path)
        assert batch.matched >= 1

        # Verify the output photo has GPS data
        from gps_photo_tracker.core.exif_writer import EXIFWriter
        output_photo = output_dir / tmp_path.name / "photo.jpg"
        assert output_photo.exists()
        written_gps = EXIFWriter.read_gps(output_photo)
        assert written_gps is not None
        assert abs(written_gps.latitude - 25.0) < 0.01

    def test_full_review_flow_skip(self, tmp_path):
        """Match fails -> user skips -> write skips the photo."""
        _create_test_gpx(tmp_path / "track.gpx")
        _create_test_photo(tmp_path / "photo.jpg")

        service = GPSTaggingService()
        segments = service.scan_gpx(InputSelection.of([tmp_path]))
        photos = service.scan_photos(InputSelection.of([tmp_path]))
        config = MatcherConfig()

        result = service.preview(segments, photos, config)
        state = service.prepare_review(result.results, segments)

        failed_photo = state.failed_results[0]
        state.decisions[str(failed_photo.photo.path)] = ReviewDecision(
            photo_path=str(failed_photo.photo.path),
            action=ReviewAction.SKIP,
        )
        modified = service.apply_review(result.results, state)
        assert modified[0].success is False

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        options = ProcessOptions(mode=ProcessMode.COPY, output_dir=output_dir)
        batch = service.write_phase(modified, options, photo_dir=tmp_path)
        assert batch.matched == 0
        assert batch.failed >= 1
        assert (output_dir / tmp_path.name / "photo.jpg").exists()
