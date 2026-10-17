"""HIDCircus —— 多厂商外设统一控制面板（本地服务）。

零云依赖：只在本机 127.0.0.1 起一个 HTTP 服务，供桌面外壳和浏览器共用。
所有设备通信都走 HID，不需要厂商软件常驻。

注意并发：托盘线程、主窗口线程、HTTP 请求线程都会调 collect_devices()。
同一个 HID 设备被两处同时打开会互相抢响应，所以扫描必须串行，并带一层
短时缓存把同一时刻的多次请求合并成一次真实扫描。
"""

import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import hid

from providers import build_providers

HOST = "127.0.0.1"
PORT = 8777
PORT_TRIES = 8          # 端口被占用时依次往后试
CACHE_TTL = 2.0         # 秒，这个时间内重复请求复用上一次扫描结果

# PyInstaller onefile 会把资源解压到 _MEIPASS
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

PROVIDERS = build_providers(hid)

_scan_lock = threading.Lock()
_cache = {"at": 0.0, "devices": []}


class LocalServer(ThreadingHTTPServer):
    """本地 HTTP 服务。

    Windows 的 SO_REUSEADDR 语义和 Unix 不同：开着它时第二个进程能抢占同一端口，
    导致「端口被占用却以为自己绑上了」。所以 Windows 下关掉，让占用能被检测到，
    交给 create_server() 顺延端口。
    """
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"


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
        # 排队期间可能已经有别的线程扫完了
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 静默访问日志

    def _send(self, body: bytes, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            f = WEB_DIR / "index.html"
            self._send(f.read_bytes(), "text/html; charset=utf-8")
            return
        if self.path == "/api/devices":
            self._send(json.dumps({"devices": collect_devices()},
                                  ensure_ascii=False).encode())
            return
        self._send(b'{"error":"not found"}', status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(b'{"ok":false,"error":"invalid json"}', status=400)
            return
        if self.path == "/api/control":
            result = do_control(body.get("vendor", ""), body.get("device_id", ""),
                                body.get("action", ""), body.get("payload", {}))
            self._send(json.dumps(result, ensure_ascii=False).encode())
            return
        self._send(b'{"error":"not found"}', status=404)


def main():
    server, port = create_server()
    print(f"HIDCircus 已启动: http://{HOST}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
