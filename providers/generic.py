
import ctypes
from ctypes import wintypes as w

from .base import Device, Provider

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HANDLE = ctypes.c_void_p
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
SPDRP_DEVICEDESC = 0x00
SPDRP_FRIENDLYNAME = 0x0C

IOCTL_BATTERY_QUERY_TAG = 0x294040
IOCTL_BATTERY_QUERY_INFORMATION = 0x294044
IOCTL_BATTERY_QUERY_STATUS = 0x29404C

BATTERY_POWER_ON_LINE = 0x00000001
BATTERY_CHARGING = 0x00000008

class GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

GUID_DEVCLASS_BATTERY = GUID(0x72631E54, 0x78A4, 0x11D0,
                             (ctypes.c_ubyte * 8)(0xBC, 0xF7, 0x00, 0xAA, 0x00, 0xB7, 0xB3, 0x2A))

class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", w.DWORD), ("Reserved", ctypes.POINTER(w.DWORD))]

class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("DevicePath", w.WCHAR * 1024)]

class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("ClassGuid", GUID),
                ("DevInst", w.DWORD), ("Reserved", ctypes.c_void_p)]

class BATTERY_QUERY_INFORMATION(ctypes.Structure):
    _fields_ = [("BatteryTag", w.ULONG), ("InformationLevel", w.ULONG),
                ("AtRate", w.LONG)]

class BATTERY_INFORMATION(ctypes.Structure):
    _fields_ = [("Capabilities", w.ULONG), ("Technology", ctypes.c_ubyte),
                ("Reserved", ctypes.c_ubyte * 3), ("Chemistry", ctypes.c_ubyte * 4),
                ("DesignedCapacity", w.ULONG), ("FullChargedCapacity", w.ULONG),
                ("DefaultAlert1", w.ULONG), ("DefaultAlert2", w.ULONG),
                ("CriticalBias", w.ULONG), ("CycleCount", w.ULONG)]

class BATTERY_WAIT_STATUS(ctypes.Structure):
    _fields_ = [("BatteryTag", w.ULONG), ("Timeout", w.ULONG),
                ("PowerState", w.ULONG), ("LowCapacity", w.ULONG),
                ("HighCapacity", w.ULONG)]

class BATTERY_STATUS(ctypes.Structure):
    _fields_ = [("PowerState", w.ULONG), ("Capacity", w.ULONG),
                ("Voltage", w.ULONG), ("Rate", w.LONG)]

setupapi.SetupDiGetClassDevsW.restype = HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), w.LPCWSTR, w.HWND, w.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = w.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), w.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = w.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
    ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W), w.DWORD,
    ctypes.POINTER(w.DWORD), ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiGetDeviceRegistryPropertyW.restype = w.BOOL
setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), w.DWORD,
    ctypes.POINTER(w.DWORD), ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
setupapi.SetupDiDestroyDeviceInfoList.restype = w.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HANDLE]

kernel32.CreateFileW.restype = HANDLE
kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, w.DWORD, w.DWORD,
                                 ctypes.c_void_p, w.DWORD, w.DWORD, HANDLE]
kernel32.CloseHandle.argtypes = [HANDLE]
kernel32.DeviceIoControl.restype = w.BOOL
kernel32.DeviceIoControl.argtypes = [HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD,
                                     ctypes.c_void_p, w.DWORD,
                                     ctypes.POINTER(w.DWORD), ctypes.c_void_p]

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_RW = 0x03
OPEN_EXISTING = 3

def _ioctl(h, code, inbuf, insize, outbuf, outsize):
    ret = w.DWORD(0)
    ok = kernel32.DeviceIoControl(h, code, inbuf, insize, outbuf, outsize,
                                  ctypes.byref(ret), None)
    return ok and ret.value > 0

def _read_battery(path):
    """读一个电池设备，返回 (百分比, 是否充电) 或 None。"""
    h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_RW,
                             None, OPEN_EXISTING, 0, None)
    if not h or h == INVALID_HANDLE_VALUE:
        return None
    try:
        tag = w.ULONG(0)
        wait = w.ULONG(0)             
        if not _ioctl(h, IOCTL_BATTERY_QUERY_TAG, ctypes.byref(wait), 4,
                      ctypes.byref(tag), 4):
            return None
        if not tag.value:
            return None

        query = BATTERY_QUERY_INFORMATION(tag.value, 0, 0)                           
        info = BATTERY_INFORMATION()
        if not _ioctl(h, IOCTL_BATTERY_QUERY_INFORMATION, ctypes.byref(query),
                      ctypes.sizeof(query), ctypes.byref(info), ctypes.sizeof(info)):
            return None

        wait_status = BATTERY_WAIT_STATUS(tag.value, 0, 0, 0, 0)
        status = BATTERY_STATUS()
        if not _ioctl(h, IOCTL_BATTERY_QUERY_STATUS, ctypes.byref(wait_status),
                      ctypes.sizeof(wait_status), ctypes.byref(status),
                      ctypes.sizeof(status)):
            return None

        full = info.FullChargedCapacity or info.DesignedCapacity
        if not full:
            return None
        percent = round(status.Capacity * 100 / full)
        charging = bool(status.PowerState & (BATTERY_CHARGING | BATTERY_POWER_ON_LINE))
        return max(0, min(100, percent)), charging
    finally:
        kernel32.CloseHandle(h)

def _device_name(hdev, devinfo):
    buf = ctypes.create_unicode_buffer(256)
    needed = w.DWORD(0)
    for prop in (SPDRP_FRIENDLYNAME, SPDRP_DEVICEDESC):
        if setupapi.SetupDiGetDeviceRegistryPropertyW(
                hdev, ctypes.byref(devinfo), prop, None, buf,
                ctypes.sizeof(buf), ctypes.byref(needed)) and buf.value:
            return buf.value
    return ""

def _dump_battery_devices():
    """枚举系统里所有电池设备（调试用：确认过滤规则是否符合预期）。"""
    out = []
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(GUID_DEVCLASS_BATTERY), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev == INVALID_HANDLE_VALUE:
        return out
    try:
        index = 0
        while True:
            did = SP_DEVICE_INTERFACE_DATA()
            did.cbSize = ctypes.sizeof(did)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                    hdev, None, ctypes.byref(GUID_DEVCLASS_BATTERY), index,
                    ctypes.byref(did)):
                break
            index += 1
            detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
            detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            devinfo = SP_DEVINFO_DATA()
            devinfo.cbSize = ctypes.sizeof(devinfo)
            required = w.DWORD(0)
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                    hdev, ctypes.byref(did), ctypes.byref(detail),
                    ctypes.sizeof(detail), ctypes.byref(required),
                    ctypes.byref(devinfo)):
                continue
            out.append({"name": _device_name(hdev, devinfo),
                        "path": detail.DevicePath})
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out

class GenericBatteryProvider(Provider):
    """把 Windows 认得的"外设电池设备"作为设备列出来。"""

    VENDOR = "generic"
    LABEL = "其它设备"

    def __init__(self, hid_module):
        self.hid = hid_module

    def scan(self):
        devices = []
        for entry in _dump_battery_devices():
            name = entry["name"] or "未命名电池设备"
            path = entry["path"]

            if "ACPI" in name.upper() or "ACPI" in path.upper():
                continue
            reading = _read_battery(path)
            if reading is None:
                continue
            percent, charging = reading
            dev = Device(id=f"generic:{abs(hash(path)) & 0xFFFFFF:06x}",
                         name=name, vendor=self.LABEL, kind="unknown",
                         battery=percent, charging=charging,
                         note="通过系统电池接口读取，仅支持电量")
            devices.append(dev)
        return devices

    def control(self, device_id, action, payload):
        return {"ok": False, "error": "该设备只有系统电量，暂不支持控制"}
