"""Tests for core.path_layout.lowest_common_ancestor."""
from pathlib import Path

from gps_photo_tracker.core.path_layout import lowest_common_ancestor as lca


def test_lca_siblings_is_parent():
    assert lca([Path("/photos/t1/a.jpg"), Path("/photos/t2/b.jpg")]) == Path("/photos")


def test_lca_nested():
    assert lca([Path("/photos/t1/a.jpg"), Path("/photos/t1/sub/b.jpg")]) == Path("/photos/t1")


def test_lca_empty_is_none():
    assert lca([]) is None


def test_lca_single_file_is_parent():
    assert lca([Path("/photos/x/a.jpg")]) == Path("/photos/x")


def test_lca_different_top_dirs_is_root():  # POSIX: 共享 '/'
    assert lca([Path("/photos/a.jpg"), Path("/var/b.jpg")]) == Path("/")
