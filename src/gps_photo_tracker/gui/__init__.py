def run_app():
    import sys
    from PySide6.QtWidgets import QApplication
    from gps_photo_tracker.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
