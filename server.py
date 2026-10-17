
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
PORT = int(os.environ.get("HIDCIRCUS_PORT", "8777"))                  
PORT_TRIES = 8                       
CACHE_TTL = 2.0                               
MAX_BACKGROUND = 12 * 1024 * 1024               

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

EXTENSION_DIRS = list(dict.fromkeys([DATA_DIR / "extensions",
                                    BASE_DIR / "extensions"]))

PROVIDERS = build_providers(hid, EXTENSION_DIRS)

DEFAULT_SETTINGS = {
    "theme": "auto",                             
    "language": "zh",                
    "background": "",                         
    "bg_dim": 0.72,                        
    "bg_blur": 0,                           
    "refresh_seconds": 10,          
    "device_order": [],                            
    "aliases": {},                              
    "palette": "silver",                                         
    "motion": "auto",                                         
}

VERSION = "1.2.0"
STATUS = {"tray": None, "port": None, "log": "", "last_ping": 0.0,
          "version": VERSION, "pid": os.getpid()}

UI_REQUESTS = {"panel": 0.0, "show": 0.0}

SESSION_TOKEN = secrets.token_urlsafe(18)

_scan_lock = threading.Lock()
_cache = {"at": 0.0, "devices": []}
_settings_lock = threading.Lock()

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

def create_server():
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
                item["vendor_key"] = p.VENDOR                    
                out.append(item)
        except Exception as e:                       
            out.append({"id": f"{p.VENDOR}:error", "name": p.LABEL,
                        "vendor": p.LABEL, "vendor_key": p.VENDOR,
                        "connected": False, "note": f"扫描异常: {e}"})
    return _drop_duplicate_extensions(out)

def _drop_duplicate_extensions(devices):
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
            continue                                  
        kept.append(d)
    return kept

def collect_devices(force=False):
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
    aliases = load_settings().get("aliases") or {}
    for d in devices:
        d.setdefault("raw_name", d.get("name", ""))
        alias = aliases.get(d.get("id", ""))
        if alias:
            d["name"] = alias

def do_control(vendor, device_id, action, payload):
    with _scan_lock:
        for p in PROVIDERS:
            if p.VENDOR == vendor:
                result = p.control(device_id, action, payload)
                if result.get("ok"):
                    _cache["at"] = 0.0                 
                return result
    return {"ok": False, "error": f"未知厂商: {vendor}"}

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
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"

class Handler(BaseHTTPRequestHandler):
    server_version = "HIDCircus"

    def log_message(self, *args):
        pass          

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
        if self.headers.get("X-HIDCircus-Token") == SESSION_TOKEN:
            return True
        self._json({"ok": False, "error": "unauthorized"}, 403)
        return False

    def _safe_web_path(self, rel: str) -> Path:
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
            return None
        return target

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

    def do_POST(self):
        route = urlparse(self.path).path
        _debug_log(f"POST {self.path}")
        raw = self._read_body()

        if route not in ("/api/ping", "/api/show") and not self._require_token():
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
        if route == "/api/show":

            UI_REQUESTS["show"] = time.time()
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

        if route == "/api/extensions/open-dir":
            target = next((d for d in EXTENSION_DIRS if d.is_dir()), None)
            if target is None:
                self._json({"ok": False, "error": "扩展目录不存在"}, 404)
                return
            try:
                subprocess.Popen(["explorer.exe", str(target)])
                self._json({"ok": True, "dir": str(target)})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 500)
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

        covered = [f"0x{e.vid:04X}:" + "/".join(f"0x{p:04X}" for p in e.pids)
                   for e in EXTENSIONS]
        from providers import build_providers as _bp                         

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
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        ext = IMAGE_EXT.get(ctype)
        if ext is None:
            self._json({"ok": False, "error": f"不支持的图片类型: {ctype}"}, 400)
            return
        if not raw or len(raw) > MAX_BACKGROUND:
            self._json({"ok": False, "error": "图片为空或超过 12MB"}, 400)
            return
        BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)
        for old in BACKGROUND_DIR.iterdir():            
            if old.is_file():
                old.unlink(missing_ok=True)
        name = f"bg{ext}"
        (BACKGROUND_DIR / name).write_bytes(raw)
        settings = save_settings({"background": name})
        self._json({"ok": True, "settings": settings})

def autostart_enabled():
    try:
        proc = subprocess.run(["schtasks", "/query", "/tn", "HIDCircus"],
                              capture_output=True, text=True, timeout=15,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.returncode == 0
    except Exception:
        return False

def set_autostart(enabled: bool):
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
