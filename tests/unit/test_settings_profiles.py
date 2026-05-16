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
            "match_tail": False,
            "mode": 2,
            "workers": 4,
        })
        dialog._profile_cb.addItem("hiking")
        dialog._profile_cb.setCurrentText("hiking")
        dialog._load_profile()
        assert dialog._isolated[1].value() == 900
        assert dialog._distance[1].value() == 500
        assert dialog._match_tail.isChecked() is False
        assert dialog._mode_overwrite_rb.isChecked() is True
        assert dialog._workers_spin.value() == 4

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
        dialog._match_tail.setChecked(False)
        dialog._reset_defaults()
        assert dialog._isolated[1].value() == SETTINGS_KEYS["isolated_window"]
        assert dialog._match_tail.isChecked() == SETTINGS_KEYS["match_tail"]
