"""GPS tagging service: orchestrates scan → match → write pipeline."""

import logging
import time
from pathlib import Path
from typing import Callable

from gps_photo_tracker.core.exif_writer import EXIFWriter
from gps_photo_tracker.core.file_provider import FileProvider
from gps_photo_tracker.core.gps_matcher import GPSMatcher
from gps_photo_tracker.core.track_parser import TrackParser
from gps_photo_tracker.core.checkpoint import CheckpointManager
from gps_photo_tracker.core.concurrency import BatchProcessor, WriteTask
from gps_photo_tracker.core.orientation import OrientationReader
from gps_photo_tracker.core.param_tuner import ParamTuner
from gps_photo_tracker.core.report_builder import ReportBuilder
from gps_photo_tracker.core.models import (
    BatchResult,
    GPSInfo,
    GPXSegment,
    InputSelection,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    ProcessMode,
    ProcessOptions,
    ProgressPhase,
    ProgressUpdate,
    ReviewAction,
    ReviewDecision,
    ReviewState,
)
from gps_photo_tracker.logging_.logger import OperationLogger
from gps_photo_tracker.service.cancel_token import CancellationToken

logger = logging.getLogger(__name__)


class GPSTaggingService:
    """Orchestrate GPS tagging: scan → match → write.

    Pure Python, no GUI dependency. All callbacks are optional.
    """

    def __init__(self, log_dir: Path | None = None):
        self._track_parser = TrackParser()
        self._file_provider = FileProvider()
        self._op_logger = OperationLogger(log_dir) if log_dir else None

    def auto_tune(self, segments: list[GPXSegment], photos: list[PhotoInfo]) -> MatcherConfig:
        """Recommend optimal parameters based on track and photo data."""
        return ParamTuner.recommend(segments, photos)

    def prepare_review(self, results: list[MatchResult], segments: list[GPXSegment]) -> ReviewState:
        """Extract failed match results into a ReviewState for GUI review."""
        failed = [r for r in results if not r.success]
        return ReviewState(failed_results=failed, gps_segments=segments, all_results=results)

    def apply_review(self, results: list[MatchResult], state: ReviewState) -> list[MatchResult]:
        """Merge user review decisions back into match results."""
        # Build time-ordered lookup for follow-prev/next
        ordered = sorted(
            [r for r in (state.all_results or results) if r.photo.timestamp is not None],
            key=lambda r: r.photo.timestamp or 0,
        )
        path_to_idx = {str(r.photo.path): i for i, r in enumerate(ordered)}

        for result in results:
            if result.success:
                continue
            path_str = str(result.photo.path)
            decision = state.decisions.get(path_str)
            if not decision:
                continue
            if decision.action == ReviewAction.MANUAL_GPS and decision.selected_point:
                pt = decision.selected_point
                result.review_gps = GPSInfo(
                    latitude=pt.latitude,
                    longitude=pt.longitude,
                    altitude=pt.altitude,
                )
                result.success = True
                result.method = "manual_gps"
            elif decision.action == ReviewAction.MANUAL_COORD:
                if (decision.manual_lat is not None
                        and decision.manual_lon is not None
                        and -90 <= decision.manual_lat <= 90
                        and -180 <= decision.manual_lon <= 180):
                    result.review_gps = GPSInfo(
                        latitude=decision.manual_lat,
                        longitude=decision.manual_lon,
                    )
                    result.success = True
                    result.method = "manual_coord"
            elif decision.action == ReviewAction.FOLLOW_PREV:
                self._apply_follow(result, ordered, path_to_idx, path_str, -1, "follow_prev")
            elif decision.action == ReviewAction.FOLLOW_NEXT:
                self._apply_follow(result, ordered, path_to_idx, path_str, 1, "follow_next")
            # KEEP_SKIP and SKIP: no change
        return results

    def _apply_follow(
        self,
        result: MatchResult,
        ordered: list[MatchResult],
        path_to_idx: dict[str, int],
        path_str: str,
        direction: int,
        method: str,
    ):
        """Resolve follow-prev/next by finding the nearest matched neighbor."""
        idx = path_to_idx.get(path_str)
        if idx is None:
            return
        search_range = range(idx + direction, -1 if direction < 0 else len(ordered), direction)
        for j in search_range:
            neighbor = ordered[j]
            if neighbor.success and neighbor.gps and neighbor.method not in ("skipped", "protected"):
                result.review_gps = GPSInfo(
                    latitude=neighbor.gps.latitude,
                    longitude=neighbor.gps.longitude,
                    altitude=neighbor.gps.altitude,
                )
                result.success = True
                result.method = method
                return

    def write_phase(
        self,
        results: list[MatchResult],
        options: ProcessOptions,
        photo_dir: Path | None = None,
        on_progress: Callable | None = None,
        on_photo_processed: Callable | None = None,
        cancel: CancellationToken | None = None,
    ) -> BatchResult:
        """Write GPS data for matched/reviewed photos. Uses review_gps when set."""
        start = time.time()
        is_preview = options.mode == ProcessMode.PREVIEW
        is_copy = options.mode == ProcessMode.COPY
        matched = 0
        skipped = 0
        failed = 0
        overwritten = 0
        reject_groups: dict[str, list[str]] = {}

        for i, result in enumerate(results):
            if cancel and cancel.is_cancelled:
                break

            effective_gps = result.review_gps if result.review_gps else result.gps

            if on_progress:
                on_progress(ProgressUpdate(
                    phase=ProgressPhase.WRITING if not is_preview else ProgressPhase.MATCHING,
                    current=i + 1,
                    total=len(results),
                    current_file=result.photo.filename,
                    elapsed_seconds=time.time() - start,
                ))

            if result.method == "skipped" or result.method == "protected":
                skipped += 1
                if is_copy and options and options.output_dir:
                    dst = self._copy_destination(result.photo.path, options, photo_dir)
                    self._file_provider.copy_file(result.photo.path, dst)
            elif result.success and effective_gps:
                matched += 1
                if not is_preview:
                    write_result = MatchResult(
                        photo=result.photo, success=True, gps=effective_gps,
                        method=result.method, time_diff=result.time_diff,
                    )
                    if self._should_write(write_result, options):
                        if result.photo.has_gps:
                            overwritten += 1
                        try:
                            dst = self._write_photo(write_result, options, photo_dir)
                            if self._op_logger:
                                self._op_logger.log_write_success(result.photo, effective_gps, dest=dst)
                        except Exception as e:
                            failed += 1
                            matched -= 1
                            if self._op_logger:
                                self._op_logger.log_error(f"write: {result.photo.filename}", e)
                            if is_copy and options.output_dir:
                                try:
                                    dst = self._copy_destination(result.photo.path, options, photo_dir)
                                    self._file_provider.copy_file(result.photo.path, dst)
                                except Exception as copy_err:
                                    if self._op_logger:
                                        self._op_logger.log_error(f"copy_fallback: {result.photo.filename}", copy_err)
                    else:
                        skipped += 1
                        if is_copy and options.output_dir:
                            dst = self._copy_destination(result.photo.path, options, photo_dir)
                            self._file_provider.copy_file(result.photo.path, dst)
            else:
                failed += 1
                reason = result.reject_reason or "unknown"
                reject_groups.setdefault(reason, []).append(result.photo.filename)
                if is_copy and options.output_dir:
                    dst = self._copy_destination(result.photo.path, options, photo_dir)
                    self._file_provider.copy_file(result.photo.path, dst)

            if on_photo_processed:
                on_photo_processed(result)

        elapsed = time.time() - start
        success_rate = matched / len(results) if results else 0.0
        return BatchResult(
            total=len(results),
            matched=matched,
            skipped=skipped,
            failed=failed,
            overwritten=overwritten,
            success_rate=success_rate,
            results=results,
            reject_groups=reject_groups,
        )

    def scan_gpx(self, selection: InputSelection, on_progress: Callable | None = None) -> list[GPXSegment]:
        """Scan selection for track files (GPX, KML, TCX, FIT) and parse them."""
        start = time.time()
        track_files = self._file_provider.resolve_tracks(selection)
        all_segments: list[GPXSegment] = []
        for i, track_path in enumerate(track_files):
            try:
                segments = self._track_parser.parse_file(track_path)
                all_segments.extend(segments)
            except Exception as e:
                logger.warning("跳过无法解析的轨迹文件: %s", track_path)
                if self._op_logger:
                    self._op_logger.log_error(f"scan_gpx: {track_path}", e)
            if on_progress:
                on_progress(ProgressUpdate(
                    phase=ProgressPhase.SCANNING_GPX,
                    current=i + 1,
                    total=len(track_files),
                    current_file=track_path.name,
                    elapsed_seconds=time.time() - start,
                ))
        logger.debug("scan_gpx 完成 | 输入=%s, 文件=%d, 段=%d, 耗时=%.1fs",
                     selection, len(track_files), len(all_segments), time.time() - start)
        return all_segments

    def scan_photos(self, selection: InputSelection, on_progress: Callable | None = None) -> list[PhotoInfo]:
        """Scan selection for JPEG files and read their timestamps."""
        start = time.time()
        photo_paths = self._file_provider.resolve_photos(selection)
        photos: list[PhotoInfo] = []
        for i, path in enumerate(photo_paths):
            try:
                ts = EXIFWriter.read_datetime(path)
                gps = EXIFWriter.read_gps(path)
                orientation = OrientationReader.get_orientation(path)
                photos.append(PhotoInfo(
                    path=path,
                    filename=path.name,
                    timestamp=ts,
                    has_gps=gps is not None,
                    existing_gps=gps,
                    orientation=orientation,
                ))
            except Exception as e:
                logger.warning("读取照片 EXIF 失败: %s", path)
                if self._op_logger:
                    self._op_logger.log_error(f"scan_photos: {path}", e)
                photos.append(PhotoInfo(
                    path=path,
                    filename=path.name,
                    timestamp=None,
                    has_gps=False,
                ))
            if on_progress:
                on_progress(ProgressUpdate(
                    phase=ProgressPhase.SCANNING_PHOTOS,
                    current=i + 1,
                    total=len(photo_paths),
                    current_file=path.name,
                    elapsed_seconds=time.time() - start,
                ))
        logger.debug("scan_photos 完成 | 输入=%s, 照片=%d, 耗时=%.1fs",
                     selection, len(photos), time.time() - start)
        return photos

    def preview(
        self,
        segments: list[GPXSegment],
        photos: list[PhotoInfo],
        config: MatcherConfig,
        on_progress: Callable | None = None,
        on_photo_processed: Callable | None = None,
        cancel: CancellationToken | None = None,
    ) -> BatchResult:
        """Match photos against GPS segments without writing."""
        return self._run_pipeline(
            segments, photos, config, None, None,
            on_progress, on_photo_processed, cancel,
        )

    def process(
        self,
        segments: list[GPXSegment],
        photos: list[PhotoInfo],
        config: MatcherConfig,
        options: ProcessOptions,
        photo_dir: Path | None = None,
        on_progress: Callable | None = None,
        on_photo_processed: Callable | None = None,
        cancel: CancellationToken | None = None,
    ) -> BatchResult:
        """Match photos and write GPS EXIF data."""
        return self._run_pipeline(
            segments, photos, config, options, photo_dir,
            on_progress, on_photo_processed, cancel,
        )

    def _run_pipeline(
        self,
        segments: list[GPXSegment],
        photos: list[PhotoInfo],
        config: MatcherConfig,
        options: ProcessOptions | None,
        photo_dir: Path | None,
        on_progress: Callable | None,
        on_photo_processed: Callable | None,
        cancel: CancellationToken | None,
    ) -> BatchResult:
        start = time.time()
        matcher = GPSMatcher(config)
        is_preview = options is None or options.mode == ProcessMode.PREVIEW
        is_copy = options and options.mode == ProcessMode.COPY
        use_checkpoint = (
            options and options.resume
            and is_copy and options.output_dir
        )

        # Resume: skip already-completed photos
        completed_set: set[str] = set()
        if use_checkpoint and options.output_dir:
            completed_set = CheckpointManager.load(options.output_dir)
            if completed_set:
                logger.info("断点续传: 跳过 %d 已完成照片", len(completed_set))

        if self._op_logger:
            self._op_logger.log_operation_start({
                "mode": "preview" if is_preview else (options.mode.value if options else "unknown"),
                "total_photos": len(photos),
                "total_segments": len(segments),
            })

        # Filter photos with valid timestamps
        valid_photos = [p for p in photos if p.timestamp is not None]
        match_results: list[MatchResult] = []

        # Matching phase
        if valid_photos:
            match_results = matcher.match(valid_photos, segments)
            matcher.auto_follow(match_results)

        # Create checkpoint for COPY mode resume
        if use_checkpoint and options and options.output_dir:
            CheckpointManager.create(options.output_dir, total_photos=len(match_results))

        matched = 0
        skipped = 0
        failed = 0
        overwritten = 0
        reject_groups: dict[str, list[str]] = {}

        # Parallel writes: only COPY/OVERWRITE modes (PREVIEW never writes)
        use_parallel = (
            not is_preview and options
            and options.workers > 1
            and options.mode in (ProcessMode.COPY, ProcessMode.OVERWRITE)
        )
        write_tasks: list[WriteTask] = []
        path_to_overwritten: dict[str, bool] = {}  # keyed by str(photo.path); tracks parallel overwrites

        for i, result in enumerate(match_results):
            if cancel and cancel.is_cancelled:
                break

            # Resume: skip already-completed photos (keyed by full path to avoid cross-dir collision)
            if completed_set and str(result.photo.path) in completed_set:
                continue

            elapsed = time.time() - start
            if on_progress:
                on_progress(ProgressUpdate(
                    phase=ProgressPhase.WRITING if not is_preview else ProgressPhase.MATCHING,
                    current=i + 1,
                    total=len(match_results),
                    current_file=result.photo.filename,
                    elapsed_seconds=elapsed,
                ))

            if result.success:
                if result.method in ("skipped", "protected"):
                    skipped += 1
                    if is_copy and options and options.output_dir:
                        dst = self._copy_destination(result.photo.path, options, photo_dir)
                        self._file_provider.copy_file(result.photo.path, dst)
                else:
                    matched += 1
                    if self._op_logger:
                        self._op_logger.log_match_success(result)
                    if not is_preview and options and result.gps:
                        if self._should_write(result, options):
                            if result.photo.has_gps:
                                overwritten += 1
                                if self._op_logger and result.photo.existing_gps:
                                    self._op_logger.log_gps_overwrite(
                                        result.photo, result.photo.existing_gps, result.gps,
                                    )
                            if use_parallel:
                                write_tasks.append(WriteTask(
                                    match_result=result, options=options, photo_dir=photo_dir,
                                ))
                                path_to_overwritten[str(result.photo.path)] = result.photo.has_gps
                            else:
                                try:
                                    dst = self._write_photo(result, options, photo_dir)
                                    if self._op_logger:
                                        self._op_logger.log_write_success(result.photo, result.gps, dest=dst)
                                except Exception as e:
                                    failed += 1
                                    matched -= 1
                                    if self._op_logger:
                                        self._op_logger.log_error(f"write: {result.photo.filename}", e)
                                    if is_copy and options.output_dir:
                                        try:
                                            dst = self._copy_destination(result.photo.path, options, photo_dir)
                                            self._file_provider.copy_file(result.photo.path, dst)
                                        except Exception as copy_err:
                                            if self._op_logger:
                                                self._op_logger.log_error(f"copy_after_write_fail: {result.photo.filename}", copy_err)
                        else:
                            skipped += 1
                            if is_copy and options.output_dir:
                                dst = self._copy_destination(result.photo.path, options, photo_dir)
                                self._file_provider.copy_file(result.photo.path, dst)
            else:
                failed += 1
                if self._op_logger:
                    self._op_logger.log_match_failed(result)
                reason = result.reject_reason or "unknown"
                reject_groups.setdefault(reason, []).append(result.photo.filename)
                if is_copy and options and options.output_dir:
                    dst = self._copy_destination(result.photo.path, options, photo_dir)
                    self._file_provider.copy_file(result.photo.path, dst)

            if on_photo_processed:
                on_photo_processed(result)

            # Checkpoint: mark completed (sequential mode only; parallel marks after batch)
            if not use_parallel and use_checkpoint and options and options.output_dir and result.success:
                CheckpointManager.mark(options.output_dir, str(result.photo.path))

        # Parallel write phase
        if use_parallel and write_tasks:
            logger.info("并行写入: %d 任务, %d workers", len(write_tasks), options.workers)
            processor = BatchProcessor(workers=options.workers)

            # Build lookup dict keyed by full photo path (handles same filename in different dirs)
            task_by_path: dict[str, WriteTask] = {}
            for wt in write_tasks:
                task_by_path[str(wt.match_result.photo.path)] = wt

            completed_paths: list[str] = []
            def _on_write_progress(done: int, total: int):
                if on_progress:
                    on_progress(ProgressUpdate(
                        phase=ProgressPhase.WRITING,
                        current=done,
                        total=total,
                        current_file="",
                        elapsed_seconds=time.time() - start,
                    ))

            def _on_write_result(wr):
                nonlocal overwritten
                if wr.success:
                    completed_paths.append(str(wr.photo_path))
                    if self._op_logger:
                        task = task_by_path.get(str(wr.photo_path))
                        if task:
                            r = task.match_result
                            self._op_logger.log_write_success(r.photo, r.gps, dest=wr.dest_path)
                else:
                    nonlocal failed, matched
                    failed += 1
                    matched -= 1
                    if path_to_overwritten.get(str(wr.photo_path), False):
                        overwritten -= 1
                    if self._op_logger:
                        self._op_logger.log_error(f"parallel_write: {wr.filename}", wr.error)
                    # Fallback: copy original photo to output (all photos must output)
                    if is_copy and options.output_dir:
                        try:
                            task = task_by_path.get(str(wr.photo_path))
                            if task:
                                dst = self._copy_destination(task.match_result.photo.path, options, photo_dir)
                                self._file_provider.copy_file(task.match_result.photo.path, dst)
                        except Exception as copy_err:
                            if self._op_logger:
                                self._op_logger.log_error(f"parallel_fallback_copy: {wr.filename}", copy_err)

            try:
                write_results = processor.submit_all(
                    write_tasks,
                    on_progress=_on_write_progress,
                    on_result=_on_write_result,
                    cancel=cancel,
                )
            except Exception as e:
                logger.error("并行写入基础设施失败: %s", e)
                if self._op_logger:
                    self._op_logger.log_error("parallel_submit_all", e)
                # Fallback: copy all queued photos to output sequentially
                for wt in write_tasks:
                    try:
                        dst = self._copy_destination(wt.match_result.photo.path, options, photo_dir)
                        self._file_provider.copy_file(wt.match_result.photo.path, dst)
                    except Exception as copy_err:
                        failed += 1
                        matched -= 1

            # Checkpoint: batch-mark all completed writes (no race — single-threaded)
            if use_checkpoint and options.output_dir:
                for p in completed_paths:
                    CheckpointManager.mark(options.output_dir, p)

        # Checkpoint: finalize if not cancelled
        if use_checkpoint and options and options.output_dir:
            if not (cancel and cancel.is_cancelled):
                CheckpointManager.complete(options.output_dir)

        elapsed = time.time() - start
        success_rate = matched / len(valid_photos) if valid_photos else 0.0

        logger.info(
            "处理完成: %d/%d 成功, %d 跳过, %d 失败, %.1f%%, %.1fs",
            matched, len(valid_photos), skipped, failed, success_rate * 100, elapsed,
        )

        batch_result = BatchResult(
            total=len(valid_photos),
            matched=matched,
            skipped=skipped,
            failed=failed,
            overwritten=overwritten,
            success_rate=success_rate,
            results=match_results,
            reject_groups=reject_groups,
            concurrent_workers=options.workers if options else 1,
        )

        if self._op_logger:
            self._op_logger.log_operation_end({
                "matched": matched,
                "failed": failed,
                "skipped": skipped,
                "overwritten": overwritten,
                "success_rate": f"{success_rate * 100:.1f}%",
                "elapsed": f"{elapsed:.1f}s",
            })

        # Generate HTML report if requested
        if options and options.generate_report and options.output_dir:
            try:
                report_path = options.output_dir / "report.html"
                ReportBuilder.build(batch_result, config, segments, report_path)
                logger.info("报告已生成: %s", report_path)
            except Exception as e:
                logger.warning("报告生成失败: %s", e)

        return batch_result

    def _should_write(self, result: MatchResult, options: ProcessOptions) -> bool:
        """Decide if GPS should be written for this photo."""
        if result.photo.has_gps and not options.overwrite_gps:
            return False
        return True

    def _write_photo(self, result: MatchResult, options: ProcessOptions, photo_dir: Path | None = None) -> Path | None:
        """Write GPS data to photo based on process mode. Returns destination path for COPY, None otherwise."""
        if options.mode == ProcessMode.COPY and options.output_dir:
            dst = self._copy_destination(result.photo.path, options, photo_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            EXIFWriter.write_gps(result.photo.path, dst, result.gps)
            return dst
        elif options.mode == ProcessMode.OVERWRITE:
            EXIFWriter.write_gps(result.photo.path, result.photo.path, result.gps)
        return None

    def _copy_destination(self, src_path: Path, options: ProcessOptions, photo_dir: Path | None = None) -> Path:
        """Compute destination path, preserving directory structure if keep_structure."""
        if options.keep_structure and options.output_dir and photo_dir:
            try:
                rel = src_path.relative_to(photo_dir)
                # For flat photo directories (no subdirs), use photo_dir.name as wrapper
                if rel.parent == Path("."):
                    return options.output_dir / photo_dir.name / rel
                return options.output_dir / rel
            except ValueError:
                return options.output_dir / photo_dir.name / src_path.name
        return options.output_dir / src_path.name
