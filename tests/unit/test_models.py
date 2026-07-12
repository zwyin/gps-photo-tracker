"""Tests for core data models."""
from pathlib import Path

from gps_photo_tracker.core.models import InputSelection


def test_input_selection_empty_default():
    assert InputSelection().is_empty and InputSelection().paths == ()


def test_input_selection_of_dedups_and_keeps_order():
    sel = InputSelection.of([Path("/a/b.jpg"), Path("/a/b.jpg"), Path("/c.gpx")])
    assert sel.paths == (Path("/a/b.jpg"), Path("/c.gpx"))
