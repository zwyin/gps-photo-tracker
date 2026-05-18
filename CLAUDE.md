# GPS Photo Tracker

Batch geotag photos from GPX/KML/TCX tracks. PySide6 GUI + Python core.

## Quick Start

```bash
pip install -e ".[dev]"
python -m gps_photo_tracker
pytest tests/unit/ -q
```

## Architecture

```
gui/          → PySide6 UI (main_window, worker, dialogs)
service/      → Business orchestration (tagging_service, cancel_token)
core/         → Algorithms & parsers (gps_matcher, gpx/kml/tcx parsers, exif_writer)
logging_/     → OperationLogger (4 log files + debug)
```

## Test & Coverage

- Run: `pytest tests/unit/ -q`
- Coverage: `pytest tests/unit/ --cov --cov-report=term-missing`
- Current: 859 tests, 99.80% overall coverage

### Coverage Gates

| Layer | Target | Actual |
|-------|--------|--------|
| core/models | ≥95% | 100% |
| core/* (algorithms) | ≥90% | 100% |
| service | ≥85% | 100% |
| gui/main_window | ≥85% | 100% |
| gui/* (widgets) | ≥80% | 100% |
| logging_ | ≥90% | 100% |
| **Overall** | **≥95%** | **99.80%** |

8 uncovered lines in `gui/__init__.py` (event loop entry) and `__main__.py` (`if __name__` guard) — untestable by design.

## Versioning

Pre-release: use `0.x.y`. First public release will be `1.0.0`.

## Iteration Workflow

1. Develop per iteration plan
2. Run full test suite (all must pass)
3. Independent code review
4. Commit + push to `github develop`
5. Merge to master + tag + GitHub Release

Remote `origin` (SSH/NAS) is unreliable — always use `github` (HTTPS).
