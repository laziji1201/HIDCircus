
import ctypes
import threading
from ctypes import wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_NULL = 0x0000
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04
MF_STRING = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080
CS_VREDRAW, CS_HREDRAW = 0x0001, 0x0002

WM_CLASS_NAME = "HIDCircusTrayWnd"
ICON_ID = 1

class GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("hWnd", w.HWND),
        ("uID", w.UINT),
        ("uFlags", w.UINT),
        ("uCallbackMessage", w.UINT),
        ("hIcon", w.HICON),
        ("szTip", w.WCHAR * 128),
        ("dwState", w.DWORD),
        ("dwStateMask", w.DWORD),
        ("szInfo", w.WCHAR * 256),
        ("uVersion", w.UINT),
        ("szInfoTitle", w.WCHAR * 64),
        ("dwInfoFlags", w.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", w.HICON),
    ]

class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", w.BOOL), ("xHotspot", w.DWORD), ("yHotspot", w.DWORD),
                ("hbmMask", w.HBITMAP), ("hbmColor", w.HBITMAP)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
                ("biPlanes", w.WORD), ("biBitCount", w.WORD),
                ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
                ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG),
                ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD)]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]

class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.RegisterClassW.restype = w.ATOM
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.restype = w.HWND
user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]
user32.GetMessageW.restype = w.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.RegisterWindowMessageW.restype = w.UINT
user32.RegisterWindowMessageW.argtypes = [w.LPCWSTR]
user32.CreatePopupMenu.restype = w.HMENU
user32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, w.HWND, ctypes.c_void_p]
user32.DestroyMenu.argtypes = [w.HMENU]
user32.DestroyIcon.argtypes = [w.HICON]
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.GetDC.restype = w.HDC
user32.GetDC.argtypes = [w.HWND]
user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
user32.CreateIconIndirect.restype = w.HICON
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.DestroyWindow.argtypes = [w.HWND]

shell32.Shell_NotifyIconW.restype = w.BOOL
shell32.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

gdi32.CreateDIBSection.restype = w.HBITMAP
gdi32.CreateDIBSection.argtypes = [w.HDC, ctypes.POINTER(BITMAPINFO), w.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
gdi32.CreateBitmap.restype = w.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, w.UINT, w.UINT, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [w.HGDIOBJ]

kernel32.GetModuleHandleW.restype = w.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]

def _hicon(image):
    """PIL 图像 -> HICON（32 位带 alpha，系统托盘才不糊）。"""
    img = image.convert("RGBA")
    width, height = img.size
    pixels = img.tobytes("raw", "BGRA")

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = width
    bi.bmiHeader.biHeight = -height                     
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0

    bits = ctypes.c_void_p()
    hdc = user32.GetDC(None)
    try:
        hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bi), 0,
                                      ctypes.byref(bits), None, 0)
    finally:
        user32.ReleaseDC(None, hdc)
    if not hbmp:
        return None
    ctypes.memmove(bits, pixels, len(pixels))

    mask = gdi32.CreateBitmap(width, height, 1, 1, None)
    info = ICONINFO(True, 0, 0, mask, hbmp)
    hicon = user32.CreateIconIndirect(ctypes.byref(info))
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteObject(mask)
    return hicon

class Tray:
    """一个最小的系统托盘。start() 之后消息循环跑在自己的线程里。"""

    def __init__(self, image, title, items, on_click=None):
        self._image = image
        self._title = title
        self._items = list(items)                               
        self._on_click = on_click
        self._hwnd = None
        self._hicon = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._wndproc = WNDPROC(self._handle_message)
        self._taskbar_created = 0
        self._thread = None
        self.ok = False

    def start(self, timeout=4.0):
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.ok

    def update(self, image, title=None):
        with self._lock:
            self._image = image
            if title is not None:
                self._title = title
            if not self.ok or not self._hwnd:
                return
            self._apply_icon()

    def stop(self):
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)

    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = ICON_ID
        return nid

    def _apply_icon(self):
        with self._lock:
            old = self._hicon
            self._hicon = _hicon(self._image) or old
            nid = self._nid()
            nid.uFlags = NIF_ICON | NIF_TIP
            nid.hIcon = self._hicon
            nid.szTip = self._title[:127]
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
            if old and old != self._hicon:
                user32.DestroyIcon(old)

    def _add_icon(self):
        with self._lock:
            if self._hicon:
                user32.DestroyIcon(self._hicon)
            self._hicon = _hicon(self._image)
            nid = self._nid()
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = self._hicon
            nid.szTip = self._title[:127]
            ctypes.set_last_error(0)
            ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
            self.last_error = ctypes.get_last_error()
        return ok

    def _show_menu(self):
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            for idx, (label, _) in enumerate(self._items, start=1):
                user32.AppendMenuW(menu, MF_STRING, idx, label)
            pt = w.POINT()
            user32.GetCursorPos(ctypes.byref(pt))

            user32.SetForegroundWindow(self._hwnd)
            cmd = user32.TrackPopupMenu(
                menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                pt.x, pt.y, 0, self._hwnd, None)
            user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
            if cmd:
                _label, callback = self._items[cmd - 1]
                try:
                    callback()
                except Exception:
                    pass
        finally:
            user32.DestroyMenu(menu)

    def _handle_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            event = lparam & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                if self._on_click:
                    try:
                        self._on_click()
                    except Exception:
                        pass
            elif event == WM_RBUTTONUP:
                self._show_menu()
            return 0
        if msg == WM_COMMAND:
            idx = wparam & 0xFFFF
            if 1 <= idx <= len(self._items):
                try:
                    self._items[idx - 1][1]()
                except Exception:
                    pass
            return 0
        if msg == WM_DESTROY:
            nid = self._nid()
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            if self._hicon:
                user32.DestroyIcon(self._hicon)
                self._hicon = None
            user32.PostQuitMessage(0)
            return 0
        if msg == self._taskbar_created and self._taskbar_created:

            self._add_icon()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.style = CS_HREDRAW | CS_VREDRAW
            wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
            wc.hInstance = hinst
            wc.lpszClassName = WM_CLASS_NAME
            user32.RegisterClassW(ctypes.byref(wc))

            self._hwnd = user32.CreateWindowExW(
                0, WM_CLASS_NAME, "HIDCircusTray", 0, 0, 0, 0, 0,
                None, None, hinst, None)
            if not self._hwnd:
                return

            self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
            self.ok = self._add_icon()
            self._ready.set()
            if not self.ok:
                return

            msg = w.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self.ok = False
        finally:
            self._ready.set()
