from dataclasses import asdict, dataclass
from ctypes.wintypes import MSG
import json
import os
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QEvent, QRect, QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QMessageBox, QPushButton, QSizePolicy, QSlider, QStackedWidget, QStyle,
    QToolButton, QVBoxLayout, QWidget,
)
from shiboken6 import delete

from browser import DocumentView, configure_portable_paths, make_profile, normalize_document_url
import win32 as native


TITLE = "Support App"
RESTORE_SIZE = 50
MINIMUM_SIZE = QSize(440, 250)
DEFAULT_SIZE = QSize(800, 680)
PANIC, GHOST, GHOST_ALT, SHARE = range(1, 5)
HOTKEYS = {
    PANIC: (native.MOD_CONTROL | native.MOD_SHIFT, ord("Z")),
    GHOST: (native.MOD_CONTROL | native.MOD_ALT, ord("Z")),
    GHOST_ALT: (native.MOD_CONTROL | native.MOD_ALT | native.MOD_SHIFT, ord("Z")),
    SHARE: (native.MOD_CONTROL | native.MOD_ALT, ord("A")),
}


STYLES = """
QWidget { color: #172339; font-size: 13px; }
QWidget#shell { background: #fff; border: 1px solid #c8d2e0; }
QWidget#titleBar { background: #edf3fb; border-bottom: 1px solid #d9e3f0; }
QLabel#title { font-size: 13px; font-weight: 700; }
QLabel#emptyTitle { font-size: 20px; font-weight: 650; }
QLabel#emptyHelp, QLabel#status { color: #4a5e77; }
QFrame#statusBar { background: #f2f6fd; border-bottom: 1px solid #dce5f2; }
QWidget#docGrid { background: #d5deea; }
QLineEdit {
    background: #fff;
    border: 1px solid #becce0;
    border-radius: 6px;
    padding: 5px 9px;
    selection-background-color: #1f6feb;
}
QLineEdit:focus { border-color: #1f6feb; }
QPushButton {
    background: #f3f6fa;
    border: 1px solid #d1dbea;
    border-radius: 6px;
    padding: 4px 9px;
}
QPushButton:hover { background: #e5eefb; border-color: #a7bfe0; }
QPushButton:checked { background: #deebff; color: #174f9f; border-color: #91b8f4; }
QPushButton:disabled { color: #8995a6; background: #f6f8fb; }
QPushButton#load, QPushButton#restore { background: #1f6feb; color: white; border-color: #1f6feb; }
QPushButton#load:hover, QPushButton#restore:hover { background: #185dca; }
QPushButton#restore { border-radius: 25px; padding: 0; }
QToolButton { border: none; background: transparent; padding: 4px 7px; border-radius: 4px; }
QToolButton:hover { background: #dbe8fb; }
QToolButton#close:hover { background: #f7d9df; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: #cdd9ea; }
QSlider::handle:horizontal { width: 12px; margin: -4px 0; border-radius: 6px; background: #1f6feb; }
"""


@dataclass
class Settings:
    last_doc_url: str = ""
    opacity: int = 100
    hide_from_share: bool = False
    hide_from_taskbar: bool = False

    @classmethod
    def read(cls, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        url = data.get("last_doc_url", "")
        opacity = data.get("opacity")
        return cls(
            last_doc_url=normalize_document_url(url) if isinstance(url, str) else "",
            opacity=max(20, min(100, opacity)) if type(opacity) is int else 100,
            hide_from_share=data.get("hide_from_share") is True,
            hide_from_taskbar=data.get("hide_from_taskbar") is True,
        )

    def write(self, path):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def document_icon(white=False):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#ffffff" if white else "#1f6feb")
    ink = QColor("#1f6feb" if white else "#ffffff")
    page = QPainterPath()
    page.moveTo(15, 6)
    page.lineTo(39, 6)
    page.lineTo(54, 21)
    page.lineTo(54, 55)
    page.quadTo(54, 59, 50, 59)
    page.lineTo(15, 59)
    page.quadTo(11, 59, 11, 55)
    page.lineTo(11, 10)
    page.quadTo(11, 6, 15, 6)
    page.closeSubpath()
    painter.fillPath(page, color)
    fold = QPainterPath()
    fold.moveTo(39, 6)
    fold.lineTo(39, 21)
    fold.lineTo(54, 21)
    fold.closeSubpath()
    painter.fillPath(fold, QColor("#bed9ff"))
    pen = QPen(ink, 3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for y, width in ((32, 26), (40, 26), (48, 17)):
        painter.drawLine(20, y, 20 + width, y)
    painter.end()
    return QIcon(pixmap)


class DragGrip(QToolButton):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.window().windowHandle().startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)


class SupportWindow(QWidget):
    def __init__(self, profile, config_path, settings):
        super().__init__(None, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window)
        self.profile = profile
        self.config_path = config_path
        self.settings = settings
        self.doc_url = ""
        self.ghost = False
        self.split = False
        self.collapsed = False
        self.unsplit_geometry = QRect()
        self.expanded_geometry = QRect()
        self.hwnd = None
        self.fallback_hotkeys = {}
        self.hotkeys_registered = []

        self.setObjectName("MollySupportDoc")
        self.setWindowTitle(TITLE)
        self.setWindowIcon(document_icon())
        self.setStyleSheet(STYLES)
        self.config_timer = QTimer(self, interval=250, singleShot=True, timeout=self.save_settings)
        self.hotkey_timer = QTimer(self, interval=65, timeout=self.poll_hotkeys)

        self.stack = QStackedWidget(self)
        self.shell = QWidget(objectName="shell")
        self.stack.addWidget(self.shell)
        self.restore_button = QPushButton(objectName="restore")
        self.restore_button.setFixedSize(RESTORE_SIZE, RESTORE_SIZE)
        self.restore_button.setIcon(document_icon(white=True))
        self.restore_button.setIconSize(QSize(23, 23))
        self.restore_button.setToolTip("Double-click to restore Support App")
        self.restore_button.setAccessibleName("Restore Support App")
        self.restore_button.installEventFilter(self)
        self.stack.addWidget(self.restore_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.addWidget(self.stack)
        self.setup_shell()
        self.setMinimumSize(MINIMUM_SIZE)
        self.resize(DEFAULT_SIZE.boundedTo(self.screen().availableGeometry().size()))
        self.move(self.screen().availableGeometry().center() - self.rect().center())

    def setup_shell(self):
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setSpacing(0)
        shell_layout.setContentsMargins(1, 1, 1, 1)

        title_bar = QWidget(objectName="titleBar")
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(10, 4, 7, 4)
        title_row.setSpacing(6)
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(17, 17))
        title_row.addWidget(icon)
        title_row.addWidget(QLabel(TITLE, objectName="title"))
        title_row.addStretch()
        grip = DragGrip(text="Move")
        grip.setToolTip("Drag to move the window")
        grip.setCursor(Qt.CursorShape.SizeAllCursor)
        title_row.addWidget(grip)
        minimize = self.system_button(QStyle.StandardPixmap.SP_TitleBarMinButton,
                                      "Minimize", self.showMinimized)
        close = self.system_button(QStyle.StandardPixmap.SP_TitleBarCloseButton, "Close", self.close)
        close.setObjectName("close")
        title_row.addWidget(minimize)
        title_row.addWidget(close)
        shell_layout.addWidget(title_bar)

        link_row = QHBoxLayout()
        link_row.setContentsMargins(9, 7, 9, 4)
        self.link = QLineEdit(placeholderText="Paste a Google Docs link")
        self.link.setAccessibleName("Google Docs link")
        self.link.returnPressed.connect(self.load_document)
        self.load_button = self.button("Load", "Load Google Doc", self.load_document)
        self.load_button.setObjectName("load")
        link_row.addWidget(self.link, 1)
        link_row.addWidget(self.load_button)
        shell_layout.addLayout(link_row)

        controls = QHBoxLayout()
        controls.setContentsMargins(9, 2, 9, 7)
        controls.setSpacing(5)
        self.share_button = self.button("Hide", "Exclude this window from screen capture (Ctrl+Alt+A)",
                                        self.set_share, self.settings.hide_from_share)
        self.ghost_button = self.button(
            "Ghost", "Clicks pass through the window. Press Ctrl+Shift+Z to turn it off.",
            self.set_ghost, False,
        )
        self.split_button = self.button("Split", "Fill the screen with this same document, six times",
                                        self.set_split, False)
        self.split_button.setEnabled(False)
        self.taskbar_button = self.button("Taskbar", "Hide the taskbar button", self.set_taskbar,
                                          self.settings.hide_from_taskbar)
        self.taskbar_button.setAccessibleName("Hide taskbar button")
        self.collapse_button = self.button("Collapse", "Collapse to a restore button", self.collapse_window)
        for button in (self.share_button, self.ghost_button, self.split_button,
                       self.taskbar_button, self.collapse_button):
            controls.addWidget(button)
        controls.addStretch()
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(self.settings.opacity)
        self.opacity.setMinimumWidth(56)
        self.opacity.setMaximumWidth(125)
        self.opacity.setAccessibleName("Window opacity")
        self.opacity.setToolTip("Window opacity")
        self.opacity.valueChanged.connect(self.set_opacity)
        self.opacity_label = QLabel(f"{self.settings.opacity}%", alignment=Qt.AlignmentFlag.AlignRight |
                                                                             Qt.AlignmentFlag.AlignVCenter)
        self.opacity_label.setFixedWidth(self.opacity_label.fontMetrics().horizontalAdvance("100%") + 2)
        controls.addWidget(self.opacity, 1)
        controls.addWidget(self.opacity_label)
        shell_layout.addLayout(controls)

        self.status_bar = QFrame(objectName="statusBar")
        status_row = QHBoxLayout(self.status_bar)
        status_row.setContentsMargins(10, 3, 10, 3)
        self.status = QLabel(objectName="status")
        self.status.setWordWrap(True)
        self.open_browser = self.button("Open in browser", "Open this document in your default browser",
                                        self.open_document_in_browser)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.open_browser)
        self.status_bar.hide()
        shell_layout.addWidget(self.status_bar)

        self.documents = QStackedWidget()
        placeholder = QWidget()
        empty_layout = QVBoxLayout(placeholder)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        empty_icon.setPixmap(self.windowIcon().pixmap(42, 42))
        empty_layout.addWidget(empty_icon)
        empty_layout.addWidget(QLabel("Open a Google Doc", objectName="emptyTitle",
                                      alignment=Qt.AlignmentFlag.AlignCenter))
        empty_layout.addWidget(QLabel("Paste its link above, then press Enter.", objectName="emptyHelp",
                                      alignment=Qt.AlignmentFlag.AlignCenter))
        self.documents.addWidget(placeholder)
        doc_panel = QWidget(objectName="docGrid")
        self.grid = QGridLayout(doc_panel)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(1)
        self.documents.addWidget(doc_panel)
        shell_layout.addWidget(self.documents, 1)
        self.views = []

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

    def system_button(self, icon, title, callback):
        button = QToolButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.clicked.connect(callback)
        return button

    def initialize_window(self):
        self.attach_native_window(int(self.winId()))
        self.show()
        self.apply_window_state()
        if self.settings.last_doc_url:
            self.link.setText(self.settings.last_doc_url)
            self.load_document()
        else:
            self.link.setFocus()

    def attach_native_window(self, hwnd):
        self.detach_native_window()
        self.hwnd = hwnd
        native.configure_frame(hwnd)
        if not native.set_property(hwnd, native.WINDOW_PROPERTY, 1):
            raise RuntimeError("Could not register the Support App window.")
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

    def add_view(self, index):
        view = DocumentView(self.profile, self.documents.widget(1))
        view.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        if index == 0:
            view.status_changed.connect(self.set_status)
        self.grid.addWidget(view, index // 3, index % 3)
        self.views.append(view)
        view.load(QUrl(self.doc_url))

    def load_document(self):
        url = normalize_document_url(self.link.text())
        if not url:
            self.set_status("Enter a Google Docs document link.", False)
            self.link.setFocus()
            return
        self.doc_url = url
        self.link.setText(url)
        self.settings.last_doc_url = url
        self.config_timer.start()
        self.split_button.setEnabled(True)
        if not self.views:
            self.add_view(0)
            self.documents.setCurrentIndex(1)
        else:
            for view in self.views:
                view.load(QUrl(url))

    def set_status(self, text, browser_available=False):
        self.status.setText(text)
        self.open_browser.setVisible(browser_available and bool(self.doc_url))
        self.status_bar.setVisible(bool(text))

    def open_document_in_browser(self):
        if self.doc_url:
            QDesktopServices.openUrl(QUrl(self.doc_url))

    def save_settings(self):
        try:
            self.settings.write(self.config_path)
        except OSError:
            self.set_status("Windows could not save your Support App settings.", False)

    def apply_window_state(self):
        if self.hwnd is None:
            return
        hide_taskbar = self.collapsed or self.settings.hide_from_taskbar
        refresh_taskbar = self.isVisible() and native.needs_taskbar_update(self.hwnd, hide_taskbar)
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
        native.configure_window(self.hwnd, 100 if self.collapsed else self.settings.opacity,
                                self.ghost and not self.collapsed,
                                self.collapsed or self.settings.hide_from_taskbar)

    def apply_capture(self):
        requested = self.settings.hide_from_share
        success = native.set_capture_exclusion(self.hwnd, requested)
        # All six Chromium views are children of this top-level window.
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

    def set_taskbar(self, hidden):
        self.settings.hide_from_taskbar = hidden
        self.apply_window_state()
        self.config_timer.start()

    def set_split(self, enabled):
        self.split = enabled
        self.split_button.setText("Single" if enabled else "Split")
        for column in (1, 2):
            self.grid.setColumnStretch(column, int(enabled))
        self.grid.setColumnStretch(0, 1)
        self.grid.setRowStretch(0, 1)
        self.grid.setRowStretch(1, int(enabled))
        if enabled:
            self.unsplit_geometry = self.geometry()
            self.setGeometry(self.screen().availableGeometry())
            for index in range(1, 6):
                self.add_view(index)
        else:
            for view in self.views[1:]:
                self.grid.removeWidget(view)
                view.hide()
                view.dispose()
            del self.views[1:]
            self.setGeometry(self.unsplit_geometry)

    def collapse_window(self):
        self.expanded_geometry = self.geometry()
        area = self.screen().availableGeometry()
        self.collapsed = True
        self.stack.setCurrentWidget(self.restore_button)
        self.setFixedSize(RESTORE_SIZE, RESTORE_SIZE)
        self.move(area.left() + 16, area.bottom() - RESTORE_SIZE - 15)
        self.setMask(QRegion(self.rect(), QRegion.RegionType.Ellipse))
        self.apply_window_state()

    def restore_window(self):
        if not self.collapsed:
            return
        self.collapsed = False
        self.clearMask()
        self.setMaximumSize(16777215, 16777215)
        self.setMinimumSize(MINIMUM_SIZE)
        self.stack.setCurrentWidget(self.shell)
        self.setGeometry(self.expanded_geometry)
        self.apply_window_state()

    def eventFilter(self, watched, event):
        if watched is self.restore_button:
            double_click = (event.type() == QEvent.Type.MouseButtonDblClick
                            and event.button() == Qt.MouseButton.LeftButton)
            confirmed = (event.type() == QEvent.Type.KeyPress
                         and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Enter, Qt.Key.Key_Return))
            if double_click or confirmed:
                self.restore_window()
                return True
        return super().eventFilter(watched, event)

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

    def activate_existing(self):
        self.restore_window()
        if self.isMinimized():
            self.showNormal()
            self.apply_window_state()
        self.raise_()
        self.activateWindow()
        native.set_foreground(self.hwnd)

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
            if data.message == native.WM_NCHITTEST and not self.collapsed and not self.ghost:
                edge = native.hit_test(hwnd, data.lParam, round(6 * self.devicePixelRatioF()))
                if edge:
                    return True, edge
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event):
        if self.hwnd:
            self.config_timer.stop()
            self.detach_native_window()
            self.save_settings()
        super().closeEvent(event)


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
            QMessageBox.critical(None, TITLE, "Support App could not start.\n\n" + error.splitlines()[-1])
            return 1
    finally:
        native.close_handle(handle)


if __name__ == "__main__":
    sys.exit(main())
