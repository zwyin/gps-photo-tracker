"""Tests for EF-09 ReportBuilder."""
from pathlib import Path

from gps_photo_tracker.core.models import (
    BatchResult, MatcherConfig, MatchResult, PhotoInfo, GPSInfo,
)
from gps_photo_tracker.core.report_builder import ReportBuilder


def _make_result(matched=5, failed=2, skipped=1) -> BatchResult:
    total = matched + failed + skipped
    photos = [
        PhotoInfo(path=Path(f"/photo{i}.jpg"), filename=f"photo{i}.jpg",
                  timestamp=float(i), has_gps=False)
        for i in range(total)
    ]
    results = []
    for i in range(matched):
        results.append(MatchResult(
            photo=photos[i], success=True, gps=GPSInfo(35.0, 139.0, 50),
            method="interpolated", time_diff=10.0,
        ))
    for i in range(matched, matched + failed):
        results.append(MatchResult(photo=photos[i], success=False, reject_reason="no_gps_coverage"))
    for i in range(matched + failed, total):
        results.append(MatchResult(photo=photos[i], success=False, reject_reason="already_has_gps"))

    return BatchResult(
        total=total, matched=matched, failed=failed, skipped=skipped,
        overwritten=0, success_rate=matched / total,
        results=results,
        reject_groups={
            "no_gps_coverage": [f"photo{i}.jpg" for i in range(matched, matched + failed)],
        },
    )


class TestReportBuilder:
    def test_build_creates_html_file(self, tmp_path):
        result = _make_result()
        config = MatcherConfig()
        output = tmp_path / "report.html"
        path = ReportBuilder.build(result, config, [], output)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "<html" in content
        assert "</html>" in content

    def test_report_contains_stats(self, tmp_path):
        result = _make_result(matched=5, failed=2, skipped=1)
        config = MatcherConfig()
        output = tmp_path / "report.html"
        content = ReportBuilder.build(result, config, [], output).read_text(encoding="utf-8")
        assert "5" in content
        assert "2" in content
        assert "1" in content

    def test_report_contains_svg_pie(self, tmp_path):
        result = _make_result()
        config = MatcherConfig()
        output = tmp_path / "report.html"
        content = ReportBuilder.build(result, config, [], output).read_text(encoding="utf-8")
        assert "<svg" in content
        assert "circle" in content or "path" in content

    def test_report_contains_match_table(self, tmp_path):
        result = _make_result()
        config = MatcherConfig()
        output = tmp_path / "report.html"
        content = ReportBuilder.build(result, config, [], output).read_text(encoding="utf-8")
        assert "photo0.jpg" in content
        assert "35.0" in content

    def test_report_contains_params(self, tmp_path):
        result = _make_result()
        config = MatcherConfig(isolated_window=600)
        output = tmp_path / "report.html"
        content = ReportBuilder.build(result, config, [], output).read_text(encoding="utf-8")
        assert "600" in content

    def test_empty_result_report(self, tmp_path):
        result = BatchResult(total=0, matched=0, skipped=0, failed=0,
                             overwritten=0, success_rate=0.0)
        config = MatcherConfig()
        output = tmp_path / "report.html"
        content = ReportBuilder.build(result, config, [], output).read_text(encoding="utf-8")
        assert "0" in content
        assert "<html" in content

    def test_utf8_encoding(self, tmp_path):
        result = _make_result()
        config = MatcherConfig()
        output = tmp_path / "report.html"
        content = ReportBuilder.build(result, config, [], output).read_text(encoding="utf-8")
        assert "Success Rate" in content or "success" in content.lower()


class TestReportBuilderRejectTruncation:

    def test_reject_groups_truncated_at_20(self, tmp_path):
        """When reject_groups has >20 files, file list should be truncated."""
        total = 25
        photos = [
            PhotoInfo(path=Path(f"/photo{i}.jpg"), filename=f"photo{i}.jpg",
                      timestamp=float(i), has_gps=False)
            for i in range(total)
        ]
        results = [MatchResult(photo=p, success=False, reject_reason="no_gps_coverage") for p in photos]
        result = BatchResult(
            total=total, matched=0, failed=total, skipped=0,
            overwritten=0, success_rate=0.0, results=results,
            reject_groups={"no_gps_coverage": [f"photo{i}.jpg" for i in range(total)]},
        )
        config = MatcherConfig()
        output = tmp_path / "report.html"
        content = ReportBuilder.build(result, config, [], output).read_text(encoding="utf-8")
        assert "25 total" in content
