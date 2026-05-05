"""EXIF reader/writer for GPS tagging.

Reads photo timestamps and GPS data from EXIF.
Writes GPS coordinates into EXIF using piexif.
"""

from datetime import datetime
from pathlib import Path

import piexif

from gps_photo_tracker.core.models import EXIFReadError, EXIFWriteError, GPSInfo


class EXIFWriter:
    """Read and write GPS EXIF data in JPEG files."""

    @staticmethod
    def _to_dms_rational(decimal: float) -> tuple:
        """Convert decimal degrees to EXIF GPS DMS rational format."""
        degrees = int(decimal)
        minutes_decimal = (decimal - degrees) * 60
        minutes = int(minutes_decimal)
        seconds = (minutes_decimal - minutes) * 60
        return ((degrees, 1), (minutes, 1), (int(seconds * 10000), 10000))

    @staticmethod
    def _to_altitude_rational(altitude: float) -> tuple:
        """Convert altitude to EXIF GPS rational format, 0.01m precision."""
        return (int(abs(altitude) * 100), 100)

    @staticmethod
    def read_datetime(path: Path) -> float | None:
        """Read photo capture time from EXIF, return UTC timestamp.

        Priority: DateTimeOriginal > DateTimeDigitized > DateTime.
        EXIF time is naive local time; converted to UTC via mktime.
        """
        try:
            exif_dict = piexif.load(str(path))
        except Exception as e:
            raise EXIFReadError(f"Cannot read EXIF from {path}: {e}") from e

        # DateTimeOriginal and DateTimeDigitized are in Exif IFD
        _exif = exif_dict.get("Exif", {})
        for tag in (piexif.ExifIFD.DateTimeOriginal,
                    piexif.ExifIFD.DateTimeDigitized):
            dt_str = _exif.get(tag)
            if dt_str:
                return EXIFWriter._parse_exif_datetime(dt_str)

        # DateTime is in 0th IFD
        dt_str = exif_dict.get("0th", {}).get(piexif.ImageIFD.DateTime)
        if dt_str:
            return EXIFWriter._parse_exif_datetime(dt_str)
        return None

    @staticmethod
    def _parse_exif_datetime(dt_str) -> float | None:
        """Parse EXIF datetime string 'YYYY:MM:DD HH:MM:SS' to UTC timestamp."""
        try:
            if isinstance(dt_str, bytes):
                dt_str = dt_str.decode("ascii")
            dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
            return dt.timestamp()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def read_gps(path: Path) -> GPSInfo | None:
        """Read GPS coordinates from EXIF. Returns GPSInfo or None."""
        try:
            exif_dict = piexif.load(str(path))
        except Exception as e:
            raise EXIFReadError(f"Cannot read EXIF from {path}: {e}") from e

        gps_ifd = exif_dict.get("GPS", {})
        if not gps_ifd or piexif.GPSIFD.GPSLatitude not in gps_ifd:
            return None

        lat = EXIFWriter._dms_to_decimal(
            gps_ifd[piexif.GPSIFD.GPSLatitude],
            gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef, b'N'),
        )
        lon = EXIFWriter._dms_to_decimal(
            gps_ifd[piexif.GPSIFD.GPSLongitude],
            gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef, b'E'),
        )

        alt = None
        if piexif.GPSIFD.GPSAltitude in gps_ifd:
            alt_num, alt_den = gps_ifd[piexif.GPSIFD.GPSAltitude]
            alt = alt_num / alt_den
            if gps_ifd.get(piexif.GPSIFD.GPSAltitudeRef, 0) == 1:
                alt = -alt

        return GPSInfo(latitude=lat, longitude=lon, altitude=alt)

    @staticmethod
    def _dms_to_decimal(dms: tuple, ref: bytes) -> float:
        """Convert EXIF DMS rational tuple to decimal degrees."""
        degrees = dms[0][0] / dms[0][1]
        minutes = dms[1][0] / dms[1][1]
        seconds = dms[2][0] / dms[2][1]
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if ref in (b'S', b'W'):
            decimal = -decimal
        return decimal

    @staticmethod
    def write_gps(src: Path, dst: Path, gps: GPSInfo) -> None:
        """Write GPS data into EXIF. Preserves existing EXIF fields.

        Args:
            src: Source JPEG path.
            dst: Destination JPEG path (can be same as src for in-place).
            gps: GPS coordinates to write.
        """
        if not src.exists():
            raise EXIFWriteError(f"Source file not found: {src}")

        try:
            exif_dict = piexif.load(str(src))
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

        if "GPS" not in exif_dict:
            exif_dict["GPS"] = {}

        gps_ifd = exif_dict["GPS"]
        gps_ifd[piexif.GPSIFD.GPSVersionID] = (2, 3, 0, 0)

        gps_ifd[piexif.GPSIFD.GPSLatitudeRef] = b'N' if gps.latitude >= 0 else b'S'
        gps_ifd[piexif.GPSIFD.GPSLongitudeRef] = b'E' if gps.longitude >= 0 else b'W'
        gps_ifd[piexif.GPSIFD.GPSLatitude] = EXIFWriter._to_dms_rational(abs(gps.latitude))
        gps_ifd[piexif.GPSIFD.GPSLongitude] = EXIFWriter._to_dms_rational(abs(gps.longitude))

        if gps.altitude is not None:
            gps_ifd[piexif.GPSIFD.GPSAltitudeRef] = 0 if gps.altitude >= 0 else 1
            gps_ifd[piexif.GPSIFD.GPSAltitude] = EXIFWriter._to_altitude_rational(gps.altitude)
        else:
            gps_ifd.pop(piexif.GPSIFD.GPSAltitudeRef, None)
            gps_ifd.pop(piexif.GPSIFD.GPSAltitude, None)

        try:
            exif_bytes = piexif.dump(exif_dict)
        except Exception as e:
            raise EXIFWriteError(f"Failed to serialize EXIF: {e}") from e

        if src == dst:
            # In-place write
            piexif.insert(exif_bytes, str(dst))
        else:
            import shutil
            shutil.copy2(src, dst)
            piexif.insert(exif_bytes, str(dst))

        # Write verification: read back and check coordinates within 0.001°
        verify_gps = EXIFWriter.read_gps(dst)
        if verify_gps is None:
            raise EXIFWriteError(f"Write verification failed: no GPS data in {dst}")
        if abs(verify_gps.latitude - gps.latitude) > 0.001:
            raise EXIFWriteError(
                f"Latitude verification failed: expected {gps.latitude}, got {verify_gps.latitude}"
            )
        if abs(verify_gps.longitude - gps.longitude) > 0.001:
            raise EXIFWriteError(
                f"Longitude verification failed: expected {gps.longitude}, got {verify_gps.longitude}"
            )
