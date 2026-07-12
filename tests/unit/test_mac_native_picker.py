import sys, builtins, pytest
from gps_photo_tracker.gui import mac_native_picker as mnp
def test_is_supported_matches_platform():
    assert mnp.is_supported() == (sys.platform=="darwin")
def test_pick_paths_none_when_appkit_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "AppKit", None)  # 让 import 失败
    assert mnp.pick_paths(title="t") is None
def test_pick_paths_cancel_empty(monkeypatch):
    pytest.importorskip("AppKit")  # 非 mac 或无 pyobjc 时跳过（单层即可，无需再加 skipif）
    class _P:
        @classmethod
        def openPanel(cls): return cls()
        def setCanChooseFiles_(s,v): pass
        def setCanChooseDirectories_(s,v): pass
        def setAllowsMultipleSelection_(s,v): pass
        def setTitle_(s,v): pass
        def setAllowedFileTypes_(s,v): pass
        def runModal(s): return 0  # 立即返回取消，不阻塞
    monkeypatch.setattr("AppKit.NSOpenPanel", _P, raising=False)
    assert mnp.pick_paths(title="t") == []
