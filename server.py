"""HIDCircus —— 多厂商外设统一控制面板（本地服务）。

零云依赖：只在本机 127.0.0.1 起一个 HTTP 服务，桌面外壳（WebView2）和浏览器共用同一套页面。

注意并发：托盘线程、HTTP 请求线程都会调 collect_devices()。
同一个 HID 设备被两处同时打开会互相抢响应，所以扫描必须串行，并带一层
短时缓存把同一时刻的多次请求合并成一次真实扫描。
"""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

import hid

from providers import build_providers

HOST = "127.0.0.1"
PORT = int(os.environ.get("HIDCIRCUS_PORT", "8777"))   # 端口冲突时可用环境变量覆盖
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
# 扩展目录：用户自己写的适配文件放这里（打包后跟 exe 同级的 extensions/）
EXTENSION_DIRS = list(dict.fromkeys([DATA_DIR / "extensions",
                                    BASE_DIR / "extensions"]))

PROVIDERS = build_providers(hid, EXTENSION_DIRS)

DEFAULT_SETTINGS = {
    "theme": "auto",        # auto | dark | light
    "language": "zh",       # zh | en
    "background": "",       # 背景图文件名，空字符串表示不使用
    "bg_dim": 0.72,         # 背景遮罩强度 0–0.95
    "bg_blur": 0,           # 背景模糊半径 0–24 px
    "refresh_seconds": 10,  # 自动刷新间隔
    "device_order": [],     # 用户拖拽出来的设备顺序（设备 id 列表）
    "aliases": {},          # device_id -> 自定义名字
    "palette": "silver",    # 配色预设 silver / amber / sakura / neon
    "motion": "auto",       # auto=跟随系统（关掉动画时少做位移） / on=始终开启动效
}

# 运行状态（app.py 启动后回填，供页面显示托盘是否可用）
STATUS = {"tray": None, "port": None, "log": "", "last_ping": 0.0}

# 页面发过来、由桌面壳（app.py）执行的请求：0 表示没有
UI_REQUESTS = {"panel": 0.0}

# 本机随机 token：只有页面知道自己该带什么，别的程序随手调不了 /api/control。
# 注意它只防"顺手误调/顺手乱改"，不是网络级安全（服务只监听 127.0.0.1）。
SESSION_TOKEN = secrets.token_urlsafe(18)

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
    return _drop_duplicate_extensions(out)


def _drop_duplicate_extensions(devices):
    """内置 provider 已经认出的设备，不再被扩展重复报一份。

    内置型号 id 形如 `razer:00c1`（末尾是 product id），扩展设备的 extra 里带着
    自己的 pid。两者撞上就丢掉扩展那份，避免面板出现两台一模一样的设备。
    """
    from providers import EXTENSIONS
    builtin_pids = set()
    for d in devices:
        if (d.get("extra") or {}).get("extension"):
            continue
        tail = (d.get("id") or "").rsplit(":", 1)[-1]
        if len(tail) == 4:
            builtin_pids.add(tail.lower())

    kept = []
    for d in devices:
        info = (d.get("extra") or {}).get("extension")
        if not info:
            kept.append(d)
            continue
        ext = next((e for e in EXTENSIONS if e.id == info.get("id")), None)
        pids = {f"{p:04x}" for p in (ext.pids if ext else [])}
        if pids & builtin_pids:
            continue                     # 内置已经能读，扩展跳过
        kept.append(d)
    return kept


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
        _apply_aliases(devices)
        _cache["devices"] = devices
        _cache["at"] = time.time()
    return [dict(d) for d in devices]


def _apply_aliases(devices):
    """把用户起的名字套到设备上（改完后名称即别名，原厂名留在 raw_name）。"""
    aliases = load_settings().get("aliases") or {}
    for d in devices:
        d.setdefault("raw_name", d.get("name", ""))
        alias = aliases.get(d.get("id", ""))
        if alias:
            d["name"] = alias


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

    def _send(self, body: bytes, content_type="application/json", status=200,
              extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
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
        # 页面拿这个 token 才能调写入接口，别的本机程序读不到它
        html = html.replace("__SESSION_TOKEN__", SESSION_TOKEN)
        self._send(html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_file(self, path: Path):
        if not path.is_file():
            self._json({"error": "not found"}, 404)
            return
        ext = path.suffix.lower()
        self._send(path.read_bytes(),
                   CONTENT_TYPES.get(ext, "application/octet-stream"))

    def _require_token(self) -> bool:
        """写入类接口要求 token；不对就回 403。"""
        if self.headers.get("X-HIDCircus-Token") == SESSION_TOKEN:
            return True
        self._json({"ok": False, "error": "unauthorized"}, 403)
        return False

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
        if route == "/api/autostart":
            self._json({"enabled": autostart_enabled()})
            return
        if route.startswith("/api/extensions/export"):
            self._export_extension(route)
            return
        if route == "/api/hid-report":
            self._hid_report()
            return
        if route == "/api/extensions":
            from providers import EXTENSIONS, EXTENSION_ERRORS
            self._json({
                "dirs": [str(d) for d in EXTENSION_DIRS],
                "loaded": [e.to_dict() for e in EXTENSIONS],
                "errors": EXTENSION_ERRORS,
            })
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

        # ping 不校验（心跳要简单可靠），其余写入接口都要
        if route != "/api/ping" and not self._require_token():
            return

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
            aliases = patch.get("aliases")
            if aliases is not None:
                if not isinstance(aliases, dict):
                    self._json({"ok": False, "error": "aliases 必须是对象"}, 400)
                    return
                # 只保留 "字符串键 -> 短字符串值"，防止塞进奇怪的东西
                patch["aliases"] = {str(k)[:64]: str(v)[:24]
                                    for k, v in aliases.items() if v}
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

        if route == "/api/autostart":
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._json({"ok": False, "error": "invalid json"}, 400)
                return
            result = set_autostart(bool(body.get("on")))
            self._json(result)
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

    def _export_extension(self, route):
        """把某个扩展的原始 JSON 原样吐出来，前端直接下载。"""
        from urllib.parse import parse_qs
        from providers import EXTENSIONS
        query = parse_qs(urlparse(self.path).query)
        ext_id = (query.get("id") or [""])[0]
        ext = next((e for e in EXTENSIONS if e.id == ext_id), None)
        if ext is None:
            self._json({"error": "没有这个扩展"}, 404)
            return
        try:
            raw = ext.path.read_bytes()
        except OSError as e:
            self._json({"error": f"读不到文件: {e}"}, 500)
            return
        self._send(raw, "application/json; charset=utf-8", extra_headers={
            "Content-Disposition": f'attachment; filename="{ext.path.name}"'})

    def _hid_report(self):
        """枚举所有 HID 接口，产出给维护者看的探测报告。

        面对一台没适配的设备，用户点一下就能拿到这份 JSON 发给维护者：
        里面是接口列表（vid/pid/usage/产品名）+ 扩展模板骨架 + 环境信息。
        不包含任何读数尝试，避免向未知设备乱发报文。
        """
        from providers import EXTENSIONS
        entries = []
        try:
            for d in hid.enumerate():
                entries.append({
                    "vendor_id": f"0x{d.get('vendor_id', 0):04X}",
                    "product_id": f"0x{d.get('product_id', 0):04X}",
                    "usage_page": f"0x{d.get('usage_page', 0):04X}",
                    "usage": f"0x{d.get('usage', 0):04X}",
                    "interface_number": d.get("interface_number"),
                    "product_string": d.get("product_string") or "",
                    "manufacturer_string": d.get("manufacturer_string") or "",
                    "release_number": d.get("release_number"),
                })
        except Exception as e:
            self._json({"error": f"枚举失败: {e}"}, 500)
            return

        # 已经适配过的 vid/pid 标出来，方便维护者跳过
        covered = [f"0x{e.vid:04X}:" + "/".join(f"0x{p:04X}" for p in e.pids)
                   for e in EXTENSIONS]
        from providers import build_providers as _bp  # noqa: F401  (说明用，不调用)

        report = {
            "_what": "HIDCircus 设备探测报告，可发给维护者用于适配",
            "_version": 1,
            "generated_by": "HIDCircus /api/hid-report",
            "env": {"platform": sys.platform, "python": sys.version.split()[0]},
            "loaded_extensions": covered,
            "interfaces": entries,
            "draft": {
                "spec": 1,
                "id": "vendor-model",
                "name": "厂商 型号（电量）",
                "author": "你的名字",
                "match": {
                    "vid": "<从上面挑 usage_page=0xFF00 的那一行>",
                    "pid": ["<同一行的 product_id>"],
                    "usage_page": "0xFF00",
                },
                "device": {"name": "型号", "kind": "mouse",
                           "vendor_label": "厂商"},
                "read": {
                    "battery": {
                        "transport": "feature",
                        "report_id": "0x00",
                        "request": "",
                        "value": {"offset": 0, "size": 1},
                    }
                },
            },
        }
        body = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", extra_headers={
            "Content-Disposition": 'attachment; filename="hidcircus-hid-report.json"'})

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


def autostart_enabled():
    """计划任务是否存在（普通用户查询自己的任务不需要权限）。"""
    try:
        proc = subprocess.run(["schtasks", "/query", "/tn", "HIDCircus"],
                              capture_output=True, text=True, timeout=15,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.returncode == 0
    except Exception:
        return False


def set_autostart(enabled: bool):
    """注册/移除开机自启计划任务（调用 tools/setup.ps1）。

    普通用户权限就能注册"以当前用户身份运行"的任务，不需要管理员。
    """
    script = BASE_DIR / "tools" / "setup.ps1"
    if not script.exists():
        return {"ok": False, "error": "找不到 tools/setup.ps1"}
    mode = "install" if enabled else "uninstall"
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-Mode", mode],
            capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ok = proc.returncode == 0
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        detail = (proc.stderr or "").strip()
        message = lines[-1] if lines else (detail[:300] or "执行失败")
        if not ok and detail and detail not in message:
            message = f"{message} | {detail[:200]}"
        return {"ok": ok, "enabled": enabled, "message": message}
    except Exception as e:
        return {"ok": False, "error": f"执行失败: {e}"}


def main():
    server, port = create_server()
    print(f"HIDCircus 已启动: http://{HOST}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
