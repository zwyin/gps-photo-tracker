"""Command-line interface for GPS Photo Tracker (headless, reuses GPSTaggingService)."""
import argparse
import os
import signal
import sys
from pathlib import Path

from gps_photo_tracker import __version__
from gps_photo_tracker.core.models import (
    InputSelection, MatcherConfig,
)
from gps_photo_tracker.service.cancel_token import CancellationToken
from gps_photo_tracker.service.tagging_service import GPSTaggingService

# Config keys recognized in TOML (snake_case, mirror CLI flag names).
_CONFIG_KEYS = {"workers", "time_offset", "quiet", "verbose", "report", "overwrite"}
_LOCAL_CONFIG_NAME = "gps-photo-tracker.toml"


class _CliArgumentParser(argparse.ArgumentParser):
    """Override error() → exit 1 (not default 2), so exit 2 stays reserved
    for 'partial match failure' (rsync/cp convention)."""
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)


def _find_config_path(explicit: str | None) -> Path | None:
    """Resolution order: --config PATH > ./gps-photo-tracker.toml > XDG config."""
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            print(f"error: config file not found: {p}", file=sys.stderr)
            sys.exit(1)
        return p
    local = Path.cwd() / _LOCAL_CONFIG_NAME
    if local.is_file():
        return local
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    xdg_cfg = xdg / "gps-photo-tracker" / "config.toml"
    return xdg_cfg if xdg_cfg.is_file() else None


def _load_config(path: Path | None) -> dict:
    """Load TOML defaults. Invalid file → warning + empty dict (never fatal).
    Unknown keys are ignored (forward-compatible)."""
    if path is None:
        return {}
    try:
        import tomllib
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"warning: ignoring config file {path}: {e}", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        print(f"warning: ignoring config file {path}: not a table", file=sys.stderr)
        return {}
    return {k: v for k, v in data.items() if k in _CONFIG_KEYS}


def _build_parser(cfg: dict) -> argparse.ArgumentParser:
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
    p.add_argument("--config", metavar="PATH",
                   help=f"TOML config with defaults ({', '.join(sorted(_CONFIG_KEYS))}); "
                        f"search: --config > ./{_LOCAL_CONFIG_NAME} > XDG gps-photo-tracker/config.toml. "
                        f"CLI flags always win.")
    p.add_argument("--overwrite", action="store_true", default=cfg.get("overwrite", False),
                   help="Write EXIF in-place, overwriting originals AND existing GPS")
    p.add_argument("-n", "--dry-run", action="store_true", help="Explicit dry-run (default)")
    p.add_argument("-j", "--workers", type=int, default=cfg.get("workers", 1),
                   help=f"Parallel workers (default: {cfg.get('workers', 1)})")
    p.add_argument("--time-offset", type=int, default=cfg.get("time_offset", 0),
                   help=f"Photo time offset seconds (default: {cfg.get('time_offset', 0)})")
    p.add_argument("-q", "--quiet", action="store_true", default=cfg.get("quiet", False),
                   help="Only print final summary")
    p.add_argument("-v", "--verbose", action="store_true", default=cfg.get("verbose", False),
                   help="Verbose: one line per photo")
    p.add_argument("--report", action="store_true", default=cfg.get("report", False),
                   help="Write CSV + HTML reports")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _sigint_handler(token: CancellationToken, prev_handler):
    """First Ctrl-C: set token (pipeline stops at next photo boundary, partial
    summary + CSV still produced, exit 130). Second Ctrl-C: previous/default
    behavior (hard KeyboardInterrupt)."""
    state = {"pressed": False}

    def handler(signum, frame):
        if state["pressed"]:
            raise KeyboardInterrupt  # second press: bail out hard
        state["pressed"] = True
        token.cancel()
        print("\nCtrl-C: finishing current photo, then partial summary "
              "(press again to abort immediately)", file=sys.stderr)
    return handler


def main(argv: list[str] | None = None) -> int:
    # Two-phase parse: first pass gets --config (if any), second pass builds
    # full parser with config-sourced defaults. parse_known_args keeps first
    # pass tolerant of not-yet-known flags.
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--config")
    cfg_path = _find_config_path(probe.parse_known_args(argv)[0].config)
    cfg = _load_config(cfg_path)

    args = _build_parser(cfg).parse_args(argv)  # usage error → exit 1 (override)

    token = CancellationToken()
    prev_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _sigint_handler(token, prev_handler))
    try:
        return _run(args, token)
    except KeyboardInterrupt:
        print("\ninterrupted (in-flight writes may be incomplete)", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, prev_handler)


def _run(args, token: CancellationToken | None = None) -> int:
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

    # photo_dir: keep_structure relative base. Single source → that path; multi → None + flat.
    if len(args.photos) == 1:
        photo_dir = Path(args.photos[0])
        keep_structure = True
    else:
        photo_dir = None
        keep_structure = False
        if args.output:
            print("warning: multiple photo sources with --output → flat output "
                  "(keep_structure off); same-name files may collide", file=sys.stderr)

    if args.output or args.overwrite:
        from gps_photo_tracker.core.models import ProcessMode, ProcessOptions
        mode = ProcessMode.OVERWRITE if args.overwrite else ProcessMode.COPY
        options = ProcessOptions(
            mode=mode,
            output_dir=args.output,
            keep_structure=keep_structure,
            overwrite_gps=args.overwrite,
            workers=args.workers,
            generate_report=args.report,
        )
        result = service.process(
            segments, photos, config, options=options, photo_dir=photo_dir,
            on_progress=_on_progress, on_photo_processed=_on_photo(args),
            cancel=token,
        )
    else:
        result = service.preview(
            segments, photos, config,
            on_progress=_on_progress, on_photo_processed=_on_photo(args),
            cancel=token,
        )

    cancelled = token is not None and token.is_cancelled
    if cancelled:
        print("cancelled: partial results below")
    _print_summary(result, args)
    if args.report:
        _write_csv(result, args)
    return 130 if cancelled else _exit_code(result)


def _on_progress(update):
    print(f"\r{update.phase.value}: {update.current}/{update.total} {update.current_file}",
          end="", file=sys.stderr)


def _on_photo(args):
    def _cb(result):
        if args.verbose and not args.quiet:
            status = "ok" if result.success else f"FAIL({result.reject_reason})"
            print(f"{result.photo.filename}\t{status}")
    return _cb


def _write_csv(result, args):
    """CLI 生成 CSV（每张照片一行，批量统计用）。HTML 由 service 在写模式生成。"""
    import csv
    csv_path = (args.output / "report.csv") if args.output else Path("report.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "path", "success", "method", "latitude",
                    "longitude", "altitude", "time_diff", "reject_reason",
                    "has_gps_before", "overwritten"])
        for r in result.results:
            w.writerow([
                r.photo.filename, str(r.photo.path), r.success, r.method or "",
                r.gps.latitude if r.gps else "", r.gps.longitude if r.gps else "",
                r.gps.altitude if r.gps else "", r.time_diff or "",
                r.reject_reason or "", r.photo.has_gps,
                r.photo.has_gps and r.success and r.gps is not None,
            ])
    print(f"CSV report: {csv_path}", file=sys.stderr)


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
