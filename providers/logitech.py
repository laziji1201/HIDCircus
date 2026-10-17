
import time
from .base import Device, Provider

class LogitechProvider(Provider):
    VENDOR = "logitech"
    LABEL = "Logitech"

    KNOWN = {
        0xC352: ("PRO X TKL", "keyboard"),
    }

    def __init__(self, hid_module):
        self.hid = hid_module

    def _find(self, pid):
        short = long_ = None
        for d in self.hid.enumerate(0x046D, pid):
            if d.get("usage_page") == 0xFF00:
                if d.get("usage") == 0x01:
                    short = d["path"]
                elif d.get("usage") == 0x02:
                    long_ = d["path"]
        return short, long_

    def _open(self, path):
        h = self.hid.device()
        h.open_path(path)
        h.set_nonblocking(1)
        return h

    def _drain(self, h):
        while h.read(64):
            pass

    def _xfer(self, hs, hl, payload, dev_idx=0xFF, timeout=0.8):
        """短接口写，长接口读。返回响应字节串或 None。"""
        self._drain(hl)
        hs.write(bytes(payload))
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = hl.read(64)
            if not d:
                time.sleep(0.01)
                continue
            r = bytes(d)
            if len(r) >= 4 and r[1] == dev_idx and r[2] == payload[2] and r[3] == payload[3]:
                return r
        return None

    def _battery(self, hs, hl):
        """返回 (电量, 充电标志) 或 (None, None)"""
        r = self._xfer(hs, hl, [0x10, 0xFF, 0x00, 0x00, 0x10, 0x04, 0x00])
        if not r or len(r) < 5 or r[4] == 0:
            return None, None
        feat = r[4]
        s = self._xfer(hs, hl, [0x10, 0xFF, feat, 0x10, 0x00, 0x00, 0x00])
        if not s or len(s) < 6:
            return None, None
        return s[4], bool(s[5] & 0x01)

    def _all_pids(self):
        pids = []
        for d in self.hid.enumerate(0x046D):
            if d.get("usage_page") == 0xFF00 and d["product_id"] not in pids:
                pids.append(d["product_id"])
        return pids

    def _product_name(self, pid, fallback):
        for d in self.hid.enumerate(0x046D, pid):
            name = (d.get("product_string") or "").strip()
            if name:
                return name
        return fallback

    def _probe_unknown(self, pid):
        """HID++ 的电量 feature 0x1004 是跨型号通用的，先试探它。"""
        short, long_ = self._find(pid)
        if not short or not long_:
            return None
        hs, hl = self._open(short), self._open(long_)
        try:
            dev = Device(id=f"logitech:{pid:04x}",
                         name=self._product_name(pid, f"Logitech {pid:04x}"),
                         vendor=self.LABEL, kind="unknown")
            battery, charging = self._battery(hs, hl)
            if battery is None:
                dev.note = "该型号尚未适配，读不到电量"
            else:
                dev.battery = battery
                dev.charging = charging
            return dev
        finally:
            hs.close()
            hl.close()

    def scan(self):
        devices = []
        for pid, (name, kind) in self.KNOWN.items():
            short, long_ = self._find(pid)
            if not short or not long_:
                continue
            hs, hl = self._open(short), self._open(long_)
            try:
                dev = Device(id=f"logitech:{pid:04x}", name=name,
                             vendor=self.LABEL, kind=kind)
                battery, charging = self._battery(hs, hl)
                if battery is None:
                    dev.note = "HID++ 电量无响应（可能被 G HUB 占用）"
                else:
                    dev.battery = battery
                    dev.charging = charging
                devices.append(dev)
            finally:
                hs.close()
                hl.close()
        seen = set(self.KNOWN)
        for pid in self._all_pids():
            if pid in seen:
                continue
            try:
                dev = self._probe_unknown(pid)
            except Exception:
                dev = None
            if dev is not None:
                devices.append(dev)
        return devices

    def control(self, device_id, action, payload):
        return {"ok": False, "error": "罗技控制项尚未实现（规划中）"}
