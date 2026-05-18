"""Tests for EXIFWriter."""

import piexif
import pytest
from pathlib import Path
from PIL import Image

from gps_photo_tracker.core.exif_writer import EXIFWriter
from gps_photo_tracker.core.models import GPSInfo, EXIFReadError, EXIFWriteError


def _create_jpeg(path: Path, exif_dict: dict | None = None) -> Path:
    """Create a minimal JPEG file for testing."""
    img = Image.new("RGB", (100, 100), color="red")
    if exif_dict is not None:
        exif_bytes = piexif.dump(exif_dict)
        img.save(path, "JPEG", exif=exif_bytes)
    else:
        img.save(path, "JPEG")
    return path


def _make_exif_with_datetime(dt_str: str) -> dict:
    """Create EXIF dict with DateTimeOriginal in Exif IFD."""
    return {"Exif": {piexif.ExifIFD.DateTimeOriginal: dt_str}}


def _make_exif_with_gps(lat: float, lon: float, alt: float | None = None) -> dict:
    """Create EXIF dict with GPS IFD."""
    gps_ifd = {}
    gps_ifd[piexif.GPSIFD.GPSVersionID] = (2, 3, 0, 0)

    lat_ref = b'N' if lat >= 0 else b'S'
    lon_ref = b'E' if lon >= 0 else b'W'
    gps_ifd[piexif.GPSIFD.GPSLatitudeRef] = lat_ref
    gps_ifd[piexif.GPSIFD.GPSLongitudeRef] = lon_ref
    gps_ifd[piexif.GPSIFD.GPSLatitude] = EXIFWriter._to_dms_rational(abs(lat))
    gps_ifd[piexif.GPSIFD.GPSLongitude] = EXIFWriter._to_dms_rational(abs(lon))

    if alt is not None:
        gps_ifd[piexif.GPSIFD.GPSAltitudeRef] = 0 if alt >= 0 else 1
        gps_ifd[piexif.GPSIFD.GPSAltitude] = (int(abs(alt) * 100), 100)

    return {"GPS": gps_ifd}


# ── DMS conversion tests ──────────────────────────────────

class TestDMSConversion:

    def test_positive_latitude(self):
        result = EXIFWriter._to_dms_rational(25.953)
        degrees, minutes, seconds = result
        assert degrees == (25, 1)
        assert minutes == (57, 1)
        # 0.953 * 60 = 57.18, 0.18 * 60 = 10.8, 10.8 * 10000 = 108000
        # Float precision: 0.953 * 60 = 57.18, 0.18 * 60 = 10.8, 10.8 * 10000 ≈ 108000
        assert abs(seconds[0] - 108000) <= 1
        assert seconds[1] == 10000

    def test_integer_degree(self):
        result = EXIFWriter._to_dms_rational(25.0)
        assert result == ((25, 1), (0, 1), (0, 10000))

    def test_negative_value(self):
        """_to_dms_rational receives abs value, so always positive."""
        result = EXIFWriter._to_dms_rational(abs(-25.5))
        assert result[0] == (25, 1)
        assert result[1] == (30, 1)

    def test_altitude_rational_positive(self):
        assert EXIFWriter._to_altitude_rational(1810.6) == (181060, 100)

    def test_altitude_rational_zero(self):
        assert EXIFWriter._to_altitude_rational(0.0) == (0, 100)

    def test_altitude_rational_negative(self):
        """Altitude rational takes abs value."""
        assert EXIFWriter._to_altitude_rational(-50.3) == (5030, 100)


# ── Read tests ────────────────────────────────────────────

class TestReadDatetime:

    def test_read_datetime_original(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "test.jpg", _make_exif_with_datetime("2026:02:17 08:00:00"))
        ts = EXIFWriter.read_datetime(jpg)
        assert ts is not None
        # Verify it's a reasonable UTC timestamp for 2026-02-17 08:00:00
        from datetime import datetime, timezone
        expected = datetime(2026, 2, 17, 8, 0, 0).timestamp()
        assert abs(ts - expected) < 1.0

    def test_read_datetime_no_exif(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "test.jpg")
        assert EXIFWriter.read_datetime(jpg) is None

    def test_read_datetime_no_datetime_field(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "test.jpg", {"0th": {}})
        assert EXIFWriter.read_datetime(jpg) is None

    def test_read_datetime_invalid_format(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "test.jpg", _make_exif_with_datetime("not-a-date"))
        assert EXIFWriter.read_datetime(jpg) is None

    def test_read_datetime_nonexistent_file(self):
        with pytest.raises(EXIFReadError):
            EXIFWriter.read_datetime(Path("/nonexistent/file.jpg"))


class TestReadGPS:

    def test_read_gps_present(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "test.jpg", _make_exif_with_gps(25.953, 102.758, 1810.6))
        gps = EXIFWriter.read_gps(jpg)
        assert gps is not None
        assert abs(gps.latitude - 25.953) < 0.001
        assert abs(gps.longitude - 102.758) < 0.001
        assert abs(gps.altitude - 1810.6) < 0.1

    def test_read_gps_no_gps(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "test.jpg")
        assert EXIFWriter.read_gps(jpg) is None

    def test_read_gps_no_altitude(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "test.jpg", _make_exif_with_gps(25.0, 100.0))
        gps = EXIFWriter.read_gps(jpg)
        assert gps is not None
        assert gps.altitude is None

    def test_read_gps_nonexistent_file(self):
        with pytest.raises(EXIFReadError):
            EXIFWriter.read_gps(Path("/nonexistent/file.jpg"))


# ── Write tests ───────────────────────────────────────────

class TestWriteGPS:

    def test_write_gps_basic(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.953, longitude=102.758, altitude=1810.6)

        EXIFWriter.write_gps(jpg, dst, gps)

        # Verify by reading back
        result = EXIFWriter.read_gps(dst)
        assert result is not None
        assert abs(result.latitude - 25.953) < 0.001
        assert abs(result.longitude - 102.758) < 0.001
        assert abs(result.altitude - 1810.6) < 0.1

    def test_write_gps_in_place(self, tmp_path):
        """src == dst should work (overwrite mode)."""
        jpg = _create_jpeg(tmp_path / "test.jpg")
        gps = GPSInfo(latitude=25.0, longitude=100.0, altitude=1000.0)

        EXIFWriter.write_gps(jpg, jpg, gps)

        result = EXIFWriter.read_gps(jpg)
        assert result is not None
        assert abs(result.latitude - 25.0) < 0.001

    def test_write_gps_zero_altitude(self, tmp_path):
        """altitude=0 must be written, not skipped."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0, altitude=0.0)

        EXIFWriter.write_gps(jpg, dst, gps)

        result = EXIFWriter.read_gps(dst)
        assert result is not None
        assert result.altitude is not None
        assert abs(result.altitude) < 0.1

    def test_write_gps_none_altitude(self, tmp_path):
        """altitude=None → no altitude tags."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0, altitude=None)

        EXIFWriter.write_gps(jpg, dst, gps)

        exif_dict = piexif.load(str(dst))
        gps_ifd = exif_dict.get("GPS", {})
        assert piexif.GPSIFD.GPSAltitude not in gps_ifd
        assert piexif.GPSIFD.GPSAltitudeRef not in gps_ifd

    def test_write_gps_negative_altitude(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0, altitude=-50.3)

        EXIFWriter.write_gps(jpg, dst, gps)

        exif_dict = piexif.load(str(dst))
        gps_ifd = exif_dict.get("GPS", {})
        assert gps_ifd[piexif.GPSIFD.GPSAltitudeRef] == 1  # below sea level

    def test_write_gps_negative_latitude(self, tmp_path):
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=-33.8688, longitude=151.2093, altitude=10.0)

        EXIFWriter.write_gps(jpg, dst, gps)

        result = EXIFWriter.read_gps(dst)
        assert result is not None
        assert abs(result.latitude - (-33.8688)) < 0.001
        assert abs(result.longitude - 151.2093) < 0.001

    def test_write_gps_preserves_existing_exif(self, tmp_path):
        """Writing GPS should not destroy other EXIF fields."""
        exif = _make_exif_with_datetime("2026:02:17 08:00:00")
        jpg = _create_jpeg(tmp_path / "src.jpg", exif)
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0, altitude=100.0)

        EXIFWriter.write_gps(jpg, dst, gps)

        # DateTimeOriginal should still be there in Exif IFD
        exif_dict = piexif.load(str(dst))
        assert piexif.ExifIFD.DateTimeOriginal in exif_dict.get("Exif", {})

    def test_write_gps_gps_version_id(self, tmp_path):
        """GPS Version ID must be (2, 3, 0, 0)."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0)

        EXIFWriter.write_gps(jpg, dst, gps)

        exif_dict = piexif.load(str(dst))
        assert exif_dict["GPS"][piexif.GPSIFD.GPSVersionID] == (2, 3, 0, 0)

    def test_write_gps_src_not_exists(self, tmp_path):
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0)
        with pytest.raises(EXIFWriteError):
            EXIFWriter.write_gps(Path("/nonexistent.jpg"), dst, gps)

    def test_write_gps_verification_roundtrip(self, tmp_path):
        """Write then read back — error must be < 0.001 degree."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.953, longitude=102.758, altitude=1810.6)

        EXIFWriter.write_gps(jpg, dst, gps)

        result = EXIFWriter.read_gps(dst)
        assert result is not None
        assert abs(result.latitude - gps.latitude) < 0.001
        assert abs(result.longitude - gps.longitude) < 0.001


class TestEXIFWriterEdgeCases:
    """Cover: DateTime fallback, piexif.load failure, GPS key missing,
    piexif.dump failure, verification failures."""

    def test_read_datetime_fallback_0th_ifd(self, tmp_path):
        """DateTime in 0th IFD (not Exif) should be read."""
        exif = {"0th": {piexif.ImageIFD.DateTime: "2026:03:15 10:30:00"}}
        jpg = _create_jpeg(tmp_path / "dt_0th.jpg", exif)
        ts = EXIFWriter.read_datetime(jpg)
        assert ts is not None

    def test_write_gps_piexif_load_failure(self, tmp_path, monkeypatch):
        """When piexif.load fails on write, should use fresh exif_dict."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0)

        original_load = piexif.load
        call_count = [0]

        def flaky_load(path):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("corrupt")
            return original_load(path)

        monkeypatch.setattr(piexif, "load", flaky_load)
        EXIFWriter.write_gps(jpg, dst, gps)
        result = EXIFWriter.read_gps(dst)
        assert result is not None

    def test_write_gps_no_gps_key_in_exif(self, tmp_path, monkeypatch):
        """When loaded exif_dict has no GPS key, should add it."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0)

        original_load = piexif.load
        call_count = [0]

        def load_no_gps(path):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"0th": {}, "Exif": {}}  # no GPS key
            return original_load(path)

        monkeypatch.setattr(piexif, "load", load_no_gps)
        EXIFWriter.write_gps(jpg, dst, gps)
        result = EXIFWriter.read_gps(dst)
        assert result is not None

    def test_write_gps_dump_failure_raises(self, tmp_path, monkeypatch):
        """piexif.dump failure should raise EXIFWriteError."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0)

        monkeypatch.setattr(piexif, "dump", lambda d: (_ for _ in ()).throw(RuntimeError("dump error")))
        with pytest.raises(EXIFWriteError, match="serialize"):
            EXIFWriter.write_gps(jpg, dst, gps)

    def test_write_gps_verify_no_gps_raises(self, tmp_path, monkeypatch):
        """Verification finds no GPS data should raise EXIFWriteError."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0)

        # After piexif.insert writes, read_gps returns None
        monkeypatch.setattr(EXIFWriter, "read_gps", lambda p: None)
        with pytest.raises(EXIFWriteError, match="no GPS"):
            EXIFWriter.write_gps(jpg, dst, gps)

    def test_write_gps_verify_latitude_mismatch_raises(self, tmp_path, monkeypatch):
        """Latitude verification mismatch should raise EXIFWriteError."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0)

        from gps_photo_tracker.core.models import GPSInfo as GI

        original_read_gps = EXIFWriter.read_gps
        monkeypatch.setattr(EXIFWriter, "read_gps",
                            lambda p: GI(latitude=99.0, longitude=100.0))
        with pytest.raises(EXIFWriteError, match="Latitude"):
            EXIFWriter.write_gps(jpg, dst, gps)

    def test_write_gps_verify_longitude_mismatch_raises(self, tmp_path, monkeypatch):
        """Longitude verification mismatch should raise EXIFWriteError."""
        jpg = _create_jpeg(tmp_path / "src.jpg")
        dst = tmp_path / "out.jpg"
        gps = GPSInfo(latitude=25.0, longitude=100.0)

        from gps_photo_tracker.core.models import GPSInfo as GI

        monkeypatch.setattr(EXIFWriter, "read_gps",
                            lambda p: GI(latitude=25.0, longitude=99.0))
        with pytest.raises(EXIFWriteError, match="Longitude"):
            EXIFWriter.write_gps(jpg, dst, gps)
