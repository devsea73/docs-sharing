"""A persistent Qt WebEngine profile and a live, fitted Google Docs view."""

import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlencode, urlsplit

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication


DOCUMENT_PATH = re.compile(r"^/document/(?:u/\d+/)?d/([a-zA-Z0-9_-]+)(?=/|$)")
SCRIPT_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld.value


def normalize_document_url(value):
    value = value.strip()
    if value.startswith("docs.google.com/"):
        value = "https://" + value
    try:
        parts = urlsplit(value)
        valid_host = parts.hostname == "docs.google.com" and parts.username is None
        valid_port = parts.port in (None, 80, 443)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not valid_host or not valid_port:
        return ""
    match = DOCUMENT_PATH.match(parts.path)
    if not match or (match[1] == "e" and parts.path[match.end():].startswith("/")):
        return ""
    url = f"https://docs.google.com/document/d/{match[1]}/edit"
    resource_keys = parse_qs(parts.query).get("resourcekey")
    return url + "?" + urlencode({"resourcekey": resource_keys[0]}) if resource_keys else url


def configure_portable_paths():
    # PyInstaller's PySide6 hook configures the bundled Qt plugin directory.
    # Explicit WebEngine paths keep its helper independent of the working directory.
    if not getattr(sys, "frozen", False):
        return
    qt = Path(sys._MEIPASS) / "PySide6"
    for path in (qt / "Qt" / "bin" / "QtWebEngineProcess.exe",
                 qt / "QtWebEngineProcess.exe"):
        if path.is_file():
            os.environ["QTWEBENGINEPROCESS_PATH"] = str(path)
            qt = path.parent.parent if path.parent.name == "bin" else path.parent
            for variable, folder in (("QTWEBENGINE_RESOURCES_PATH", qt / "resources"),
                                     ("QTWEBENGINE_LOCALES_PATH", qt / "translations" / "qtwebengine_locales")):
                if folder.is_dir():
                    os.environ[variable] = str(folder)
            break


def make_profile(app_data, parent):
    profile = QWebEngineProfile("SupportApp", parent)
    profile.setPersistentStoragePath(str(app_data / "chromium" / "storage"))
    profile.setCachePath(str(app_data / "chromium" / "cache"))
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

    script = QWebEngineScript()
    script.setName("Support App document layout")
    script.setWorldId(SCRIPT_WORLD)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setSourceCode(Path(__file__).with_name("docs_view.js").read_text(encoding="utf-8"))
    profile.scripts().insert(script)
    return profile


class DocumentPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation, is_main_frame):
        if (is_main_frame and navigation == self.NavigationType.NavigationTypeLinkClicked
                and url.scheme() in ("http", "https")
                and url.host() not in ("docs.google.com", "accounts.google.com")):
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, navigation, is_main_frame)


class DocumentView(QWebEngineView):
    status_changed = Signal(str, bool)

    def __init__(self, profile, parent):
        super().__init__(parent)
        self.setMinimumSize(0, 0)
        page = DocumentPage(profile, self)
        self.setPage(page)
        page.setBackgroundColor(Qt.GlobalColor.white)
        page.newWindowRequested.connect(self.open_link)
        page.permissionRequested.connect(lambda permission: permission.deny())
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.loadStarted.connect(self.on_load_started)
        self.loadFinished.connect(self.on_load_finished)
        self.renderProcessTerminated.connect(self.on_render_terminated)
        self.fit_timer = QTimer(self, interval=650, timeout=self.fit_document)
        self.resize_timer = QTimer(self, interval=110, singleShot=True, timeout=self.fit_document)
        self.loading = False
        self.fit_pending = False
        self.document_ready = False
        self.disposed = False
        self.generation = 0
        self.load_waits = 0
        QApplication.instance().installEventFilter(self)

    def open_link(self, request):
        url = request.requestedUrl()
        if url.scheme() == "https" and url.host() == "accounts.google.com":
            request.openIn(self.page())
        elif url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if watched is self or watched == self.focusProxy():
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_timer.start()

    def on_load_started(self):
        self.generation += 1
        self.fit_pending = False
        self.document_ready = False
        self.load_waits = 0
        self.loading = True
        self.setZoomFactor(1)
        self.status_changed.emit("Loading document…", False)

    def on_load_finished(self, ok):
        self.loading = False
        if ok and self.url().host() == "accounts.google.com":
            self.status_changed.emit("Google requires sign-in for this document.", True)
        elif ok:
            self.status_changed.emit("", False)
            self.fit_document()
        else:
            self.status_changed.emit("The document could not be loaded.", True)

    def on_render_terminated(self, _status, _exit_code):
        self.status_changed.emit("The document view closed. Press Load to reopen it.", True)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.disposed:
            self.fit_timer.start()
            self.resize_timer.start()

    def hideEvent(self, event):
        self.fit_timer.stop()
        self.resize_timer.stop()
        super().hideEvent(event)

    def dispose(self):
        self.disposed = True
        self.fit_timer.stop()
        self.resize_timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.stop()
        self.deleteLater()

    def fit_document(self):
        if self.loading or self.fit_pending or not self.isVisible() or self.width() < 50:
            return
        if self.url().host() != "docs.google.com":
            return
        self.fit_pending = True
        generation = self.generation
        self.page().runJavaScript("JSON.stringify(globalThis.supportAppMetrics?.() ?? null)",
                                  SCRIPT_WORLD, lambda result: self.apply_fit(result, generation))

    def apply_fit(self, result, generation):
        if self.disposed or generation != self.generation:
            return
        self.fit_pending = False
        metrics = json.loads(result) if result else None
        if not metrics:
            self.load_waits += 1
            if self.load_waits == 12 and not self.document_ready:
                self.status_changed.emit("The document editor is unavailable.", True)
            return
        if not self.document_ready:
            self.document_ready = True
            self.status_changed.emit("", False)
        page_width = metrics["pageWidth"]
        viewport = metrics["viewportWidth"]
        if page_width < 50 or viewport < 50:
            return
        current = self.zoomFactor()
        target = max(0.25, min(5.0, current * viewport / page_width))
        if abs(target - current) > 0.005:
            self.setZoomFactor(target)
