"""Tests for GPSPointPicker and ReviewDialog GUI components."""

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog

from gps_photo_tracker.core.models import (
    GPSInfo, GPXSegment, MatchResult, PhotoInfo,
    ReviewAction, ReviewDecision, ReviewState, TrackPoint,
)


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


class TestGPSPointPicker:

    def test_populates_track_points(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        points = [
            TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1050.0, latitude=25.001, longitude=100.001, altitude=110),
        ]
        picker = GPSPointPicker(points, photo_timestamp=1025.0)
        qtbot.addWidget(picker)
        assert picker._table.rowCount() == 2

    def test_confirm_returns_selected_point(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        points = [
            TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1050.0, latitude=25.001, longitude=100.001, altitude=110),
        ]
        picker = GPSPointPicker(points, photo_timestamp=1025.0)
        qtbot.addWidget(picker)
        picker._table.selectRow(0)
        result = picker.get_selected_point()
        assert result is not None
        assert result.latitude == 25.0

    def test_no_selection_returns_none(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        points = [
            TrackPoint(timestamp=1000.0, latitude=25.0, longitude=100.0),
        ]
        picker = GPSPointPicker(points, photo_timestamp=1000.0)
        qtbot.addWidget(picker)
        picker._table.clearSelection()
        assert picker.get_selected_point() is None

    def test_empty_points_disables_confirm(self, app, qtbot):
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        picker = GPSPointPicker([], photo_timestamp=1000.0)
        qtbot.addWidget(picker)
        assert not picker._confirm_btn.isEnabled()


def _make_failed_result(filename: str, reason: str = "time_diff",
                         time_diff: float | None = None) -> MatchResult:
    return MatchResult(
        photo=PhotoInfo(path=Path(f"/tmp/{filename}"), filename=filename,
                        timestamp=1000.0, has_gps=False),
        success=False, reject_reason=reason, time_diff=time_diff,
    )


def _make_review_state(count: int = 2):
    seg = GPXSegment(
        filename="track.gpx", start=900.0, end=1100.0,
        points=[
            TrackPoint(timestamp=950.0, latitude=25.0, longitude=100.0, altitude=100),
            TrackPoint(timestamp=1000.0, latitude=25.001, longitude=100.001, altitude=110),
        ],
    )
    results = [_make_failed_result(f"fail{i}.jpg", time_diff=10.0 * i)
               for i in range(count)]
    return ReviewState(
        failed_results=results,
        gps_segments=[seg],
    )


class TestReviewDialog:

    def test_table_shows_all_failures(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert dialog._table.rowCount() == 2

    def test_skip_all_sets_skip_decisions(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._skip_all()
        assert len(dialog._state.decisions) == 2
        for d in dialog._state.decisions.values():
            assert d.action == ReviewAction.SKIP

    def test_confirm_with_no_decisions_treated_as_skip(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._confirm()
        for d in dialog._state.decisions.values():
            assert d.action == ReviewAction.SKIP

    def test_get_state_returns_review_state(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert dialog.get_state() is state

    def test_close_event_treated_as_skip_all(self, app, qtbot):
        from PySide6.QtGui import QCloseEvent
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        event = QCloseEvent()
        dialog.closeEvent(event)
        assert len(dialog._state.decisions) == 2
        for d in dialog._state.decisions.values():
            assert d.action == ReviewAction.SKIP
        assert event.isAccepted()

    def test_action_dropdown_skip(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._action_combos[0].setCurrentIndex(1)  # "跳过"
        path_str = str(state.failed_results[0].photo.path)
        assert path_str in dialog._state.decisions
        assert dialog._state.decisions[path_str].action == ReviewAction.SKIP

    def test_batch_skip_selected(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        from PySide6.QtCore import Qt
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        # Checkbox is a checkable QTableWidgetItem (not cell widget)
        check_item = dialog._table.item(0, 0)
        assert check_item.checkState() == Qt.CheckState.Checked
        dialog._batch_action(1)  # index 1 = skip
        path_str = str(state.failed_results[0].photo.path)
        assert path_str in dialog._state.decisions
        assert dialog._state.decisions[path_str].action == ReviewAction.SKIP

    def test_progress_updates(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert dialog._progress_label.text() == "已处理 0/2"
        dialog._action_combos[0].setCurrentIndex(1)  # skip first
        assert "1/2" in dialog._progress_label.text()

    def test_row_click_updates_info(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._on_row_clicked(0, 0)
        assert "fail0.jpg" in dialog._info_label.text()

    # --- Extended coverage tests ---

    def test_row_click_shows_time_diff(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._on_row_clicked(0, 0)
        assert "时间差" in dialog._info_label.text()

    def test_row_click_no_time_diff(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        result = _make_failed_result("notdiff.jpg", reason="no_gps_coverage",
                                      time_diff=None)
        state = ReviewState(failed_results=[result], gps_segments=[])
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._on_row_clicked(0, 0)
        assert "<b>时间差:</b>" not in dialog._info_label.text()

    def test_confirm_skips_already_decided(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        path_str = str(state.failed_results[0].photo.path)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        state.decisions[path_str] = ReviewDecision(
            photo_path=path_str, action=ReviewAction.MANUAL_GPS,
        )
        dialog._confirm()
        assert state.decisions[path_str].action == ReviewAction.MANUAL_GPS
        path2 = str(state.failed_results[1].photo.path)
        assert state.decisions[path2].action == ReviewAction.SKIP

    def test_on_select_all_unchecks_and_checks(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        from PySide6.QtCore import Qt
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._on_select_all(Qt.CheckState.Unchecked.value)
        for row in range(dialog._table.rowCount()):
            item = dialog._table.item(row, 0)
            assert item.checkState() == Qt.CheckState.Unchecked
        dialog._on_select_all(Qt.CheckState.Checked.value)
        for row in range(dialog._table.rowCount()):
            item = dialog._table.item(row, 0)
            assert item.checkState() == Qt.CheckState.Checked

    def test_get_nearby_points_sorted_by_distance(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        points = dialog._get_nearby_points(1000.0, window=200)
        assert len(points) == 2
        assert points[0].timestamp == 1000.0
        assert points[1].timestamp == 950.0

    def test_get_nearby_points_empty_segments(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = ReviewState(
            failed_results=[_make_failed_result("a.jpg")],
            gps_segments=[],
        )
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert dialog._get_nearby_points(1000.0) == []

    def test_format_time_none(self):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        assert ReviewDialog._format_time(None) == "—"

    def test_format_time_valid(self):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        result = ReviewDialog._format_time(1000.0)
        assert ":" in result

    def test_format_time_invalid(self):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        result = ReviewDialog._format_time(float("nan"))
        assert isinstance(result, str)

    def test_open_gps_picker_no_nearby(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = ReviewState(
            failed_results=[_make_failed_result("a.jpg")],
            gps_segments=[],
        )
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        with patch("gps_photo_tracker.gui.review_dialog.QMessageBox.information"):
            dialog._open_gps_picker(0)
        assert dialog._action_combos[0].currentIndex() == 0

    def test_open_gps_picker_accept(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        fake_pt = TrackPoint(timestamp=950.0, latitude=25.0, longitude=100.0)
        with patch.object(GPSPointPicker, "exec", return_value=QDialog.DialogCode.Accepted), \
             patch.object(GPSPointPicker, "get_selected_point", return_value=fake_pt):
            dialog._open_gps_picker(0)
        path_str = str(state.failed_results[0].photo.path)
        assert state.decisions[path_str].action == ReviewAction.MANUAL_GPS
        assert state.decisions[path_str].selected_point.latitude == 25.0

    def test_open_gps_picker_reject_resets(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        with patch.object(GPSPointPicker, "exec", return_value=QDialog.DialogCode.Rejected):
            dialog._open_gps_picker(0)
        assert dialog._action_combos[0].currentIndex() == 0

    def test_open_coord_input_valid(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        with patch("gps_photo_tracker.gui.review_dialog.QInputDialog.getText") as mock_input:
            mock_input.side_effect = [("25.5", True), ("100.3", True)]
            dialog._open_coord_input(0)
        path_str = str(state.failed_results[0].photo.path)
        assert state.decisions[path_str].action == ReviewAction.MANUAL_COORD
        assert state.decisions[path_str].manual_lat == 25.5
        assert state.decisions[path_str].manual_lon == 100.3

    def test_open_coord_input_cancel_lat(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        with patch("gps_photo_tracker.gui.review_dialog.QInputDialog.getText",
                   return_value=("", False)):
            dialog._open_coord_input(0)
        assert dialog._action_combos[0].currentIndex() == 0

    def test_open_coord_input_cancel_lon(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        with patch("gps_photo_tracker.gui.review_dialog.QInputDialog.getText") as mock_input:
            mock_input.side_effect = [("25.5", True), ("", False)]
            dialog._open_coord_input(0)
        assert dialog._action_combos[0].currentIndex() == 0

    def test_open_coord_input_invalid_number(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        with patch("gps_photo_tracker.gui.review_dialog.QInputDialog.getText") as mock_input, \
             patch("gps_photo_tracker.gui.review_dialog.QMessageBox.warning"):
            mock_input.side_effect = [("abc", True), ("100", True)]
            dialog._open_coord_input(0)
        assert dialog._action_combos[0].currentIndex() == 0

    def test_open_coord_input_out_of_range(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        with patch("gps_photo_tracker.gui.review_dialog.QInputDialog.getText") as mock_input, \
             patch("gps_photo_tracker.gui.review_dialog.QMessageBox.warning"):
            mock_input.side_effect = [("999", True), ("100", True)]
            dialog._open_coord_input(0)
        assert dialog._action_combos[0].currentIndex() == 0

    def test_batch_action_gps(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        from gps_photo_tracker.gui.gps_point_picker import GPSPointPicker
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        fake_pt = TrackPoint(timestamp=950.0, latitude=25.0, longitude=100.0)
        with patch.object(GPSPointPicker, "exec", return_value=QDialog.DialogCode.Accepted), \
             patch.object(GPSPointPicker, "get_selected_point", return_value=fake_pt):
            dialog._batch_action(2)
        path_str = str(state.failed_results[0].photo.path)
        assert state.decisions[path_str].action == ReviewAction.MANUAL_GPS

    def test_batch_action_coord(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog
        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        with patch("gps_photo_tracker.gui.review_dialog.QInputDialog.getText") as mock_input:
            mock_input.side_effect = [("25.5", True), ("100.3", True)]
            dialog._batch_action(3)
        path_str = str(state.failed_results[0].photo.path)
        assert state.decisions[path_str].action == ReviewAction.MANUAL_COORD


class TestReviewDialogSuggestions:

    def _make_state_with_suggestions(self):
        """Create a ReviewState with matched neighbors for suggestion generation."""
        matched_result = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/ok.jpg"), filename="ok.jpg",
                            timestamp=1000.0, has_gps=False),
            success=True, gps=GPSInfo(25.0, 100.0, 50),
            method="interpolated", time_diff=5.0,
        )
        failed_result = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/fail0.jpg"), filename="fail0.jpg",
                            timestamp=1010.0, has_gps=False),
            success=False, reject_reason="time_diff", time_diff=10.0,
        )
        seg = GPXSegment(
            filename="track.gpx", start=900.0, end=1100.0,
            points=[TrackPoint(timestamp=950.0, latitude=25.0, longitude=100.0)],
        )
        return ReviewState(
            failed_results=[failed_result],
            gps_segments=[seg],
            all_results=[matched_result, failed_result],
        )

    def test_suggestions_computed_for_failed(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        state = self._make_state_with_suggestions()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert len(dialog._suggestions) > 0
        assert "跟随" in dialog._suggestions[0]

    def test_apply_suggestions_sets_combos(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        state = self._make_state_with_suggestions()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._apply_all_suggestions()
        assert dialog._action_combos[0].currentIndex() >= 4

    def test_suggestion_column_has_content(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        state = self._make_state_with_suggestions()
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        sug_item = dialog._table.item(0, 4)
        assert sug_item is not None
        assert sug_item.text() != "—"

    def test_no_suggestions_when_no_matches(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        failed = _make_failed_result("fail0.jpg", time_diff=10.0)
        state = ReviewState(
            failed_results=[failed],
            gps_segments=[],
            all_results=[failed],
        )
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert len(dialog._suggestions) == 0


class TestReviewDialogRowClick:

    def test_row_click_negative_row(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._on_row_clicked(-1, 0)

    def test_row_click_shows_preview(self, app, qtbot, tmp_path):
        from PySide6.QtGui import QPixmap
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        img = tmp_path / "photo.jpg"
        QPixmap(40, 40).save(str(img))

        result = MatchResult(
            photo=PhotoInfo(path=img, filename="photo.jpg",
                            timestamp=1000.0, has_gps=False),
            success=False, reject_reason="time_diff", time_diff=5.0,
        )
        state = ReviewState(failed_results=[result], gps_segments=[])
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._on_row_clicked(0, 0)
        assert "photo.jpg" in dialog._info_label.text()

    def test_row_click_bad_preview(self, app, qtbot, tmp_path):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        bad = tmp_path / "bad.jpg"
        bad.write_bytes(b"notimage")

        result = MatchResult(
            photo=PhotoInfo(path=bad, filename="bad.jpg",
                            timestamp=1000.0, has_gps=False),
            success=False, reject_reason="time_diff", time_diff=5.0,
        )
        state = ReviewState(failed_results=[result], gps_segments=[])
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._on_row_clicked(0, 0)


class TestReviewDialogActionFollow:

    def test_action_follow_prev(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._action_combos[0].setCurrentIndex(4)
        path_str = str(state.failed_results[0].photo.path)
        assert path_str in dialog._state.decisions

    def test_action_follow_next(self, app, qtbot):
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        state = _make_review_state(count=1)
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        dialog._action_combos[0].setCurrentIndex(5)
        path_str = str(state.failed_results[0].photo.path)
        assert path_str in dialog._state.decisions


class TestReviewDialogSuggestionEdgeCases:

    def test_suggestion_skips_null_timestamp(self, app, qtbot):
        """Failed photo with timestamp=None gets no suggestion (L221)."""
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        matched = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/ok.jpg"), filename="ok.jpg",
                            timestamp=1000.0, has_gps=False),
            success=True, gps=GPSInfo(25.0, 100.0), method="interpolated",
        )
        failed = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/fail.jpg"), filename="fail.jpg",
                            timestamp=None, has_gps=False),
            success=False, reject_reason="time_diff",
        )
        state = ReviewState(
            failed_results=[failed], gps_segments=[],
            all_results=[matched, failed],
        )
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert 0 not in dialog._suggestions

    def test_suggestion_skips_far_neighbor(self, app, qtbot):
        """Matched photo >300s away gets no suggestion (L237)."""
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        matched = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/ok.jpg"), filename="ok.jpg",
                            timestamp=1000.0, has_gps=False),
            success=True, gps=GPSInfo(25.0, 100.0), method="interpolated",
        )
        failed = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/fail.jpg"), filename="fail.jpg",
                            timestamp=1500.0, has_gps=False),
            success=False, reject_reason="time_diff", time_diff=10.0,
        )
        state = ReviewState(
            failed_results=[failed], gps_segments=[],
            all_results=[matched, failed],
        )
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert len(dialog._suggestions) == 0

    def test_suggestion_follow_next(self, app, qtbot):
        """Failed photo before matched → '跟随下一个' (L243)."""
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        matched = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/ok.jpg"), filename="ok.jpg",
                            timestamp=1000.0, has_gps=False),
            success=True, gps=GPSInfo(25.0, 100.0), method="interpolated",
        )
        failed = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/fail.jpg"), filename="fail.jpg",
                            timestamp=990.0, has_gps=False),
            success=False, reject_reason="time_diff", time_diff=10.0,
        )
        state = ReviewState(
            failed_results=[failed], gps_segments=[],
            all_results=[matched, failed],
        )
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert "下一个" in dialog._suggestions[0]

    def test_apply_next_suggestion_sets_combo(self, app, qtbot):
        """'跟随下一个' suggestion sets combo to index 5 (L252-253)."""
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        matched = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/ok.jpg"), filename="ok.jpg",
                            timestamp=1000.0, has_gps=False),
            success=True, gps=GPSInfo(25.0, 100.0), method="interpolated",
        )
        failed = MatchResult(
            photo=PhotoInfo(path=Path("/tmp/fail.jpg"), filename="fail.jpg",
                            timestamp=990.0, has_gps=False),
            success=False, reject_reason="time_diff", time_diff=10.0,
        )
        state = ReviewState(
            failed_results=[failed], gps_segments=[],
            all_results=[matched, failed],
        )
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)
        assert "下一个" in dialog._suggestions[0]
        dialog._apply_all_suggestions()
        assert dialog._action_combos[0].currentIndex() == 5

    def test_row_click_preview_exception(self, app, qtbot, monkeypatch, tmp_path):
        """Preview loading exception shows fallback text (L275-276)."""
        from gps_photo_tracker.gui.review_dialog import ReviewDialog

        img = tmp_path / "photo.jpg"

        result = MatchResult(
            photo=PhotoInfo(path=img, filename="photo.jpg",
                            timestamp=1000.0, has_gps=False),
            success=False, reject_reason="time_diff", time_diff=5.0,
        )
        state = ReviewState(failed_results=[result], gps_segments=[])
        dialog = ReviewDialog(state)
        qtbot.addWidget(dialog)

        # Make QPixmap throw
        from PySide6.QtGui import QPixmap
        monkeypatch.setattr(QPixmap, "__init__", lambda self, *a: (_ for _ in ()).throw(RuntimeError("fail")))

        dialog._on_row_clicked(0, 0)
        assert "无法加载" in dialog._preview_label.text()
