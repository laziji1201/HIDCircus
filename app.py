"""HIDCircus 桌面入口。

形态：托盘常驻 + tkinter 原生主窗口。
- 托盘图标实时显示当前最低电量
- 左键点托盘 -> 打开主面板
- 右键菜单 -> 打开面板 / 刷新 / 退出
- 关闭窗口时隐藏而非退出，托盘继续常驻
- 若当前环境不允许托盘，则直接显示主窗口、关闭即退出

线程模型：Tk 只能在主线程操作。托盘回调跑在 pystray 自己的线程里，
所以它们只往队列里塞一个函数，由主线程的 _pump 取出执行。
"""

import queue
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont
import tkinter as tk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server import create_server, collect_devices, HOST
from ui import HIDCircusUI

APP_NAME = "HIDCircus"
POLL_INTERVAL = 30
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"

_root = None
_icon = None
_ui = None
_ui_queue = queue.Queue()


def make_icon(battery):
    """托盘图标：圆环 + 电量数字，按低电量变色"""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if battery is None:
        color, text = (139, 147, 167), "--"
    else:
        color = (61, 220, 132) if battery > 50 else (
            (255, 176, 32) if battery > 20 else (255, 92, 92))
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
    """按当前电量刷新托盘图标与提示"""
    if _icon is None:
        return None
    values = [d["battery"] for d in collect_devices(force=force)
              if d.get("battery") is not None]
    low = min(values) if values else None
    _icon.icon = make_icon(low)
    _icon.title = (f"{APP_NAME} — {low}%" if low is not None
                   else f"{APP_NAME} — 无设备")
    return low


def poll(interval=POLL_INTERVAL):
    """后台轮询电量，刷新托盘图标"""
    while True:
        try:
            update_tray()
        except Exception:
            pass
        time.sleep(interval)


def show_window():
    if _root is None:
        return
    _root.deiconify()
    _root.lift()
    _root.attributes("-topmost", True)
    _root.after(300, lambda: _root.attributes("-topmost", False))


def hide_window():
    if _root is not None:
        _root.withdraw()


def _pump():
    """主线程定时取出托盘线程投递的动作并执行"""
    try:
        while True:
            _ui_queue.get_nowait()()
    except queue.Empty:
        pass
    except Exception:
        pass
    if _root is not None:
        _root.after(100, _pump)


def on_tray_open(icon=None, item=None):
    _ui_queue.put(show_window)


def on_tray_refresh(icon=None, item=None):
    def run():
        update_tray(force=True)
        if _ui is not None:
            _ui.refresh()
    _ui_queue.put(run)


def quit_app(icon=None, item=None):
    def run():
        if _root is not None:
            _root.destroy()

    if icon is not None:
        icon.stop()
    _ui_queue.put(run)


def main():
    global _root, _icon, _ui

    # 本地 API 服务（浏览器也能直接访问）
    server, port = create_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"HTTP 面板: http://{HOST}:{port}")

    _root = tk.Tk()
    _ui = HIDCircusUI(_root, api_url=f"http://{HOST}:{port}")
    _root.after(100, _pump)

    # 托盘（当前环境可能不允许 UI 操作，失败则退化为直接显示窗口）
    tray_ok = False
    tray_error = []

    def _thread_hook(args):
        tray_error.append(args.exc_value)

    threading.excepthook = _thread_hook
    try:
        _icon = pystray.Icon(
            "hidcircus", make_icon(None), APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("打开面板", on_tray_open, default=True),
                pystray.MenuItem("刷新", on_tray_refresh),
                pystray.MenuItem("退出", quit_app),
            ),
        )
        _icon.run_detached()
        time.sleep(1.2)
        # pystray 内部线程抛异常时 _hwnd 可能已赋值，必须另外检查异常
        tray_ok = bool(getattr(_icon, "_hwnd", None)) and not tray_error
        if not tray_ok:
            _icon = None
    except Exception as e:
        print(f"托盘不可用: {e}")
        _icon = None
    finally:
        threading.excepthook = threading.__excepthook__ if hasattr(
            threading, "__excepthook__") else threading.excepthook

    if tray_ok:
        _root.protocol("WM_DELETE_WINDOW", hide_window)
    else:
        _root.protocol("WM_DELETE_WINDOW", quit_app)

    if _icon is not None:
        threading.Thread(target=poll, daemon=True).start()

    _root.mainloop()


if __name__ == "__main__":
    main()
