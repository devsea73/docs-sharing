"""Windows integration for the application's own top-level window."""

import ctypes as c
from ctypes import wintypes as w
import time


def bind(dll, name, result, *parameters):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = parameters
    return function


kernel = c.WinDLL("kernel32", use_last_error=True)
user = c.WinDLL("user32", use_last_error=True)
enum_callback = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
create_mutex = bind(kernel, "CreateMutexW", w.HANDLE, c.c_void_p, w.BOOL, w.LPCWSTR)
close_handle = bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)
enum_windows = bind(user, "EnumWindows", w.BOOL, enum_callback, w.LPARAM)
set_property = bind(user, "SetPropW", w.BOOL, w.HWND, w.LPCWSTR, w.HANDLE)
get_property = bind(user, "GetPropW", w.HANDLE, w.HWND, w.LPCWSTR)
remove_property = bind(user, "RemovePropW", w.HANDLE, w.HWND, w.LPCWSTR)
register_message = bind(user, "RegisterWindowMessageW", w.UINT, w.LPCWSTR)
post_message = bind(user, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
get_window_thread = bind(user, "GetWindowThreadProcessId", w.DWORD, w.HWND, c.POINTER(w.DWORD))
allow_foreground = bind(user, "AllowSetForegroundWindow", w.BOOL, w.DWORD)
set_foreground = bind(user, "SetForegroundWindow", w.BOOL, w.HWND)
show_window = bind(user, "ShowWindow", w.BOOL, w.HWND, c.c_int)
get_window_rect = bind(user, "GetWindowRect", w.BOOL, w.HWND, c.POINTER(w.RECT))
get_window_style = bind(user, "GetWindowLongPtrW", c.c_ssize_t, w.HWND, c.c_int)
set_window_style = bind(user, "SetWindowLongPtrW", c.c_ssize_t, w.HWND, c.c_int, c.c_ssize_t)
set_window_pos = bind(user, "SetWindowPos", w.BOOL, w.HWND, w.HWND, c.c_int, c.c_int,
                      c.c_int, c.c_int, w.UINT)
set_layered_alpha = bind(user, "SetLayeredWindowAttributes", w.BOOL, w.HWND, w.DWORD, w.BYTE, w.DWORD)
set_display_affinity = bind(user, "SetWindowDisplayAffinity", w.BOOL, w.HWND, w.DWORD)
register_hotkey = bind(user, "RegisterHotKey", w.BOOL, w.HWND, c.c_int, w.UINT, w.UINT)
unregister_hotkey = bind(user, "UnregisterHotKey", w.BOOL, w.HWND, c.c_int)
get_key_state = bind(user, "GetAsyncKeyState", c.c_short, c.c_int)

MUTEX_NAME = r"Global\SupportApp_SingleInstance_v1"
WINDOW_PROPERTY = "MollySupportDoc.MainWindow"
ACTIVATE_MESSAGE = register_message("SupportApp.Activate.v1")
if not ACTIVATE_MESSAGE:
    raise c.WinError(c.get_last_error())

WM_HOTKEY = 0x0312
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_THICKFRAME = 0x00040000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WDA_NONE = 0
WDA_EXCLUDEFROMCAPTURE = 0x11

MOD_ALT = 1
MOD_CONTROL = 2
MOD_SHIFT = 4
MOD_WIN = 8
MOD_NOREPEAT = 0x4000


def acquire_instance():
    c.set_last_error(0)
    handle = create_mutex(None, False, MUTEX_NAME)
    error = c.get_last_error()
    if not handle:
        raise c.WinError(error)
    return handle, error == 183  # ERROR_ALREADY_EXISTS


def find_instance():
    found = []

    @enum_callback
    def visit(hwnd, _):
        if get_property(hwnd, WINDOW_PROPERTY):
            found.append(hwnd)
            return False
        return True

    enum_windows(visit, 0)
    return found[0] if found else None


def activate_instance(timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = find_instance()
        if hwnd:
            process = w.DWORD()
            get_window_thread(hwnd, c.byref(process))
            allow_foreground(process.value)
            if post_message(hwnd, ACTIVATE_MESSAGE, 0, 0):
                return True
        time.sleep(0.1)
    return False


def update_style(hwnd, style_type, style):
    if get_window_style(hwnd, style_type) == style:
        return
    c.set_last_error(0)
    previous = set_window_style(hwnd, style_type, style)
    if previous == 0 and c.get_last_error():
        raise c.WinError(c.get_last_error())
    # Apply the style without moving, sizing, activating, or changing Z order.
    set_window_pos(hwnd, None, 0, 0, 0, 0, 0x0237)


def configure_frame(hwnd):
    update_style(hwnd, GWL_STYLE, get_window_style(hwnd, GWL_STYLE) | WS_THICKFRAME)


def needs_taskbar_update(hwnd):
    style = get_window_style(hwnd, GWL_EXSTYLE)
    return style & (WS_EX_APPWINDOW | WS_EX_TOOLWINDOW) != WS_EX_TOOLWINDOW


def configure_window(hwnd, opacity, ghost):
    style = get_window_style(hwnd, GWL_EXSTYLE)
    style &= ~(WS_EX_APPWINDOW | WS_EX_TOOLWINDOW | WS_EX_LAYERED |
               WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
    style |= WS_EX_TOOLWINDOW
    if ghost:
        style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
    if ghost or opacity < 100:
        style |= WS_EX_LAYERED
    update_style(hwnd, GWL_EXSTYLE, style)
    if style & WS_EX_LAYERED and not set_layered_alpha(hwnd, 0, round(opacity * 255 / 100), 2):
        raise c.WinError(c.get_last_error())


def set_capture_exclusion(hwnd, exclude):
    affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
    return bool(set_display_affinity(hwnd, affinity))


def hit_test(hwnd, position, border):
    rectangle = w.RECT()
    if not get_window_rect(hwnd, c.byref(rectangle)):
        return 0
    x = c.c_short(position & 0xFFFF).value
    y = c.c_short((position >> 16) & 0xFFFF).value
    left = x < rectangle.left + border
    right = x >= rectangle.right - border
    top = y < rectangle.top + border
    bottom = y >= rectangle.bottom - border
    if top:
        return 13 if left else 14 if right else 12
    if bottom:
        return 16 if left else 17 if right else 15
    return 10 if left else 11 if right else 0


def key_is_down(code):
    return bool(get_key_state(code) & 0x8000)


def held_modifiers():
    return (
        (MOD_ALT if key_is_down(0x12) else 0)
        | (MOD_CONTROL if key_is_down(0x11) else 0)
        | (MOD_SHIFT if key_is_down(0x10) else 0)
        | (MOD_WIN if key_is_down(0x5B) or key_is_down(0x5C) else 0)
    )
