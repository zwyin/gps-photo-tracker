"""Tests for settings dialog profile management."""

from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from gps_photo_tracker.gui.settings_dialog import (
    SettingsDialog, SETTINGS_KEYS, load_settings, save_settings,
)


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def clean_settings():
    """Clear all settings before each test."""
    s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
    s.clear()
    yield
    s.clear()


@pytest.fixture
def dialog(app, qtbot):
    d = SettingsDialog()
    qtbot.addWidget(d)
    return d


class TestLoadSaveSettings:

    def test_load_defaults(self):
        settings = load_settings()
        assert settings["isolated_window"] == 300
        assert settings["mode"] == 0

    def test_save_and_load(self):
        save_settings({"isolated_window": 600, "mode": 1})
        settings = load_settings()
        assert settings["isolated_window"] == 600
        assert settings["mode"] == 1


class TestProfileList:

    def test_empty_profiles(self):
        assert SettingsDialog._list_profiles() == []

    def test_add_and_list_profiles(self):
        SettingsDialog._set_profile_list(["航拍", "街拍"])
        assert SettingsDialog._list_profiles() == ["航拍", "街拍"]


class TestSaveAsProfile:

    def test_save_creates_profile(self, dialog):
        dialog._isolated[1].setValue(600)
        dialog._distance[1].setValue(500)
        with patch("gps_photo_tracker.gui.settings_dialog.QInputDialog.getText",
                   return_value=("航拍", True)):
            dialog._save_as_profile()
        profiles = dialog._list_profiles()
        assert "航拍" in profiles
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        values = s.value("profile/航拍", {})
        assert values["isolated_window"] == 600
        assert values["max_gps_distance"] == 500

    def test_save_cancelled(self, dialog):
        with patch("gps_photo_tracker.gui.settings_dialog.QInputDialog.getText",
                   return_value=("", False)):
            dialog._save_as_profile()
        assert dialog._list_profiles() == []

    def test_save_empty_name_ignored(self, dialog):
        with patch("gps_photo_tracker.gui.settings_dialog.QInputDialog.getText",
                   return_value=("  ", True)):
            dialog._save_as_profile()
        assert dialog._list_profiles() == []

    def test_save_existing_name_updates(self, dialog):
        dialog._distance[1].setValue(300)
        with patch("gps_photo_tracker.gui.settings_dialog.QInputDialog.getText",
                   return_value=("test", True)):
            dialog._save_as_profile()
        dialog._distance[1].setValue(800)
        with patch("gps_photo_tracker.gui.settings_dialog.QInputDialog.getText",
                   return_value=("test", True)):
            dialog._save_as_profile()
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        values = s.value("profile/test", {})
        assert values["max_gps_distance"] == 800
        # Should only appear once in list
        assert dialog._list_profiles().count("test") == 1


class TestLoadProfile:

    def test_load_applies_values(self, dialog):
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        s.setValue("profile/hiking", {
            "isolated_window": 900,
            "max_gps_distance": 500,
            "match_isolated": False,
            "mode": 2,
            "workers": 4,
            "log_dir": "/tmp/logs",
            "log_retention_days": 60,
        })
        dialog._profile_cb.addItem("hiking")
        dialog._profile_cb.setCurrentText("hiking")
        dialog._load_profile()
        assert dialog._isolated[1].value() == 900
        assert dialog._distance[1].value() == 500
        assert dialog._match_isolated.isChecked() is False
        assert dialog._mode_overwrite_rb.isChecked() is True
        assert dialog._workers_spin.value() == 4
        assert dialog._log_dir_edit.text() == "/tmp/logs"
        assert dialog._retention_spin.value() == 60

    def test_load_empty_profile(self, dialog):
        dialog._profile_cb.setCurrentIndex(0)
        dialog._load_profile()
        # Should not crash, nothing changes

    def test_load_nonexistent_profile(self, dialog):
        dialog._profile_cb.addItem("ghost")
        dialog._profile_cb.setCurrentText("ghost")
        dialog._load_profile()
        # Should not crash


class TestDeleteProfile:

    def test_delete_removes_profile(self, dialog):
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        s.setValue("profile/test", {"isolated_window": 600})
        dialog._set_profile_list(["test"])
        dialog._profile_cb.addItem("test")
        dialog._profile_cb.setCurrentText("test")
        with patch("gps_photo_tracker.gui.settings_dialog.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            dialog._delete_profile()
        assert dialog._list_profiles() == []
        assert s.value("profile/test") is None

    def test_delete_cancelled(self, dialog):
        dialog._set_profile_list(["test"])
        dialog._profile_cb.addItem("test")
        dialog._profile_cb.setCurrentText("test")
        with patch("gps_photo_tracker.gui.settings_dialog.QMessageBox.question",
                   return_value=None):
            dialog._delete_profile()
        assert "test" in dialog._list_profiles()

    def test_delete_no_selection(self, dialog):
        dialog._profile_cb.setCurrentIndex(0)
        dialog._delete_profile()
        # Should not crash


class TestResetDefaults:

    def test_reset_restores_defaults(self, dialog):
        dialog._isolated[1].setValue(999)
        dialog._match_isolated.setChecked(False)
        dialog._reset_defaults()
        assert dialog._isolated[1].value() == SETTINGS_KEYS["isolated_window"]
        assert dialog._match_isolated.isChecked() == SETTINGS_KEYS["match_isolated"]
        assert dialog._log_dir_edit.text() == ""
        assert dialog._retention_spin.value() == SETTINGS_KEYS["log_retention_days"]


class TestFullRoundTrip:

    def test_all_keys_survive_save_load_cycle(self, dialog):
        """Every SETTINGS_KEYS field must round-trip through profile save/load."""
        non_defaults = {
            "isolated_window": 1200,
            "middle_time_window": 5000,
            "context_window": 600,
            "max_gps_distance": 800,
            "time_offset": 300,
            "match_isolated": False,
            "overwrite_gps": True,
            "keep_structure": False,
            "resume": True,
            "generate_report": True,
            "workers": 6,
            "mode": 2,
            "log_dir": "/custom/logs",
            "log_retention_days": 90,
        }
        dialog._apply_values(non_defaults)
        with patch("gps_photo_tracker.gui.settings_dialog.QInputDialog.getText",
                   return_value=("full", True)):
            dialog._save_as_profile()

        # Reset to defaults, then load profile
        dialog._apply_values(SETTINGS_KEYS)
        dialog._profile_cb.setCurrentText("full")
        dialog._load_profile()

        assert dialog._isolated[1].value() == 1200
        assert dialog._middle[1].value() == 5000
        assert dialog._context[1].value() == 600
        assert dialog._distance[1].value() == 800
        assert dialog._offset[1].value() == 300
        assert dialog._match_isolated.isChecked() is False
        assert dialog._overwrite.isChecked() is True
        assert dialog._keep_structure.isChecked() is False
        assert dialog._resume.isChecked() is True
        assert dialog._generate_report.isChecked() is True
        assert dialog._workers_spin.value() == 6
        assert dialog._mode_overwrite_rb.isChecked() is True
        assert dialog._log_dir_edit.text() == "/custom/logs"
        assert dialog._retention_spin.value() == 90

    def test_mode_out_of_range_ignored(self, dialog):
        s = QSettings("GPSPhotoTracker", "GPSPhotoTracker")
        s.setValue("profile/bad_mode", {"mode": 99})
        dialog._profile_cb.addItem("bad_mode")
        dialog._profile_cb.setCurrentText("bad_mode")
        dialog._load_profile()
        assert dialog._mode_preview_rb.isChecked() is True
