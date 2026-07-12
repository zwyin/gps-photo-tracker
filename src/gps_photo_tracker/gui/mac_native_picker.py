"""macOS 原生打开面板：一个对话框选文件和/或目录。Qt 没暴露 NSOpenPanel 的双选开关，
macOS 用 pyobjc 直调；非 macOS 或无 pyobjc → 调用方降级。"""
import sys
from pathlib import Path
def is_supported() -> bool: return sys.platform=="darwin"
def pick_paths(title="", allowed_exts=None):
    try: from AppKit import NSOpenPanel
    except ImportError: return None
    panel=NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(True); panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(True)
    if title: panel.setTitle_(title)
    if allowed_exts: panel.setAllowedFileTypes_(allowed_exts)
    if panel.runModal()!=1: return []   # NSModalResponseOK=1
    return [Path(u.path()) for u in panel.URLs()]
