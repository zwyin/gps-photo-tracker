"""Tests for EF-03 BatchProcessor."""
from pathlib import Path
from unittest.mock import patch, MagicMock

from gps_photo_tracker.core.concurrency import (
    BatchProcessor, WriteTask, WriteResult, execute_task, _copy_destination,
)
from gps_photo_tracker.core.models import (
    GPSInfo, MatchResult, PhotoInfo, ProcessMode, ProcessOptions,
)


def _make_task(filename="photo.jpg") -> WriteTask:
    photo = PhotoInfo(path=Path(f"/{filename}"), filename=filename,
                      timestamp=1.0, has_gps=False)
    match = MatchResult(photo=photo, success=True, gps=GPSInfo(35.0, 139.0))
    opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=Path("/out"))
    return WriteTask(match_result=match, options=opts, photo_dir=Path("/photos"))


def _create_jpeg(path: Path):
    """Create a minimal valid JPEG file for testing."""
    from PIL import Image
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(str(path))


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


class TestExecuteTask:
    """Direct tests for execute_task without mocking."""

    def test_no_gps_returns_failure(self):
        photo = PhotoInfo(path=Path("/a.jpg"), filename="a.jpg",
                          timestamp=1.0, has_gps=False)
        match = MatchResult(photo=photo, success=True, gps=None)
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=Path("/out"))
        task = WriteTask(match_result=match, options=opts)
        result = execute_task(task)
        assert not result.success
        assert "no GPS" in result.error

    def test_copy_mode_writes(self, tmp_path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        _create_jpeg(src)
        dst_dir = tmp_path / "out"
        dst_dir.mkdir()
        photo = PhotoInfo(path=src, filename="photo.jpg",
                          timestamp=1.0, has_gps=True)
        match = MatchResult(photo=photo, success=True, gps=GPSInfo(35.0, 139.0))
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=dst_dir)
        task = WriteTask(match_result=match, options=opts)
        result = execute_task(task)
        assert result.success
        assert result.dest_path is not None

    def test_overwrite_mode_writes(self, tmp_path):
        src = tmp_path / "photo.jpg"
        _create_jpeg(src)
        photo = PhotoInfo(path=src, filename="photo.jpg",
                          timestamp=1.0, has_gps=True)
        match = MatchResult(photo=photo, success=True, gps=GPSInfo(35.0, 139.0))
        opts = ProcessOptions(mode=ProcessMode.OVERWRITE)
        task = WriteTask(match_result=match, options=opts)
        result = execute_task(task)
        assert result.success

    def test_unsupported_mode_returns_failure(self):
        photo = PhotoInfo(path=Path("/a.jpg"), filename="a.jpg",
                          timestamp=1.0, has_gps=True)
        match = MatchResult(photo=photo, success=True, gps=GPSInfo(35.0, 139.0))
        opts = ProcessOptions(mode=ProcessMode.PREVIEW)
        task = WriteTask(match_result=match, options=opts)
        result = execute_task(task)
        assert not result.success
        assert "unsupported" in result.error

    def test_exception_returns_failure(self):
        photo = PhotoInfo(path=Path("/nonexistent/path.jpg"), filename="path.jpg",
                          timestamp=1.0, has_gps=True)
        match = MatchResult(photo=photo, success=True, gps=GPSInfo(35.0, 139.0))
        opts = ProcessOptions(mode=ProcessMode.OVERWRITE)
        task = WriteTask(match_result=match, options=opts)
        result = execute_task(task)
        assert not result.success
        assert result.error is not None


class TestCopyDestination:
    """Tests for _copy_destination helper."""

    def test_simple_destination(self):
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=Path("/out"))
        result = _copy_destination(Path("/photos/a.jpg"), opts)
        assert result == Path("/out/a.jpg")

    def test_keep_structure_with_photo_dir(self):
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=Path("/out"),
                              keep_structure=True)
        result = _copy_destination(Path("/photos/sub/a.jpg"), opts, Path("/photos"))
        assert result == Path("/out/sub/a.jpg")

    def test_keep_structure_fallback_on_value_error(self):
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=Path("/out"),
                              keep_structure=True)
        # Path not relative to photo_dir → fallback to photo_dir.name / filename
        result = _copy_destination(Path("/other/a.jpg"), opts, Path("/photos"))
        assert result == Path("/out/photos/a.jpg")

    def test_no_keep_structure_ignores_photo_dir(self):
        opts = ProcessOptions(mode=ProcessMode.COPY, output_dir=Path("/out"),
                              keep_structure=False)
        result = _copy_destination(Path("/photos/sub/a.jpg"), opts, Path("/photos"))
        assert result == Path("/out/a.jpg")


class TestSequentialCancelMidRun:
    def test_cancel_stops_mid_sequence(self):
        from gps_photo_tracker.service.cancel_token import CancellationToken
        with patch("gps_photo_tracker.core.concurrency.execute_task") as mock_exec:
            mock_exec.side_effect = lambda t: WriteResult(success=True, filename=t.match_result.photo.filename)
            bp = BatchProcessor(workers=1)
            cancel = CancellationToken()
            tasks = [_make_task(f"p{i}.jpg") for i in range(5)]
            # Cancel after checking — simulate by pre-cancelling
            cancel.cancel()
            results = bp.submit_all(tasks, cancel=cancel)
            assert len(results) == 0


class TestBatchProcessorParallel:
    def test_multi_worker_uses_executor(self):
        with patch("gps_photo_tracker.core.concurrency.ThreadPoolExecutor") as MockExec:
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

    def test_parallel_cancel_cancels_futures(self):
        from gps_photo_tracker.service.cancel_token import CancellationToken
        with patch("gps_photo_tracker.core.concurrency.ThreadPoolExecutor") as MockExec:
            mock_future = MagicMock()
            mock_future.result.return_value = WriteResult(success=True, filename="a.jpg")
            ctx = MagicMock()
            ctx.submit.return_value = mock_future
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            MockExec.return_value = ctx
            cancel = CancellationToken()
            cancel.cancel()
            with patch("gps_photo_tracker.core.concurrency.as_completed", return_value=[mock_future]):
                bp = BatchProcessor(workers=2)
                results = bp.submit_all([_make_task()], cancel=cancel)
                assert len(results) == 0

    def test_parallel_progress_and_result_callbacks(self):
        with patch("gps_photo_tracker.core.concurrency.ThreadPoolExecutor") as MockExec:
            mock_future = MagicMock()
            mock_future.result.return_value = WriteResult(success=True, filename="a.jpg")
            ctx = MagicMock()
            ctx.submit.return_value = mock_future
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            MockExec.return_value = ctx
            progress_calls = []
            result_calls = []
            with patch("gps_photo_tracker.core.concurrency.as_completed", return_value=[mock_future]):
                bp = BatchProcessor(workers=2)
                bp.submit_all(
                    [_make_task()],
                    on_progress=lambda i, t: progress_calls.append(i),
                    on_result=lambda r: result_calls.append(r),
                )
                assert len(progress_calls) == 1
                assert len(result_calls) == 1
