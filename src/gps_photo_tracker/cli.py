"""Command-line interface for GPS Photo Tracker (headless, reuses GPSTaggingService)."""
import argparse
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from gps_photo_tracker import __version__
from gps_photo_tracker.core.models import (
    InputSelection, MatcherConfig, ReviewAction, ReviewDecision,
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
    p.add_argument("--review", action="store_true",
                   help="Interactive review of failed matches before writing "
                        "(requires a terminal; skipped with a notice if stdin is not a tty)")
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
    photo_dir, keep_structure = _photo_layout(args)

    if args.review:
        return _run_review(args, service, segments, photos, config,
                           photo_dir, keep_structure)

    if args.output or args.overwrite:
        options = _build_write_options(args, keep_structure)
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


def _photo_layout(args) -> tuple[Path | None, bool]:
    """photo_dir: keep_structure relative base. Single source → that path; multi → None + flat."""
    if len(args.photos) == 1:
        return Path(args.photos[0]), True
    if args.output:
        print("warning: multiple photo sources with --output → flat output "
              "(keep_structure off); same-name files may collide", file=sys.stderr)
    return None, False


def _build_write_options(args, keep_structure: bool):
    from gps_photo_tracker.core.models import ProcessMode, ProcessOptions
    mode = ProcessMode.OVERWRITE if args.overwrite else ProcessMode.COPY
    return ProcessOptions(
        mode=mode,
        output_dir=args.output,
        keep_structure=keep_structure,
        overwrite_gps=args.overwrite,
        workers=args.workers,
        generate_report=args.report,
    )


# ── Interactive review (--review) ───────────────────────────

_REVIEW_ACTIONS_HELP = ("actions: Enter=keep failed  s=skip  g=pick GPS point  "
                        "c=manual coords  p=follow prev  n=follow next  q=abort")


def _run_review(args, service, segments, photos, config,
                photo_dir: Path | None, keep_structure: bool) -> int:
    """preview → interactive review of failures → apply_review → write/summarize."""
    result = service.preview(
        segments, photos, config,
        on_progress=_on_progress, on_photo_processed=_on_photo(args),
    )
    failed = [r for r in result.results if not r.success]
    final = result.results
    if not failed:
        print("review: nothing to review (no failed matches)")
    else:
        if not sys.stdin.isatty():
            print("review: stdin is not a terminal — interactive review skipped; "
                  "rerun in a terminal or drop --review", file=sys.stderr)
            _print_summary(result, args)
            return _exit_code(result)
        state = service.prepare_review(result.results, segments)
        try:
            state = _review_loop(state)
        except KeyboardInterrupt:
            print("\nreview aborted", file=sys.stderr)
            return 1
        if state is None:
            print("review aborted, nothing applied", file=sys.stderr)
            return 1
        final = service.apply_review(result.results, state)
        _print_review_summary(state)

    if args.output or args.overwrite:
        options = _build_write_options(args, keep_structure)
        result = service.write_phase(
            final, options, photo_dir=photo_dir,
            on_progress=_on_progress, on_photo_processed=_on_photo(args),
        )
        if args.report and options.output_dir:
            _write_html(result, args, config, segments)
    else:
        result = _recount(final)

    _print_summary(result, args)
    if args.report:
        _write_csv(result, args)
    return _exit_code(result)


def _review_loop(state):
    """Prompt per failed photo. Returns state (decisions filled) or None on abort (q/EOF)."""
    failed = state.failed_results
    print(f"── interactive review: {len(failed)} failed ──")
    print(_REVIEW_ACTIONS_HELP)
    try:
        for i, r in enumerate(failed, 1):
            _print_review_item(i, len(failed), r)
            while True:
                choice = input("  action> ").strip().lower()
                if choice in ("", "k", "keep"):
                    break
                if choice == "s":
                    _decide(state, r, ReviewAction.SKIP)
                    break
                if choice == "g":
                    pt = _pick_gps_point(state, r)
                    if pt is not None:
                        _decide(state, r, ReviewAction.MANUAL_GPS, selected_point=pt)
                        break
                    continue  # cancelled → re-prompt
                if choice == "c":
                    coords = _prompt_coords()
                    if coords is not None:
                        _decide(state, r, ReviewAction.MANUAL_COORD,
                                manual_lat=coords[0], manual_lon=coords[1])
                        break
                    continue
                if choice == "p":
                    _decide(state, r, ReviewAction.FOLLOW_PREV)
                    break
                if choice == "n":
                    _decide(state, r, ReviewAction.FOLLOW_NEXT)
                    break
                if choice == "q":
                    return None
                print(f"  unknown action {choice!r}; {_REVIEW_ACTIONS_HELP}")
    except EOFError:
        return None
    return state


def _decide(state, result, action: ReviewAction, **kwargs) -> None:
    path_str = str(result.photo.path)
    state.decisions[path_str] = ReviewDecision(photo_path=path_str, action=action, **kwargs)


def _print_review_item(i: int, total: int, r) -> None:
    line = (f"[{i}/{total}] {r.photo.filename}  time={_fmt_ts(r.photo.timestamp)}"
            f"  reason={r.reject_reason or 'unknown'}")
    if r.time_diff is not None:
        line += f"  dt={r.time_diff:.0f}s"
    print(line)


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "?"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _nearby_points(state, photo_ts: float | None,
                   window: float = 1800.0, limit: int = 8) -> list:
    """Track points within ±window of the photo, nearest first (mirrors GUI picker)."""
    if photo_ts is None:
        return []
    pts = [p for seg in state.gps_segments for p in seg.points
           if abs(p.timestamp - photo_ts) <= window]
    pts.sort(key=lambda p: abs(p.timestamp - photo_ts))
    return pts[:limit]


def _pick_gps_point(state, r):
    pts = _nearby_points(state, r.photo.timestamp)
    if not pts:
        print("  no track points within ±30 min of capture time")
        return None
    print("  nearest track points:")
    for j, pt in enumerate(pts, 1):
        alt = f"  alt={pt.altitude:.0f}m" if pt.altitude is not None else ""
        print(f"    {j}) dt={pt.timestamp - (r.photo.timestamp or 0):+.0f}s  "
              f"{pt.latitude:.5f}, {pt.longitude:.5f}{alt}")
    while True:
        s = input("  pick # (Enter=cancel)> ").strip()
        if not s:
            return None
        if s.isdigit() and 1 <= int(s) <= len(pts):
            return pts[int(s) - 1]
        print("  invalid number, try again")


def _prompt_coords() -> tuple[float, float] | None:
    lat = _prompt_coord("latitude", -90.0, 90.0)
    if lat is None:
        return None
    lon = _prompt_coord("longitude", -180.0, 180.0)
    if lon is None:
        return None
    return lat, lon


def _prompt_coord(name: str, lo: float, hi: float) -> float | None:
    while True:
        s = input(f"  {name} ({lo:.0f}..{hi:.0f}, Enter=cancel)> ").strip()
        if not s:
            return None
        try:
            v = float(s)
        except ValueError:
            print("  not a number, try again")
            continue
        if not (lo <= v <= hi):
            print("  out of range, try again")
            continue
        return v


def _print_review_summary(state) -> None:
    if not state.decisions:
        print("review: no decisions (all kept as-is)")
        return
    counts: dict[str, int] = {}
    for d in state.decisions.values():
        counts[d.action.value] = counts.get(d.action.value, 0) + 1
    parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"review applied: {len(state.decisions)} decided ({parts})")


def _recount(results) -> "BatchResult":
    """Recompute preview-mode counts after review (mirrors service.write_phase counting)."""
    from gps_photo_tracker.core.models import BatchResult
    matched = skipped = failed = 0
    for r in results:
        effective = r.review_gps if r.review_gps else r.gps
        if r.method in ("skipped", "protected"):
            skipped += 1
        elif r.success and effective is not None:
            matched += 1
        else:
            failed += 1
    total = len(results)
    return BatchResult(
        total=total, matched=matched, skipped=skipped, failed=failed,
        overwritten=0, success_rate=matched / total if total else 0.0,
        results=results,
    )


def _write_html(result, args, config, segments) -> None:
    """HTML report in review write mode (parity with service's write-mode report)."""
    from gps_photo_tracker.core.report_builder import ReportBuilder
    try:
        ReportBuilder.build(result, config, segments, args.output / "report.html")
    except Exception as e:
        print(f"warning: HTML report generation failed: {e}", file=sys.stderr)


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
            gps = r.review_gps if r.review_gps else r.gps
            w.writerow([
                r.photo.filename, str(r.photo.path), r.success, r.method or "",
                gps.latitude if gps else "", gps.longitude if gps else "",
                gps.altitude if gps else "", r.time_diff or "",
                r.reject_reason or "", r.photo.has_gps,
                r.photo.has_gps and r.success and gps is not None,
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
