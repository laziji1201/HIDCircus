"""HIDCircus —— 多厂商外设统一控制面板（本地服务）。

零云依赖：只在本机 127.0.0.1 起一个 HTTP 服务，桌面外壳（WebView2）和浏览器共用同一套页面。

注意并发：托盘线程、HTTP 请求线程都会调 collect_devices()。
同一个 HID 设备被两处同时打开会互相抢响应，所以扫描必须串行，并带一层
短时缓存把同一时刻的多次请求合并成一次真实扫描。
"""

import json
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

import hid

from providers import build_providers

HOST = "127.0.0.1"
PORT = 8777
PORT_TRIES = 8          # 端口被占用时依次往后试
CACHE_TTL = 2.0         # 秒，这个时间内重复请求复用上一次扫描结果
MAX_BACKGROUND = 12 * 1024 * 1024   # 背景图上限 12MB

# PyInstaller onefile 会把资源解压到 _MEIPASS
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
    DATA_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR
WEB_DIR = BASE_DIR / "web"
ASSET_DIR = BASE_DIR / "assets"
CONFIG_PATH = DATA_DIR / "config.json"
BACKGROUND_DIR = DATA_DIR / "assets" / "background"

PROVIDERS = build_providers(hid)

DEFAULT_SETTINGS = {
    "theme": "auto",        # auto | dark | light
    "language": "zh",       # zh | en
    "background": "",       # 背景图文件名，空字符串表示不使用
    "bg_dim": 0.72,         # 背景遮罩强度 0–0.95
    "bg_blur": 0,           # 背景模糊半径 0–24 px
    "refresh_seconds": 10,  # 自动刷新间隔
    "device_order": [],     # 用户拖拽出来的设备顺序（设备 id 列表）
    "palette": "silver",    # 配色预设 silver / amber / sakura / neon
    "motion": "auto",       # auto=跟随系统（关掉动画时少做位移） / on=始终开启动效
}

# 运行状态（app.py 启动后回填，供页面显示托盘是否可用）
STATUS = {"tray": None, "port": None, "log": "", "last_ping": 0.0}

# 页面发过来、由桌面壳（app.py）执行的请求：0 表示没有
UI_REQUESTS = {"panel": 0.0}

_scan_lock = threading.Lock()
_cache = {"at": 0.0, "devices": []}
_settings_lock = threading.Lock()


# ---------- 配置读写 ----------

def load_settings():
    data = dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k in DEFAULT_SETTINGS:
                    data[k] = v
    except (OSError, ValueError):
        pass
    return data


def save_settings(patch):
    """合并写入。先写临时文件再替换，避免写一半断电留下坏配置。"""
    with _settings_lock:
        data = load_settings()
        for k, v in (patch or {}).items():
            if k in DEFAULT_SETTINGS:
                data[k] = v
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(CONFIG_PATH)
        return data


# ---------- 设备扫描 ----------

def create_server():
    """依次尝试端口，返回 (server, 实际端口)。"""
    last_error = None
    for offset in range(PORT_TRIES):
        port = PORT + offset
        try:
            return LocalServer((HOST, port), Handler), port
        except OSError as e:
            last_error = e
            continue
    raise OSError(f"{PORT}–{PORT + PORT_TRIES - 1} 全部被占用: {last_error}")


def _scan_all():
    out = []
    for p in PROVIDERS:
        try:
            for d in p.scan():
                item = d.to_dict()
                item["vendor_key"] = p.VENDOR   # 稳定标识，客户端别靠显示名匹配
                out.append(item)
        except Exception as e:  # 单个 provider 出错不影响其他
            out.append({"id": f"{p.VENDOR}:error", "name": p.LABEL,
                        "vendor": p.LABEL, "vendor_key": p.VENDOR,
                        "connected": False, "note": f"扫描异常: {e}"})
    return out


def collect_devices(force=False):
    """枚举所有设备。串行执行 + 短时缓存，避免多线程抢 HID 句柄。"""
    now = time.time()
    if not force and now - _cache["at"] < CACHE_TTL:
        return [dict(d) for d in _cache["devices"]]
    with _scan_lock:
        now = time.time()
        if not force and now - _cache["at"] < CACHE_TTL:
            return [dict(d) for d in _cache["devices"]]
        devices = _scan_all()
        _cache["devices"] = devices
        _cache["at"] = time.time()
    return [dict(d) for d in devices]


def do_control(vendor, device_id, action, payload):
    """执行控制写入。与扫描共用同一把锁，避免写入和扫描抢同一个 HID 句柄。"""
    with _scan_lock:
        for p in PROVIDERS:
            if p.VENDOR == vendor:
                result = p.control(device_id, action, payload)
                if result.get("ok"):
                    _cache["at"] = 0.0  # 状态变了，让下次读走真扫描
                return result
    return {"ok": False, "error": f"未知厂商: {vendor}"}


# ---------- HTTP ----------

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".woff2": "font/woff2",
}

IMAGE_EXT = {"image/png": ".png", "image/jpeg": ".jpg",
             "image/webp": ".webp", "image/gif": ".gif"}


def _debug_log(msg):
    """请求日志，只在 HIDCIRCUS_DEBUG=1 时写（排查"浏览器到底连没连上"用）。"""
    if os.environ.get("HIDCIRCUS_DEBUG") != "1":
        return
    try:
        p = DATA_DIR / "logs" / "requests.log"
        p.parent.mkdir(exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


class LocalServer(ThreadingHTTPServer):
    """本地 HTTP 服务。

    Windows 的 SO_REUSEADDR 语义和 Unix 不同：开着它时第二个进程能抢占同一端口，
    导致「端口被占用却以为自己绑上了」。所以 Windows 下关掉，让占用能被检测到，
    交给 create_server() 顺延端口。
    """
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"


class Handler(BaseHTTPRequestHandler):
    server_version = "HIDCircus"

    def log_message(self, *args):
        pass  # 静默访问日志

    # ----- 工具 -----

    def _send(self, body: bytes, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), status=status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else b""

    def _serve_index(self):
        """把主题/配色/语言注入 HTML，避免首帧闪一下再变。"""
        try:
            html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        except OSError:
            self._json({"error": "index.html missing"}, 500)
            return
        s = load_settings()
        prefs = {"theme": s.get("theme", "auto"),
                 "palette": s.get("palette", "silver"),
                 "language": s.get("language", "zh")}
        html = html.replace("__PREFS_JSON__", json.dumps(prefs))
        self._send(html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_file(self, path: Path):
        if not path.is_file():
            self._json({"error": "not found"}, 404)
            return
        ext = path.suffix.lower()
        self._send(path.read_bytes(),
                   CONTENT_TYPES.get(ext, "application/octet-stream"))

    def _safe_web_path(self, rel: str) -> Path:
        """只允许 web/ 下的文件，挡住 .. 穿越。"""
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
            return None
        return target

    # ----- GET -----

    def do_GET(self):
        route = urlparse(self.path).path
        _debug_log(f"GET {self.path} ua={self.headers.get('User-Agent', '-')[:40]}")

        if route in ("/", "/index.html"):
            self._serve_index()
            return
        if route == "/api/devices":
            self._json({"devices": collect_devices()})
            return
        if route == "/api/status":
            self._json(STATUS)
            return
        if route == "/api/settings":
            self._json(load_settings())
            return
        if route.startswith("/assets/background/"):
            name = Path(unquote(route.rsplit("/", 1)[-1])).name
            self._serve_file(BACKGROUND_DIR / name)
            return
        if route.startswith("/assets/"):
            rel = unquote(route[len("/assets/"):])
            target = (ASSET_DIR / rel).resolve()
            if ASSET_DIR.resolve() not in target.parents or not target.is_file():
                self._json({"error": "not found"}, 404)
                return
            self._serve_file(target)
            return
        if route.startswith("/web/"):
            target = self._safe_web_path(route[len("/web/"):])
            if target is None:
                self._json({"error": "forbidden"}, 403)
            else:
                self._serve_file(target)
            return
        self._json({"error": "not found"}, 404)

    # ----- 写入 -----

    def do_POST(self):
        route = urlparse(self.path).path
        _debug_log(f"POST {self.path}")
        raw = self._read_body()

        if route == "/api/control":
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._json({"ok": False, "error": "invalid json"}, 400)
                return
            self._json(do_control(body.get("vendor", ""), body.get("device_id", ""),
                                  body.get("action", ""), body.get("payload", {})))
            return

        if route == "/api/status":
            self._json(STATUS)
            return
        if route == "/api/settings":
            try:
                patch = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._json({"ok": False, "error": "invalid json"}, 400)
                return
            if not isinstance(patch, dict):
                self._json({"ok": False, "error": "expect object"}, 400)
                return
            self._json({"ok": True, "settings": save_settings(patch)})
            return

        if route == "/api/background":
            self._save_background(raw)
            return

        if route == "/api/panel":
            UI_REQUESTS["panel"] = time.time()
            self._json({"ok": True})
            return
        if route == "/api/ping":
            STATUS["last_ping"] = time.time()
            self._json({"ok": True})
            return

        if route == "/api/refresh":
            collect_devices(force=True)
            self._json({"ok": True})
            return

        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        route = urlparse(self.path).path
        if route == "/api/background":
            settings = load_settings()
            name = settings.get("background")
            if name:
                (BACKGROUND_DIR / Path(name).name).unlink(missing_ok=True)
            save_settings({"background": ""})
            self._json({"ok": True, "settings": load_settings()})
            return
        self._json({"error": "not found"}, 404)

    def _save_background(self, raw: bytes):
        """接收原始图片字节，存成固定文件名（只保留一张，省得堆垃圾）。"""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        ext = IMAGE_EXT.get(ctype)
        if ext is None:
            self._json({"ok": False, "error": f"不支持的图片类型: {ctype}"}, 400)
            return
        if not raw or len(raw) > MAX_BACKGROUND:
            self._json({"ok": False, "error": "图片为空或超过 12MB"}, 400)
            return
        BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)
        for old in BACKGROUND_DIR.iterdir():      # 旧图删掉
            if old.is_file():
                old.unlink(missing_ok=True)
        name = f"bg{ext}"
        (BACKGROUND_DIR / name).write_bytes(raw)
        settings = save_settings({"background": name})
        self._json({"ok": True, "settings": settings})


def main():
    server, port = create_server()
    print(f"HIDCircus 已启动: http://{HOST}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
