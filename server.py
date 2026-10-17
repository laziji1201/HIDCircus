"""HIDCircus —— 多厂商外设统一控制面板（本地服务）。

零云依赖：只在本机 127.0.0.1 起一个 HTTP 服务，供桌面外壳和浏览器共用。
所有设备通信都走 HID，不需要厂商软件常驻。
"""

import json
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import hid

from providers import build_providers

HOST = "127.0.0.1"
PORT = 8777

# PyInstaller onefile 会把资源解压到 _MEIPASS
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

PROVIDERS = build_providers(hid)


def create_server():
    return ThreadingHTTPServer((HOST, PORT), Handler)


def collect_devices():
    out = []
    for p in PROVIDERS:
        try:
            out.extend(d.to_dict() for d in p.scan())
        except Exception as e:  # 单个 provider 出错不影响其他
            out.append({"id": f"{p.VENDOR}:error", "name": p.LABEL,
                        "vendor": p.LABEL, "connected": False,
                        "note": f"扫描异常: {e}"})
    return out


def do_control(vendor, device_id, action, payload):
    for p in PROVIDERS:
        if p.VENDOR == vendor:
            return p.control(device_id, action, payload)
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
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"PeriDeck 已启动: http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
