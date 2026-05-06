"""Tests for EF-04 CheckpointManager."""
import json
from pathlib import Path

from gps_photo_tracker.core.checkpoint import CheckpointManager


class TestCheckpointManager:
    def test_fresh_dir_no_checkpoint(self, tmp_path):
        assert CheckpointManager.is_interrupted(tmp_path) is False

    def test_create_and_load(self, tmp_path):
        CheckpointManager.create(tmp_path, total_photos=10)
        assert CheckpointManager.is_interrupted(tmp_path) is True
        completed = CheckpointManager.load(tmp_path)
        assert completed == set()

    def test_mark_and_load(self, tmp_path):
        CheckpointManager.create(tmp_path, total_photos=3)
        CheckpointManager.mark(tmp_path, "a.jpg")
        CheckpointManager.mark(tmp_path, "b.jpg")
        completed = CheckpointManager.load(tmp_path)
        assert completed == {"a.jpg", "b.jpg"}

    def test_complete_removes_file(self, tmp_path):
        CheckpointManager.create(tmp_path, total_photos=1)
        assert CheckpointManager.is_interrupted(tmp_path) is True
        CheckpointManager.complete(tmp_path)
        assert CheckpointManager.is_interrupted(tmp_path) is False

    def test_load_missing_file_returns_empty(self, tmp_path):
        assert CheckpointManager.load(tmp_path) == set()

    def test_checkpoint_file_format(self, tmp_path):
        CheckpointManager.create(tmp_path, total_photos=5)
        CheckpointManager.mark(tmp_path, "x.jpg")
        data = json.loads((tmp_path / ".checkpoint.json").read_text())
        assert data["version"] == 1
        assert data["total_photos"] == 5
        assert "x.jpg" in data["completed"]
        assert "started_at" in data

    def test_mark_after_complete_is_noop(self, tmp_path):
        CheckpointManager.create(tmp_path, total_photos=2)
        CheckpointManager.mark(tmp_path, "a.jpg")
        CheckpointManager.complete(tmp_path)
        assert CheckpointManager.is_interrupted(tmp_path) is False
