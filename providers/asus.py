"""ROG PELTA 耳机 provider。

协议来源：G-Helper（GPL-3.0）的观察结果；
本文件为独立实现，仅复现通信行为，未复制其代码。

控制接口：usage_page = 0xFF00，64 字节 output/input report
报文格式：[0xCC, 命令, 子命令, 0, 0, 数据...]
读取用 0x12 前缀，写入用 0x41 / 0x51 / 0x61 前缀。
"""

import time
from .base import Device, Provider

RID = 0xCC
PKT = 64


class AsusProvider(Provider):
    VENDOR = "asus"
    LABEL = "ASUS/ROG"

    # 已验证的型号：PELTA（有线/2.4G 共用 0x1B84）
    KNOWN = {
        0x1B84: "ROG PELTA",
    }

    def __init__(self, hid_module):
        self.hid = hid_module

    # ---------- 底层收发 ----------

    def _find_path(self, pid):
        for d in self.hid.enumerate(0x0B05, pid):
            if d.get("usage_page") == 0xFF00:
                return d["path"]
        return None

    def _open(self, path):
        h = self.hid.device()
        h.open_path(path)
        h.set_nonblocking(1)
        return h

    def _drain(self, h):
        while h.read(PKT):
            pass

    def _xfer(self, h, packet, timeout=0.8):
        pkt = bytearray(PKT)
        pkt[:len(packet)] = packet
        self._drain(h)
        h.write(bytes(pkt))
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = h.read(PKT)
            if not d:
                time.sleep(0.01)
                continue
            r = bytes(d)
            if len(r) > 2 and r[1] == 0xFF and r[2] == 0xAA:
                return None
            if len(r) > 2 and r[1] == packet[1] and r[2] == packet[2]:
                return r
        return None

    def _read(self, h, dev_id, cmd, sub):
        r = self._xfer(h, [RID, cmd, sub])
        return r

    # ---------- 对外接口 ----------

    def scan(self):
        devices = []
        for pid, name in self.KNOWN.items():
            path = self._find_path(pid)
            if not path:
                continue
            h = self._open(path)
            try:
                dev = Device(id=f"asus:{pid:04x}", name=name,
                             vendor=self.LABEL, kind="headset")
                if (r := self._read(h, dev.id, 0x12, 0x07)):
                    dev.battery = r[6]
                else:
                    dev.note = "电量读取无响应"
                if (r := self._read(h, dev.id, 0x12, 0x08)):
                    dev.charging = r[5] == 1
                # 灯效开关：0x12/0x13 的 resp[5] == 1 表示灯效开着
                # （真机验证：写 0x51/0x10 的 1 之后读回就是 1，写 0 读回 0）
                if (r := self._read(h, dev.id, 0x12, 0x13)):
                    dev.extra["lighting_on"] = r[5] == 1
                if (r := self._read(h, dev.id, 0x12, 0x03)):
                    dev.extra["lighting"] = {
                        "mode": r[5], "brightness": r[6],
                        "color": [r[7], r[8], r[9]],
                    }
                # 均衡器
                if (r := self._read(h, dev.id, 0x12, 0x21)):
                    dev.extra["eq"] = {"enabled": r[5] == 1,
                                       "gains": list(r[6:16])}
                # 降噪
                if (r := self._read(h, dev.id, 0x41, 0x20)):
                    dev.extra["noise_reduction"] = {"enabled": r[5] == 1,
                                                    "level": r[6]}
                devices.append(dev)
            finally:
                h.close()
        return devices

    def control(self, device_id, action, payload):
        pid = int(device_id.split(":")[1], 16)
        path = self._find_path(pid)
        if not path:
            return {"ok": False, "error": "设备未连接"}
        h = self._open(path)
        try:
            if action == "lighting":
                mode = payload.get("mode", 1)
                bright = payload.get("brightness", 100)
                color = payload.get("color", [255, 0, 0])
                pkt = [RID, 0x51, 0x28, 0, 0, mode, bright,
                       color[0], color[1], color[2]]
                return {"ok": self._xfer(h, pkt) is not None}
            if action == "lighting_off":
                return {"ok": self._xfer(h, [RID, 0x51, 0x10, 0, 0, 0]) is not None}
            if action == "lighting_on":
                return {"ok": self._xfer(h, [RID, 0x51, 0x10, 0, 0, 1]) is not None}
            if action == "eq_enabled":
                v = 1 if payload.get("enabled") else 0
                return {"ok": self._xfer(h, [RID, 0x41, 0x03, 0, 0, v]) is not None}
            if action == "eq_gains":
                gains = payload.get("gains", [12] * 10)
                ok = self._xfer(h, [RID, 0x41, 0x03, 0, 0, 1]) is not None
                time.sleep(0.1)
                ok = self._xfer(h, [RID, 0x41, 0x04, 0, 0] + list(gains[:10])) is not None and ok
                for band in range(len(gains)):
                    self._xfer(h, [RID, 0x41, 0x06, 0, 0, band, gains[band]])
                return {"ok": ok}
            if action == "noise_reduction":
                enabled = 1 if payload.get("enabled") else 0
                ok = self._xfer(h, [RID, 0x41, 0x02, 0, 0, enabled]) is not None
                level = payload.get("level", 0)
                self._xfer(h, [RID, 0x41, 0x10, 0, 0, level])
                return {"ok": ok}
            return {"ok": False, "error": f"未知动作: {action}"}
        finally:
            h.close()
