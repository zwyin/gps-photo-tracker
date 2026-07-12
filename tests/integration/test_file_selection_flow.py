"""Integration tests: file-or-directory selection → scan → COPY (T12).

End-to-end coverage for the file-selection feature (Tasks 1-11):
  - InputSelection.of([file, file]) resolves to exactly those files (T3)
  - scan_photos keeps them because they have EXIF DateTimeOriginal inside the
    GPX time range (without that timestamp, scan_photos filters them out and
    zero writes happen — the round-1 B3 bug)
  - COPY with photo_root = lowest_common_ancestor(...) (T2) drives
    _copy_destination's real branches: flat-relative file →
    output/<photo_root.name>/<file>; nested file → output/<rel> (T9)
  - Two same-named photos in different dirs survive (no collision / data loss)
    thanks to file-selection forcing keep_structure + LCA (T9 + T2)
"""

from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image

from gps_photo_tracker.core.models import (
    InputSelection,
    MatcherConfig,
    ProcessMode,
    ProcessOptions,
)
from gps_photo_tracker.core.path_layout import lowest_common_ancestor
from gps_photo_tracker.service.tagging_service import GPSTaggingService

# GPX below spans 2020-01-01T11:55:00Z - 12:05:00Z. The photo must fall inside
# that UTC window or GPSMatcher rejects it with `no_gps_coverage` and COPY
# writes nothing. EXIFWriter.read_datetime treats DateTimeOriginal as naive
# LOCAL time and converts via datetime.timestamp(), so we compute the local
# string that round-trips to the GPX midpoint UTC epoch — this keeps the test
# correct on any runner TZ (UTC, UTC+8, …). Round-trip identity:
#   strptime(local_str).timestamp() == _GPX_MID_UTC_EPOCH
_GPX_MID_UTC_EPOCH = 1577880000  # 2020-01-01T12:00:00Z
_PHOTO_DT = (
    datetime.fromtimestamp(_GPX_MID_UTC_EPOCH).strftime("%Y:%m:%d %H:%M:%S").encode()
)


def _jpg_with_exif(p: Path, dt: bytes = _PHOTO_DT) -> None:
    """Create a minimal JPEG with EXIF DateTimeOriginal.

    DateTimeOriginal lives in piexif.ExifIFD (IFD key "Exif"), NOT in
    piexif.ImageIFD — verified: piexif.ImageIFD.DateTimeOriginal raises
    AttributeError. Without this tag, scan_photos yields PhotoInfo.timestamp
    is None and the matcher filters the photo out.
    """
    img = Image.new("RGB", (10, 10))
    exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: dt}}
    img.save(p, "JPEG", exif=piexif.dump(exif))


def _gpx(p: Path) -> None:
    """Write a minimal GPX whose track spans 11:55:00 - 12:05:00 UTC."""
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        "<trk><trkseg>"
        '<trkpt lat="31.0" lon="121.0"><time>2020-01-01T11:55:00Z</time></trkpt>'
        '<trkpt lat="31.0" lon="121.0"><time>2020-01-01T12:05:00Z</time></trkpt>'
        "</trkseg></trk></gpx>",
        encoding="utf-8",
    )


class TestFileSelectionCopyFlow:
    """Tie together: InputSelection → scan_photos → LCA → COPY → _copy_destination."""

    def test_files_selection_copy_preserves_relative(self, tmp_path):
        """File selection + LCA photo_root → real relative output paths.

        Layout under tmp_path/src:
            trip1/x.jpg       (rel to photo_root=trip1 → "x.jpg", flat)
            trip1/sub/y.jpg   (rel to photo_root=trip1 → "sub/y.jpg", nested)
        _copy_destination branches:
            flat  → output/<photo_root.name>/<file>      == out/trip1/x.jpg
            nested→ output/<rel>                          == out/sub/y.jpg
        """
        root = tmp_path / "src"
        sub = root / "trip1" / "sub"
        sub.mkdir(parents=True)
        gpx = root / "a.gpx"
        _gpx(gpx)
        p1 = root / "trip1" / "x.jpg"
        p2 = root / "trip1" / "sub" / "y.jpg"
        _jpg_with_exif(p1)
        _jpg_with_exif(p2)

        out = tmp_path / "out"
        out.mkdir()

        svc = GPSTaggingService()
        segs = svc.scan_gpx(InputSelection.of([gpx]))
        photos = svc.scan_photos(InputSelection.of([p1, p2]))
        # File selection → exactly the two files (no directory recursion).
        assert {ph.path for ph in photos} == {p1, p2}
        # LCA of {p1.parent, p2.parent} == .../src/trip1
        photo_root = lowest_common_ancestor([ph.path for ph in photos])
        assert photo_root == (root / "trip1").resolve()

        result = svc.process(
            segs,
            photos,
            MatcherConfig(),
            ProcessOptions(
                mode=ProcessMode.COPY,
                output_dir=out,
                keep_structure=True,
            ),
            photo_dir=photo_root,
        )

        # Both photos are within the GPX time range → both matched + written.
        assert result.matched == 2
        # _copy_destination real branches (see docstring):
        assert (out / "trip1" / "x.jpg").exists()  # p1: rel=x.jpg flat
        assert (out / "sub" / "y.jpg").exists()  # p2: rel=sub/y.jpg nested

    def test_same_name_different_dir_not_collide(self, tmp_path):
        """Two IMG_001.jpg in different dirs → both written, distinct paths.

        File selection forces keep_structure=True (T9) and LCA of the two
        parent dirs is tmp_path itself (T2). Each photo's rel-to-LCA is
        a/IMG_001.jpg / b/IMG_001.jpg → distinct output paths, no overwrite
        (no data loss — the bug T10 fixes via full-path keying).
        """
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        d2.mkdir()
        gpx = tmp_path / "t.gpx"
        _gpx(gpx)
        f1 = d1 / "IMG_001.jpg"
        f2 = d2 / "IMG_001.jpg"
        _jpg_with_exif(f1)
        _jpg_with_exif(f2)

        out = tmp_path / "out"
        out.mkdir()

        svc = GPSTaggingService()
        segs = svc.scan_gpx(InputSelection.of([gpx]))
        photos = svc.scan_photos(InputSelection.of([f1, f2]))
        assert {ph.path for ph in photos} == {f1, f2}
        photo_root = lowest_common_ancestor([ph.path for ph in photos])
        assert photo_root == tmp_path.resolve()

        result = svc.process(
            segs,
            photos,
            MatcherConfig(),
            ProcessOptions(
                mode=ProcessMode.COPY,
                output_dir=out,
                keep_structure=True,
            ),
            photo_dir=photo_root,
        )

        assert result.matched == 2
        # Both same-named photos survive; distinct output paths.
        written = sorted(out.rglob("IMG_001.jpg"))
        assert len(written) == 2
        assert {w.relative_to(out) for w in written} == {
            Path("a") / "IMG_001.jpg",
            Path("b") / "IMG_001.jpg",
        }
