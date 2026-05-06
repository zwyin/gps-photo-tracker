"""Tests for EF-10 OrientationReader."""
from pathlib import Path
from unittest.mock import patch

from gps_photo_tracker.core.orientation import OrientationReader


class TestGetOrientation:
    def test_no_exif_returns_none(self, tmp_path):
        """File with no EXIF should return None."""
        from PIL import Image
        img = Image.new("RGB", (10, 10))
        f = tmp_path / "no_exif.jpg"
        img.save(f)
        result = OrientationReader.get_orientation(f)
        assert result is None or result == 1

    def test_valid_orientation_values(self):
        import piexif
        for val in range(1, 9):
            with patch("gps_photo_tracker.core.orientation.piexif") as mock_piexif:
                mock_piexif.load.return_value = {"0th": {piexif.ImageIFD.Orientation: val}}
                mock_piexif.ImageIFD.Orientation = 274
                result = OrientationReader.get_orientation(Path("/fake/path.jpg"))
                assert result == val, f"Expected {val}, got {result}"

    def test_missing_orientation_tag_returns_none(self):
        import piexif
        with patch("gps_photo_tracker.core.orientation.piexif") as mock_piexif:
            mock_piexif.load.return_value = {"0th": {}}
            mock_piexif.ImageIFD.Orientation = 274
            result = OrientationReader.get_orientation(Path("/fake/path.jpg"))
            assert result is None

    def test_read_error_returns_none(self):
        with patch("gps_photo_tracker.core.orientation.piexif") as mock_piexif:
            mock_piexif.load.side_effect = Exception("read error")
            result = OrientationReader.get_orientation(Path("/fake/path.jpg"))
            assert result is None


class TestTransformMatrix:
    def test_orientation_1_no_transform(self):
        t = OrientationReader.transform_matrix(1)
        assert t.isIdentity()

    def test_orientation_6_not_identity(self):
        t = OrientationReader.transform_matrix(6)
        assert not t.isIdentity()

    def test_orientation_3_not_identity(self):
        t = OrientationReader.transform_matrix(3)
        assert not t.isIdentity()

    def test_invalid_orientation_returns_identity(self):
        t = OrientationReader.transform_matrix(99)
        assert t.isIdentity()

    def test_all_orientations_1_to_8(self):
        for val in range(1, 9):
            t = OrientationReader.transform_matrix(val)
            assert t is not None
