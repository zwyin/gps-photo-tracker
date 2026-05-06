"""EF-09: Self-contained HTML report builder with inline SVG charts."""
import math
from pathlib import Path

from gps_photo_tracker.core.models import BatchResult, MatcherConfig, GPXSegment


class ReportBuilder:

    @staticmethod
    def build(
        result: BatchResult,
        config: MatcherConfig,
        segments: list[GPXSegment],
        output_path: Path,
    ) -> Path:
        sections = [
            ReportBuilder._header_html(config, result, segments),
            ReportBuilder._stats_html(result),
            ReportBuilder._pie_chart_svg(result),
            ReportBuilder._bar_chart_svg(result),
            ReportBuilder._table_html(result),
            ReportBuilder._reject_analysis(result),
        ]
        body = "\n".join(sections)
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>GPS Photo Tracker Report</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 960px; margin: 0 auto; padding: 20px; color: #333; }}
  h1 {{ color: #2c3e50; }}
  h2 {{ color: #34495e; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  .card {{ display: inline-block; background: #f8f9fa; border-radius: 8px; padding: 16px 24px; margin: 4px; text-align: center; }}
  .card .num {{ font-size: 2em; font-weight: bold; color: #2c3e50; }}
  .card .lbl {{ font-size: 0.85em; color: #666; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 0.9em; }}
  th {{ background: #f0f0f0; }}
  .ok {{ color: #27ae60; }}
  .fail {{ color: #e74c3c; }}
  .skip {{ color: #f39c12; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    @staticmethod
    def _header_html(config: MatcherConfig, result: BatchResult, segments: list[GPXSegment]) -> str:
        return f"""<h1>GPS Photo Tracker Report</h1>
<h2>Parameters</h2>
<table>
<tr><th>Parameter</th><th>Value</th></tr>
<tr><td>Isolated Window</td><td>{config.isolated_window}s</td></tr>
<tr><td>Middle Time Window</td><td>{config.middle_time_window}s</td></tr>
<tr><td>Context Window</td><td>{config.context_window}s</td></tr>
<tr><td>Max GPS Distance</td><td>{config.max_gps_distance}m</td></tr>
<tr><td>Match Tail</td><td>{config.match_tail}</td></tr>
<tr><td>Time Offset</td><td>{config.time_offset}s</td></tr>
<tr><td>Photos</td><td>{result.total}</td></tr>
<tr><td>Segments</td><td>{len(segments)}</td></tr>
</table>"""

    @staticmethod
    def _stats_html(result: BatchResult) -> str:
        pct = f"{result.success_rate * 100:.1f}%"
        return f"""<h2>Statistics</h2>
<div class="card"><div class="num">{result.total}</div><div class="lbl">Total</div></div>
<div class="card"><div class="num ok">{result.matched}</div><div class="lbl">Matched</div></div>
<div class="card"><div class="num fail">{result.failed}</div><div class="lbl">Failed</div></div>
<div class="card"><div class="num skip">{result.skipped}</div><div class="lbl">Skipped</div></div>
<div class="card"><div class="num">{pct}</div><div class="lbl">Success Rate</div></div>"""

    @staticmethod
    def _pie_chart_svg(result: BatchResult) -> str:
        if result.total == 0:
            return '<h2>Distribution</h2><p>No data</p>'
        r = 80
        cx, cy = 100, 100
        data = [
            (result.matched, "#27ae60", "Matched"),
            (result.failed, "#e74c3c", "Failed"),
            (result.skipped, "#f39c12", "Skipped"),
        ]
        paths = []
        cumulative = 0
        for count, color, _ in data:
            if count == 0:
                continue
            start_angle = 2 * math.pi * cumulative / result.total
            end_angle = 2 * math.pi * (cumulative + count) / result.total
            x1 = cx + r * math.cos(start_angle)
            y1 = cy + r * math.sin(start_angle)
            x2 = cx + r * math.cos(end_angle)
            y2 = cy + r * math.sin(end_angle)
            large = 1 if count / result.total > 0.5 else 0
            paths.append(
                f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} '
                f'A{r},{r} 0 {large},1 {x2:.1f},{y2:.1f} Z" fill="{color}"/>'
            )
            cumulative += count
        legend = "".join(
            f'<rect x="210" y="{60 + i * 20}" width="12" height="12" fill="{c}"/>'
            f'<text x="228" y="{71 + i * 20}" font-size="13">{l}: {cnt}</text>'
            for i, (cnt, c, l) in enumerate(data)
        )
        return f'<h2>Distribution</h2><svg width="360" height="220">{"".join(paths)}{legend}</svg>'

    @staticmethod
    def _bar_chart_svg(result: BatchResult) -> str:
        groups = result.reject_groups
        if not groups:
            return ""
        items = sorted(groups.items(), key=lambda x: -len(x[1]))
        max_val = max(len(v) for v in groups.values())
        bar_h = 24
        gap = 4
        rows = ""
        for i, (reason, files) in enumerate(items):
            y = i * (bar_h + gap)
            bw = int(300 * len(files) / max_val) if max_val else 0
            rows += f'<rect x="100" y="{y}" width="{bw}" height="{bar_h}" fill="#e74c3c" rx="3"/>'
            rows += f'<text x="95" y="{y + 16}" text-anchor="end" font-size="12">{reason}</text>'
            rows += f'<text x="{105 + bw}" y="{y + 16}" font-size="12">{len(files)}</text>'
        h = len(items) * (bar_h + gap)
        return f'<h2>Failure Analysis</h2><svg width="400" height="{h}">{rows}</svg>'

    @staticmethod
    def _table_html(result: BatchResult) -> str:
        rows = ""
        for r in result.results:
            status = '<span class="ok">OK</span>' if r.success else '<span class="fail">FAIL</span>'
            gps = f"{r.gps.latitude:.4f}, {r.gps.longitude:.4f}" if r.gps else "-"
            method = r.method or "-"
            td = f"{r.time_diff:.1f}s" if r.time_diff else "-"
            rows += (
                f"<tr><td>{r.photo.filename}</td><td>{status}</td>"
                f"<td>{gps}</td><td>{method}</td><td>{td}</td></tr>"
            )
        return f"""<h2>Match Details</h2>
<table>
<tr><th>File</th><th>Status</th><th>GPS</th><th>Method</th><th>Time Diff</th></tr>
{rows}
</table>"""

    @staticmethod
    def _reject_analysis(result: BatchResult) -> str:
        if not result.reject_groups:
            return ""
        rows = ""
        for reason, files in sorted(result.reject_groups.items(), key=lambda x: -len(x[1])):
            file_list = ", ".join(files[:20])
            if len(files) > 20:
                file_list += f" ... ({len(files)} total)"
            rows += f"<tr><td>{reason}</td><td>{len(files)}</td><td>{file_list}</td></tr>"
        return f"""<h2>Reject Reasons</h2>
<table>
<tr><th>Reason</th><th>Count</th><th>Files</th></tr>
{rows}
</table>"""
