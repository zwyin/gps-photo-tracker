"""Worker thread for GPS tagging processing."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from PySide6.QtCore import QThread, Signal

from gps_photo_tracker.core.models import (
    InputSelection,
    MatchResult,
    OperationCancelledError,
    ProcessMode,
    ProcessOptions,
)
from gps_photo_tracker.service.cancel_token import CancellationToken
from gps_photo_tracker.service.tagging_service import GPSTaggingService


class Worker(QThread):
    """Background thread for scan → match → write pipeline."""

    progress_signal = Signal(str, int, int, str, float)  # phase, current, total, filename, elapsed
    photo_signal = Signal(dict)  # MatchResult as dict
    write_signal = Signal(dict)  # Write phase update (MatchResult as dict)
    done_signal = Signal(dict)  # BatchResult as dict
    scan_done_signal = Signal(list)  # list of GPX segment dicts for browser
    photos_scanned_signal = Signal(list)  # list of photo info dicts for browser
    review_ready_signal = Signal(dict)  # ReviewState serialized as dict

    def __init__(
        self,
        gps_dir: Path,
        photo_dir: Path,
        config,
        options: ProcessOptions,
        log_dir: Path | None = None,
        excluded_filenames: set[str] | None = None,
        pre_computed_results: list[MatchResult] | None = None,
    ):
        super().__init__()
        self._gps_dir = gps_dir
        self._photo_dir = photo_dir
        self._config = config
        self._options = options
        self._log_dir = log_dir
        self._excluded_filenames = excluded_filenames or set()
        self._token = CancellationToken()
        self._pre_computed_results = pre_computed_results

    def cancel(self):
        self._token.cancel()

    def run(self):
        service = GPSTaggingService(log_dir=self._log_dir)

        # Direct write path: skip scan+match, use pre-computed results
        if self._pre_computed_results is not None:
            self._run_direct_write(service)
            return

        # Scan with progress
        def on_scan_progress(update):
            self.progress_signal.emit(
                update.phase.value, update.current, update.total,
                update.current_file, update.elapsed_seconds,
            )

        try:
            segments = service.scan_gpx(InputSelection.of([self._gps_dir]), on_progress=on_scan_progress)
            photos = service.scan_photos(InputSelection.of([self._photo_dir]), on_progress=on_scan_progress)
        except Exception as e:
            logger.error("扫描失败: %s", e)
            self.done_signal.emit({"error": str(e), "total": 0, "matched": 0})
            return

        logger.info("扫描完成 | GPX: %d段, 照片: %d张", len(segments), len(photos))

        # Filter out excluded filenames
        if self._excluded_filenames:
            segments = [s for s in segments if s.filename not in self._excluded_filenames]

        # Emit segment summaries for GPX browser
        seg_dicts = []
        for seg in segments:
            seg_dicts.append({
                "filename": seg.filename,
                "start": seg.start,
                "end": seg.end,
                "point_count": len(seg.points),
            })
        self.scan_done_signal.emit(seg_dicts)

        # Emit photo summaries for photo browser
        photo_dicts = []
        for p in photos:
            d = {
                "filename": p.filename,
                "path": str(p.path),
                "timestamp": p.timestamp,
                "has_gps": p.has_gps,
            }
            if p.existing_gps:
                d["latitude"] = p.existing_gps.latitude
                d["longitude"] = p.existing_gps.longitude
                d["altitude"] = p.existing_gps.altitude
            photo_dicts.append(d)
        self.photos_scanned_signal.emit(photo_dicts)

        # Process
        def on_progress(update):
            self.progress_signal.emit(
                update.phase.value,
                update.current,
                update.total,
                update.current_file,
                update.elapsed_seconds,
            )

        def on_photo(result):
            from gps_photo_tracker.gui.settings_dialog import format_timestamp
            capture_time = ""
            if result.photo.timestamp is not None:
                capture_time = format_timestamp(result.photo.timestamp)
            gps_before = ""
            if result.photo.existing_gps:
                g = result.photo.existing_gps
                gps_before = f"{g.latitude:.4f}, {g.longitude:.4f}"
            gps_old = None
            gps_new = None
            if result.photo.has_gps and result.success and result.gps:
                gps_old = f"{result.photo.existing_gps.latitude:.4f}, {result.photo.existing_gps.longitude:.4f}" if result.photo.existing_gps else None
                gps_new = f"{result.gps.latitude:.4f}, {result.gps.longitude:.4f}" if result.gps else None
            source_gpx = ""
            if result.success and result.photo.timestamp is not None:
                ts = result.photo.timestamp + self._config.time_offset
                for seg in segments:
                    if seg.start <= ts <= seg.end:
                        source_gpx = seg.filename
                        break
            detail = {
                "filename": result.photo.filename,
                "path": str(result.photo.path),
                "success": result.success,
                "method": result.method,
                "reject_reason": result.reject_reason,
                "has_gps": result.photo.has_gps,
                "overwritten": result.photo.has_gps and result.success and result.gps is not None and result.method != "skipped",
                "latitude": result.gps.latitude if result.gps else None,
                "longitude": result.gps.longitude if result.gps else None,
                "altitude": result.gps.altitude if result.gps else None,
                "time_diff": result.time_diff,
                "interpolation_distance": result.interpolation_distance,
                "interpolation_ratio": result.interpolation_ratio,
                "capture_time": capture_time,
                "capture_time_ts": result.photo.timestamp,
                "gps_before": gps_before,
                "gps_old": gps_old,
                "gps_new": gps_new,
                "source_gpx": source_gpx,
            }
            if result.interpolation_prev:
                detail["interpolation_prev"] = {
                    "lat": result.interpolation_prev.latitude,
                    "lon": result.interpolation_prev.longitude,
                    "alt": result.interpolation_prev.altitude,
                }
            if result.interpolation_next:
                detail["interpolation_next"] = {
                    "lat": result.interpolation_next.latitude,
                    "lon": result.interpolation_next.longitude,
                    "alt": result.interpolation_next.altitude,
                }
            self.photo_signal.emit(detail)

        try:
            result = service.preview(
                segments, photos, self._config,
                on_progress=on_progress,
                on_photo_processed=on_photo,
                cancel=self._token,
            )

            # Check for failures needing review
            failed_results = [r for r in result.results if not r.success]
            if failed_results:
                review_state = service.prepare_review(result.results, segments)
                self.review_ready_signal.emit({
                    "failed_results": [
                        {
                            "photo_path": str(r.photo.path),
                            "filename": r.photo.filename,
                            "timestamp": r.photo.timestamp,
                            "reject_reason": r.reject_reason,
                            "time_diff": r.time_diff,
                        }
                        for r in review_state.failed_results
                    ],
                    "gps_segments": [
                        {
                            "filename": s.filename,
                            "start": s.start,
                            "end": s.end,
                            "points": [
                                {"timestamp": p.timestamp, "latitude": p.latitude,
                                 "longitude": p.longitude, "altitude": p.altitude}
                                for p in s.points
                            ],
                        }
                        for s in review_state.gps_segments
                    ],
                    "all_results": [
                        {
                            "photo_path": str(r.photo.path),
                            "filename": r.photo.filename,
                            "timestamp": r.photo.timestamp,
                            "success": r.success,
                            "latitude": r.gps.latitude if r.gps else None,
                            "longitude": r.gps.longitude if r.gps else None,
                            "altitude": r.gps.altitude if r.gps else None,
                            "method": r.method,
                        }
                        for r in review_state.all_results
                    ],
                    "total": result.total,
                    "matched": result.matched,
                    "failed": result.failed,
                })
                return

            self.done_signal.emit({
                "total": result.total,
                "matched": result.matched,
                "failed": result.failed,
                "skipped": result.skipped,
                "overwritten": result.overwritten,
                "success_rate": result.success_rate,
            })
        except OperationCancelledError:
            self.done_signal.emit({"cancelled": True})
        except Exception as e:
            self.done_signal.emit({
                "error": str(e),
                "total": 0, "matched": 0, "failed": 0,
                "skipped": 0, "overwritten": 0, "success_rate": 0.0,
            })

    def _run_direct_write(self, service):
        """Write pre-computed results directly (WYSIWYG execution)."""
        def on_progress(update):
            self.progress_signal.emit(
                update.phase.value, update.current, update.total,
                update.current_file, update.elapsed_seconds,
            )

        def on_photo(result):
            from gps_photo_tracker.gui.settings_dialog import format_timestamp
            capture_time = ""
            if result.photo.timestamp is not None:
                capture_time = format_timestamp(result.photo.timestamp)
            gps_before = ""
            if result.photo.existing_gps:
                g = result.photo.existing_gps
                gps_before = f"{g.latitude:.4f}, {g.longitude:.4f}"
            detail = {
                "filename": result.photo.filename,
                "path": str(result.photo.path),
                "success": result.success,
                "method": result.method,
                "reject_reason": result.reject_reason,
                "has_gps": result.photo.has_gps,
                "overwritten": result.photo.has_gps and result.success and result.gps is not None,
                "latitude": result.gps.latitude if result.gps else None,
                "longitude": result.gps.longitude if result.gps else None,
                "altitude": result.gps.altitude if result.gps else None,
                "capture_time": capture_time,
                "capture_time_ts": result.photo.timestamp,
                "gps_before": gps_before,
            }
            self.write_signal.emit(detail)

        try:
            result = service.write_phase(
                self._pre_computed_results, self._options,
                photo_dir=self._photo_dir,
                on_progress=on_progress,
                on_photo_processed=on_photo,
                cancel=self._token,
            )
            self.done_signal.emit({
                "total": result.total,
                "matched": result.matched,
                "failed": result.failed,
                "skipped": result.skipped,
                "overwritten": result.overwritten,
                "success_rate": result.success_rate,
            })
        except OperationCancelledError:
            self.done_signal.emit({"cancelled": True})
        except Exception as e:
            self.done_signal.emit({
                "error": str(e),
                "total": 0, "matched": 0, "failed": 0,
                "skipped": 0, "overwritten": 0, "success_rate": 0.0,
            })
