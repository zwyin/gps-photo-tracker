"""Worker thread for GPS tagging processing."""

from pathlib import Path
from dataclasses import asdict

from PySide6.QtCore import QThread, Signal

from gps_photo_tracker.core.models import (
    BatchResult,
    MatcherConfig,
    ProcessOptions,
    ProgressPhase,
)
from gps_photo_tracker.service.cancel_token import CancellationToken
from gps_photo_tracker.service.tagging_service import GPSTaggingService


class Worker(QThread):
    """Background thread for scan → match → write pipeline."""

    progress_signal = Signal(str, int, int, str, float)  # phase, current, total, filename, elapsed
    photo_signal = Signal(dict)  # MatchResult as dict
    done_signal = Signal(dict)  # BatchResult as dict
    scan_done_signal = Signal(list)  # list of GPX segment dicts for browser
    photos_scanned_signal = Signal(list)  # list of photo info dicts for browser

    def __init__(
        self,
        gps_dir: Path,
        photo_dir: Path,
        config: MatcherConfig,
        options: ProcessOptions,
    ):
        super().__init__()
        self._gps_dir = gps_dir
        self._photo_dir = photo_dir
        self._config = config
        self._options = options
        self._token = CancellationToken()

    def cancel(self):
        self._token.cancel()

    def run(self):
        service = GPSTaggingService()

        # Scan
        try:
            segments = service.scan_gpx(self._gps_dir)
            photos = service.scan_photos(self._photo_dir)
        except Exception as e:
            self.done_signal.emit({"error": str(e), "total": 0, "matched": 0})
            return

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
            detail = {
                "filename": result.photo.filename,
                "path": str(result.photo.path),
                "success": result.success,
                "method": result.method,
                "reject_reason": result.reject_reason,
                "has_gps": result.photo.has_gps,
                "latitude": result.gps.latitude if result.gps else None,
                "longitude": result.gps.longitude if result.gps else None,
                "altitude": result.gps.altitude if result.gps else None,
                "time_diff": result.time_diff,
                "interpolation_distance": result.interpolation_distance,
                "interpolation_ratio": result.interpolation_ratio,
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

        result = service.process(
            segments, photos, self._config, self._options,
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
