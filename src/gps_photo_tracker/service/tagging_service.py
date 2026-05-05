"""GPS tagging service: orchestrates scan → match → write pipeline."""

import logging
import time
from pathlib import Path
from typing import Callable

from gps_photo_tracker.core.exif_writer import EXIFWriter
from gps_photo_tracker.core.file_provider import FileProvider
from gps_photo_tracker.core.gps_matcher import GPSMatcher
from gps_photo_tracker.core.gpx_parser import GPXParser
from gps_photo_tracker.core.models import (
    BatchResult,
    GPXSegment,
    MatcherConfig,
    MatchResult,
    PhotoInfo,
    ProcessMode,
    ProcessOptions,
    ProgressPhase,
    ProgressUpdate,
)
from gps_photo_tracker.logging_.logger import OperationLogger
from gps_photo_tracker.service.cancel_token import CancellationToken

logger = logging.getLogger("gps_tracker")


class GPSTaggingService:
    """Orchestrate GPS tagging: scan → match → write.

    Pure Python, no GUI dependency. All callbacks are optional.
    """

    def __init__(self, log_dir: Path | None = None):
        self._gpx_parser = GPXParser()
        self._file_provider = FileProvider()
        self._op_logger = OperationLogger(log_dir) if log_dir else None

    def scan_gpx(self, gpx_dir: Path, on_progress: Callable | None = None) -> list[GPXSegment]:
        """Scan directory for GPX files and parse them."""
        start = time.time()
        gpx_files = self._file_provider.list_gpx(gpx_dir)
        all_segments: list[GPXSegment] = []
        for i, gpx_path in enumerate(gpx_files):
            try:
                segments = self._gpx_parser.parse_file(gpx_path)
                all_segments.extend(segments)
            except Exception as e:
                logger.warning("跳过无法解析的 GPX 文件: %s", gpx_path)
                if self._op_logger:
                    self._op_logger.log_error(f"scan_gpx: {gpx_path}", e)
            if on_progress:
                on_progress(ProgressUpdate(
                    phase=ProgressPhase.SCANNING_GPX,
                    current=i + 1,
                    total=len(gpx_files),
                    current_file=gpx_path.name,
                    elapsed_seconds=time.time() - start,
                ))
        return all_segments

    def scan_photos(self, photo_dir: Path, on_progress: Callable | None = None) -> list[PhotoInfo]:
        """Scan directory for JPEG files and read their timestamps."""
        start = time.time()
        photo_paths = self._file_provider.list_photos(photo_dir)
        photos: list[PhotoInfo] = []
        for i, path in enumerate(photo_paths):
            try:
                ts = EXIFWriter.read_datetime(path)
                gps = EXIFWriter.read_gps(path)
                photos.append(PhotoInfo(
                    path=path,
                    filename=path.name,
                    timestamp=ts,
                    has_gps=gps is not None,
                    existing_gps=gps,
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

        matched = 0
        skipped = 0
        failed = 0
        overwritten = 0
        reject_groups: dict[str, list[str]] = {}

        for i, result in enumerate(match_results):
            if cancel and cancel.is_cancelled:
                break

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
                        try:
                            dst = self._write_photo(result, options, photo_dir)
                            if self._op_logger:
                                self._op_logger.log_write_success(result.photo, result.gps, dest=dst)
                        except Exception as e:
                            failed += 1
                            matched -= 1
                            if self._op_logger:
                                self._op_logger.log_error(f"write: {result.photo.filename}", e)
                            # COPY mode: copy even if GPS write fails (output == input)
                            if is_copy and options.output_dir:
                                try:
                                    dst = self._copy_destination(result.photo.path, options, photo_dir)
                                    self._file_provider.copy_file(result.photo.path, dst)
                                except Exception as copy_err:
                                    if self._op_logger:
                                        self._op_logger.log_error(f"copy_after_write_fail: {result.photo.filename}", copy_err)
                    else:
                        # COPY mode: still copy even if not writing GPS
                        skipped += 1
                        if is_copy and options.output_dir:
                            dst = self._copy_destination(result.photo.path, options, photo_dir)
                            self._file_provider.copy_file(result.photo.path, dst)
            else:
                failed += 1
                if self._op_logger:
                    self._op_logger.log_match_failed(result)
                # Track reject reasons
                reason = result.reject_reason or "unknown"
                reject_groups.setdefault(reason, []).append(result.photo.filename)
                # COPY mode: copy even unmatched photos
                if is_copy and options and options.output_dir:
                    dst = self._copy_destination(result.photo.path, options, photo_dir)
                    self._file_provider.copy_file(result.photo.path, dst)

            if on_photo_processed:
                on_photo_processed(result)

        elapsed = time.time() - start
        success_rate = matched / len(valid_photos) if valid_photos else 0.0

        logger.info(
            "处理完成: %d/%d 成功, %d 跳过, %d 失败, %.1f%%, %.1fs",
            matched, len(valid_photos), skipped, failed, success_rate * 100, elapsed,
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

        return BatchResult(
            total=len(valid_photos),
            matched=matched,
            skipped=skipped,
            failed=failed,
            overwritten=overwritten,
            success_rate=success_rate,
            results=match_results,
            reject_groups=reject_groups,
        )

    def _should_write(self, result: MatchResult, options: ProcessOptions) -> bool:
        """Decide if GPS should be written for this photo."""
        if result.photo.has_gps and not options.overwrite_gps:
            return False
        return True

    def _write_photo(self, result: MatchResult, options: ProcessOptions, photo_dir: Path | None = None) -> Path | None:
        """Write GPS data to photo based on process mode. Returns destination path for COPY, None otherwise."""
        if options.mode == ProcessMode.COPY and options.output_dir:
            dst = self._copy_destination(result.photo.path, options, photo_dir)
            self._file_provider.copy_file(result.photo.path, dst)
            EXIFWriter.write_gps(dst, dst, result.gps)
            return dst
        elif options.mode == ProcessMode.OVERWRITE:
            EXIFWriter.write_gps(result.photo.path, result.photo.path, result.gps)
        return None

    def _copy_destination(self, src_path: Path, options: ProcessOptions, photo_dir: Path | None = None) -> Path:
        """Compute destination path, preserving directory structure if keep_structure."""
        if options.keep_structure and options.output_dir and photo_dir:
            try:
                rel = src_path.relative_to(photo_dir)
                return options.output_dir / rel
            except ValueError:
                return options.output_dir / src_path.name
        return options.output_dir / src_path.name
