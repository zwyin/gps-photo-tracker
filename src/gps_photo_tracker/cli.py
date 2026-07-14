"""Command-line interface for GPS Photo Tracker (headless, reuses GPSTaggingService)."""
import argparse
import sys
from pathlib import Path

from gps_photo_tracker import __version__
from gps_photo_tracker.core.models import (
    InputSelection, MatcherConfig,
)
from gps_photo_tracker.service.tagging_service import GPSTaggingService


class _CliArgumentParser(argparse.ArgumentParser):
    """Override error() → exit 1 (not default 2), so exit 2 stays reserved
    for 'partial match failure' (rsync/cp convention)."""
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    p = _CliArgumentParser(
        prog="gps-photo-tracker-cli",
        description="Batch geotag photos from GPS tracks (GPX/KML/TCX/FIT). Writes EXIF GPS tags.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("photos", nargs="+", help="Photo files or directories (multiple; directories scanned recursively)")
    p.add_argument("-t", "--track", action="append", required=True, metavar="PATH",
                   help="GPS track file/dir (GPX/KML/TCX/FIT). Repeatable: -t a.gpx -t b.tcx")
    p.add_argument("-o", "--output", type=Path, metavar="DIR",
                   help="Copy photos to DIR and write EXIF there (originals untouched)")
    p.add_argument("--overwrite", action="store_true",
                   help="Write EXIF in-place, overwriting originals AND existing GPS")
    p.add_argument("-n", "--dry-run", action="store_true", help="Explicit dry-run (default)")
    p.add_argument("-j", "--workers", type=int, default=1, help="Parallel workers (default: 1)")
    p.add_argument("--time-offset", type=int, default=0, help="Photo time offset seconds (default: 0)")
    p.add_argument("-q", "--quiet", action="store_true", help="Only print final summary")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose: one line per photo")
    p.add_argument("--report", action="store_true", help="Write CSV + HTML reports")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)  # usage error → exit 1 (override)
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("\ninterrupted (in-flight writes may be incomplete)", file=sys.stderr)
        return 1


def _run(args) -> int:
    service = GPSTaggingService()

    segments = service.scan_gpx(InputSelection.of([Path(t) for t in args.track]))
    if not segments:
        print(f"error: no track points parsed from {args.track} (file missing/corrupt/empty?)",
              file=sys.stderr)
        return 1

    photos = service.scan_photos(InputSelection.of([Path(p) for p in args.photos]))
    if not photos:
        print(f"error: no photos found in {args.photos} (path missing/empty?)", file=sys.stderr)
        return 1

    config = MatcherConfig(time_offset=args.time_offset)

    if args.output or args.overwrite:
        # Task 2 fills copy/overwrite (process). Task 1 skeleton: fall through to preview.
        pass

    # dry-run (default) — Task 1 scope
    result = service.preview(segments, photos, config)
    _print_summary(result, args)
    return _exit_code(result)


def _exit_code(result) -> int:
    return 2 if result.failed > 0 else 0


def _print_summary(result, args):
    """Print final summary to stdout (pipe-friendly)."""
    print(f"total: {result.total}  matched: {result.matched}  "
          f"skipped: {result.skipped}  failed: {result.failed}  "
          f"overwritten: {result.overwritten}")
    if result.total:
        print(f"success rate: {result.success_rate:.1%}")


if __name__ == "__main__":
    sys.exit(main())
