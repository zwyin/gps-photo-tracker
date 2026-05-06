"""Tests for EF-03 BatchProcessor."""
from pathlib import Path
from unittest.mock import patch, MagicMock

from gps_photo_tracker.core.concurrency import BatchProcessor, WriteTask, WriteResult
from gps_photo_tracker.core.models import (
    GPSInfo, MatchResult, PhotoInfo, ProcessMode, ProcessOptions,
)


def _make_task(filename="photo.jpg") -> WriteTask:
    photo = PhotoInfo(path=Path(f"/{filename}"), filename=filename,
                      timestamp=1.0, has_gps=False)
    match = MatchResult(photo=photo, success=True, gps=GPSInfo(35.0, 139.0))
    opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=Path("/out"))
    return WriteTask(match_result=match, options=opts, photo_dir=Path("/photos"))


class TestWriteTaskResult:
    def test_write_task_dataclass(self):
        task = _make_task()
        assert task.match_result.photo.filename == "photo.jpg"
        assert task.options.mode == ProcessMode.COPY

    def test_write_result_dataclass(self):
        r = WriteResult(success=True, filename="test.jpg", error=None, dest_path=None)
        assert r.success is True
        assert r.filename == "test.jpg"


class TestBatchProcessorSequential:
    def test_single_worker_returns_results(self):
        with patch("gps_photo_tracker.core.concurrency.execute_task") as mock_exec:
            mock_exec.return_value = WriteResult(success=True, filename="photo.jpg")
            bp = BatchProcessor(workers=1)
            results = bp.submit_all([_make_task()])
            assert len(results) == 1
            assert results[0].success is True

    def test_on_progress_called(self):
        with patch("gps_photo_tracker.core.concurrency.execute_task") as mock_exec:
            mock_exec.return_value = WriteResult(success=True, filename="a.jpg")
            bp = BatchProcessor(workers=1)
            progress_calls = []
            bp.submit_all([_make_task()], on_progress=lambda i, t: progress_calls.append(i))
            assert len(progress_calls) == 1

    def test_on_result_called(self):
        with patch("gps_photo_tracker.core.concurrency.execute_task") as mock_exec:
            mock_exec.return_value = WriteResult(success=True, filename="a.jpg")
            bp = BatchProcessor(workers=1)
            result_calls = []
            bp.submit_all([_make_task()], on_result=lambda r: result_calls.append(r))
            assert len(result_calls) == 1
            assert isinstance(result_calls[0], WriteResult)

    def test_cancel_stops_processing(self):
        from gps_photo_tracker.service.cancel_token import CancellationToken
        with patch("gps_photo_tracker.core.concurrency.execute_task") as mock_exec:
            bp = BatchProcessor(workers=1)
            cancel = CancellationToken()
            cancel.cancel()
            results = bp.submit_all([_make_task()], cancel=cancel)
            assert len(results) == 0
            mock_exec.assert_not_called()

    def test_multiple_tasks(self):
        with patch("gps_photo_tracker.core.concurrency.execute_task") as mock_exec:
            mock_exec.side_effect = [
                WriteResult(success=True, filename="a.jpg"),
                WriteResult(success=True, filename="b.jpg"),
            ]
            bp = BatchProcessor(workers=1)
            results = bp.submit_all([_make_task("a.jpg"), _make_task("b.jpg")])
            assert len(results) == 2


class TestBatchProcessorParallel:
    def test_multi_worker_uses_executor(self):
        with patch("gps_photo_tracker.core.concurrency.ProcessPoolExecutor") as MockExec:
            mock_future = MagicMock()
            mock_future.result.return_value = WriteResult(success=True, filename="a.jpg")
            ctx = MagicMock()
            ctx.submit.return_value = mock_future
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            MockExec.return_value = ctx

            # Mock as_completed to return the future
            with patch("gps_photo_tracker.core.concurrency.as_completed", return_value=[mock_future]):
                bp = BatchProcessor(workers=2)
                results = bp.submit_all([_make_task()])
                assert len(results) == 1
                MockExec.assert_called_once_with(max_workers=2)
