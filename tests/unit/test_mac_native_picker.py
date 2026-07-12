import sys, pytest
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
        def setCanChooseFiles_(self,v): pass
        def setCanChooseDirectories_(self,v): pass
        def setAllowsMultipleSelection_(self,v): pass
        def setTitle_(self,v): pass
        def setAllowedFileTypes_(self,v): pass
        def runModal(self): return 0  # 立即返回取消，不阻塞
    monkeypatch.setattr("AppKit.NSOpenPanel", _P, raising=False)
    assert mnp.pick_paths(title="t") == []
def test_pick_paths_ok_returns_posix_paths(monkeypatch, tmp_path):
    pytest.importorskip("AppKit")  # 非 mac 或无 pyobjc 时跳过
    a = tmp_path/"a.jpg"; a.write_text("x")
    b = tmp_path/"b.jpg"; b.write_text("y")
    class _URL:
        def __init__(self, p): self._p = p
        def path(self): return self._p
    class _P:
        @classmethod
        def openPanel(cls): return cls()
        def setCanChooseFiles_(self,v): pass
        def setCanChooseDirectories_(self,v): pass
        def setAllowsMultipleSelection_(self,v): pass
        def setTitle_(self,v): pass
        def setAllowedFileTypes_(self,v): pass
        def runModal(self): return 1  # NSModalResponseOK
        def URLs(self): return [_URL(str(a)), _URL(str(b))]
    monkeypatch.setattr("AppKit.NSOpenPanel", _P, raising=False)
    got = mnp.pick_paths(title="t", allowed_exts=["jpg"])
    assert got == [a, b]
    assert all(isinstance(p, type(a)) for p in got)  # 全是 Path，不是 URL 字符串
