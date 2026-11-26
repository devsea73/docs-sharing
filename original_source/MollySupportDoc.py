"""Support App - simple Google Doc viewer with a saved session."""

from __future__ import annotations
import ctypes
import json
import os
import re
import sys
import time
from ctypes import wintypes
from pathlib import Path


def _prepare_portable_runtime() -> None:
    """Point Qt at the files packed inside the single portable program."""
    if not getattr(sys, "frozen", False):
        return None
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    base = getattr(sys, "_MEIPASS", "")
    if not base:
        return None
    pyside = os.path.join(base, "PySide6")
    os.environ["PATH"] = (pyside + os.pathsep) + os.environ.get("PATH", "")
    process = os.path.join(pyside, "QtWebEngineProcess.exe")
    if os.path.isfile(process):
        os.environ["QTWEBENGINEPROCESS_PATH"] = process
    for plugins in (os.path.join(pyside, "qt-plugins"), os.path.join(pyside, "plugins")):
        if not os.path.isdir(plugins):
            continue
        os.environ["QT_PLUGIN_PATH"] = plugins
        return None


_prepare_portable_runtime()
from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QPointF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

DOC_ID_PATTERN = re.compile("/document/d/([a-zA-Z0-9_-]+)")
DEFAULT_PAGE_WIDTH = 816
WDA_NONE = 0
WDA_EXCLUDEFROMCAPTURE = 17
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 128
WS_EX_APPWINDOW = 262144
WS_EX_TRANSPARENT = 32
WS_EX_LAYERED = 524288
WS_EX_NOACTIVATE = 134217728
LWA_ALPHA = 2
SWP_FRAMECHANGED = 32
SWP_NOMOVE = 1
SWP_NOSIZE = 2
SWP_NOZORDER = 4
SWP_NOACTIVATE = 16
CLICK_THROUGH_EXSTYLE = (WS_EX_LAYERED | WS_EX_TRANSPARENT) | WS_EX_NOACTIVATE
VK_CONTROL = 17
VK_SHIFT = 16
VK_MENU = 18
VK_Z = 90
VK_A = 65
VK_LCONTROL = 162
VK_RCONTROL = 163
VK_LSHIFT = 160
VK_RSHIFT = 161
VK_LMENU = 164
VK_RMENU = 165
WM_HOTKEY = 786
WM_NCHITTEST = 132
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
GHOST_HOTKEY_ID_ALT = 19713
GHOST_HOTKEY_ID_SHIFT = 19714
MOD_ALT = 1
MOD_CONTROL = 2
MOD_SHIFT = 4
MOD_NOREPEAT = 16384
ERROR_ALREADY_EXISTS = 183
APP_NAME = "Support App"
MUTEX_NAME = "Global\\SupportApp_SingleInstance_v1"
WINDOW_TITLE_MARKER = APP_NAME
_app_mutex = None


def _document_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#2c2c2c"))
    pen.setWidthF(1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(7, 4, 16, 20, 1.6, 1.6)
    painter.setBrush(QColor("#f3f3f3"))
    fold = [QPointF(17, 4), QPointF(23, 10), QPointF(17, 10)]
    painter.drawPolygon(QPolygonF(fold))
    painter.setPen(QPen(QColor("#6b6b6b"), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(11, 15, 19, 15)
    painter.drawLine(11, 18, 17, 18)
    painter.end()
    return QIcon(pix)


FIT_PAGE_JS = r"""
(function() {
    var styleId = "support-page-fit";
    if (!document.getElementById(styleId)) {
        var style = document.createElement("style");
        style.id = styleId;
        style.textContent = [
            ".kix-appview-editor, .kix-rotatingtilemanager, .kix-rotatingtilemanager-container {",
            "  background: #ffffff !important;",
            "}",
            "html, body, .kix-appview-editor { overflow-x: hidden !important; }",
            "#docs-chrome, #docs-header, #docs-titlebar, .docs-titlebar-container,",
            "#docs-menubar, .docs-menubar, #docs-toolbar, #docs-toolbar-wrapper,",
            ".docs-toolbar-wrapper, .docs-ruler, .kix-ruler, #kix-horizontal-ruler,",
            "#docs-additional-bars, .docs-butterbar-container, .docs-branding-container,",
            ".companion-app-switcher-container, #docs-banners, .docs-explore-widget,",
            "#docs-omnibox-toolbar, .docs-omnibox-container, #docs-header-container {",
            "  display: none !important;",
            "  height: 0 !important;",
            "}",
            ".kix-appview-editor { top: 0 !important; margin-top: 0 !important; }",
            ".kix-page { box-shadow: none !important; border: none !important; }",
            ".kix-page-paginated { margin-left: 0 !important; margin-right: 0 !important; }"
        ].join("\n");
        document.documentElement.appendChild(style);
    }

    [
        "#docs-chrome",
        "#docs-header",
        "#docs-titlebar",
        ".docs-titlebar-container",
        "#docs-menubar",
        ".docs-menubar",
        "#docs-toolbar",
        "#docs-toolbar-wrapper",
        ".docs-toolbar-wrapper",
        ".docs-ruler",
        ".kix-ruler",
        "#kix-horizontal-ruler",
        "#docs-additional-bars",
        ".docs-butterbar-container",
        ".docs-branding-container",
        ".companion-app-switcher-container",
        "#docs-banners",
        ".docs-explore-widget",
        "#docs-omnibox-toolbar"
    ].forEach(function(selector) {
        document.querySelectorAll(selector).forEach(function(node) {
            node.style.setProperty("display", "none", "important");
        });
    });

    if (!window.__supportLockScrollZoom) {
        window.__supportLockScrollZoom = true;
        window.addEventListener("wheel", function (event) {
            if (event.ctrlKey) {
                event.preventDefault();
                event.stopImmediatePropagation();
            }
        }, { capture: true, passive: false });
    }

    var page = document.querySelector(".kix-page")
        || document.querySelector(".kix-page-paginated");
    var editor = document.querySelector(".kix-appview-editor")
        || document.querySelector(".docs-editor-container");
    if (!page) return 0;

    document.querySelectorAll(".kix-page-paginated, .kix-page").forEach(function(node) {
        node.style.setProperty("margin-left", "0px", "important");
        node.style.setProperty("margin-right", "0px", "important");
        node.style.setProperty("box-shadow", "none", "important");
    });

    if (editor) {
        editor.style.setProperty("background", "#ffffff", "important");
        editor.style.setProperty("padding-left", "0px", "important");
        editor.style.setProperty("padding-right", "0px", "important");
        editor.style.setProperty("overflow-x", "hidden", "important");
        editor.style.setProperty("top", "0px", "important");
        editor.style.setProperty("margin-top", "0px", "important");
    }

    var width = page.offsetWidth || page.getBoundingClientRect().width;
    if (!(width > 50)) return "0:0:0";
    var client = editor ? editor.clientWidth : 0;
    var scroll = editor ? editor.scrollWidth : 0;
    return width + ":" + client + ":" + scroll;
})();
"""


def activate_existing_window() -> None:
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    matches = []

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        if WINDOW_TITLE_MARKER in buf.value:
            matches.append(hwnd)
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(visit), 0)
    if not matches:
        return None
    hwnd = matches[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)


def ensure_single_instance() -> bool:
    global _app_mutex
    if sys.platform != "win32":
        return True
    _app_mutex = ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        activate_existing_window()
        return False
    return True


def set_exclude_from_capture(hwnd: int, exclude: bool) -> bool:
    """Hide the window from screen capture without flashing it onto another monitor.

    The document view is a separate window, so it needs the same flag.
    Setting the flag again when it is already set makes Windows repaint
    that window on the other monitor, so unchanged windows are left alone.
    """
    if sys.platform != "win32" or hwnd <= 0:
        return False
    affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
    user32 = ctypes.windll.user32
    user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    root_ok = False
    for target in _click_through_targets(hwnd):
        current = wintypes.DWORD()
        if (
            user32.GetWindowDisplayAffinity(wintypes.HWND(target), ctypes.byref(current))
            and int(current.value) == affinity
        ):
            if target == hwnd:
                root_ok = True
            continue
        if user32.SetWindowDisplayAffinity(wintypes.HWND(target), affinity) and target == hwnd:
            root_ok = True
    return root_ok


def _user32_ptr():
    api = getattr(_user32_ptr, "api", None)
    if api is not None:
        return api
    api = ctypes.WinDLL("user32", use_last_error=True)
    get_name = "GetWindowLongPtrW" if hasattr(api, "GetWindowLongPtrW") else "GetWindowLongW"
    set_name = "SetWindowLongPtrW" if hasattr(api, "SetWindowLongPtrW") else "SetWindowLongW"
    api.GetExStyle = getattr(api, get_name)
    api.SetExStyle = getattr(api, set_name)
    api.GetExStyle.argtypes = [wintypes.HWND, ctypes.c_int]
    api.GetExStyle.restype = ctypes.c_ssize_t
    api.SetExStyle.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    api.SetExStyle.restype = ctypes.c_ssize_t
    api.SetLayeredWindowAttributes.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        wintypes.BYTE,
        wintypes.DWORD,
    ]
    api.SetLayeredWindowAttributes.restype = wintypes.BOOL
    api.GetLayeredWindowAttributes.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.BYTE),
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.GetLayeredWindowAttributes.restype = wintypes.BOOL
    api.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    api.RedrawWindow.restype = wintypes.BOOL
    api.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    api.SetWindowPos.restype = wintypes.BOOL
    api.GetForegroundWindow.restype = wintypes.HWND
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.SetForegroundWindow.restype = wintypes.BOOL
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsWindowVisible.restype = wintypes.BOOL
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    api.GetWindowTextLengthW.restype = ctypes.c_int
    api.GetClassNameW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
    api.GetClassNameW.restype = ctypes.c_int
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    api.GetWindowRect.restype = wintypes.BOOL
    _user32_ptr.api = api
    return api


def _get_exstyle(hwnd: int) -> int:
    return int(_user32_ptr().GetExStyle(wintypes.HWND(hwnd), GWL_EXSTYLE)) & 4294967295


def _set_exstyle(hwnd: int, style: int) -> None:
    api = _user32_ptr()
    api.SetExStyle(wintypes.HWND(hwnd), GWL_EXSTYLE, (style & 4294967295))
    api.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0, 55)


def _child_hwnds(root: int) -> list[int]:
    children = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(child, _lparam):
        value = int((child or 0))
        if value:
            children.append(value)
        return True

    callback = callback_type(visit)
    _child_hwnds.callback = callback
    ctypes.windll.user32.EnumChildWindows(wintypes.HWND(root), callback, 0)
    return children


def _window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32_ptr().GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def _process_image(pid: int) -> str:
    if pid <= 0:
        return ""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_wchar_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(4096, False, pid)
    if not handle:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    size = wintypes.DWORD(512)
    kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
    kernel32.CloseHandle(handle)
    return buf.value


def _rects_overlap(a: wintypes.RECT, b: wintypes.RECT) -> bool:
    return a.left < b.right and a.right > b.left and a.top < b.bottom and a.bottom > b.top


def _click_through_targets(root: int) -> list[int]:
    """Top-level window plus the Chromium windows that actually draw the page."""
    api = _user32_ptr()
    targets = []
    seen = set()

    def add(hwnd: int) -> None:
        value = int((hwnd or 0))
        if not value or value in seen:
            return None
        if "RenderWidgetHost" in _window_class(value):
            return None
        seen.add(value)
        targets.append(value)

    add(root)
    for child in _child_hwnds(root):
        add(child)
    root_pid = wintypes.DWORD()
    api.GetWindowThreadProcessId(wintypes.HWND(root), ctypes.byref(root_pid))
    root_rect = wintypes.RECT()
    api.GetWindowRect(wintypes.HWND(root), ctypes.byref(root_rect))
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    tops = []
    images = {}

    def image_for(pid: int) -> str:
        if pid not in images:
            images[pid] = _process_image(pid)
        return images[pid]

    def visit(hwnd, _lparam):
        tops.append(int(hwnd))
        return True

    callback = callback_type(visit)
    _click_through_targets.callback = callback
    ctypes.windll.user32.EnumWindows(callback, 0)
    for top in tops:
        proc = wintypes.DWORD()
        api.GetWindowThreadProcessId(wintypes.HWND(top), ctypes.byref(proc))
        class_name = _window_class(top)
        if "Chrome" not in class_name and "Qt" not in class_name:
            continue
        same_process = proc.value == root_pid.value
        if not same_process:
            if "QtWebEngine" not in image_for(proc.value):
                continue
            top_rect = wintypes.RECT()
            api.GetWindowRect(wintypes.HWND(top), ctypes.byref(top_rect))
            if not _rects_overlap(root_rect, top_rect):
                continue
        elif "Chrome_WidgetWin" not in class_name and top != root:
            continue
        add(top)
        for child in _child_hwnds(top):
            child_class = _window_class(child)
            if "RenderWidgetHost" in child_class:
                continue
            if not "Chrome_WidgetWin" in child_class and not child_class.startswith("Qt"):
                continue
            add(child)
    return targets


def set_taskbar_visible(hwnd: int, visible: bool) -> None:
    if sys.platform != "win32" or hwnd <= 0:
        return None
    style = _get_exstyle(hwnd)
    if visible:
        new_style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
    else:
        new_style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    if new_style != style:
        _set_exstyle(hwnd, new_style)
        return None


def _redraw_window(hwnd: int) -> None:
    _user32_ptr().RedrawWindow(wintypes.HWND(hwnd), None, None, 1409)


def _layered_alpha(hwnd: int) -> int | None:
    api = _user32_ptr()
    color = wintypes.DWORD()
    alpha = wintypes.BYTE()
    flags = wintypes.DWORD()
    if not api.GetLayeredWindowAttributes(
        wintypes.HWND(hwnd), ctypes.byref(color), ctypes.byref(alpha), ctypes.byref(flags)
    ):
        return None
    if not (int(flags.value) & LWA_ALPHA):
        return None
    return int(alpha.value)


def apply_click_through(hwnd: int, enabled: bool, opacity_percent: int) -> None:
    """Apply click-through and the opacity slider to the window and the doc view.

    Partial opacity and click-through both use a layered window. At 100% with
    click-through off, the layered style is removed so the window paints solid
    again instead of staying stuck on the last translucent frame.
    """
    if sys.platform != "win32" or hwnd <= 0:
        return None
    api = _user32_ptr()
    percent = max(1, min(100, int(opacity_percent)))
    alpha = int(round(((percent * 255) / 100)))
    changed = False
    for target in _click_through_targets(hwnd):
        style = _get_exstyle(target)
        if enabled:
            bits = CLICK_THROUGH_EXSTYLE if target == hwnd else (WS_EX_LAYERED | WS_EX_TRANSPARENT)
            new_style = style | bits
        else:
            new_style = style & (~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE))
            if target != hwnd or percent >= 100:
                new_style &= ~WS_EX_LAYERED
            elif target == hwnd:
                new_style |= WS_EX_LAYERED
        if new_style != style:
            _set_exstyle(target, new_style)
            changed = True
        if not (new_style & WS_EX_LAYERED):
            continue
        if not _layered_alpha(target) != alpha:
            continue
        api.SetLayeredWindowAttributes(wintypes.HWND(target), 0, alpha, LWA_ALPHA)
        changed = True
    if changed:
        _redraw_window(hwnd)
        return None


def yield_foreground(our_hwnd: int) -> None:
    if sys.platform != "win32" or our_hwnd <= 0:
        return None
    api = _user32_ptr()
    if int((api.GetForegroundWindow() or 0)) != our_hwnd:
        return None
    target = 0
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        nonlocal target
        if target:
            return True
        value = int((hwnd or 0))
        if not value or value == our_hwnd or not api.IsWindowVisible(hwnd):
            return True
        if api.GetWindowTextLengthW(hwnd) <= 0:
            return True
        target = value
        return True

    callback = callback_type(visit)
    yield_foreground.callback = callback
    ctypes.windll.user32.EnumWindows(callback, 0)
    if target:
        api.SetForegroundWindow(wintypes.HWND(target))
        return None


def is_key_down(vk: int) -> bool:
    return bool((ctypes.windll.user32.GetAsyncKeyState(vk) & 32768))


def is_ctrl_down() -> bool:
    return is_key_down(VK_CONTROL) or is_key_down(VK_LCONTROL) or is_key_down(VK_RCONTROL)


def is_alt_down() -> bool:
    return is_key_down(VK_MENU) or is_key_down(VK_LMENU) or is_key_down(VK_RMENU)


def is_shift_down() -> bool:
    return is_key_down(VK_SHIFT) or is_key_down(VK_LSHIFT) or is_key_down(VK_RSHIFT)


def register_ghost_hotkeys(hwnd: int) -> None:
    if sys.platform != "win32" or hwnd <= 0:
        return None
    user32 = ctypes.windll.user32
    mods = MOD_CONTROL | MOD_NOREPEAT
    user32.RegisterHotKey(hwnd, GHOST_HOTKEY_ID_ALT, (mods | MOD_ALT), VK_Z)
    user32.RegisterHotKey(hwnd, GHOST_HOTKEY_ID_SHIFT, (mods | MOD_SHIFT), VK_Z)


def unregister_ghost_hotkeys(hwnd: int) -> None:
    if sys.platform != "win32" or hwnd <= 0:
        return None
    user32 = ctypes.windll.user32
    user32.UnregisterHotKey(hwnd, GHOST_HOTKEY_ID_ALT)
    user32.UnregisterHotKey(hwnd, GHOST_HOTKEY_ID_SHIFT)


def native_message_address(message) -> int:
    if isinstance(message, int):
        return message
    return int(message)


def is_ghost_hotkey_pressed() -> bool:
    if sys.platform != "win32":
        return False
    z_down = is_key_down(VK_Z)
    return z_down and is_ctrl_down() and (is_alt_down() or is_shift_down())


def is_share_hotkey_pressed() -> bool:
    if sys.platform != "win32":
        return False
    return is_key_down(VK_A) and is_ctrl_down() and is_shift_down()


def app_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent
    data = base / "data"
    data.mkdir(exist_ok=True)
    return data


def config_path() -> Path:
    return app_data_dir() / "config.json"


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return {}


def save_config(**values) -> None:
    config = load_config()
    config.update(values)
    config_path().write_text(json.dumps(config, indent=2), encoding="utf-8")


def extract_doc_id(url: str) -> str | None:
    match = DOC_ID_PATTERN.search(url.strip())
    if match:
        return match.group(1)


def to_live_url(url: str) -> str | None:
    doc_id = extract_doc_id(url)
    if not doc_id:
        return None
    return f"https://docs.google.com/document/d/{doc_id}/edit"


class DocWebPage(QWebEnginePage):
    def createWindow(self, _type):
        pass


class GhostHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, viewer: GoogleDocViewer) -> None:
        super().__init__()
        self._viewer = viewer

    def nativeEventFilter(self, eventType, message):
        if sys.platform != "win32":
            return (False, 0)
        try:
            event_name = bytes(eventType)
            if event_name not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                return (False, 0)
            msg = wintypes.MSG.from_address(native_message_address(message))
            if msg.message == WM_HOTKEY and msg.wParam in (
                GHOST_HOTKEY_ID_ALT,
                GHOST_HOTKEY_ID_SHIFT,
            ):
                QTimer.singleShot(0, self._viewer._toggle_click_through)
                return (True, 0)
        except AttributeError, OSError, TypeError, ValueError:
            pass
        return (False, 0)


class GoogleDocViewer(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(_document_icon())
        self.setWindowFlags(
            (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        )
        self.resize(1200, 800)
        profile = QWebEngineProfile("SupportApp", self)
        self._profile = profile
        storage = app_data_dir() / "browser"
        storage.mkdir(exist_ok=True)
        profile.setPersistentStoragePath(str(storage))
        profile.setCachePath(str((app_data_dir() / "cache")))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )
        central = QWidget()
        central.setObjectName("appFrame")
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        central.setStyleSheet("#appFrame { background: #6b7585; }")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)
        self._body_layout = layout
        inner = QWidget()
        inner.setObjectName("appInner")
        inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        inner.setStyleSheet("#appInner { background: #ffffff; border: 1px solid #d5dbe3; }")
        self._inner = inner
        self._inner_style = inner.styleSheet()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        layout.addWidget(inner)
        layout = inner_layout
        self._content_layout = layout
        self.toolbar = QWidget()
        self.toolbar.setObjectName("appTitleBar")
        self.toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.toolbar.setFixedHeight(40)
        self.toolbar.setStyleSheet(
            "QWidget#appTitleBar { background: #f4f6f8; border-bottom: 1px solid #c5ced8; }QLabel { color: #667085; background: transparent; }QLabel#opacityValue { color: #1c2430; }QLineEdit {  background: #ffffff; color: #1c2430; border: 1px solid #d8dee6;  border-radius: 6px; padding: 0 8px; selection-background-color: #d6e6ff;}QLineEdit:focus { border: 1px solid #1f6feb; }QPushButton {  background: #ffffff; color: #1c2430; border: 1px solid #d8dee6;  border-radius: 6px; padding: 0 8px;}QPushButton:hover { background: #f3f6fa; }QPushButton#loadBtn { background: #1f6feb; color: #ffffff; border: none; }QPushButton#loadBtn:hover { background: #1a62d0; }QPushButton#ghostBtn:checked, QPushButton#shareBtn:checked, QPushButton#splitBtn:checked {  background: #e8f1ff; color: #1d4f91; border: 1px solid #b9d4f5;}QPushButton#titleMin, QPushButton#titleClose {  border: none; border-radius: 0; background: transparent; color: #3d4654; padding: 0;}QPushButton#titleMin:hover { background: #e8ebf0; }QPushButton#titleClose:hover { background: #d92d20; color: #ffffff; }QLabel#moveGrip { color: #667085; padding: 0 14px; border-left: 1px solid #e4e7ec; }QLabel#moveGrip:hover { background: #eef1f5; color: #1c2430; }QSlider::groove:horizontal { height: 4px; background: #d8dee6; border-radius: 2px; }QSlider::handle:horizontal {  width: 12px; height: 12px; margin: -5px 0; background: #1f6feb; border-radius: 6px;}QPushButton#restoreBtn {  border: 1px solid #e2e2e2; border-radius: 12px; background: #ffffff; padding: 0;}QPushButton#restoreBtn:hover { background: #f6f6f6; border-color: #d0d0d0; }"
        )
        self._title_bar_style = self.toolbar.styleSheet()
        input_row = QHBoxLayout(self.toolbar)
        input_row.setContentsMargins(10, 6, 0, 6)
        input_row.setSpacing(6)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste a Google Doc link")
        self.url_input.setFont(QFont("Segoe UI", 9))
        self.url_input.setFixedWidth(220)
        self.url_input.setToolTip("Paste a Google Doc link, then press Enter or Load")
        self.url_input.returnPressed.connect(self.load_document)
        load_btn = QPushButton("Load")
        load_btn.setObjectName("loadBtn")
        load_btn.setFont(QFont("Segoe UI", 9))
        load_btn.setFixedWidth(64)
        load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        load_btn.setToolTip("Open the document")
        load_btn.clicked.connect(self.load_document)
        self.load_btn = load_btn
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setFixedWidth(96)
        self.opacity_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.opacity_slider.setToolTip("Drag to fade the window. 100% is fully solid")
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.opacity_value = QLabel("100%")
        self.opacity_value.setObjectName("opacityValue")
        self.opacity_value.setFont(QFont("Segoe UI", 9))
        self.opacity_value.setFixedWidth(40)
        self.opacity_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.share_hide_btn = QPushButton("Hide")
        self.share_hide_btn.setObjectName("shareBtn")
        self.share_hide_btn.setFont(QFont("Segoe UI", 9))
        self.share_hide_btn.setCheckable(True)
        self.share_hide_btn.setFixedWidth(72)
        self.share_hide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.share_hide_btn.setToolTip(
            "Hide this window from screen share. Shows Hidden when it is on"
        )
        self.share_hide_btn.toggled.connect(self._on_share_privacy_toggled)
        self.split_btn = QPushButton("6")
        self.split_btn.setObjectName("splitBtn")
        self.split_btn.setFont(QFont("Segoe UI", 9))
        self.split_btn.setCheckable(True)
        self.split_btn.setFixedWidth(40)
        self.split_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.split_btn.setToolTip(
            "Fill the screen with this same document, six times. Click again to show one."
        )
        self.split_btn.toggled.connect(self._on_split_toggled)
        self.ghost_btn = QPushButton("Ghost")
        self.ghost_btn.setObjectName("ghostBtn")
        self.ghost_btn.setFont(QFont("Segoe UI", 9))
        self.ghost_btn.setCheckable(True)
        self.ghost_btn.setFixedWidth(84)
        self.ghost_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ghost_btn.setToolTip(
            "Clicks pass through the window. Press Ctrl+Shift+Z to turn it off"
        )
        self.ghost_btn.toggled.connect(self._on_ghost_button_toggled)
        self.min_btn = QPushButton("—")
        self.min_btn.setObjectName("titleMin")
        self.min_btn.setFixedWidth(40)
        self.min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.min_btn.setToolTip(
            "Shrink to a button at the bottom-left. Double-click that button to open again"
        )
        self.min_btn.clicked.connect(self._collapse_to_button)
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("titleClose")
        self.close_btn.setFixedWidth(46)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setToolTip("Close")
        self.close_btn.clicked.connect(self.close)
        self.move_grip = QLabel("Move")
        self.move_grip.setObjectName("moveGrip")
        self.move_grip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.move_grip.setCursor(Qt.CursorShape.SizeAllCursor)
        self.move_grip.setToolTip("Drag here to move the window")
        self.restore_btn = QPushButton()
        self.restore_btn.setObjectName("restoreBtn")
        self.restore_btn.setIcon(_document_icon())
        self.restore_btn.setIconSize(QSize(20, 20))
        self.restore_btn.setFixedSize(48, 48)
        self.restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore_btn.setToolTip("Double-click to open the document")
        self.restore_btn.hide()
        self._collapsed = False
        self._saved_geometry = None
        self._share_before_collapse = False
        self._ghost_before_collapse = False
        self._collapse_press = None
        self._collapse_dragging = False
        self._split_on = False
        self._geometry_before_split = None
        self._stable_page_width = None
        self._fit_widths = {}
        self._doc_views = []
        self.restore_btn.installEventFilter(self)
        input_row.addWidget(self.restore_btn)
        input_row.addWidget(self.url_input)
        input_row.addWidget(load_btn)
        input_row.addWidget(self.ghost_btn)
        input_row.addWidget(self.share_hide_btn)
        input_row.addWidget(self.opacity_slider)
        input_row.addWidget(self.opacity_value)
        input_row.addWidget(self.split_btn)
        input_row.addWidget(self.move_grip, stretch=1)
        input_row.addWidget(self.min_btn)
        input_row.addWidget(self.close_btn)
        layout.addWidget(self.toolbar)
        self._title_full_widths = {
            self.url_input: 220,
            self.load_btn: 64,
            self.ghost_btn: 84,
            self.share_hide_btn: 72,
            self.opacity_slider: 96,
            self.opacity_value: 40,
            self.split_btn: 40,
            self.min_btn: 40,
            self.close_btn: 46,
        }
        self.setMinimumWidth(120)
        self._layout_title_bar(self.width())
        self.web_view = self._make_doc_view()
        self._doc_views = [self.web_view]
        layout.addWidget(self.web_view, stretch=1)
        self._grid_host = QWidget()
        self._grid_host.setObjectName("docGrid")
        self._grid_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._grid_host.setStyleSheet("QWidget#docGrid { background: #d5dbe3; }")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(3)
        self._grid_host.hide()
        self.current_url = None
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(200)
        self._fit_timer.timeout.connect(self._fit_to_window)
        self._zoom_lock_timer = QTimer(self)
        self._zoom_lock_timer.setSingleShot(True)
        self._zoom_lock_timer.setInterval(40)
        self._zoom_lock_timer.timeout.connect(self._restore_locked_zoom)
        self._click_through_enabled = False
        self._os_click_through = False
        self._last_ghost_toggle = 0.0
        self._hotkey_was_down = False
        self._share_hotkey_was_down = False
        self._click_through_timer = QTimer(self)
        self._click_through_timer.setInterval(100)
        self._click_through_timer.timeout.connect(self._reapply_click_through)
        self._hotkey_poll_timer = QTimer(self)
        self._hotkey_poll_timer.setInterval(50)
        self._hotkey_poll_timer.timeout.connect(self._poll_hotkeys)
        self._hotkey_poll_timer.start()
        config = load_config()
        saved_url = config.get("doc_url", "")
        saved_opacity = config.get("opacity", 100)
        self._share_privacy_enabled = bool(config.get("hide_from_share", False))
        self.share_hide_btn.setChecked(self._share_privacy_enabled)
        self.opacity_slider.setValue(int(saved_opacity))
        self._apply_opacity(int(saved_opacity))
        if saved_url:
            self.url_input.setText(saved_url)
            QTimer.singleShot(300, self.load_document)
            return None

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32":
            try:
                event_name = bytes(eventType)
            except TypeError:
                event_name = b""
            if event_name in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = wintypes.MSG.from_address(native_message_address(message))
                if msg.message == WM_NCHITTEST:
                    hit = self._title_bar_hit()
                    if hit:
                        return (True, hit)
        return super().nativeEvent(eventType, message)

    def _title_bar_hit(self) -> int:
        pos = self.mapFromGlobal(QCursor.pos())
        if self.isMinimized():
            return 0
        border = 0 if self.isMaximized() else 6
        width = self.width()
        height = self.height()
        on_left = pos.x() <= border
        on_right = pos.x() >= (width - border)
        on_top = pos.y() <= border
        on_bottom = pos.y() >= (height - border)
        if on_top and on_left:
            return HTTOPLEFT
        if on_top and on_right:
            return HTTOPRIGHT
        if on_bottom and on_left:
            return HTBOTTOMLEFT
        if on_bottom and on_right:
            return HTBOTTOMRIGHT
        if on_left:
            return HTLEFT
        if on_right:
            return HTRIGHT
        if on_top:
            return HTTOP
        if on_bottom:
            return HTBOTTOM
        if not self.toolbar.geometry().contains(pos):
            return 0
        local = self.toolbar.mapFromGlobal(QCursor.pos())
        child = self.toolbar.childAt(local)
        if child is None or child is self.move_grip:
            return HTCAPTION
        return 0

    def eventFilter(self, watched, event):
        if watched in getattr(self, "_doc_views", []) and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                return True
            if hasattr(self, "_zoom_lock_timer"):
                self._zoom_lock_timer.start()
        if watched is self.restore_btn and getattr(self, "_collapsed", False):
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self._expand_from_min()
                return True
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._collapse_press = event.globalPosition().toPoint()
                self._collapse_dragging = False
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._collapse_press = None
                self._collapse_dragging = False
            elif (
                event.type() == QEvent.Type.MouseMove
                and (event.buttons() & Qt.MouseButton.LeftButton)
                and self._collapse_press is not None
            ):
                now = event.globalPosition().toPoint()
                delta = now - self._collapse_press
                if self._collapse_dragging or delta.manhattanLength() > 8:
                    self._collapse_dragging = True
                    self.move((self.x() + delta.x()), (self.y() + delta.y()))
                    self._collapse_press = now
                    return True
        return super().eventFilter(watched, event)

    def _bar_widgets(self) -> list[QWidget]:
        return [
            self.url_input,
            self.load_btn,
            self.ghost_btn,
            self.share_hide_btn,
            self.opacity_slider,
            self.opacity_value,
            self.split_btn,
            self.move_grip,
            self.min_btn,
            self.close_btn,
        ]

    def _collapse_to_button(self) -> None:
        if self._collapsed:
            return None
        self._saved_geometry = self.geometry()
        self._share_before_collapse = self._share_privacy_enabled
        self._ghost_before_collapse = self._click_through_enabled
        if self._click_through_enabled:
            self._set_ghost_mode(False)
        self._collapsed = True
        if self._split_on:
            self._grid_host.hide()
        else:
            self.web_view.hide()
        for widget in self._bar_widgets():
            widget.hide()
        for widget in self.toolbar.findChildren(QPushButton):
            if not widget is not self.restore_btn:
                continue
            widget.hide()
        self.restore_btn.show()
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._inner.setStyleSheet("#appInner { background: #ffffff; border: none; }")
        bar_layout = self.toolbar.layout()
        bar_layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar.setFixedHeight(48)
        self.toolbar.setStyleSheet(
            "QWidget#appTitleBar { background: #ffffff; border: none; }QPushButton#restoreBtn {  border: 2px solid #6b7585;  border-radius: 12px;  background: #ffffff;  padding: 0;}QPushButton#restoreBtn:hover { background: #f4f6f8; border-color: #6b7585; }"
        )
        self.setMinimumSize(48, 48)
        self.setMaximumSize(48, 48)
        center = self.frameGeometry().center()
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = area.left() + 20
        y = (area.bottom() - 48) - 20
        self.setGeometry(x, y, 48, 48)
        self.clearMask()
        self.raise_()
        self.show()
        self._apply_opacity(self.opacity_slider.value())
        set_exclude_from_capture(int(self.winId()), True)
        self._hide_from_taskbar()

    def _expand_from_min(self) -> None:
        if not self._collapsed:
            return None
        self._collapsed = False
        self.restore_btn.hide()
        self._body_layout.setContentsMargins(8, 8, 8, 8)
        self._inner.setStyleSheet(self._inner_style)
        bar_layout = self.toolbar.layout()
        bar_layout.setContentsMargins(10, 6, 0, 6)
        self.toolbar.setFixedHeight(40)
        self.toolbar.setStyleSheet(self._title_bar_style)
        self.clearMask()
        self.web_view.show() if not self._split_on else self._grid_host.show()
        for widget in self._bar_widgets():
            widget.show()
        for widget in self.toolbar.findChildren(QPushButton):
            if not widget is not self.restore_btn:
                continue
            widget.show()
        self.setMinimumSize(120, 160)
        self.setMaximumSize(16777215, 16777215)
        if self._saved_geometry is not None:
            self.setGeometry(self._saved_geometry)
        self._apply_share_privacy(self._share_before_collapse)
        if self._ghost_before_collapse:
            self._set_ghost_mode(True)
        self._apply_opacity(self.opacity_slider.value())
        self._layout_title_bar(self.width())
        QTimer.singleShot(0, self._fit_to_window)

    def _layout_title_bar(self, width: int) -> None:
        if self._collapsed or not hasattr(self, "_title_full_widths"):
            return None
        controls = list(self._title_full_widths)
        only_move = width <= 340
        for widget in controls:
            widget.setVisible((not only_move))
        self.move_grip.show()
        if only_move:
            return None
        scale = 0.45 + (0.55 * min(1.0, max(0.0, ((width - 340) / 660))))
        for widget, full in self._title_full_widths.items():
            widget.setFixedWidth(max(24, int((full * scale))))

    def load_document(self) -> None:
        raw_url = self.url_input.text().strip()
        if not raw_url:
            QMessageBox.warning(self, "Missing URL", "Please enter a Google Doc URL.")
            return None
        doc_url = to_live_url(raw_url)
        if not doc_url:
            QMessageBox.warning(self, "Invalid URL", "Could not find a Google Doc ID in that URL.")
            return None
        save_config(doc_url=raw_url)
        self.current_url = doc_url
        self._stable_page_width = None
        self._fit_widths.clear()
        for view in self._doc_views:
            view.setUrl(QUrl(doc_url))

    def _make_doc_view(self) -> QWebEngineView:
        view = QWebEngineView()
        page = DocWebPage(self._profile, view)
        view.setPage(page)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        settings = view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.AllowWindowActivationFromJavaScript, False
        )
        view.loadFinished.connect(self._on_page_loaded)
        view.installEventFilter(self)
        view.page().setBackgroundColor(QColor("white"))
        return view

    def _on_split_toggled(self, enabled: bool) -> None:
        if self._collapsed:
            self.split_btn.blockSignals(True)
            self.split_btn.setChecked(False)
            self.split_btn.blockSignals(False)
            return None
        if enabled:
            self._enter_split()
            return None
        self._leave_split()

    def _enter_split(self) -> None:
        if not self.current_url:
            self.split_btn.blockSignals(True)
            self.split_btn.setChecked(False)
            self.split_btn.blockSignals(False)
            QMessageBox.warning(self, "No document", "Load a Google Doc first, then click 6.")
            return None
        self._geometry_before_split = self.geometry()
        while len(self._doc_views) < 6:
            view = self._make_doc_view()
            self._doc_views.append(view)
            view.setUrl(QUrl(self.current_url))
        self._content_layout.removeWidget(self.web_view)
        for index, view in enumerate(self._doc_views):
            row, column = divmod(index, 3)
            self._grid.addWidget(view, row, column)
            self._grid.setRowStretch(row, 1)
            self._grid.setColumnStretch(column, 1)
            view.show()
        self._content_layout.addWidget(self._grid_host, stretch=1)
        self._grid_host.show()
        self._split_on = True
        self.split_btn.setText("1")
        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = self.screen() or QApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        self._fit_widths.clear()
        QTimer.singleShot(150, self._fit_to_window)

    def _leave_split(self) -> None:
        if not self._split_on and self.web_view.parentWidget() is not self._grid_host:
            self.split_btn.setText("6")
            return None
        self._split_on = False
        self.split_btn.setText("6")
        self._grid_host.hide()
        self._content_layout.removeWidget(self._grid_host)
        for view in self._doc_views:
            self._grid.removeWidget(view)
            if not view is not self.web_view:
                continue
            view.hide()
        self._content_layout.addWidget(self.web_view, stretch=1)
        self.web_view.show()
        self._body_layout.setContentsMargins(8, 8, 8, 8)
        self._inner.setStyleSheet(self._inner_style)
        if self._geometry_before_split is not None:
            self.setGeometry(self._geometry_before_split)
        self._fit_widths.clear()
        QTimer.singleShot(0, self._fit_to_window)

    def _shown_opacity(self) -> int:
        if self._collapsed:
            return 100
        return max(30, min(100, int(self.opacity_slider.value())))

    def _apply_opacity(self, value: int) -> None:
        value = max(30, min(100, int(value)))
        self.opacity_value.setText(f"{value}%")
        self.setWindowOpacity((self._shown_opacity() / 100.0))
        self._sync_click_through(force=True)
        self.update()
        self.web_view.update()

    def _on_opacity_changed(self, value: int) -> None:
        self._apply_opacity(value)
        save_config(opacity=value)

    def _hide_from_taskbar(self) -> None:
        set_taskbar_visible(int(self.winId()), False)

    def _register_hotkeys(self) -> None:
        register_ghost_hotkeys(int(self.winId()))

    def _poll_hotkeys(self) -> None:
        ghost_pressed = is_ghost_hotkey_pressed()
        if ghost_pressed and not self._hotkey_was_down and not self._collapsed:
            self._toggle_click_through()
        self._hotkey_was_down = ghost_pressed
        share_pressed = is_share_hotkey_pressed()
        if share_pressed and not self._share_hotkey_was_down and not self._collapsed:
            self._toggle_share_visibility()
        self._share_hotkey_was_down = share_pressed

    def _sync_click_through(self, force: bool = False) -> None:
        desired = self._click_through_enabled
        if not force and desired == self._os_click_through:
            return None
        self._os_click_through = desired
        apply_click_through(int(self.winId()), desired, self._shown_opacity())
        self._hide_from_taskbar()

    def _reapply_click_through(self) -> None:
        if not self._click_through_enabled:
            return None
        apply_click_through(int(self.winId()), True, self._shown_opacity())
        self._hide_from_taskbar()

    def _release_input_focus(self) -> None:
        grabber = QWidget.mouseGrabber()
        if grabber is not None:
            grabber.releaseMouse()
        self.releaseMouse()
        yield_foreground(int(self.winId()))

    def _set_ghost_mode(self, enabled: bool) -> None:
        if self._click_through_enabled == enabled:
            return None
        self._last_ghost_toggle = time.monotonic()
        self._click_through_enabled = enabled
        self.ghost_btn.blockSignals(True)
        self.ghost_btn.setChecked(enabled)
        self.ghost_btn.blockSignals(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        for widget in self.findChildren(QWidget):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._apply_opacity(self.opacity_slider.value())
        if self._share_privacy_enabled:
            self._apply_share_privacy(True)
        if enabled:
            self.ghost_btn.setText("Ghost ON")
            self.setWindowTitle(f"{APP_NAME} — Ghost (Ctrl+Shift+Z)")
            self._click_through_timer.start()
            QTimer.singleShot(0, self._release_input_focus)
            QTimer.singleShot(50, self._reapply_click_through)
            QTimer.singleShot(300, self._reapply_click_through)
            return None
        self._click_through_timer.stop()
        self.ghost_btn.setText("Ghost")
        self.setWindowTitle(APP_NAME)

    def _toggle_click_through(self) -> None:
        now = time.monotonic()
        if (now - self._last_ghost_toggle) < 0.35:
            return None
        self._last_ghost_toggle = now
        self._set_ghost_mode((not self._click_through_enabled))

    def _on_ghost_button_toggled(self, enabled: bool) -> None:
        self._set_ghost_mode(enabled)

    def _toggle_share_visibility(self) -> None:
        self._share_privacy_enabled = not self._share_privacy_enabled
        self.share_hide_btn.blockSignals(True)
        self.share_hide_btn.setChecked(self._share_privacy_enabled)
        self.share_hide_btn.blockSignals(False)
        self._apply_share_privacy(self._share_privacy_enabled)
        save_config(hide_from_share=self._share_privacy_enabled)

    def closeEvent(self, event) -> None:
        unregister_ghost_hotkeys(int(self.winId()))
        super().closeEvent(event)

    def _on_share_privacy_toggled(self, enabled: bool) -> None:
        self._share_privacy_enabled = enabled
        self._apply_share_privacy(enabled)
        save_config(hide_from_share=enabled)

    def _apply_share_privacy(self, enabled: bool) -> None:
        hwnd = int(self.winId())
        if enabled:
            self._apply_opacity(self.opacity_slider.value())
            capture_ok = set_exclude_from_capture(hwnd, True)
            if capture_ok:
                self.share_hide_btn.setText("Hidden")
                return None
            set_exclude_from_capture(hwnd, False)
            self.share_hide_btn.setText("Hide")
            self.share_hide_btn.blockSignals(True)
            self.share_hide_btn.setChecked(False)
            self.share_hide_btn.blockSignals(False)
            self._share_privacy_enabled = False
            self._apply_opacity(self.opacity_slider.value())
            return None
        set_exclude_from_capture(hwnd, False)
        self.share_hide_btn.setText("Hide")
        self._apply_opacity(self.opacity_slider.value())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._hide_from_taskbar)
        QTimer.singleShot(0, self._register_hotkeys)
        QTimer.singleShot(0, (lambda: self._apply_opacity(self.opacity_slider.value())))
        if self._share_privacy_enabled:
            QTimer.singleShot(0, (lambda: self._apply_share_privacy(True)))
        elif self._collapsed:
            QTimer.singleShot(0, (lambda: set_exclude_from_capture(int(self.winId()), True)))

    def _on_page_loaded(self, ok: bool) -> None:
        if not ok:
            return None
        for delay in (400, 1000, 1800, 3200, 5000):
            QTimer.singleShot(delay, self._fit_to_window)
        QTimer.singleShot(500, (lambda: self._apply_opacity(self.opacity_slider.value())))
        if self._share_privacy_enabled or self._collapsed:
            QTimer.singleShot(800, (lambda: set_exclude_from_capture(int(self.winId()), True)))
            return None

    def _restore_locked_zoom(self) -> None:
        if self._collapsed or self._stable_page_width is None:
            return None
        views = self._doc_views if self._split_on else [self.web_view]
        page_width = self._stable_page_width or DEFAULT_PAGE_WIDTH
        for view in views:
            last_width = self._fit_widths.get(view, -1)
            if last_width < 0 or abs((view.width() - last_width)) >= 2:
                continue
            zoom = (float(last_width) - 28) / page_width
            zoom = max(0.2, min(zoom, 8.0))
            if not abs(((view.zoomFactor() or 1.0) - zoom)) > 0.008:
                continue
            view.setZoomFactor(zoom)

    def _fit_to_window(self) -> None:
        views = self._doc_views if self._split_on else [self.web_view]
        for view in views:
            self._fit_one(view)

    def _fit_one(self, view: QWebEngineView) -> None:
        view_width = view.width()
        if self._collapsed or view_width < 80:
            return None

        def apply_zoom(result, view=view, view_width=view_width) -> None:
            measured = 0.0
            if isinstance(result, str) and ":" in result:
                result = result.split(":", 1)[0]
            try:
                measured = float((result or 0))
            except TypeError, ValueError:
                measured = 0.0
            learned = False
            if measured >= 100 and self._stable_page_width is None:
                self._stable_page_width = measured
                learned = True
            page_width = self._stable_page_width or DEFAULT_PAGE_WIDTH
            last_width = self._fit_widths.get(view, -1)
            width_changed = abs((view_width - last_width)) >= 2
            if not learned and not width_changed:
                return None
            self._fit_widths[view] = view_width
            current = view.zoomFactor() or 1.0
            zoom = (float(view_width) - 28) / page_width
            zoom = max(0.2, min(zoom, 8.0))
            if abs((current - zoom)) > 0.008:
                view.setZoomFactor(zoom)
            if learned or width_changed:
                QTimer.singleShot(80, (lambda view=view: self._align_page(view)))
                return None

        view.page().runJavaScript(FIT_PAGE_JS, apply_zoom)

    def _align_page(self, view: QWebEngineView | None = None) -> None:
        target = view or self.web_view
        target.page().runJavaScript((FIT_PAGE_JS + """
;(function() {
    var page = document.querySelector(".kix-page") || document.querySelector(".kix-page-paginated");
    var editor = document.querySelector(".kix-appview-editor");
    if (!page || !editor) return;
    var dx = page.getBoundingClientRect().left - editor.getBoundingClientRect().left;
    if (Math.abs(dx) > 0.5) editor.scrollLeft += dx;
})();
"""))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_title_bar(self.width())
        self._fit_timer.start()
        if self._click_through_enabled:
            QTimer.singleShot(0, self._reapply_click_through)
            return None


def main() -> int:
    if not ensure_single_instance():
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(_document_icon())
    app.setFont(QFont("Segoe UI", 9))
    window = GoogleDocViewer()
    app.installNativeEventFilter(GhostHotkeyFilter(window))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
else:
    pass
