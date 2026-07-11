def run_app():
    import sys
    from PySide6.QtWidgets import QApplication
    from gps_photo_tracker.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    from PySide6.QtGui import QPixmapCache
    # Shared pixmap cache for the whole app: PhotoPreview's 1024px previews +
    # PhotoBrowserDialog's 150x150 thumbnails. Set ONCE at startup — QPixmapCache
    # is a process-global singleton, so per-widget setCacheLimit() calls would
    # fight over the limit (v0.22.0 review, M2).
    QPixmapCache.setCacheLimit(200 * 1024)  # 200 MB
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
