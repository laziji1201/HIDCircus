"""雷蛇 provider（Viper V3 Pro 等使用 91 字节 feature report 的设备）。

协议来源：OpenRazer / viper-tray 等公开项目的观察结果；本文件为独立实现，
未复制其代码，仅复现通信行为。

要点（每条都是踩出来的，改代码前先看）：
- 鼠标集合必须用 dwDesiredAccess=0 打开，绕过 mouclass 的独占锁
- 只有「鼠标集合」（usage_page 0x0001 / usage 0x0002，通常是 MI_00）才带
  91 字节 feature report，其它集合的 feature 长度是 0
- 缓冲区第一字节是 report ID，真正的 90 字节报文从 buf[1] 开始：
    buf[1]  状态（请求填 0）
    buf[2]  事务 ID
    buf[3:5]  剩余包数
    buf[5]  协议类型
    buf[6]  数据长度 data_size
    buf[7]  命令类
    buf[8]  命令
    buf[9:89]  参数 80 字节
    buf[89] 校验（XOR）
- **校验是「对 buf[3:89] 做 XOR，结果写 buf[89]」**。写成 buf[2:88] 或写到
  buf[88]，设备会对每条命令都回 `0x03 failure`，看起来像被 Synapse 占用，
  实际上是自己算错了 CRC。
- 发完要等约 80ms 再 GetFeature，否则偶发读到上一次的响应。
"""

import ctypes
import time
from ctypes import wintypes as w

from .base import Device, Provider

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
hidlib = ctypes.WinDLL("hid", use_last_error=True)
HANDLE = ctypes.c_void_p

kernel32.CreateFileW.restype = HANDLE
kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, w.DWORD, w.DWORD,
                                 ctypes.c_void_p, w.DWORD, w.DWORD, HANDLE]
kernel32.CloseHandle.argtypes = [HANDLE]
hidlib.HidD_SetFeature.restype = w.BOOL
hidlib.HidD_SetFeature.argtypes = [HANDLE, ctypes.c_void_p, w.ULONG]
hidlib.HidD_GetFeature.restype = w.BOOL
hidlib.HidD_GetFeature.argtypes = [HANDLE, ctypes.c_void_p, w.ULONG]

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
OPEN_EXISTING = 3
SHARE_RW = 0x03
PKT = 91
DEFAULT_TXN = 0x1F
FEATURE_DELAY = 0.08

# 响应状态字节
ST_NEW, ST_BUSY, ST_SUCCESS, ST_FAILURE, ST_UNSUPPORTED, ST_TIMEOUT = range(6)
STATUS_TEXT = {
    ST_NEW: "new", ST_BUSY: "busy", ST_SUCCESS: "success",
    ST_FAILURE: "failure", ST_UNSUPPORTED: "unsupported", ST_TIMEOUT: "timeout",
}

# 电量 0–255 映射到 0–100 的分母
BATTERY_SCALE = 255

# 轮询率的编码是「反比位掩码」：码值 = 8000 / 频率
POLL_CODE = {8000: 0x01, 4000: 0x02, 2000: 0x04, 1000: 0x08, 500: 0x10, 125: 0x40}
POLL_BY_CODE = {v: k for k, v in POLL_CODE.items()}
DEFAULT_POLL_RATES = (125, 500, 1000, 2000, 4000, 8000)

# DPI 边界（该型号 35000）
DPI_MIN, DPI_MAX = 100, 35000


def _xor_crc(buf):
    c = 0
    for b in buf:
        c ^= b
    return c


class RazerProvider(Provider):
    VENDOR = "razer"
    LABEL = "Razer"

    KNOWN = {
        0x00C1: ("Viper V3 Pro", "mouse"),
    }

    def __init__(self, hid_module):
        self.hid = hid_module

    # ---------- 底层 ----------

    def _find_path(self, pid):
        """取带 91 字节 feature report 的鼠标集合。"""
        fallback = None
        for d in self.hid.enumerate(0x1532, pid):
            if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0002:
                # MI_00 才是真正承载 feature report 的那个，先记下再确认
                if d.get("interface_number") == 0:
                    return d["path"]
                fallback = fallback or d["path"]
        return fallback

    def _open(self, path):
        if isinstance(path, bytes):
            path = path.decode("utf-8", "ignore")
        h = kernel32.CreateFileW(path, 0, SHARE_RW, None, OPEN_EXISTING, 0, None)
        if not h or h == INVALID_HANDLE_VALUE:
            return None
        return h

    def _xfer(self, h, cmd_class, cmd_id, args=(), data_size=0, txn=DEFAULT_TXN):
        """发一条命令，返回 (状态码, 响应字节串)。状态不是 success 时字节串可能是 None。"""
        req = bytearray(PKT)
        req[2] = txn
        req[6] = data_size
        req[7] = cmd_class
        req[8] = cmd_id
        for i, a in enumerate(args):
            req[9 + i] = a & 0xFF
        req[89] = _xor_crc(req[3:89])

        if not hidlib.HidD_SetFeature(h, bytes(req), PKT):
            return ST_FAILURE, None
        time.sleep(FEATURE_DELAY)
        resp = ctypes.create_string_buffer(PKT)
        if not hidlib.HidD_GetFeature(h, resp, PKT):
            return ST_FAILURE, None
        raw = resp.raw
        return raw[1], raw

    def _read(self, h, cmd_class, cmd_id, args=(), data_size=0, retries=2):
        """只读命令，忙时重试；返回响应参数区的前若干字节，失败返回 None。"""
        for attempt in range(retries):
            status, raw = self._xfer(h, cmd_class, cmd_id, args, data_size)
            if status == ST_SUCCESS:
                return raw
            if status != ST_BUSY:
                break
            time.sleep(0.05 * (attempt + 1))
        return None

    # ---------- 对外接口 ----------

    def _all_pids(self):
        pids = []
        for d in self.hid.enumerate(0x1532):
            if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0002 \
                    and d["product_id"] not in pids:
                pids.append(d["product_id"])
        return pids

    def _probe_unknown(self, pid):
        """91 字节报文协议在雷蛇各型号间基本一致，逐项试探。"""
        path = self._find_path(pid)
        if not path:
            return None
        h = self._open(path)
        if h is None:
            return None
        try:
            name = None
            for d in self.hid.enumerate(0x1532, pid):
                name = (d.get("product_string") or "").strip() or name
            dev = Device(id=f"razer:{pid:04x}", name=name or f"Razer {pid:04x}",
                         vendor=self.LABEL, kind="unknown")
            self._fill(h, dev)          # 电量/充电/DPI/轮询率，能读到的都会填上
            if dev.battery is None and not dev.extra.get("dpi"):
                dev.note = "该型号尚未适配，读不到电量"
            return dev
        finally:
            kernel32.CloseHandle(h)

    def scan(self):
        devices = []
        for pid, (name, kind) in self.KNOWN.items():
            path = self._find_path(pid)
            if not path:
                continue
            dev = Device(id=f"razer:{pid:04x}", name=name,
                         vendor=self.LABEL, kind=kind)
            devices.append(dev)
            h = self._open(path)
            if h is None:
                dev.note = "设备被占用，无法打开"
                continue
            try:
                self._fill(h, dev)
            finally:
                kernel32.CloseHandle(h)
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

    def _fill(self, h, dev):
        # 电量：0x07/0x80，参数 [0,0]，结果在 arguments[1]
        raw = self._read(h, 0x07, 0x80, (0x00, 0x00), 0x02)
        if raw is None:
            dev.note = "电量读取被拒（设备忙或固件不支持）"
            return
        value = raw[10]
        if 0 < value <= BATTERY_SCALE:
            dev.battery = round(value * 100 / BATTERY_SCALE)

        # 充电状态：0x07/0x84，arguments[1] == 1 表示充电中
        raw = self._read(h, 0x07, 0x84, (0x00, 0x00), 0x02)
        if raw is not None:
            dev.charging = raw[10] == 1

        # DPI：0x04/0x85，arguments[1..2] 是 X，arguments[3..4] 是 Y（16 位大端）
        raw = self._read(h, 0x04, 0x85, (0x00,) * 7, 0x07)
        if raw is not None:
            dev.extra["dpi"] = {
                "x": (raw[10] << 8) | raw[11],
                "y": (raw[12] << 8) | raw[13],
            }

        # 轮询率：0x00/0xC0，arguments[1] 是反比位掩码，不是频率本身
        raw = self._read(h, 0x00, 0xC0, (0x00,), 0x01)
        if raw is not None:
            dev.extra["poll_rate"] = POLL_BY_CODE.get(raw[10])

        dev.extra["poll_rates"] = list(DEFAULT_POLL_RATES)
        dev.extra["dpi_max"] = DPI_MAX

    # ---------- 控制 ----------

    def control(self, device_id, action, payload):
        try:
            pid = int(device_id.split(":")[1], 16)
        except (IndexError, ValueError):
            return {"ok": False, "error": f"设备 ID 格式不对: {device_id}"}
        path = self._find_path(pid)
        if not path:
            return {"ok": False, "error": "设备未连接"}
        h = self._open(path)
        if h is None:
            return {"ok": False, "error": "设备被占用，无法打开"}
        try:
            if action == "dpi":
                return self._set_dpi(h, payload)
            if action == "poll_rate":
                return self._set_poll_rate(h, payload)
            return {"ok": False, "error": f"未知动作: {action}"}
        finally:
            kernel32.CloseHandle(h)

    def _set_dpi(self, h, payload):
        try:
            x = int(payload.get("x", 0))
            y = int(payload.get("y", x))
        except (TypeError, ValueError):
            return {"ok": False, "error": "DPI 必须是整数"}
        if not (DPI_MIN <= x <= DPI_MAX and DPI_MIN <= y <= DPI_MAX):
            return {"ok": False,
                    "error": f"DPI 必须在 {DPI_MIN}–{DPI_MAX} 之间"}
        args = [0x00, (x >> 8) & 0xFF, x & 0xFF, (y >> 8) & 0xFF, y & 0xFF, 0x00, 0x00]
        status, _ = self._xfer(h, 0x04, 0x05, args, 0x07)
        if status != ST_SUCCESS:
            return {"ok": False, "error": f"写入被拒（{STATUS_TEXT.get(status, status)}）"}
        return {"ok": True, "x": x, "y": y}

    def _set_poll_rate(self, h, payload):
        try:
            hz = int(payload.get("hz", 0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "轮询率必须是整数"}
        code = POLL_CODE.get(hz)
        if code is None:
            return {"ok": False,
                    "error": f"不支持的轮询率: {hz}（可选 {sorted(POLL_CODE, reverse=True)}）"}
        # 该型号要连发两次，arguments[0] 分别是 0x00 和 0x01
        for flag in (0x00, 0x01):
            status, _ = self._xfer(h, 0x00, 0x40, [flag, code], 0x02)
            if status != ST_SUCCESS:
                return {"ok": False,
                        "error": f"写入被拒（{STATUS_TEXT.get(status, status)}）"}
        return {"ok": True, "hz": hz}
