"""HIDCircus 桌面入口。

窗口用 Edge 的 --app 模式：没有地址栏和标签页，本质就是一个独立窗口，
但前端是完整 Chromium 渲染（CSS 全部可用），且和浏览器面板共用同一套页面。
不用内嵌 WebView（pywebview 在 .NET Framework 下加载失败，coreclr 又缺 WinForms）。

结构：
  本地 HTTP 服务（线程） + Edge 应用窗口（子进程） + 托盘（pystray）
  关闭窗口不会退出程序，托盘还在；托盘退出才真正结束。
  托盘不可用时退化为「窗口关了就把进程也收掉」，避免留后台孤儿进程。
"""

import ctypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes as w
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server import create_server, collect_devices, load_settings, STATUS, HOST

APP_NAME = "HIDCircus"
TRAY_POLL = 30
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"

_root_icon = None
_stop = threading.Event()
_ui_queue = queue.Queue()


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


def windows_with_title(needle):
    """返回标题包含 needle 的可见顶层窗口句柄列表。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    handles = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def _cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if needle.lower() in buf.value.lower():
            handles.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return handles


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


def _spawn_window(edge, url, profile: Path, wipe=False):
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
        if windows_with_title(APP_NAME):
            return True
        time.sleep(0.6)
    return False


def open_panel(port):
    """打开应用窗口。已经开着就把它提到前台。

    先用现有配置目录；起不来就说明这份 Edge 配置坏了（上一次被强杀过），
    清空重开一次——配置目录是我们自己生成的，删掉没有副作用。
    """
    existing = windows_with_title(APP_NAME)
    if existing:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
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
    if _spawn_window(edge, url, profile):
        log(f"已打开窗口: {url}")
        return True

    log("窗口未加载出来，清空配置副本重试一次")
    if _spawn_window(edge, url, profile, wipe=True):
        log(f"已打开窗口: {url}")
        return True

    log("窗口仍然打不开，服务继续在跑，可以手动运行 panel.bat")
    return False


def close_panel():
    """退出时顺手关掉我们开的窗口，别留一个连不上后端的空壳。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    for hwnd in windows_with_title(APP_NAME):
        try:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
        except Exception:
            pass


def window_watchdog(port):
    """没有托盘时，窗口一关就把进程收掉。

    Edge 冷启动到页面加载完可能要好几秒，标题也不是一开始就叫 HIDCircus，
    所以要给足启动宽限，并且连续几次都找不到才算真的关了。
    """
    deadline = time.time() + 90
    while time.time() < deadline and not _stop.is_set():
        if windows_with_title(APP_NAME):
            break
        _stop.wait(2)
    misses = 0
    while not _stop.is_set():
        if windows_with_title(APP_NAME):
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
    """主循环线程里执行队列里的动作（pystray 回调在它自己的线程）。"""
    while not _stop.is_set():
        try:
            _ui_queue.get(timeout=0.2)()
        except queue.Empty:
            pass
        except Exception:
            log("托盘动作异常: " + traceback.format_exc())


# ---------- 入口 ----------

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
    print(f"HTTP 面板: http://{HOST}:{port}")

    threading.Thread(target=pump, daemon=True).start()

    # 托盘
    tray_ok = False
    try:
        _root_icon = pystray.Icon(
            "hidcircus", make_icon(None), APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("打开面板", on_open, default=True),
                pystray.MenuItem("刷新电量", on_refresh),
                pystray.MenuItem("退出", quit_app),
            ),
        )
        _root_icon.run_detached()
        time.sleep(1.2)
        tray_ok = bool(getattr(_root_icon, "_hwnd", None))
        STATUS["tray"] = tray_ok
        log("托盘已就绪" if tray_ok else "托盘未建立（_hwnd 为空）")
    except Exception:
        log("托盘不可用: " + traceback.format_exc())
        _root_icon = None
        tray_ok = False
        STATUS["tray"] = False

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
