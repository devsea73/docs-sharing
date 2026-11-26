from dataclasses import asdict, dataclass
from ctypes.wintypes import MSG
import json
import os
from pathlib import Path
import sys
import traceback
import winreg

from PySide6.QtCore import QEvent, QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel, QLayout,
    QMessageBox, QPushButton, QScrollBar, QSizePolicy, QSlider, QStackedLayout, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)
from shiboken6 import delete

from browser import DocumentView, configure_portable_paths, make_profile, normalize_document_url
import win32 as native


TITLE = "Anti"
DOC_URL_VARIABLE = "ANTI_GOOGLE_DOC_URL"
DOC_URL_HELP = f"Set a valid {DOC_URL_VARIABLE} using set-doc-url.cmd."
DEFAULT_OPACITY = 70
MINIMUM_SIZE = QSize(440, 250)
DEFAULT_SIZE = QSize(800, 680)
SPLIT_PANES = 6
OPENING_SPLIT = "Opening six views…"
PANIC, GHOST, GHOST_ALT, SHARE, VISIBILITY = range(1, 6)
HOTKEYS = {
    PANIC: (native.MOD_CONTROL | native.MOD_SHIFT, ord("Z")),
    GHOST: (native.MOD_CONTROL | native.MOD_ALT, ord("Z")),
    GHOST_ALT: (native.MOD_CONTROL | native.MOD_ALT | native.MOD_SHIFT, ord("Z")),
    SHARE: (native.MOD_CONTROL | native.MOD_ALT, ord("A")),
    VISIBILITY: (native.MOD_CONTROL | native.MOD_ALT, ord("Q")),
}


STYLES = """
QWidget { color: #f4f7ff; font-size: 14px; }
QWidget#shell { background: #151e2b; border: 1px solid #54647d; }
QWidget#titleBar { background: #202d40; border-bottom: 1px solid #3a4b63; }
QLabel#emptyTitle { font-size: 23px; font-weight: 700; }
QLabel#emptyHelp, QLabel#status { color: #cbd8ec; }
QLabel#opacityValue { color: #f4f7ff; font-weight: 700; }
QWidget#statusPanel { background: #151e2b; }
QWidget#docGrid { background: #45556d; }
QLabel#mirrorCover { background: #111923; }
QScrollBar#splitScroll:vertical { background: #202d40; width: 12px; }
QScrollBar#splitScroll::handle:vertical { background: #697e9c; min-height: 32px; border-radius: 4px; }
QScrollBar#splitScroll::add-line:vertical,
QScrollBar#splitScroll::sub-line:vertical { height: 0; }
QPushButton {
    background: #26354b;
    border: 1px solid #526784;
    border-radius: 6px;
    padding: 4px 9px;
    font-weight: 600;
}
QPushButton:hover { background: #314665; border-color: #8baddb; }
QPushButton:checked { background: #284d77; color: #fff; border-color: #a1caff; }
QPushButton:disabled { color: #9baac0; background: #202b3c; }
QPushButton:focus, QToolButton:focus { border: 1px solid #97c4ff; }
QToolButton {
    border: 1px solid transparent;
    background: transparent;
    padding: 4px 4px;
    border-radius: 4px;
    font-weight: 600;
}
QToolButton:hover { background: #314665; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: #617595; }
QSlider::handle:horizontal { width: 12px; margin: -4px 0; border-radius: 6px; background: #a8ceff; }
"""


@dataclass
class Settings:
    opacity: int = DEFAULT_OPACITY
    hide_from_share: bool = False

    @classmethod
    def read(cls, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        opacity = data.get("opacity")
        return cls(
            opacity=max(20, min(100, opacity)) if type(opacity) is int else DEFAULT_OPACITY,
            hide_from_share=data.get("hide_from_share") is True,
        )

    def write(self, path):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def configured_document_link():
    # Read persistent values first so launches from an older terminal see updates.
    for hive, path in (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ):
        try:
            with winreg.OpenKey(hive, path) as key:
                value, kind = winreg.QueryValueEx(key, DOC_URL_VARIABLE)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return winreg.ExpandEnvironmentStrings(value) if kind == winreg.REG_EXPAND_SZ else value
    return os.environ.get(DOC_URL_VARIABLE, "")


class DragGrip(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent, text="Move")
        self.drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.window().pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self.drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        super().mouseReleaseEvent(event)


class MirrorPane(QWidget):
    def __init__(self, number, profile, parent):
        super().__init__(parent)
        self.setAccessibleName(f"Document view {number}")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layers = QStackedLayout(self)
        layers.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.view = DocumentView(profile, self, mirrored=True)
        self.view.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.view.setAccessibleName(self.accessibleName())
        layers.addWidget(self.view)
        self.cover = QLabel(
            "Loading document…", objectName="mirrorCover", alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.cover.setWordWrap(True)
        layers.addWidget(self.cover)
        layers.setCurrentWidget(self.cover)
        self.view.readiness_changed.connect(lambda ready: self.cover.setVisible(not ready))
        self.view.status_changed.connect(self.show_status)

    def show_status(self, message, _failed):
        if message:
            self.cover.setText(message)


class SplitPages(QWidget):
    def __init__(self, profile, parent):
        super().__init__(parent)
        self.profile = profile
        self.panes = []
        self.document_width = 0
        self.viewport_height = 0
        self.columns = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.content = QWidget(self, objectName="docGrid")
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(2)
        layout.addWidget(self.content, 1)
        self.scrollbar = QScrollBar(Qt.Orientation.Vertical, objectName="splitScroll")
        self.scrollbar.setAccessibleName("Scroll all six views")
        self.scrollbar.setSingleStep(64)
        self.scrollbar.setRange(0, 0)
        self.scrollbar.valueChanged.connect(self.apply_scroll_position)
        layout.addWidget(self.scrollbar)
        self.zoom_timer = QTimer(self, interval=0, singleShot=True, timeout=self.fit_views)
        self.range_timer = QTimer(self, interval=0, singleShot=True, timeout=self.update_scroll_range)

    def load_views(self, url, state):
        self.clear()
        self.document_width = state["pageWidth"]
        start = round(state["scrollTop"])
        self.scrollbar.setRange(0, max(start, state["scrollHeight"]))
        self.scrollbar.setValue(start)
        for index in range(SPLIT_PANES):
            pane = MirrorPane(index + 1, self.profile, self.content)
            pane.view.scroll_requested.connect(self.scroll_by)
            pane.view.viewport_changed.connect(self.range_timer.start)
            pane.view.readiness_changed.connect(lambda _ready: self.range_timer.start())
            self.panes.append(pane)
        self.arrange_panes()
        self.apply_scroll_position(start)
        for pane in self.panes:
            pane.view.load(url)
        self.zoom_timer.start()

    def clear(self):
        self.zoom_timer.stop()
        self.range_timer.stop()
        for pane in self.panes:
            self.grid.removeWidget(pane)
            pane.hide()
            pane.view.dispose()
            pane.deleteLater()
        self.panes.clear()
        self.columns = 0
        self.viewport_height = 0
        self.scrollbar.setRange(0, 0)

    def arrange_panes(self):
        columns = 3 if self.width() >= 640 else 2
        if not self.panes or columns == self.columns:
            return
        self.columns = columns
        for index in range(3):
            self.grid.setColumnStretch(index, int(index < columns))
            self.grid.setRowStretch(index, int(index < SPLIT_PANES // columns))
        for index, pane in enumerate(self.panes):
            self.grid.addWidget(pane, *divmod(index, columns))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange_panes()
        if self.panes:
            self.zoom_timer.start()

    def fit_views(self):
        if not self.panes:
            return
        width = min(pane.view.width() for pane in self.panes)
        if width > 0:
            zoom = max(0.25, min(5.0, width / self.document_width))
            for pane in self.panes:
                pane.view.set_mirror_zoom(zoom)

    def wheelEvent(self, event):
        if self.panes and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.pixelDelta().y() or round(event.angleDelta().y() / 120 * 64)
            self.scroll_by(round(delta / self.panes[0].view.zoomFactor()))
        event.accept()

    def update_scroll_range(self):
        measured = [pane.view for pane in self.panes if pane.view.viewport_height and pane.view.scroll_extent]
        if not measured:
            return
        self.viewport_height = min(view.viewport_height for view in measured)
        limit = min(view.scroll_extent for view in measured) - self.viewport_height
        if len(measured) < len(self.panes):
            # Keep the startup position until all views report their scroll ranges.
            limit = max(limit, self.scrollbar.value())
        self.scrollbar.setPageStep(self.viewport_height)
        self.scrollbar.setRange(0, max(0, limit))
        self.apply_scroll_position(self.scrollbar.value())

    def apply_scroll_position(self, position):
        for pane in self.panes:
            pane.view.set_mirror_scroll(position, self.viewport_height)

    def scroll_by(self, delta):
        self.scrollbar.setValue(self.scrollbar.value() - delta)


class SupportWindow(QWidget):
    def __init__(self, profile, config_path, settings):
        super().__init__(None, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window)
        self.profile = profile
        self.config_path = config_path
        self.settings = settings
        self.doc_url = ""
        self.view = None
        self.ghost = False
        self.split = False
        self.split_request = 0
        self.hwnd = None
        self.fallback_hotkeys = {}
        self.hotkeys_registered = []

        self.setObjectName("MollySupportDoc")
        self.setWindowTitle(TITLE)
        self.setStyleSheet(STYLES)
        self.config_timer = QTimer(self, interval=250, singleShot=True, timeout=self.save_settings)
        self.hotkey_timer = QTimer(self, interval=65, timeout=self.poll_hotkeys)

        self.shell = QWidget(objectName="shell")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.addWidget(self.shell)
        self.setup_shell()
        self.setMinimumSize(MINIMUM_SIZE)
        self.resize(DEFAULT_SIZE.boundedTo(self.screen().availableGeometry().size()))
        self.move(self.screen().availableGeometry().center() - self.rect().center())

    def setup_shell(self):
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setSpacing(0)
        shell_layout.setContentsMargins(1, 1, 1, 1)

        title_bar = QWidget(self.shell, objectName="titleBar")
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(8, 6, 6, 6)
        title_row.setSpacing(4)
        self.share_button = self.button("Hide", "Exclude this window from screen capture (Ctrl+Alt+A)",
                                        self.set_share, self.settings.hide_from_share)
        self.ghost_button = self.button(
            "Ghost", "Clicks pass through the window. Press Ctrl+Shift+Z to turn it off.",
            self.set_ghost, False,
        )
        self.split_button = self.button("Split", "Show six copies with linked scrolling",
                                        self.set_split, False)
        self.split_button.setEnabled(False)
        for button in (self.share_button, self.ghost_button, self.split_button):
            title_row.addWidget(button)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(self.settings.opacity)
        self.opacity.setMinimumWidth(56)
        self.opacity.setMaximumWidth(125)
        self.opacity.setAccessibleName("Window opacity")
        self.opacity.setToolTip("Window opacity")
        self.opacity.valueChanged.connect(self.set_opacity)
        self.opacity_label = QLabel(
            f"{self.settings.opacity}%",
            title_bar,
            objectName="opacityValue",
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        self.opacity_label.ensurePolished()
        self.opacity_label.setFixedWidth(self.opacity_label.fontMetrics().horizontalAdvance("100%") + 2)
        title_row.addWidget(self.opacity, 1)
        title_row.addWidget(self.opacity_label)
        title_row.addStretch()
        grip = DragGrip()
        grip.setToolTip("Drag to move the window")
        title_row.addWidget(grip)
        shell_layout.addWidget(title_bar)

        content = QWidget()
        layers = QStackedLayout(content)
        layers.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.documents = QStackedWidget()
        placeholder = QWidget()
        empty_layout = QVBoxLayout(placeholder)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title = QLabel("No Google Doc configured", objectName="emptyTitle",
                                  alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(QLabel("Run set-doc-url.cmd, then reopen Anti.", objectName="emptyHelp",
                                      alignment=Qt.AlignmentFlag.AlignCenter))
        self.documents.addWidget(placeholder)
        self.split_pages = SplitPages(self.profile, self.documents)
        self.documents.addWidget(self.split_pages)
        layers.addWidget(self.documents)

        self.status_panel = QWidget(objectName="statusPanel")
        status_layout = QVBoxLayout(self.status_panel)
        status_layout.setContentsMargins(20, 20, 20, 20)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status = QLabel(objectName="status", alignment=Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        status_layout.addWidget(self.status)
        self.open_browser = self.button("Open in browser", "Open this document in your default browser",
                                        self.open_document_in_browser)
        status_layout.addWidget(self.open_browser, alignment=Qt.AlignmentFlag.AlignHCenter)
        layers.addWidget(self.status_panel)
        layers.setCurrentWidget(self.status_panel)
        self.status_panel.hide()
        shell_layout.addWidget(content, 1)

    def button(self, text, tooltip, callback, checked=None):
        button = QPushButton(text)
        button.setToolTip(tooltip)
        if checked is None:
            button.clicked.connect(callback)
        else:
            button.setCheckable(True)
            button.setChecked(checked)
            button.toggled.connect(callback)
        return button

    def initialize_window(self):
        self.attach_native_window(int(self.winId()))
        self.show()
        self.apply_window_state()
        self.load_configured_document()

    def attach_native_window(self, hwnd):
        self.detach_native_window()
        self.hwnd = hwnd
        native.configure_frame(hwnd)
        if not native.set_property(hwnd, native.WINDOW_PROPERTY, 1):
            raise RuntimeError(f"Could not register the {TITLE} window.")
        self.configure_native_styles()
        native.set_capture_exclusion(hwnd, self.settings.hide_from_share)
        for action, (modifiers, key) in HOTKEYS.items():
            if native.register_hotkey(hwnd, action, modifiers | native.MOD_NOREPEAT, key):
                self.hotkeys_registered.append(action)
            else:
                self.fallback_hotkeys[action] = False
        if self.fallback_hotkeys:
            self.hotkey_timer.start()

    def detach_native_window(self):
        if self.hwnd is None:
            return
        self.hotkey_timer.stop()
        for action in self.hotkeys_registered:
            native.unregister_hotkey(self.hwnd, action)
        native.remove_property(self.hwnd, native.WINDOW_PROPERTY)
        self.hotkeys_registered.clear()
        self.fallback_hotkeys.clear()
        self.hwnd = None

    def event(self, event):
        if event.type() == QEvent.Type.WinIdChange and getattr(self, "hwnd", None):
            # WebEngine may recreate the top-level HWND when its surface first appears.
            hwnd = int(self.internalWinId() or 0)
            if hwnd and hwnd != self.hwnd:
                self.attach_native_window(hwnd)
                QTimer.singleShot(0, self.apply_window_state)
        return super().event(event)

    def load_configured_document(self):
        value = configured_document_link().strip()
        url = normalize_document_url(value)
        if not url:
            if self.view is None:
                self.empty_title.setText("Invalid Google Docs URL" if value else "No Google Doc configured")
            else:
                self.set_status(DOC_URL_HELP)
            return
        if url == self.doc_url and self.view and (self.view.loading or self.view.document_ready):
            if self.status.text() == DOC_URL_HELP:
                self.set_status("")
            return
        self.doc_url = url
        if self.view is None:
            self.view = DocumentView(self.profile, self.documents)
            self.view.status_changed.connect(self.set_status)
            self.view.readiness_changed.connect(self.update_split_control)
            self.documents.addWidget(self.view)
        self.split_button.setChecked(False)
        self.documents.setCurrentWidget(self.view)
        self.view.load(QUrl(url))

    def set_status(self, text, browser_available=False):
        self.status.setText(text)
        self.open_browser.setVisible(browser_available and bool(self.doc_url))
        self.status_panel.setVisible(bool(text))
        if text:
            self.status_panel.raise_()

    def open_document_in_browser(self):
        if self.doc_url:
            QDesktopServices.openUrl(QUrl(self.doc_url))

    def save_settings(self):
        try:
            self.settings.write(self.config_path)
        except OSError:
            self.set_status(f"Windows could not save your {TITLE} settings.", False)

    def apply_window_state(self):
        if self.hwnd is None:
            return
        refresh_taskbar = self.isVisible() and native.needs_taskbar_update(self.hwnd)
        if refresh_taskbar:
            native.show_window(self.hwnd, 0)  # SW_HIDE
        try:
            self.configure_native_styles()
        finally:
            if refresh_taskbar:
                native.show_window(self.hwnd, 4)  # SW_SHOWNOACTIVATE
        if self.isVisible():
            self.apply_capture()

    def configure_native_styles(self):
        native.configure_window(self.hwnd, self.settings.opacity, self.ghost)

    def apply_capture(self):
        requested = self.settings.hide_from_share
        success = native.set_capture_exclusion(self.hwnd, requested)
        # The document panes are children of this top-level window.
        self.share_button.setText("Hidden" if requested and success else "Hide")
        if not success and requested:
            self.share_button.setChecked(False)
            self.set_status("Windows could not exclude this window from capture.", False)

    def set_share(self, enabled):
        self.settings.hide_from_share = enabled
        self.apply_capture()
        self.config_timer.start()

    def set_ghost(self, enabled):
        self.ghost = enabled
        self.apply_window_state()

    def set_opacity(self, value):
        self.settings.opacity = value
        self.opacity_label.setText(f"{value}%")
        self.apply_window_state()
        self.config_timer.start()

    def set_split(self, enabled):
        self.split_request += 1
        if enabled:
            if self.view and self.view.document_ready:
                self.split_button.setText("Single")
                self.set_status(OPENING_SPLIT)
                request = self.split_request
                self.view.read_scroll_state(lambda state: self.show_split_views(state, request))
            return
        self.split_button.setText("Split")
        if self.status.text() == OPENING_SPLIT:
            self.set_status("")
        if self.split:
            position = self.split_pages.scrollbar.value()
            self.documents.setCurrentWidget(self.view)
            self.split_pages.clear()
            self.split = False
            self.view.seek_to(position)

    def update_split_control(self, ready):
        self.split_button.setEnabled(ready or self.split_button.isChecked())
        if ready and self.split_button.isChecked() and not self.split:
            self.set_split(True)

    def show_split_views(self, state, request):
        if request != self.split_request or not self.split_button.isChecked():
            return
        if not state or not state["pageWidth"]:
            self.split_button.setChecked(False)
            self.set_status("The document could not be opened in Split.", True)
            return
        self.split = True
        self.set_status("")
        self.documents.setCurrentWidget(self.split_pages)
        self.split_pages.load_views(self.view.url(), state)

    def poll_hotkeys(self):
        modifiers = native.held_modifiers()
        for action, was_down in self.fallback_hotkeys.items():
            required, key = HOTKEYS[action]
            down = modifiers == required and native.key_is_down(key)
            if down and not was_down:
                self.run_hotkey(action)
            self.fallback_hotkeys[action] = down

    def run_hotkey(self, action):
        if action == PANIC:
            self.ghost_button.setChecked(False)
        elif action in (GHOST, GHOST_ALT):
            self.ghost_button.toggle()
        elif action == SHARE:
            self.share_button.toggle()
        elif action == VISIBILITY:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.restore_window()

    def restore_window(self):
        if not self.isVisible() or self.isMinimized():
            self.showNormal()
            self.apply_window_state()
        self.raise_()
        self.activateWindow()
        native.set_foreground(self.hwnd)

    def activate_existing(self):
        self.restore_window()
        self.load_configured_document()
        if self.split:
            for pane in self.split_pages.panes:
                if pane.view.renderer_failed:
                    pane.view.load(self.view.url())

    def nativeEvent(self, event_type, message):
        if event_type != b"windows_generic_MSG":
            return super().nativeEvent(event_type, message)
        data = MSG.from_address(int(message))
        if data.message == native.WM_NCCALCSIZE and data.wParam:
            return True, 0
        hwnd = getattr(self, "hwnd", None)
        if hwnd:
            if data.message == native.ACTIVATE_MESSAGE:
                QTimer.singleShot(0, self.activate_existing)
                return True, 0
            if data.message == native.WM_HOTKEY:
                self.run_hotkey(data.wParam)
                return True, 0
            if data.message == native.WM_NCHITTEST and not self.ghost:
                edge = native.hit_test(hwnd, data.lParam, round(6 * self.devicePixelRatioF()))
                if edge:
                    return True, edge
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event):
        self.split_request += 1
        self.split_pages.clear()
        if self.view is not None:
            self.view.dispose()
        if self.hwnd:
            self.config_timer.stop()
            self.detach_native_window()
            self.save_settings()
        super().closeEvent(event)
        QTimer.singleShot(0, QApplication.instance().quit)


def main():
    handle, already_running = native.acquire_instance()
    try:
        if already_running:
            return 0 if native.activate_instance() else 1
        configure_portable_paths()
        if "--disable-webengine-sandbox" in sys.argv:
            sys.argv.remove("--disable-webengine-sandbox")
            os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
        app = QApplication(sys.argv)
        app.setApplicationName("SupportApp")
        app.setApplicationDisplayName(TITLE)
        app.setFont(QFont("Segoe UI", 10))
        app_data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        try:
            app_data.mkdir(parents=True, exist_ok=True)
            config_file = app_data / "config.json"
            profile = make_profile(app_data, app)
            window = SupportWindow(profile, config_file, Settings.read(config_file))
            try:
                window.initialize_window()
                return app.exec()
            finally:
                delete(window)
                delete(profile)
        except Exception:
            error = traceback.format_exc()
            try:
                (app_data / "startup-error.log").write_text(error, encoding="utf-8")
            except OSError:
                pass
            QMessageBox.critical(None, TITLE, f"{TITLE} could not start.\n\n" + error.splitlines()[-1])
            return 1
    finally:
        native.close_handle(handle)


if __name__ == "__main__":
    sys.exit(main())
