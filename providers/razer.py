"""雷蛇 provider（Viper V3 Pro 等 91 字节 feature report 设备）。

协议来源：OpenRazer / viper-tray 的公开观察结果；本文件为独立实现。

要点：
- 鼠标集合必须用 dwDesiredAccess=0 打开，绕过 mouclass 独占锁
- 报文 91 字节：[0]=report id, [1]=状态, [2]=事务ID, [7]=命令类, [8]=命令
- 电量命令：命令类 0x07 + 命令 0x80，结果在 arguments[1]（offset 10）
"""

import ctypes
from ctypes import wintypes as w

from .base import Device, Provider

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
HANDLE = ctypes.c_void_p

kernel32.CreateFileW.restype = HANDLE
kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, w.DWORD, w.DWORD,
                                 ctypes.c_void_p, w.DWORD, w.DWORD, HANDLE]
kernel32.CloseHandle.argtypes = [HANDLE]
hid.HidD_SetFeature.restype = w.BOOL
hid.HidD_SetFeature.argtypes = [HANDLE, ctypes.c_void_p, w.ULONG]
hid.HidD_GetFeature.restype = w.BOOL
hid.HidD_GetFeature.argtypes = [HANDLE, ctypes.c_void_p, w.ULONG]

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
OPEN_EXISTING = 3
SHARE_RW = 0x03
PKT = 91

STATUS = {0: "new", 1: "busy", 2: "success", 3: "failure", 4: "unsupported", 5: "timeout"}


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

    def _find_path(self, pid):
        for d in self.hid.enumerate(0x1532, pid):
            # 鼠标集合：usage_page 0x0001 / usage 0x0002
            if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0002:
                return d["path"]
        return None

    def _query(self, path, cmd_class, cmd_id, transaction=0x1F):
        if isinstance(path, bytes):
            path = path.decode("utf-8", "ignore")
        h = kernel32.CreateFileW(path, 0, SHARE_RW, None, OPEN_EXISTING, 0, None)
        if not h or h == INVALID_HANDLE_VALUE:
            return None, "无法打开设备"
        try:
            req = bytearray(PKT)
            req[0] = 0x00
            req[1] = 0x00
            req[2] = transaction
            req[6] = 0x00
            req[7] = cmd_class
            req[8] = cmd_id
            req[88] = _xor_crc(req[2:88])
            if not hid.HidD_SetFeature(h, bytes(req), PKT):
                return None, "SetFeature 失败"
            resp = ctypes.create_string_buffer(PKT)
            if not hid.HidD_GetFeature(h, resp, PKT):
                return None, "GetFeature 失败"
            return resp.raw, None
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
            resp, err = self._query(path, 0x07, 0x80)
            if resp is None:
                dev.note = err or "读取失败"
            else:
                status = resp[1]
                if status == 0x02:
                    dev.battery = round(resp[10] * 100 / 255)
                else:
                    dev.note = f"设备返回 {STATUS.get(status, hex(status))}（可能被 Synapse 占用）"
            devices.append(dev)
        return devices

    def control(self, device_id, action, payload):
        return {"ok": False, "error": "雷蛇控制项尚未实现（规划中）"}
