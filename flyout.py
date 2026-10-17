"""原生托盘小面板：GDI 自绘，不依赖浏览器窗口。

为什么不用网页做：用 Edge --app 开的小窗口本质还是"一个小窗口的浏览器"——
启动慢、会和应用窗口抢配置目录、遇到"管理员实例"还会弹权限对话框。
这个面板只显示几行电量，用 GDI 直接画既轻又快（几十毫秒），也不会有任何浏览器副作用。

外观：圆角卡片 + 一行一台设备（厂商色圆点 / 名称 / 状态 / 百分比）+ 底部两个按钮。
行为：左键托盘弹出在光标上方；失去焦点或按 ESC 自动收起；打开期间每 5 秒自动刷新。
"""

import ctypes
import threading
import time
from ctypes import wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
CS_DROPSHADOW = 0x00020000

WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_ACTIVATE = 0x0006
WM_KEYDOWN = 0x0100
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONUP = 0x0202
WM_SETFOCUS = 0x0007
WM_KILLFOCUS = 0x0008
WA_INACTIVE = 0
VK_ESCAPE = 0x1B

IDC_ARROW = 32512
DT_LEFT = 0x0000
DT_RIGHT = 0x0002
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020
DT_NOPREFIX = 0x0800
TRANSPARENT = 1
PS_SOLID = 0
FW_SEMIBOLD = 600

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.RegisterClassW.restype = w.ATOM
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.CreateWindowExW.restype = w.HWND
user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]
user32.GetMessageW.restype = w.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.InvalidateRect.argtypes = [w.HWND, ctypes.c_void_p, w.BOOL]
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [w.HWND, ctypes.c_size_t, w.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [w.HWND, ctypes.c_size_t]
user32.GetDC.restype = w.HDC
user32.GetDC.argtypes = [w.HWND]
user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
user32.BeginPaint.restype = w.HDC
user32.BeginPaint.argtypes = [w.HWND, ctypes.c_void_p]
user32.EndPaint.argtypes = [w.HWND, ctypes.c_void_p]
user32.FillRect.argtypes = [w.HDC, ctypes.c_void_p, w.HBRUSH]
user32.LoadCursorW.restype = w.HANDLE
user32.DestroyWindow.argtypes = [w.HWND]
user32.SetCapture.argtypes = [w.HWND]
user32.ReleaseCapture.argtypes = []

gdi32.CreateSolidBrush.restype = w.HBRUSH
gdi32.CreateSolidBrush.argtypes = [w.DWORD]
gdi32.CreatePen.restype = w.HANDLE
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, w.DWORD]
gdi32.SelectObject.restype = w.HANDLE
gdi32.SelectObject.argtypes = [w.HDC, w.HANDLE]
gdi32.DeleteObject.argtypes = [w.HANDLE]
gdi32.RoundRect.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.SetBkMode.argtypes = [w.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [w.HDC, w.DWORD]
gdi32.CreateFontW.restype = w.HANDLE
gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, w.LPCWSTR]
user32.DrawTextW.argtypes = [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.c_void_p, w.UINT]
gdi32.GetDeviceCaps.argtypes = [w.HDC, ctypes.c_int]
gdi32.Ellipse.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]

CLASS_NAME = "HIDCircusFlyout"
VENDOR_HUE = {"asus": (0x5A, 0x5A, 0xFF), "logitech": (0xFF, 0xB8, 0x5A),
              "razer": (0x7C, 0xE3, 0x8B)}


def _rgb(r, g, b):
    return (r & 0xFF) | ((g & 0xFF) << 8) | ((b & 0xFF) << 16)


class Flyout:
    """一个自绘的小弹窗。show() 之后阻塞在消息循环里，关闭后返回。"""

    WIDTH = 320
    ROW_H = 34
    HEAD_H = 56
    FOOT_H = 46

    # panel 模式用的大尺寸
    PANEL_WIDTH = 460
    PANEL_ROW_H = 62
    PANEL_HEAD_H = 64
    PANEL_FOOT_H = 52

    def __init__(self, devices_fn, on_open_panel, on_refresh, colors,
                 mode="flyout", on_control=None):
        self.mode = mode
        self._on_control = on_control       # (device_id, action) -> None
        self._devices_fn = devices_fn
        self._on_open_panel = on_open_panel
        self._on_refresh = on_refresh
        self._colors = colors
        self._hwnd = None
        self._rows = []          # [(x1,y1,x2,y2, btn_id)]
        self._hover = None
        self._proc = WNDPROC(self._wndproc)
        self._class_atom = None
        self._scale = 1.0
        self._refresh_rows()

    # ---------- 数据 ----------

    def _refresh_rows(self):
        try:
            self._devices = self._devices_fn()
        except Exception:
            self._devices = []

    # ---------- 窗口 ----------

    def _register(self):
        if self._class_atom:
            return
        hinst = kernel32.GetModuleHandleW(None)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", w.UINT), ("lpfnWndProc", ctypes.c_void_p),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                        ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                        ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]

        wc = WNDCLASS()
        wc.style = CS_DROPSHADOW
        wc.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        wc.lpszClassName = CLASS_NAME
        self._class_atom = user32.RegisterClassW(ctypes.byref(wc))

    def show(self):
        """在光标上方弹出；关闭时返回。"""
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        thread.join(timeout=30)

    def _run(self):
        self._register()
        hinst = kernel32.GetModuleHandleW(None)
        self._refresh_rows()
        width, height = self._size()
        cx, cy = self._cursor()
        screen_w = user32.GetSystemMetrics(0)
        left = max(8, min(cx - width // 2, screen_w - width - 8))
        top = cy - height - 12
        if top < 8:
            top = min(cy + 12, user32.GetSystemMetrics(1) - height - 8)

        self._hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW, CLASS_NAME, "HIDCircus 状态",
            WS_POPUP | WS_VISIBLE, left, top, width, height, None, None, hinst, None)
        if not self._hwnd:
            return
        user32.SetForegroundWindow(self._hwnd)
        user32.SetTimer(self._hwnd, 1, 400, None)

        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _dpi_scale(self, hwnd):
        try:
            dpi = user32.GetDpiForWindow(hwnd)
            if dpi:
                return dpi / 96.0
        except Exception:
            pass
        return 1.0

    def _size(self):
        rows = max(1, len(self._devices))
        long_rows = 0
        if self.mode == "panel":
            for d in self._devices:
                if self._has_control(d):
                    long_rows += 1
        scale = 1.15 if user32.GetSystemMetrics(0) >= 2400 else 1.0
        self._scale = scale
        if self.mode == "panel":
            width = int(self.PANEL_WIDTH * scale)
            height = int((self.PANEL_HEAD_H + rows * self.PANEL_ROW_H
                          + long_rows * 30 + self.PANEL_FOOT_H + 16) * scale)
            return width, max(height, int(240 * scale))
        width = int(self.WIDTH * scale)
        height = int((self.HEAD_H + rows * self.ROW_H + self.FOOT_H + 14) * scale)
        return width, height

    @staticmethod
    def _has_control(d):
        """这台设备有没有可以直接点的控制（目前：ASUS 灯效、扩展控件）。"""
        extra = d.get("extra") or {}
        if extra.get("lighting"):
            return True
        info = extra.get("extension") or {}
        return bool(info.get("controls"))

    def _cursor(self):
        pt = w.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    # ---------- 绘制 ----------

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_PAINT:
            self._paint(hwnd)
            return 0
        if msg == WM_TIMER:
            # 收起时机：先给 1.2 秒宽限（SetForegroundWindow 可能被系统拒绝），
            # 之后只要曾经拿到过焦点、而现在焦点不在我们身上，就收起来；
            # 如果一直没拿到焦点（被拒绝），就在面板外侧按下鼠标或超过 10 秒时收起。
            self._ticks = getattr(self, "_ticks", 0) + 1
            if self._ticks % 12 == 0:
                self._refresh_rows()
                user32.InvalidateRect(hwnd, None, False)
            if self._ticks < 3:
                return 0
            fg = user32.GetForegroundWindow()
            if fg == hwnd:
                self._had_focus = True
                return 0
            if getattr(self, "_had_focus", False):
                user32.DestroyWindow(hwnd)
                return 0
            if self._ticks > 25:                      # 约 10 秒还没拿到焦点
                user32.DestroyWindow(hwnd)
                return 0
            if (user32.GetAsyncKeyState(0x01) & 0x8000) and not self._inside_cursor(hwnd):
                user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_ACTIVATE and (wparam & 0xFFFF) == WA_INACTIVE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_KEYDOWN and wparam == VK_ESCAPE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_MOUSEMOVE:
            x, y = self._lparam(lparam)
            hover = self._hit(x, y)
            if hover != self._hover:
                self._hover = hover
                user32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == WM_LBUTTONUP:
            x, y = self._lparam(lparam)
            hit = self._hit(x, y)
            if hit == "refresh":
                self._refresh_rows()
                user32.InvalidateRect(hwnd, None, False)
                return 0
            if hit and hit.startswith("ctl:"):
                _, device_id, action = hit.split(":", 2)
                if self._on_control:
                    self._on_control(device_id, action)
                user32.InvalidateRect(hwnd, None, False)
                return 0
            if hit == "close":
                user32.DestroyWindow(hwnd)
                return 0
            if hit == "web":
                user32.DestroyWindow(hwnd)
                if self._on_open_panel:
                    self._on_open_panel()
                return 0
            if hit == "open":
                user32.DestroyWindow(hwnd)
                if self._on_open_panel:
                    self._on_open_panel()
                return 0
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.KillTimer(hwnd, 1)
            self._hwnd = None
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _inside_cursor(self, hwnd):
        rect = w.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        x, y = self._cursor()
        return rect.left <= x <= rect.right and rect.top <= y <= rect.bottom

    @staticmethod
    def _lparam(lp):
        return (lp & 0xFFFF), ((lp >> 16) & 0xFFFF)

    def _hit(self, x, y):
        for x1, y1, x2, y2, name in self._rows:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return name
        return None

    def _paint(self, hwnd):
        if self.mode == "panel":
            self._paint_panel(hwnd)
            return
        ps = ctypes.create_string_buffer(64)          # PAINTSTRUCT
        hdc = user32.BeginPaint(hwnd, ps)
        try:
            scale = self._dpi_scale(hwnd)
            client = w.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(client))
            width, height = client.right, client.bottom
            c = self._colors

            bg = gdi32.CreateSolidBrush(_rgb(*c["bg"]))
            gdi32.SelectObject(hdc, bg)
            pen = gdi32.CreatePen(PS_SOLID, 1, _rgb(*c["line"]))
            gdi32.SelectObject(hdc, pen)
            gdi32.RoundRect(hdc, 0, 0, width, height, int(14 * scale), int(14 * scale))

            gdi32.SetBkMode(hdc, TRANSPARENT)

            # 标题
            font_title = gdi32.CreateFontW(int(-14 * scale), 0, 0, 0, FW_SEMIBOLD, 0, 0, 0,
                                           0, 0, 0, 0, 0, "Microsoft YaHei UI")
            gdi32.SelectObject(hdc, font_title)
            gdi32.SetTextColor(hdc, _rgb(*c["text"]))
            self._text(hdc, "HIDCircus", int(16 * scale), int(13 * scale),
                       width - int(32 * scale), int(20 * scale), DT_LEFT)

            font_small = gdi32.CreateFontW(int(-11 * scale), 0, 0, 0, 400, 0, 0, 0,
                                           0, 0, 0, 0, 0, "Microsoft YaHei UI")
            gdi32.SelectObject(hdc, font_small)
            gdi32.SetTextColor(hdc, _rgb(*c["muted"]))
            self._text(hdc, "电量一览", int(16 * scale), int(31 * scale),
                       width - int(32 * scale), int(16 * scale), DT_LEFT)

            # 设备行
            font_row = gdi32.CreateFontW(int(-13 * scale), 0, 0, 0, 400, 0, 0, 0,
                                         0, 0, 0, 0, 0, "Microsoft YaHei UI")
            font_pct = gdi32.CreateFontW(int(-13 * scale), 0, 0, 0, FW_SEMIBOLD, 0, 0, 0,
                                         0, 0, 0, 0, 0, "Segoe UI")
            y = int((self.HEAD_H - 2) * scale)
            self._rows = []
            for d in self._devices:
                row_h = int(self.ROW_H * scale)
                dot_x = int(20 * scale)
                cy = y + row_h // 2
                hue = VENDOR_HUE.get(d.get("vendor_key", ""), (160, 160, 170))
                brush = gdi32.CreateSolidBrush(_rgb(*hue))
                gdi32.SelectObject(hdc, brush)
                r = int(3.5 * scale)
                gdi32.Ellipse(hdc, dot_x - r, cy - r, dot_x + r, cy + r)
                gdi32.DeleteObject(brush)

                gdi32.SelectObject(hdc, font_row)
                gdi32.SetTextColor(hdc, _rgb(*c["text"]))
                self._text(hdc, str(d.get("name", "?"))[:22], int(32 * scale), y,
                           width - int(150 * scale), row_h, DT_LEFT | DT_VCENTER)

                gdi32.SelectObject(hdc, font_pct)
                battery = d.get("battery")
                if battery is None:
                    color, label = c["muted"], "—"
                else:
                    color = (c["bad"] if battery <= 20 else
                             c["warn"] if battery <= 50 else c["ok"])
                    label = f"{battery}%"
                gdi32.SetTextColor(hdc, _rgb(*color))
                self._text(hdc, label, width - int(88 * scale), y, int(64 * scale),
                           row_h, DT_RIGHT | DT_VCENTER)
                y += row_h

            # 分隔线
            pen2 = gdi32.CreatePen(PS_SOLID, 1, _rgb(*c["line"]))
            gdi32.SelectObject(hdc, pen2)
            ly = height - int(self.FOOT_H * scale)
            gdi32.MoveToEx(hdc, int(16 * scale), ly, None)
            gdi32.LineTo(hdc, width - int(16 * scale), ly)

            # 底部按钮
            btn_h = int(26 * scale)
            by = ly + int(10 * scale)
            half = (width - int(44 * scale)) // 2
            refresh_rect = (int(16 * scale), by, int(16 * scale) + half, by + btn_h)
            open_rect = (refresh_rect[2] + int(12 * scale), by, width - int(16 * scale), by + btn_h)
            self._rows.append((*refresh_rect, "refresh"))
            self._rows.append((*open_rect, "open"))

            gdi32.SelectObject(hdc, font_small)
            for rect, label, active in ((refresh_rect, "刷新", False),
                                        (open_rect, "打开主面板", True)):
                fill = gdi32.CreateSolidBrush(
                    _rgb(*(c["accent"] if active else c["btn"])))
                gdi32.SelectObject(hdc, fill)
                gdi32.RoundRect(hdc, rect[0], rect[1], rect[2], rect[3],
                                int(8 * scale), int(8 * scale))
                gdi32.DeleteObject(fill)
                gdi32.SetTextColor(hdc, _rgb(*(c["accent_ink"] if active else c["text"])))
                self._text(hdc, label, rect[0], rect[1], rect[2] - rect[0], btn_h,
                           DT_LEFT | DT_VCENTER, center=True)

            for f in (font_title, font_small, font_row, font_pct):
                gdi32.DeleteObject(f)
            gdi32.DeleteObject(pen)
            gdi32.DeleteObject(pen2)
            gdi32.DeleteObject(bg)
        finally:
            user32.EndPaint(hwnd, ps)

    # ---------------- panel 模式 ----------------

    def _paint_panel(self, hwnd):
        ps = ctypes.create_string_buffer(64)
        hdc = user32.BeginPaint(hwnd, ps)
        try:
            scale = self._dpi_scale(hwnd)
            client = w.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(client))
            width, height = client.right, client.bottom
            c = self._colors

            bg = gdi32.CreateSolidBrush(_rgb(*c["bg"]))
            gdi32.SelectObject(hdc, bg)
            pen = gdi32.CreatePen(PS_SOLID, 1, _rgb(*c["line"]))
            gdi32.SelectObject(hdc, pen)
            gdi32.RoundRect(hdc, 0, 0, width, height, int(14 * scale), int(14 * scale))
            gdi32.SetBkMode(hdc, TRANSPARENT)

            font_title = gdi32.CreateFontW(int(-17 * scale), 0, 0, 0, FW_SEMIBOLD, 0, 0, 0,
                                           0, 0, 0, 0, 0, "Microsoft YaHei UI")
            font_sub = gdi32.CreateFontW(int(-11 * scale), 0, 0, 0, 400, 0, 0, 0,
                                         0, 0, 0, 0, 0, "Microsoft YaHei UI")
            font_name = gdi32.CreateFontW(int(-14 * scale), 0, 0, 0, FW_SEMIBOLD, 0, 0, 0,
                                          0, 0, 0, 0, 0, "Microsoft YaHei UI")
            font_small = gdi32.CreateFontW(int(-11 * scale), 0, 0, 0, 400, 0, 0, 0,
                                           0, 0, 0, 0, 0, "Microsoft YaHei UI")
            font_pct = gdi32.CreateFontW(int(-20 * scale), 0, 0, 0, FW_SEMIBOLD, 0, 0, 0,
                                         0, 0, 0, 0, 0, "Segoe UI")

            gdi32.SelectObject(hdc, font_title)
            gdi32.SetTextColor(hdc, _rgb(*c["text"]))
            self._text(hdc, "HIDCircus", int(18 * scale), int(12 * scale),
                       width - int(120 * scale), int(24 * scale), DT_LEFT)

            gdi32.SelectObject(hdc, font_sub)
            gdi32.SetTextColor(hdc, _rgb(*c["muted"]))
            self._text(hdc, "外设控制台", int(18 * scale), int(38 * scale),
                       width - int(120 * scale), int(16 * scale), DT_LEFT)

            # 右上角：刷新按钮
            refresh = (width - int(80 * scale), int(14 * scale),
                       width - int(16 * scale), int(42 * scale))
            self._rows = [(*refresh, "refresh")]

            y = int(self.PANEL_HEAD_H * scale)
            for d in self._devices:
                row_h = int(self.PANEL_ROW_H * scale)
                extra = d.get("extra") or {}
                hue = VENDOR_HUE.get(d.get("vendor_key", ""), (160, 160, 170))
                dot_x = int(20 * scale)
                cy = y + int(14 * scale)

                brush = gdi32.CreateSolidBrush(_rgb(*hue))
                gdi32.SelectObject(hdc, brush)
                r = int(4 * scale)
                gdi32.Ellipse(hdc, dot_x - r, cy - r, dot_x + r, cy + r)
                gdi32.DeleteObject(brush)

                gdi32.SelectObject(hdc, font_name)
                gdi32.SetTextColor(hdc, _rgb(*c["text"]))
                self._text(hdc, str(d.get("name", "?"))[:22], int(32 * scale),
                           y + int(2 * scale), width - int(140 * scale), int(20 * scale),
                           DT_LEFT)

                gdi32.SelectObject(hdc, font_small)
                gdi32.SetTextColor(hdc, _rgb(*c["muted"]))
                kind = {"mouse": "鼠标", "keyboard": "键盘", "headset": "耳机"}.get(
                    d.get("kind"), "设备")
                state = "充电中" if d.get("charging") else ("已连接" if d.get("connected", True) else "离线")
                self._text(hdc, f"{kind} · {state}", int(32 * scale), y + int(24 * scale),
                           width - int(140 * scale), int(16 * scale), DT_LEFT)

                battery = d.get("battery")
                if battery is None:
                    color, label = c["muted"], "—"
                else:
                    color = (c["bad"] if battery <= 20 else
                             c["warn"] if battery <= 50 else c["ok"])
                    label = f"{battery}%"
                gdi32.SelectObject(hdc, font_pct)
                gdi32.SetTextColor(hdc, _rgb(*color))
                self._text(hdc, label, width - int(92 * scale), y,
                           int(74 * scale), int(40 * scale), DT_RIGHT)

                ctrl_y = y + int(44 * scale)
                if extra.get("lighting"):
                    on = extra.get("lighting_on")
                    for idx, (label, action) in enumerate((("开", "lighting_on"),
                                                           ("关", "lighting_off"))):
                        bx = int(32 * scale) + idx * int(46 * scale)
                        rect = (bx, ctrl_y, bx + int(40 * scale),
                                ctrl_y + int(22 * scale))
                        active = (action == "lighting_on" and on) or (
                            action == "lighting_off" and on is False)
                        fill = gdi32.CreateSolidBrush(
                            _rgb(*(c["accent"] if active else c["btn"])))
                        gdi32.SelectObject(hdc, fill)
                        gdi32.RoundRect(hdc, rect[0], rect[1], rect[2], rect[3],
                                        int(6 * scale), int(6 * scale))
                        gdi32.DeleteObject(fill)
                        gdi32.SelectObject(hdc, font_small)
                        gdi32.SetTextColor(hdc, _rgb(*(c["accent_ink"] if active else c["text"])))
                        self._text(hdc, label, rect[0], rect[1], rect[2] - rect[0],
                                   rect[3] - rect[1], DT_LEFT | DT_VCENTER | 0x0001)
                        self._rows.append((*rect, f"ctl:{d.get('id')}:{action}"))
                    gdi32.SelectObject(hdc, font_small)
                    gdi32.SetTextColor(hdc, _rgb(*c["muted"]))
                    self._text(hdc, "灯效", int(32 * scale) + int(96 * scale),
                               ctrl_y, int(60 * scale), int(22 * scale),
                               DT_LEFT | DT_VCENTER)

                y += row_h + (int(30 * scale) if (extra.get("lighting")) else 0)

            # 底部：打开网页版 / 关闭
            ly = height - int(self.PANEL_FOOT_H * scale)
            pen2 = gdi32.CreatePen(PS_SOLID, 1, _rgb(*c["line"]))
            gdi32.SelectObject(hdc, pen2)
            gdi32.MoveToEx(hdc, int(16 * scale), ly, None)
            gdi32.LineTo(hdc, width - int(16 * scale), ly)

            btn_h = int(28 * scale)
            by = ly + int(12 * scale)
            half = (width - int(44 * scale)) // 2
            web_rect = (int(16 * scale), by, int(16 * scale) + half, by + btn_h)
            close_rect = (web_rect[2] + int(12 * scale), by, width - int(16 * scale), by + btn_h)
            self._rows.append((*web_rect, "web"))
            self._rows.append((*close_rect, "close"))

            for rect, label, active in ((web_rect, "详细设置（网页版）", False),
                                        (close_rect, "关闭", True)):
                fill = gdi32.CreateSolidBrush(_rgb(*(c["accent"] if active else c["btn"])))
                gdi32.SelectObject(hdc, fill)
                gdi32.RoundRect(hdc, rect[0], rect[1], rect[2], rect[3],
                                int(8 * scale), int(8 * scale))
                gdi32.DeleteObject(fill)
                gdi32.SelectObject(hdc, font_small)
                gdi32.SetTextColor(hdc, _rgb(*(c["accent_ink"] if active else c["text"])))
                self._text(hdc, label, rect[0], rect[1], rect[2] - rect[0], btn_h,
                           DT_LEFT | DT_VCENTER, center=True)

            for f in (font_title, font_sub, font_name, font_small, font_pct):
                gdi32.DeleteObject(f)
            gdi32.DeleteObject(pen)
            gdi32.DeleteObject(pen2)
            gdi32.DeleteObject(bg)
        finally:
            user32.EndPaint(hwnd, ps)

    @staticmethod
    def _text(hdc, text, x, y, cx, cy, flags, center=False):
        buf = ctypes.create_unicode_buffer(text)
        rect = w.RECT(x, y, x + cx, y + cy)
        if center:
            flags = DT_SINGLELINE | DT_VCENTER | 0x0001      # DT_CENTER
        user32.DrawTextW(hdc, buf, len(text), ctypes.byref(rect), flags | DT_NOPREFIX)


gdi32.MoveToEx.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.LineTo.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
user32.GetDpiForWindow.restype = w.UINT
user32.GetDpiForWindow.argtypes = [w.HWND]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.restype = w.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.GetForegroundWindow.restype = w.HWND
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.BringWindowToTop.argtypes = [w.HWND]
user32.GetForegroundWindow.argtypes = []
