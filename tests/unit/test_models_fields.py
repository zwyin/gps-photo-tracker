"""Tests for new model fields added in v0.8.0."""
from pathlib import Path

from gps_photo_tracker.core.models import (
    BatchResult, PhotoInfo, ProcessOptions,
    ProcessMode,
)


def test_process_options_new_defaults():
    opts = ProcessOptions(mode=ProcessMode.PREVIEW)
    assert opts.resume is False
    assert opts.generate_report is False
    assert opts.workers == 1


def test_batch_result_concurrent_workers():
    r = BatchResult(total=10, matched=5, skipped=2, failed=3,
                    overwritten=0, success_rate=0.5, concurrent_workers=4)
    assert r.concurrent_workers == 4


def test_batch_result_default_workers():
    r = BatchResult(total=0, matched=0, skipped=0, failed=0,
                    overwritten=0, success_rate=0.0)
    assert r.concurrent_workers == 1


def test_photo_info_orientation_default():
    p = PhotoInfo(path=Path("/x.jpg"), filename="x.jpg",
                  timestamp=1.0, has_gps=False)
    assert p.orientation is None


def test_photo_info_orientation_set():
    p = PhotoInfo(path=Path("/x.jpg"), filename="x.jpg",
                  timestamp=1.0, has_gps=False, orientation=6)
    assert p.orientation == 6
