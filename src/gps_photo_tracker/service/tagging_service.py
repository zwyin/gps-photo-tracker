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
from gps_photo_tracker.service.cancel_token import CancellationToken

logger = logging.getLogger("gps_tracker")


class GPSTaggingService:
    """Orchestrate GPS tagging: scan → match → write.

    Pure Python, no GUI dependency. All callbacks are optional.
    """

    def __init__(self):
        self._gpx_parser = GPXParser()
        self._file_provider = FileProvider()

    def scan_gpx(self, gpx_dir: Path) -> list[GPXSegment]:
        """Scan directory for GPX files and parse them."""
        gpx_files = self._file_provider.list_gpx(gpx_dir)
        all_segments: list[GPXSegment] = []
        for gpx_path in gpx_files:
            try:
                segments = self._gpx_parser.parse_file(gpx_path)
                all_segments.extend(segments)
            except Exception:
                logger.warning("跳过无法解析的 GPX 文件: %s", gpx_path)
        return all_segments

    def scan_photos(self, photo_dir: Path) -> list[PhotoInfo]:
        """Scan directory for JPEG files and read their timestamps."""
        photo_paths = self._file_provider.list_photos(photo_dir)
        photos: list[PhotoInfo] = []
        for path in photo_paths:
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
            except Exception:
                logger.warning("读取照片 EXIF 失败: %s", path)
                photos.append(PhotoInfo(
                    path=path,
                    filename=path.name,
                    timestamp=None,
                    has_gps=False,
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
            segments, photos, config, None,
            on_progress, on_photo_processed, cancel,
        )

    def process(
        self,
        segments: list[GPXSegment],
        photos: list[PhotoInfo],
        config: MatcherConfig,
        options: ProcessOptions,
        on_progress: Callable | None = None,
        on_photo_processed: Callable | None = None,
        cancel: CancellationToken | None = None,
    ) -> BatchResult:
        """Match photos and write GPS EXIF data."""
        return self._run_pipeline(
            segments, photos, config, options,
            on_progress, on_photo_processed, cancel,
        )

    def _run_pipeline(
        self,
        segments: list[GPXSegment],
        photos: list[PhotoInfo],
        config: MatcherConfig,
        options: ProcessOptions | None,
        on_progress: Callable | None,
        on_photo_processed: Callable | None,
        cancel: CancellationToken | None,
    ) -> BatchResult:
        start = time.time()
        matcher = GPSMatcher(config)
        is_preview = options is None or options.mode == ProcessMode.PREVIEW

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
        processed_count = 0

        for i, result in enumerate(match_results):
            if cancel and cancel.is_cancelled:
                break

            processed_count += 1
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
                if not is_preview and options and result.gps:
                    if self._should_write(result, options):
                        if result.photo.has_gps:
                            overwritten += 1
                        self._write_photo(result, options)
                    else:
                        skipped += 1
            else:
                failed += 1
                # COPY mode: copy even unmatched photos
                if not is_preview and options and options.mode == ProcessMode.COPY and options.output_dir:
                    dst = self._copy_destination(result.photo.path, options)
                    self._file_provider.copy_file(result.photo.path, dst)

            if on_photo_processed:
                on_photo_processed(result)

        elapsed = time.time() - start
        success_rate = matched / len(valid_photos) if valid_photos else 0.0

        logger.info(
            "处理完成: %d/%d 成功, %d 跳过, %d 失败, %.1f%%, %.1fs",
            matched, len(valid_photos), skipped, failed, success_rate * 100, elapsed,
        )

        return BatchResult(
            total=len(valid_photos),
            matched=matched,
            skipped=skipped,
            failed=failed,
            overwritten=overwritten,
            success_rate=success_rate,
            results=match_results,
        )

    def _should_write(self, result: MatchResult, options: ProcessOptions) -> bool:
        """Decide if GPS should be written for this photo."""
        if result.photo.has_gps and not options.overwrite_gps:
            return False
        return True

    def _write_photo(self, result: MatchResult, options: ProcessOptions) -> None:
        """Write GPS data to photo based on process mode."""
        if options.mode == ProcessMode.COPY and options.output_dir:
            dst = self._copy_destination(result.photo.path, options)
            self._file_provider.copy_file(result.photo.path, dst)
            EXIFWriter.write_gps(dst, dst, result.gps)
        elif options.mode == ProcessMode.OVERWRITE:
            EXIFWriter.write_gps(result.photo.path, result.photo.path, result.gps)

    def _copy_destination(self, src_path: Path, options: ProcessOptions) -> Path:
        """Compute destination path, preserving directory structure if keep_structure."""
        if options.keep_structure and options.output_dir:
            # Preserve relative path from CWD or use filename only
            try:
                rel = src_path.relative_to(Path.cwd())
                    # Keep everything after the first directory component
                parts = rel.parts[1:] if len(rel.parts) > 1 else rel.parts
                return options.output_dir / Path(*parts) if parts else options.output_dir / src_path.name
            except ValueError:
                return options.output_dir / src_path.name
        return options.output_dir / src_path.name
