"""HIDCircus 桌面入口。

窗口用 Edge 的 --app 模式：没有地址栏和标签页，本质就是一个独立窗口，
但前端是完整 Chromium 渲染（CSS 全部可用），且和浏览器面板共用同一套页面。
不用内嵌 WebView（pywebview 在 .NET Framework 下加载失败，coreclr 又缺 WinForms）。

结构：
  本地 HTTP 服务（线程） + Edge 应用窗口（子进程） + 托盘（原生 Shell_NotifyIcon）
  关闭窗口不会退出程序，托盘还在；托盘退出才真正结束。
  托盘不可用时退化为「窗口关了就把进程也收掉」，避免留后台孤儿进程。
"""

import ctypes
import json
import urllib.request
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
from pathlib import Path

from tray import Tray
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server import create_server, collect_devices, load_settings, STATUS, HOST, PORT, PORT_TRIES

APP_NAME = "HIDCircus"
TRAY_POLL = 30
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"

_root_icon = None
_stop = threading.Event()
_ui_queue = queue.Queue()
_no_window_tracking = False     # 退到默认浏览器时，没有可跟踪的窗口


# ---------- 日志 ----------

def log_dir():
    base = (Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False) else ROOT)
    d = base / "logs"
    d.mkdir(exist_ok=True)
    return d


LOG_FILE = log_dir() / "app.log"


def log(msg):
    """pythonw 没有控制台，出错只能靠文件留痕。"""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 512 * 1024:
            LOG_FILE.write_text("", encoding="utf-8")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except Exception:
        pass


# ---------- 托盘图标 ----------

def make_icon(battery):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if battery is None:
        color, text = (154, 154, 164), "--"
    else:
        color = (61, 220, 132) if battery > 50 else (
            (251, 191, 36) if battery > 20 else (248, 113, 113))
        text = str(battery)
    d.ellipse((3, 3, size - 3, size - 3), outline=color, width=5)
    try:
        f = ImageFont.truetype(FONT_PATH, 28 if len(text) > 1 else 32)
    except Exception:
        f = ImageFont.load_default()
    box = d.textbbox((0, 0), text, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]),
           text, font=f, fill=color)
    return img


def update_tray(force=False):
    if _root_icon is None:
        return None
    values = [d["battery"] for d in collect_devices(force=force)
              if d.get("battery") is not None]
    low = min(values) if values else None
    _root_icon.icon = make_icon(low)
    _root_icon.title = (f"{APP_NAME} — {low}%" if low is not None
                        else f"{APP_NAME} — 无设备")
    return low


def poll_loop():
    while not _stop.is_set():
        try:
            update_tray()
        except Exception:
            log("托盘刷新异常: " + traceback.format_exc())
        _stop.wait(TRAY_POLL)


# ---------- 窗口 ----------

def find_edge():
    candidates = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def _process_name(hwnd):
    """窗口属于哪个进程（只要 exe 名）。"""
    pid = w.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = w.DWORD(512)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return Path(buf.value).name.lower()
    finally:
        kernel32.CloseHandle(h)


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
    """只认"我们自己的面板窗口"。

    不能只按标题模糊匹配：资源管理器窗口的标题是「HIDCircus - 文件资源管理器」，
    也包含 HIDCircus，之前就会把那个文件夹窗口当成面板，导致点托盘/启动都只是
    去聚焦一个文件夹，浏览器根本不启动。所以还要限定是 Edge 进程 + 标题以应用名开头。
    """
    out = []
    for hwnd, title in _enum_windows():
        if not title.startswith(APP_NAME):
            continue
        if " - " in title:          # 「HIDCircus - 文件资源管理器」这类不算
            continue
        if _process_name(hwnd) != "msedge.exe":
            continue
        out.append(hwnd)
    return out

def kill_stale_browsers(profile: Path):
    """杀掉上次残留、还在用我们这个配置目录的 Edge 实例。

    窗口被关掉/进程被强杀后，Edge 可能留着一个后台浏览器进程；这时再启动会直接
    交给那个旧实例（它可能已经处在崩溃状态），新窗口就永远停在"已崩溃"。
    只按配置目录精确匹配，不碰用户自己的浏览器。
    """
    if sys.platform != "win32":
        return
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{profile}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log("已清理残留的旧浏览器实例")
    except Exception:
        log("清理旧实例失败（忽略）")


def clean_profile_state(profile: Path):
    """清掉 Edge 的会话恢复文件。

    Edge 被强杀后会在配置目录里留下"崩溃会话"，下次用同一份配置启动时会去恢复
    上次那个已经失效的地址，窗口就卡在错误页上（标题会变成 127.0.0.1）。
    这些都是可再生成的会话文件，删掉不影响任何设置。
    """
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


def _spawn_window(edge, url, profile: Path, wipe=False, extra=()):
    """起一次窗口，并等它真的把页面标题加载出来。"""
    if wipe:
        shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)
    kill_stale_browsers(profile)
    if not wipe:
        clean_profile_state(profile)

    args = [
        edge,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--disable-features=Translate,MediaRouter",
        "--window-size=1180,820",
        "--window-position=140,90",
        *extra,
    ]
    try:
        subprocess.Popen(args, close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        log("启动窗口失败: " + traceback.format_exc())
        return False

    # 加载失败时 Edge 的窗口标题就是地址本身，所以只有标题变成 HIDCircus 才算成功
    deadline = time.time() + 12
    while time.time() < deadline and not _stop.is_set():
        if panel_windows():
            return True
        time.sleep(0.6)

    # 失败时把当时能看到的 Edge 窗口标题记下来：能区分"窗口没出现"和"出现但页面挂了"
    seen = []
    for hwnd, title in _enum_windows():
        if _process_name(hwnd) == "msedge.exe" and ("HIDCircus" in title or title.startswith("127.0.0.1")):
            seen.append(title)
    log(f"面板窗口未就绪，当前 Edge 窗口: {seen or '无'}")
    return False


def open_panel(port):
    """打开应用窗口。已经开着就把它提到前台。

    先用现有配置目录；起不来就说明这份 Edge 配置坏了（上一次被强杀过），
    清空重开一次——配置目录是我们自己生成的，删掉没有副作用。
    """
    existing = panel_windows()
    if existing:
        for hwnd in existing:
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return True

    url = f"http://{HOST}:{port}"
    edge = find_edge()
    if not edge:
        log("没找到 Edge，退回默认浏览器")
        import webbrowser
        webbrowser.open(url)
        return False

    profile = ROOT / ".runtime" / "edge-profile"

    # 逐级降级：正常配置 → 清配置 → 关 GPU → 退到默认浏览器
    attempts = [
        ("使用现有配置", {"wipe": False, "extra": ()}),
        ("清空配置副本重试", {"wipe": True, "extra": ()}),
        ("关闭 GPU 重试", {"wipe": True, "extra": ("--disable-gpu",)}),
    ]
    for label, kwargs in attempts:
        log(f"打开面板窗口：{label}")
        if _spawn_window(edge, url, profile, **kwargs):
            log(f"已打开窗口: {url}")
            return True

    global _no_window_tracking
    _no_window_tracking = True
    log("无边框窗口在本次环境用不了，改用默认浏览器打开面板")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        log("默认浏览器也打不开: " + traceback.format_exc())
    return False


def close_panel():
    """退出时顺手关掉我们开的窗口，别留一个连不上后端的空壳。"""
    for hwnd in panel_windows():
        try:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
        except Exception:
            pass


def window_watchdog(port):
    """没有托盘时，窗口一关就把进程收掉。

    Edge 冷启动到页面加载完可能要好几秒，标题也不是一开始就叫 HIDCircus，
    所以要给足启动宽限，并且连续几次都找不到才算真的关了。
    """
    if _no_window_tracking:
        return          # 面板开在默认浏览器里，窗口标题不可控，别因此退出

    deadline = time.time() + 90
    while time.time() < deadline and not _stop.is_set():
        if panel_windows():
            break
        _stop.wait(2)
    misses = 0
    while not _stop.is_set():
        if panel_windows():
            misses = 0
        else:
            misses += 1
            if misses >= 3:
                log("窗口已关闭且无托盘，退出")
                break
        _stop.wait(2)
    quit_app()


# ---------- 托盘动作 ----------

def on_open(icon=None, item=None):
    _ui_queue.put(lambda: open_panel(PORT_HOLDER["port"]))


def on_refresh(icon=None, item=None):
    _ui_queue.put(lambda: update_tray(force=True))


def quit_app(icon=None, item=None):
    _stop.set()
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            pass
    close_panel()
    log(f"{APP_NAME} 退出")
    os._exit(0)


PORT_HOLDER = {"port": 8777}


def pump():
    """主循环线程里执行队列里的动作（托盘回调在它自己的线程）。"""
    while not _stop.is_set():
        try:
            _ui_queue.get(timeout=0.2)()
        except queue.Empty:
            pass
        except Exception:
            log("托盘动作异常: " + traceback.format_exc())


# ---------- 入口 ----------

def acquire_single_instance():
    """单实例：重复双击 run.bat 不要再起一套服务。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, "Local\\HIDCircus.SingleInstance")
    already = ctypes.get_last_error() == 183        # ERROR_ALREADY_EXISTS
    return handle, not already


def find_running_port():
    """找到已经在跑的那个实例的端口。"""
    for port in range(PORT, PORT + PORT_TRIES):
        try:
            with urllib.request.urlopen(
                    f"http://{HOST}:{port}/api/status", timeout=0.4) as resp:
                data = json.loads(resp.read())
            if isinstance(data, dict):
                return port
        except Exception:
            continue
    return None


def main():
    global _root_icon

    def _hook(exc_type, exc, tb):
        log("未捕获异常: " + "".join(traceback.format_exception(exc_type, exc, tb)))

    def _thread_hook(args):
        log(f"线程 {args.thread.name if args.thread else '?'} 异常: "
            + "".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = _hook
    threading.excepthook = _thread_hook

    _mutex, first = acquire_single_instance()
    if not first:
        port = find_running_port()
        if port:
            log(f"已有实例在运行（端口 {port}），只负责把面板打开")
            open_panel(port)
            return
        log("检测到实例标记但找不到服务，继续启动")

    log(f"{APP_NAME} 启动")

    try:
        server, port = create_server()
    except OSError as e:
        log(f"HTTP 服务启动失败: {e}")
        raise
    PORT_HOLDER["port"] = port
    STATUS["port"] = port
    STATUS["log"] = str(LOG_FILE)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"HTTP 面板: http://{HOST}:{port}")
    log(f"Edge 路径: {find_edge() or '未找到'}")
    log(f"Python: {sys.executable}")
    print(f"HTTP 面板: http://{HOST}:{port}")

    threading.Thread(target=pump, daemon=True).start()

    # 托盘（原生 Shell_NotifyIcon）
    tray_ok = False
    try:
        _root_icon = Tray(
            make_icon(None), APP_NAME,
            [("打开面板", on_open), ("刷新电量", on_refresh), ("退出", quit_app)],
            on_click=on_open,
        )
        tray_ok = _root_icon.start()
        if not tray_ok:
            log(f"托盘创建失败（Shell_NotifyIcon 错误码 {getattr(_root_icon, 'last_error', '?')}）")
            _root_icon = None
    except Exception:
        log("托盘不可用: " + traceback.format_exc())
        _root_icon = None
        tray_ok = False
    STATUS["tray"] = tray_ok
    log("托盘已就绪" if tray_ok else "托盘不可用，退化为只显示窗口")
    threading.Thread(target=open_panel, args=(port,), daemon=True).start()

    if tray_ok:
        threading.Thread(target=poll_loop, daemon=True).start()
    else:
        threading.Thread(target=window_watchdog, args=(port,), daemon=True).start()

    # 主线程只负责等退出
    while not _stop.is_set():
        time.sleep(0.4)


if __name__ == "__main__":
    main()
