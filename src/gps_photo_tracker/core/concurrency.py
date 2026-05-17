"""EF-03: Concurrent batch processor for write+copy phase."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gps_photo_tracker.core.exif_writer import EXIFWriter
from gps_photo_tracker.core.models import MatchResult, ProcessMode, ProcessOptions
from gps_photo_tracker.service.cancel_token import CancellationToken


@dataclass
class WriteTask:
    match_result: MatchResult
    options: ProcessOptions
    photo_dir: Path | None = None


@dataclass
class WriteResult:
    success: bool
    filename: str
    error: str | None = None
    dest_path: Path | None = None


def _copy_destination(src_path: Path, options: ProcessOptions, photo_dir: Path | None = None) -> Path:
    if options.keep_structure and options.output_dir and photo_dir:
        try:
            rel = src_path.relative_to(photo_dir)
            if rel.parent == Path("."):
                return options.output_dir / photo_dir.name / rel
            return options.output_dir / rel
        except ValueError:
            return options.output_dir / photo_dir.name / src_path.name
    return options.output_dir / src_path.name


def execute_task(task: WriteTask) -> WriteResult:
    """Execute a single write task. Top-level function for thread safety."""
    result = task.match_result
    opts = task.options

    try:
        if not result.gps:
            return WriteResult(success=False, filename=result.photo.filename, error="no GPS data")

        if opts.mode == ProcessMode.COPY and opts.output_dir:
            dst = _copy_destination(result.photo.path, opts, task.photo_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            EXIFWriter.write_gps(result.photo.path, dst, result.gps)
            return WriteResult(success=True, filename=result.photo.filename, dest_path=dst)
        elif opts.mode == ProcessMode.OVERWRITE:
            EXIFWriter.write_gps(result.photo.path, result.photo.path, result.gps)
            return WriteResult(success=True, filename=result.photo.filename)
        else:
            return WriteResult(success=False, filename=result.photo.filename, error="unsupported mode")

    except Exception as e:
        return WriteResult(success=False, filename=result.photo.filename, error=str(e))


class BatchProcessor:
    """Process write tasks sequentially (workers=1) or in parallel (workers>1)."""

    def __init__(self, workers: int = 1):
        self._workers = workers

    def submit_all(
        self,
        tasks: list[WriteTask],
        on_progress: Callable | None = None,
        on_result: Callable | None = None,
        cancel: CancellationToken | None = None,
    ) -> list[WriteResult]:
        if cancel and cancel.is_cancelled:
            return []

        if self._workers <= 1:
            return self._run_sequential(tasks, on_progress, on_result, cancel)
        else:
            return self._run_parallel(tasks, on_progress, on_result, cancel)

    def _run_sequential(
        self,
        tasks: list[WriteTask],
        on_progress: Callable | None,
        on_result: Callable | None,
        cancel: CancellationToken | None,
    ) -> list[WriteResult]:
        results = []
        for i, task in enumerate(tasks):
            if cancel and cancel.is_cancelled:
                break
            wr = execute_task(task)
            results.append(wr)
            if on_progress:
                on_progress(i + 1, len(tasks))
            if on_result:
                on_result(wr)
        return results

    def _run_parallel(
        self,
        tasks: list[WriteTask],
        on_progress: Callable | None,
        on_result: Callable | None,
        cancel: CancellationToken | None,
    ) -> list[WriteResult]:
        results = []
        with ThreadPoolExecutor(max_workers=self._workers) as executor:
            futures = {executor.submit(execute_task, t): t for t in tasks}
            for future in as_completed(futures):
                if cancel and cancel.is_cancelled:
                    for f in futures:
                        f.cancel()
                    break
                wr = future.result()
                results.append(wr)
                if on_progress:
                    on_progress(len(results), len(tasks))
                if on_result:
                    on_result(wr)
        return results
