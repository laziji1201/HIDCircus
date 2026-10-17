
import ctypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from ctypes import wintypes as w
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server import (create_server, collect_devices, do_control, load_settings,
                    STATUS, UI_REQUESTS, VERSION,
                    HOST, PORT, PORT_TRIES)
from flyout import Flyout
from tray import Tray

APP_NAME = "HIDCircus"
TRAY_POLL = 30
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_icon = None
_stop = threading.Event()
_ui_queue = queue.Queue()
_low_integrity = False
_flyout_open = False                       

INTEGRITY_LEVELS = {0x0000: "不可信", 0x1000: "低（受限）", 0x2000: "中",
                    0x2100: "中+", 0x3000: "高（管理员）", 0x4000: "系统"}

def current_integrity(pid=None):
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.OpenProcessToken.restype = w.BOOL
    advapi32.OpenProcessToken.argtypes = [ctypes.c_void_p, w.DWORD,
                                          ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                             ctypes.c_void_p, w.DWORD,
                                             ctypes.POINTER(w.DWORD)]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(w.DWORD)
    advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, w.DWORD]

    token = ctypes.c_void_p()
    try:
        target = kernel32.OpenProcess(0x1000, False, pid) if pid else kernel32.GetCurrentProcess()
        if not target or not advapi32.OpenProcessToken(target, 0x0008,
                                                       ctypes.byref(token)):
            return None
        size = w.DWORD(0)
        advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(max(size.value, 16))
        if not advapi32.GetTokenInformation(token, 25, buf, size.value, ctypes.byref(size)):
            return None
        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        count = advapi32.GetSidSubAuthorityCount(sid)[0]
        return advapi32.GetSidSubAuthority(sid, count - 1)[0]
    except Exception:
        return None
    finally:
        if token:
            kernel32.CloseHandle(token)

def parent_process():
    """谁启动了我们（排查"低权限"是从哪个入口继承来的）。"""
    try:
        import subprocess as sp
        out = sp.run(["powershell", "-NoProfile", "-Command",
                      f"(Get-CimInstance Win32_Process -Filter 'ProcessId={os.getppid()}')"
                      ".Name + '|' + "
                      f"(Get-CimInstance Win32_Process -Filter 'ProcessId={os.getppid()}')"
                      ".CommandLine"],
                     capture_output=True, text=True, timeout=8,
                     encoding="utf-8", errors="ignore")
        text = out.stdout.strip()
        return text[:160] if text else "未知"
    except Exception:
        return "未知"

def warn_low_integrity():
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR, w.UINT]
    if getattr(sys, "frozen", False):
        howto = f"双击 {Path(sys.executable).name}（或它的桌面快捷方式）"
    else:
        howto = f"双击项目里的 {ROOT / 'run.bat'}"
    text = (
        "HIDCircus 当前以「低权限」运行，托盘图标和面板窗口都无法工作。\n\n"
        "这通常是从受限入口（某个工具的沙箱文件管理器、被降权的终端）启动导致的。\n"
        f"请改为：{howto}\n\n"
        "点「确定」立即用管理员权限重启一次（会弹 UAC）。点「取消」继续以低权限运行。"
    )
    result = user32.MessageBoxW(None, text, "HIDCircus 权限不足",
                                0x04 | 0x30 | 0x40000)                              
    if result == 6:                                            
        try:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.ShellExecuteW.restype = ctypes.c_void_p
            shell32.ShellExecuteW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR,
                                              w.LPCWSTR, w.LPCWSTR, ctypes.c_int]
            shell32.ShellExecuteW(None, "runas", sys.executable,
                                  f'"{ROOT / "app.py"}"', str(ROOT), 1)
            os._exit(0)
        except Exception:
            log("提权重启失败: " + traceback.format_exc())

def log_dir():
    base = (Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False) else ROOT)
    d = base / "logs"
    d.mkdir(exist_ok=True)
    return d

LOG_FILE = log_dir() / "app.log"

_SCRUB_RULES = (
    (re.compile(r"([A-Za-z]:\\Users\\)[^\\\s]+"), r"\1<user>"),
    (re.compile(r"\b[0-9A-Fa-f]{12,}\b"), "<id>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
)

def _scrub(msg):
    """日志脱敏：用户名、疑似序列号、邮箱都不该写进日志文件。"""
    text = str(msg)
    for pattern, repl in _SCRUB_RULES:
        text = pattern.sub(repl, text)
    return text

def log(msg):
    """pythonw 没有控制台，出错只能靠文件留痕。"""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 512 * 1024:
            LOG_FILE.write_text("", encoding="utf-8")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {_scrub(msg)}\n")
    except Exception:
        pass

ICON_PATH = ROOT / "assets" / "icon.png"
_ICON_BASE = None

def _icon_base():
    global _ICON_BASE
    if _ICON_BASE is None:
        try:
            _ICON_BASE = Image.open(ICON_PATH).convert("RGBA")
        except Exception:
            _ICON_BASE = False
            log("图标文件读不到，托盘退回默认画法")
    return _ICON_BASE or None

def make_icon(battery):
    """托盘图标：用设计稿图标，低电量时右下角加个红点。"""
    size = 64
    base = _icon_base()
    if base is not None:
        img = base.resize((size, size), Image.LANCZOS)
    else:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        color = (61, 220, 132) if battery is None or battery > 50 else (
            (251, 191, 36) if battery > 20 else (248, 113, 113))
        d.ellipse((3, 3, size - 3, size - 3), outline=color, width=5)
        if battery is not None:
            try:
                f = ImageFont.truetype(FONT_PATH, 28 if battery > 99 else 32)
            except Exception:
                f = ImageFont.load_default()
            text = str(battery)
            box = d.textbbox((0, 0), text, font=f)
            d.text(((size - (box[2] - box[0])) / 2 - box[0],
                    (size - (box[3] - box[1])) / 2 - box[1]), text, font=f, fill=color)
        return img

    if battery is not None and battery <= 20:
        d = ImageDraw.Draw(img)
        d.ellipse((size - 22, size - 22, size - 2, size - 2),
                  fill=(248, 113, 113, 255), outline=(15, 15, 18, 255), width=3)
    return img

def update_tray(force=False):
    if _icon is None:
        return None
    try:
        values = [d["battery"] for d in collect_devices(force=force)
                  if d.get("battery") is not None]
        low = min(values) if values else None
        _icon.update(make_icon(low),
                     f"{APP_NAME} — {low}%" if low is not None else f"{APP_NAME} — 无设备")
        return low
    except Exception:
        log("托盘刷新异常: " + traceback.format_exc())
        return None

def poll_loop():
    while not _stop.is_set():
        update_tray()
        _stop.wait(TRAY_POLL)

WM_DEVICECHANGE = 0x0219
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004
DEVICE_NOTIFY_WINDOW_HANDLE = 0

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

class _DEV_BROADCAST_DEVICEINTERFACE(ctypes.Structure):
    _fields_ = [("dbcc_size", w.DWORD), ("dbcc_devicetype", w.DWORD),
                ("dbcc_reserved", w.DWORD), ("dbcc_classguid", _GUID),
                ("dbcc_name", w.WCHAR * 1)]

_HID_IFACE = _GUID(0x4D1E55B2, 0xF16F, 0x11CF,
                   (ctypes.c_ubyte * 8)(0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30))

def start_device_watch():
    user32.RegisterDeviceNotificationW.restype = ctypes.c_void_p
    user32.RegisterDeviceNotificationW.argtypes = [w.HWND, ctypes.c_void_p, w.DWORD]
    user32.CreateWindowExW.restype = w.HWND

    proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT,
                              ctypes.c_void_p, ctypes.c_void_p)(_device_wndproc)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [("style", w.UINT), ("lpfnWndProc", ctypes.c_void_p),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                    ("hCursor", w.HANDLE), ("hBackground", w.HBRUSH),
                    ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]

    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASS()
    wc.lpfnWndProc = ctypes.cast(proc, ctypes.c_void_p)
    wc.hInstance = hinst
    wc.lpszClassName = "HIDCircusDeviceWatch"
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, "HIDCircusDeviceWatch", "watch", 0,
                                  0, 0, 0, 0, None, None, hinst, None)
    if not hwnd:
        log("设备监听窗口创建失败，继续用轮询")
        return

    filt = _DEV_BROADCAST_DEVICEINTERFACE()
    filt.dbcc_size = ctypes.sizeof(_DEV_BROADCAST_DEVICEINTERFACE)
    filt.dbcc_devicetype = 5                                      
    filt.dbcc_classguid = _HID_IFACE
    notify = user32.RegisterDeviceNotificationW(hwnd, ctypes.byref(filt),
                                                DEVICE_NOTIFY_WINDOW_HANDLE)
    if not notify:
        log("设备通知注册失败，继续用轮询")
        return
    log("已监听设备插拔（插入/移除后立刻刷新）")
    msg = w.MSG()
    while not _stop.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

def _device_wndproc(hwnd, msg, wparam, lparam):
    try:
        if msg == WM_DEVICECHANGE and int(wparam or 0) in (DBT_DEVICEARRIVAL,
                                                           DBT_DEVICEREMOVECOMPLETE):

            def _rescan():
                time.sleep(0.8)
                try:
                    collect_devices(force=True)
                    update_tray(force=True)
                except Exception:
                    log("插拔后刷新失败: " + traceback.format_exc())
            threading.Thread(target=_rescan, daemon=True).start()
            return 0
    except Exception:
        pass

    wp = int(wparam or 0) & 0xFFFFFFFFFFFFFFFF
    lp = int(lparam or 0) & 0xFFFFFFFFFFFFFFFF
    return user32.DefWindowProcW(hwnd, msg, ctypes.c_void_p(wp), ctypes.c_void_p(lp))

def _process_name(hwnd):
    """窗口属于哪个进程（只取 exe 名）。"""
    pid = w.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x1000, False, pid.value)                              
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = w.DWORD(512)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return Path(buf.value).name.lower()
    finally:
        kernel32.CloseHandle(handle)

def _enum_windows():
    found = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def _cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(_cb, 0)
    return found

def panel_windows():
    out = []
    for hwnd, title in _enum_windows():
        if not title.startswith(APP_NAME):
            continue
        if " - " in title:
            continue
        if _process_name(hwnd) != "msedge.exe":
            continue
        out.append(hwnd)
    return out

CHROMIUM_CANDIDATES = [
    ("Edge", [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]),
    ("Chrome", [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]),
    ("Brave", [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"]),
    ("Vivaldi", [r"C:\Program Files\Vivaldi\Application\vivaldi.exe"]),
]

def find_browser():
    """找一个支持 --app 无边框窗口的 Chromium 系浏览器。"""
    for name, paths in CHROMIUM_CANDIDATES:
        for path in paths:
            if Path(path).is_file():
                return name, path
    for exe in ("msedge", "chrome", "brave", "vivaldi"):
        found = shutil.which(exe)
        if found:
            return exe, found
    return None, None

def kill_stale_browsers(profile: Path):
    if sys.platform != "win32":
        return
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{profile}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass

EDGE_BROWSER_FLAGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",                                   
    "--no-service-autorun",
    "--disable-session-crashed-bubble",
    "--hide-crash-restore-bubble",
    "--disable-features=Translate,MediaRouter,msEdgeSyncPromo",
    "--no-proxy-server",                         
]

def seed_profile(profile: Path):
    default = profile / "Default"
    prefs = default / "Preferences"
    if prefs.exists():
        return
    try:
        default.mkdir(parents=True, exist_ok=True)
        prefs.write_text(json.dumps({
            "sync": {"disabled": True},
            "signin": {"allowed": False, "allowed_on_next_startup": False},
            "browser": {"has_seen_welcome_page": True},
            "profile": {"exit_type": "Normal", "exited_cleanly": True},
            "edge": {"first_run_completed": True},
        }), encoding="utf-8")
    except OSError:
        pass

def clean_profile_state(profile: Path):
    """清掉会话恢复文件（被强杀后留下的"崩溃会话"会让新窗口卡在错误页）。"""
    default = profile / "Default"
    for rel in ("Sessions", "Current Session", "Current Tabs",
                "Last Session", "Last Tabs"):
        target = default / rel
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink(missing_ok=True)
        except OSError:
            pass

def _elevation_dialog():
    for hwnd, title in _enum_windows():
        if title.strip() != "Microsoft Edge":
            continue
        if _process_name(hwnd) == "msedge.exe":
            return True
    return False

def page_alive(since):
    """页面有没有在 since 之后回过心跳。"""
    return (STATUS.get("last_ping") or 0) >= since

def wait_for_page(since, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline and not _stop.is_set():
        if page_alive(since):
            return True
        time.sleep(0.4)
    return False

def _spawn_window(browser, url, profile: Path, wipe=False, extra=()):
    if wipe:
        shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)
    kill_stale_browsers(profile)
    if not wipe:
        clean_profile_state(profile)
    seed_profile(profile)

    args = [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        *EDGE_BROWSER_FLAGS,
        "--window-size=1180,820",
        "--window-position=140,90",
        *extra,
    ]
    try:
        subprocess.Popen(args, close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        log("启动窗口失败: " + traceback.format_exc())
        return False

def _profile_candidates():
    """先用手上这份配置；不行再换一份全新的（避开被提权实例锁住的那份）。"""
    base = ROOT / ".runtime"
    yield base / "browser-profile"
    yield base / f"browser-profile-{int(time.time()) % 100000}"

def open_panel(port):
    """把面板打开；已经开着就提到前台。"""
    existing = panel_windows()
    if existing:
        for hwnd in existing:
            user32.ShowWindow(hwnd, 9)                      
            user32.SetForegroundWindow(hwnd)
        if page_alive(time.time() - 30):
            return True

    url = f"http://{HOST}:{port}"
    name, browser = find_browser()
    log(f"可用浏览器: {name or '无'}")

    if _low_integrity:
        log(f"低权限会话：不尝试自动开窗，请手动访问 {url}")
        threading.Thread(target=warn_low_integrity, daemon=True).start()
        return False

    if browser:
        for profile in _profile_candidates():
            since = time.time()
            fresh = not profile.exists()
            log(f"尝试无边框窗口（{name} · {profile.name}"
                f"{' · 新配置' if fresh else ''}）")
            if not _spawn_window(browser, url, profile, wipe=fresh):
                continue
            if wait_for_page(since, 12):
                log(f"面板已就绪（{name} 无边框窗口）: {url}")
                return True
            log("没收到页面心跳")
            if _elevation_dialog():
                log("检测到「现有实例正在以提升的权限运行」：有管理员权限的 Edge 占着"
                    "这份配置目录，换一个新配置目录重试")
            else:
                break

    since = time.time()
    log("改用默认浏览器打开面板")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        log("默认浏览器打不开: " + traceback.format_exc())
        return False
    if wait_for_page(since, 20):
        log(f"面板已在默认浏览器打开: {url}")
        return True
    log(f"面板没能自动打开，请手动访问 {url}")

    if _low_integrity:
        threading.Thread(target=warn_low_integrity, daemon=True).start()
    return False

_handled = {"panel": 0.0}

def close_flyout():
    """关掉原生小面板（如果开着）。"""
    hwnd = user32.FindWindowW("HIDCircusFlyout", None)
    if hwnd:
        user32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)

def _relaunch_elevated():
    """用管理员权限重启自己（一次 UAC）。成功返回 True。"""
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.ShellExecuteW.restype = ctypes.c_void_p
        shell32.ShellExecuteW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR,
                                          w.LPCWSTR, w.LPCWSTR, ctypes.c_int]
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = "--elevated"
        else:
            exe = sys.executable
            params = f'"{ROOT / "app.py"}" --elevated'

        outcome = {"ok": False}

        def _call():
            try:
                res = shell32.ShellExecuteW(None, "runas", exe, params, str(ROOT), 1)
                outcome["ok"] = int(res or 0) > 32
            except Exception:
                outcome["ok"] = False

        worker = threading.Thread(target=_call, daemon=True)
        worker.start()
        worker.join(15)
        return outcome["ok"]
    except Exception:
        log("提权重启异常: " + traceback.format_exc())
        return False

def _system_is_dark():
    """系统主题是深色还是浅色（主题设为 auto 时用）。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            value, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return value == 0
    except Exception:
        return True

FLYOUT_COLORS = {
    ("dark", "amber"): dict(bg=(18, 18, 21), line=(35, 35, 41), text=(236, 236, 239),
                            muted=(139, 139, 150), ok=(74, 222, 128), warn=(251, 191, 36),
                            bad=(248, 113, 113), accent=(242, 163, 60),
                            accent_ink=(29, 19, 4), btn=(32, 32, 38)),
    ("dark", "silver"): dict(bg=(17, 17, 21), line=(42, 42, 49), text=(236, 236, 241),
                             muted=(164, 164, 174), ok=(74, 222, 128), warn=(251, 191, 36),
                             bad=(248, 113, 113), accent=(201, 201, 211),
                             accent_ink=(19, 19, 23), btn=(35, 35, 41)),
    ("dark", "sakura"): dict(bg=(26, 21, 23), line=(56, 46, 50), text=(244, 236, 238),
                             muted=(185, 169, 174), ok=(74, 222, 128), warn=(251, 191, 36),
                             bad=(248, 113, 113), accent=(251, 177, 197),
                             accent_ink=(58, 26, 36), btn=(46, 37, 41)),
    ("dark", "neon"): dict(bg=(10, 10, 16), line=(37, 37, 58), text=(238, 244, 246),
                           muted=(154, 168, 180), ok=(124, 255, 203), warn=(251, 191, 36),
                           bad=(255, 53, 102), accent=(82, 255, 233),
                           accent_ink=(4, 33, 31), btn=(29, 29, 42)),
    ("light", "amber"): dict(bg=(252, 251, 248), line=(229, 226, 219), text=(23, 23, 26),
                             muted=(110, 110, 116), ok=(21, 128, 61), warn=(180, 83, 9),
                             bad=(185, 28, 28), accent=(188, 114, 18),
                             accent_ink=(255, 255, 255), btn=(242, 240, 234)),
    ("light", "silver"): dict(bg=(252, 252, 253), line=(228, 228, 233), text=(24, 24, 28),
                              muted=(91, 91, 102), ok=(21, 128, 61), warn=(180, 83, 9),
                              bad=(185, 28, 28), accent=(76, 76, 88),
                              accent_ink=(255, 255, 255), btn=(241, 241, 244)),
    ("light", "sakura"): dict(bg=(251, 249, 247), line=(232, 228, 224), text=(42, 38, 40),
                              muted=(110, 104, 108), ok=(21, 128, 61), warn=(180, 83, 9),
                              bad=(185, 28, 28), accent=(217, 121, 143),
                              accent_ink=(255, 255, 255), btn=(242, 240, 236)),
    ("light", "neon"): dict(bg=(250, 253, 253), line=(220, 232, 232), text=(16, 32, 42),
                            muted=(78, 98, 108), ok=(21, 128, 61), warn=(180, 83, 9),
                            bad=(185, 28, 28), accent=(255, 53, 102),
                            accent_ink=(255, 255, 255), btn=(234, 244, 244)),
}

def flyout_colors():
    cfg = load_settings()
    mode = cfg.get("theme", "auto")
    dark = mode != "light" if mode != "dark" else True
    if mode == "auto":
        dark = _system_is_dark()
    palette = cfg.get("palette", "amber")
    return FLYOUT_COLORS.get(("dark" if dark else "light", palette),
                             FLYOUT_COLORS[("dark", "amber")])

def _panel_control(device_id, action):
    """原生面板上的按钮：查设备所属 provider 再下发动作。"""
    try:
        devices = collect_devices()
        dev = next((d for d in devices if d.get("id") == device_id), None)
        if dev is None:
            return
        vendor = dev.get("vendor_key", "")
        result = do_control(vendor, device_id, action, {})
        log(f"面板控制 {device_id} {action} -> {result}")
        collect_devices(force=True)
    except Exception:
        log("面板控制异常: " + traceback.format_exc())

def show_flyout(mode="panel"):
    """托盘左键：原生面板（不走浏览器）。再点一次收起。"""
    global _flyout_open
    existing = user32.FindWindowW("HIDCircusFlyout", None)
    if existing:
        user32.PostMessageW(ctypes.c_void_p(existing), 0x0010, 0, 0)
        return
    if _flyout_open:
        return
    _flyout_open = True
    global _panel_used
    _panel_used = True
    try:
        Flyout(collect_devices,
               lambda: _ui_queue.put(lambda: open_panel(PORT_HOLDER["port"])),
               None, flyout_colors(), mode=mode, on_control=_panel_control).show()
    except Exception:
        log("原生面板异常: " + traceback.format_exc())
    finally:
        _flyout_open = False

def handle_ui_requests():
    """页面按钮发过来的请求：打开主面板 / 关闭小面板。"""
    if UI_REQUESTS["panel"] > _handled["panel"]:
        _handled["panel"] = UI_REQUESTS["panel"]
        close_flyout()
        _ui_queue.put(lambda: open_panel(PORT_HOLDER["port"]))

def close_panel():
    """退出时关掉我们开的面板窗口，别留一个连不上后端的空壳。"""
    for hwnd in panel_windows():
        try:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)               
        except Exception:
            pass

def quit_app(icon=None, item=None):
    _stop.set()
    if _icon is not None:
        try:
            _icon.stop()
        except Exception:
            pass
    close_panel()
    log(f"{APP_NAME} 退出")
    os._exit(0)

def on_open(icon=None, item=None):
    _ui_queue.put(lambda: open_panel(PORT_HOLDER["port"]))

def on_refresh(icon=None, item=None):
    _ui_queue.put(lambda: update_tray(force=True))

def pump():
    """主循环里执行队列中的动作（托盘回调在自己的线程）。"""
    while not _stop.is_set():
        try:
            handle_ui_requests()
        except Exception:
            log("处理页面请求异常: " + traceback.format_exc())
        try:
            _ui_queue.get(timeout=0.2)()
        except queue.Empty:
            pass
        except Exception:
            log("托盘动作异常: " + traceback.format_exc())

_panel_used = False                                     

def idle_watchdog():
    started = time.time()
    while not _stop.is_set():
        if _panel_used:
            _stop.wait(5)
            continue
        last = STATUS.get("last_ping") or 0
        if last:
            if time.time() - last > 90:
                log("页面 90 秒没有心跳（面板应该被关了），退出")
                break
        elif time.time() - started > 150:
            log("面板始终没有连上来，退出")
            break
        _stop.wait(5)
    quit_app()

PORT_HOLDER = {"port": PORT}

def acquire_single_instance():
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, "Local\\HIDCircus.SingleInstance")
    already = ctypes.get_last_error() == 183                              
    return handle, not already

def find_running_instance():
    """返回 (port, status_json) 或 (None, None)。"""
    for port in range(PORT, PORT + PORT_TRIES):
        try:
            with urllib.request.urlopen(
                    f"http://{HOST}:{port}/api/status", timeout=0.4) as resp:
                data = json.loads(resp.read())
                if isinstance(data, dict) and "port" in data and "log" in data:
                    return port, data
        except Exception:
            continue
    return None, None

def pid_by_port(port):
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=10, encoding="utf-8", errors="ignore",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line.upper():
                return int(line.split()[-1])
    except Exception:
        pass
    return None


def kill_pid(pid):
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(int(pid))],
                       capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        log(f"结束旧实例 {pid} 失败: " + traceback.format_exc())
        return False

def main():
    global _icon, _low_integrity

    def _hook(exc_type, exc, tb):
        log("未捕获异常: " + "".join(traceback.format_exception(exc_type, exc, tb)))

    def _thread_hook(args):
        log(f"线程 {args.thread.name if args.thread else '?'} 异常: "
            + "".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = _hook
    threading.excepthook = _thread_hook

    level = current_integrity()
    log(f"进程完整性: {INTEGRITY_LEVELS.get(level, hex(level) if level else '未知')}")
    if level is not None and level < 0x2000:
        _low_integrity = True

        log("检测到低权限，尝试提权重启（会弹一次 UAC）")
        if "--elevated" not in sys.argv and _relaunch_elevated():
            log("已交给提权实例，当前进程退出")
            return
        log("提权被取消或失败，继续以低权限运行（托盘/窗口不可用）")

    log(f"{APP_NAME} 启动")

    _mutex, first = acquire_single_instance()
    running, running_status = find_running_instance()
    if running:
        running_version = (running_status or {}).get("version", "未知")
        if running_version != VERSION:
            old_pid = (running_status or {}).get("pid") or pid_by_port(running)
            log(f"端口 {running} 上是旧版本 {running_version}（当前 {VERSION}），准备接管")
            if old_pid and kill_pid(old_pid):
                log("旧实例已结束，继续启动新版本")
                time.sleep(1.5)
                running = None
            else:
                log("无法结束旧实例（权限不足），请手动在任务管理器结束 HIDCircus")
        if running:
            log(f"已有实例在运行（端口 {running}），叫它把面板弹出来")
            try:
                req = urllib.request.Request(
                    f"http://{HOST}:{running}/api/show", data=b"{}", method="POST")
                req.add_header("Content-Type", "application/json")
                urllib.request.urlopen(req, timeout=3).read()
            except Exception:
                log("提醒运行中实例失败: " + traceback.format_exc())
            return
    if not first:
        log("检测到实例标记但找不到服务，继续启动")
    try:
        server, port = create_server()
    except OSError as e:
        log(f"HTTP 服务启动失败: {e}")
        raise

    PORT_HOLDER["port"] = port
    STATUS["port"] = port
    STATUS["log"] = str(LOG_FILE)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=pump, daemon=True).start()
    try:
        runtime = ROOT / ".runtime"
        runtime.mkdir(exist_ok=True)
        (runtime / "port.txt").write_text(str(port), encoding="utf-8")
    except OSError:
        pass
    log(f"HTTP 面板: http://{HOST}:{port}")
    log(f"浏览器: {find_browser()[0] or '未找到'}")
    log(f"Python: {sys.executable}")
    log(f"父进程: {parent_process()}")
    log(f"父进程权限: {INTEGRITY_LEVELS.get(current_integrity(os.getppid()), '读不到')}")

    tray_ok = False
    try:
        _icon = Tray(make_icon(None), APP_NAME,
                     [("打开面板", lambda *_: threading.Thread(
                         target=show_flyout, daemon=True).start()),
                      ("主面板", on_open),
                      ("刷新电量", on_refresh),
                      ("退出", quit_app)],
                     on_click=lambda: threading.Thread(
                         target=show_flyout, daemon=True).start())
        tray_ok = _icon.start()
        if not tray_ok:
            log(f"托盘创建失败（Shell_NotifyIcon 错误码 {getattr(_icon, 'last_error', '?')}）")
            _icon = None
    except Exception:
        log("托盘不可用: " + traceback.format_exc())
        _icon = None
        tray_ok = False
    STATUS["tray"] = tray_ok
    log("托盘已就绪" if tray_ok else "托盘不可用，退化为只看窗口")

    if "--panel" in sys.argv:
        threading.Timer(1.2, lambda: show_flyout("panel")).start()
    else:
        log("启动完成，驻留托盘（点托盘图标打开面板）")

    threading.Thread(target=start_device_watch, daemon=True).start()

    if tray_ok:
        threading.Thread(target=poll_loop, daemon=True).start()
    else:
        threading.Thread(target=idle_watchdog, daemon=True).start()

    while not _stop.is_set():
        time.sleep(0.4)

if __name__ == "__main__":
    main()
