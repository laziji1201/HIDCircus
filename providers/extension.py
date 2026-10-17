"""扩展系统：用声明式 JSON 描述一台设备怎么读、怎么写。

为什么做成 JSON 而不是插件代码：
- **安全**：加载扩展不会执行任何代码，只解析固定字段；写错最多读不到，不会乱发报文
- **可协作**：有设备的用户（或他的 agent）照着协议填 JSON 就能适配，不需要懂 Python
- **可审查**：一条扩展就是一个文件，能直接看、能贴进 issue

支持的传输方式（够覆盖常见外设）：
- `feature`：发一个 HID feature report，读回响应，按偏移取值（ASUS / 罗技一类的 0xCC、0x51 报文）
- `razer`：91 字节雷蛇报文（自动补 XOR 校验）
- `output`：发 HID output report（少数设备用）

扩展文件放在 `extensions/*.json`；打包后放 `数据目录/extensions/`。
"""

import json
import time
from pathlib import Path

from .base import Device, Provider

SPEC_VERSION = 1
PKT_DEFAULT = 64
RAZER_PKT = 91


# ---------------------------------------------------------------- 解析工具

def _as_int(value, default=None):
    """接受 12 / "12" / "0x0C" / "0x0C 0x00" 这类写法，取第一个数。"""
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)):
        return _as_int(value[0], default) if value else default
    text = str(value).strip()
    for token in text.replace(",", " ").split():
        try:
            return int(token, 0)
        except ValueError:
            continue
    return default


def _as_bytes(value):
    """把 "0x51 0x28 0x00" / "51 28 00" / [0x51, 0x28] 统一成 bytes。"""
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, (list, tuple)):
        return bytes(int(v) & 0xFF for v in value)
    tokens = str(value).replace(",", " ").split()
    out = bytearray()
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token, 16 if token.lower().startswith("0x") else 10) & 0xFF)
        except ValueError:
            return bytes(out)
    return bytes(out)


def _template(template, values):
    """把 "0x51 0x28 {value}" 里的 {name} 换成数字（支持 le16/le32）。"""
    if not template:
        return b""
    data = bytearray()
    for token in str(template).replace(",", " ").split():
        low = token.lower()
        if low.startswith("{") and low.endswith("}"):
            key = low[1:-1]
            width, _, name = key.partition(":")
            width = width or "u8"
            raw = values.get(name, 0)
            try:
                num = int(raw)
            except (TypeError, ValueError):
                num = 0
            if width == "le16":
                data += (num & 0xFFFF).to_bytes(2, "little")
            elif width == "le32":
                data += (num & 0xFFFFFFFF).to_bytes(4, "little")
            else:
                data.append(num & 0xFF)
        else:
            data += _as_bytes(token)
    return bytes(data)


def _extract(report, rule):
    """按 {offset, size, scale, equals, map_...} 从响应里取一个值。"""
    if not isinstance(rule, dict) or not report:
        return None
    offset = _as_int(rule.get("offset"), 0)
    if offset < 0 or offset >= len(report):
        return None
    size = max(1, min(4, _as_int(rule.get("size"), 1)))
    chunk = report[offset:offset + size]
    if len(chunk) < size:
        return None
    value = int.from_bytes(chunk, "little")

    if "equals" in rule:
        want = _as_int(rule.get("equals"))
        return value == want

    scale = rule.get("scale", 1)
    try:
        value = value * float(scale)
    except (TypeError, ValueError):
        pass
    if rule.get("round", True):
        value = round(value)
    lo = rule.get("min")
    hi = rule.get("max")
    if lo is not None:
        value = max(_as_int(lo, value), value)
    if hi is not None:
        value = min(_as_int(hi, value), value)
    return value


# ---------------------------------------------------------------- 校验

def validate(data: dict, path: Path | None = None) -> list[str]:
    """返回错误列表，空列表表示可用。字段缺失都给出人能看懂的说明。"""
    errors = []
    where = f"{path.name}: " if path else ""

    if not isinstance(data, dict):
        return [f"{where}顶层必须是对象"]

    version = data.get("spec", SPEC_VERSION)
    if version not in (1, "1"):
        errors.append(f"{where}不支持的 spec 版本: {version}（当前只支持 1）")

    for key in ("id", "name"):
        if not data.get(key):
            errors.append(f"{where}缺少必填字段 {key}")

    match = data.get("match")
    if not isinstance(match, dict) or _as_int(match.get("vid")) is None:
        errors.append(f"{where}match.vid 必填（厂商号，例如 \"0x046D\"）")
    else:
        pids = match.get("pid")
        if isinstance(pids, list):
            if not pids:
                errors.append(f"{where}match.pid 列表不能为空")
        elif _as_int(pids) is None:
            errors.append(f"{where}match.pid 必填（产品号，可以是数组）")

    read = data.get("read") or {}
    if read and not isinstance(read, dict):
        errors.append(f"{where}read 必须是对象")
    for kind, rule in (read or {}).items():
        if not isinstance(rule, dict):
            errors.append(f"{where}read.{kind} 必须是对象")
            continue
        transport = rule.get("transport", "feature")
        if transport not in ("feature", "output", "razer"):
            errors.append(f"{where}read.{kind}.transport 不支持: {transport}")
            continue
        if transport == "razer":
            # 雷蛇要 5 字节命令头
            if not rule.get("command"):
                errors.append(f"{where}read.{kind} 用 razer 传输时必须给 command")
        elif not rule.get("request") and not rule.get("report_id"):
            errors.append(f"{where}read.{kind} 至少要给 request 或 report_id")
        if "value" not in rule and "equals" not in rule:
            errors.append(f"{where}read.{kind} 需要 value（取值规则）或 equals（布尔判断）")

    write = data.get("write") or {}
    if write and not isinstance(write, dict):
        errors.append(f"{where}write 必须是对象")
    for name, rule in (write or {}).items():
        if not isinstance(rule, dict):
            errors.append(f"{where}write.{name} 必须是对象")
            continue
        if not (rule.get("request") or rule.get("command")):
            errors.append(f"{where}write.{name} 缺少 request/command 模板")
        control = rule.get("control")
        if control is not None:
            if not isinstance(control, dict):
                errors.append(f"{where}write.{name}.control 必须是对象")
            elif control.get("type") not in ("button", "number"):
                errors.append(f"{where}write.{name}.control.type 只能是 button / number")

    return errors


def _controls_of(ext):
    """把 write 里的 control 声明整理成前端好渲染的结构。"""
    out = []
    for action, rule in ext.write_spec.items():
        control = rule.get("control")
        if not isinstance(control, dict):
            continue
        item = {
            "action": action,
            "type": control.get("type", "button"),
            "group": control.get("group") or action,
            "label": control.get("label") or action,
            "value": control.get("value"),
            "fields": control.get("fields") or [],
            "min": control.get("min"),
            "max": control.get("max"),
            "default": control.get("default"),
        }
        out.append(item)
    return out


# ---------------------------------------------------------------- 运行时

class Extension:
    """一份加载好的扩展。"""

    def __init__(self, data: dict, path: Path):
        self.path = path
        self.data = data
        self.id = str(data.get("id"))
        self.name = str(data.get("name"))
        self.author = str(data.get("author") or "")
        self.match = data.get("match") or {}
        self.device = data.get("device") or {}
        self.read_spec = data.get("read") or {}
        self.write_spec = data.get("write") or {}

    @property
    def vendor_label(self):
        return str(self.device.get("vendor_label") or "扩展")

    @property
    def vid(self):
        return _as_int(self.match.get("vid"), 0)

    @property
    def pids(self):
        raw = self.match.get("pid")
        if isinstance(raw, list):
            return [_as_int(p, 0) for p in raw]
        return [_as_int(raw, 0)]

    def matches(self, entry: dict) -> bool:
        if entry.get("vendor_id") != self.vid:
            return False
        if entry.get("product_id") not in self.pids:
            return False
        page = self.match.get("usage_page")
        if page is not None and _as_int(entry.get("usage_page")) != _as_int(page):
            return False
        usage = self.match.get("usage")
        if usage is not None and _as_int(entry.get("usage")) != _as_int(usage):
            return False
        return True

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "author": self.author,
            "vid": f"0x{self.vid:04X}", "pids": [f"0x{p:04X}" for p in self.pids],
            "vendor": self.vendor_label,
            "reads": sorted(self.read_spec.keys()),
            "writes": sorted(self.write_spec.keys()),
            "file": self.path.name,
        }


class ExtensionProvider(Provider):
    """把加载到的扩展当成一个 provider：按 vid/pid 匹配，按 JSON 读写。"""

    VENDOR = "extension"
    LABEL = "扩展"

    def __init__(self, hid_module, extensions):
        self.hid = hid_module
        self.extensions = extensions

    # ---------- 收发 ----------

    def _open(self, path, transport):
        if transport == "razer":
            import ctypes
            from ctypes import wintypes as w
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateFileW.restype = ctypes.c_void_p
            handle = kernel32.CreateFileW(path, 0xC0000000, 0x3, None, 0x3, 0, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                return None, kernel32
            return handle, kernel32
        h = self.hid.device()
        h.open_path(path)
        h.set_nonblocking(1)
        return h, None

    def _close(self, handle, kernel32):
        if kernel32 is not None:
            kernel32.CloseHandle(handle)
        else:
            handle.close()

    def _drain(self, h):
        while h.read(PKT_DEFAULT):
            pass

    def _xfer(self, h, packet, transport, read_size=PKT_DEFAULT, timeout=0.8):
        if transport == "razer":
            # 雷蛇：91 字节，CRC 落在 [89]，前面是 [0, 命令, sub, ...]
            buf = bytearray(RAZER_PKT)
            cmd = _as_bytes(packet)[:5]
            buf[:len(cmd)] = cmd
            crc = 0
            for b in buf[3:89]:
                crc ^= b
            buf[89] = crc
            h.write(bytes(buf))
            deadline = time.time() + timeout
            while time.time() < deadline:
                data = h.read(RAZER_PKT)
                if not data:
                    time.sleep(0.01)
                    continue
                resp = bytes(data)
                if len(resp) >= 90 and resp[0] == 0x02:
                    return resp
            return None

        pkt = bytearray(read_size)
        raw = _as_bytes(packet)
        pkt[:len(raw)] = raw
        self._drain(h)
        if transport == "output":
            h.write(bytes(pkt))
        else:
            h.send_feature_report(bytes(pkt))
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = h.read(read_size)
            if not data:
                time.sleep(0.01)
                continue
            return bytes(data)
        return None

    # ---------- 扫描 ----------

    def _read_one(self, h, kind, rule, values):
        transport = rule.get("transport", "feature")
        if transport == "razer":
            req = _template(rule.get("command"), values)
        else:
            head = _as_bytes(rule.get("request"))
            rid = _as_int(rule.get("report_id"))
            req = (bytes([rid]) if rid is not None and (not head or head[0] != rid) else b"") + head
        resp = self._xfer(h, req, transport, _as_int(rule.get("read_size"), PKT_DEFAULT))
        if resp is None:
            return None, "无响应"
        check = rule.get("reply_check")
        if isinstance(check, dict):
            got = _extract(resp, check)
            if got is not True:
                return None, "响应不匹配"
        # 取值规则在 value 里；个别扩展把 offset 直接写在规则上，也兼容一下
        value_rule = rule.get("value")
        if not isinstance(value_rule, dict):
            value_rule = {k: rule[k] for k in ("offset", "size", "scale",
                                               "round", "min", "max", "equals")
                          if k in rule}
        value = _extract(resp, value_rule)
        return value, ""

    def scan(self):
        if not self.extensions:
            return []
        devices = []
        seen = set()
        for entry in self.hid.enumerate():
            ext = next((e for e in self.extensions if e.matches(entry)), None)
            if ext is None or ext.id in seen:
                continue
            seen.add(ext.id)
            devices.append(self._probe(ext, entry))
        return devices

    def _probe(self, ext, entry):
        dev = Device(id=f"ext:{ext.id}", name=ext.device.get("name") or ext.name,
                     vendor=ext.vendor_label, kind=ext.device.get("kind", "unknown"))
        dev.extra["extension"] = {"id": ext.id, "name": ext.name,
                                  "file": ext.path.name,
                                  "writes": sorted(ext.write_spec.keys()),
                                  "controls": _controls_of(ext)}
        if not ext.read_spec:
            dev.note = "扩展未定义读取项"
            return dev

        transport = next(iter(ext.read_spec.values())).get("transport", "feature")
        handle, kernel32 = self._open(entry["path"], transport)
        if handle is None:
            dev.connected = False
            dev.note = "打不开设备"
            return dev
        try:
            problems = []
            for kind, rule in ext.read_spec.items():
                value, why = self._read_one(handle, kind, rule, {})
                if value is None:
                    problems.append(f"{kind}{(':' + why) if why else ''}")
                    continue
                if kind == "battery":
                    dev.battery = int(value)
                elif kind == "charging":
                    dev.charging = bool(value)
                else:
                    dev.extra[kind] = value      # 其它状态放进 extra，面板上能看到
            if problems:
                dev.note = "未读到: " + ", ".join(problems)
        finally:
            try:
                self._close(handle, kernel32)
            except Exception:
                pass
        return dev

    # ---------- 控制 ----------

    def control(self, device_id: str, action: str, payload: dict) -> dict:
        ext_id = device_id.split(":", 1)[1] if ":" in device_id else device_id
        ext = next((e for e in self.extensions if e.id == ext_id), None)
        if ext is None:
            return {"ok": False, "error": f"没有扩展 {ext_id}"}
        rule = ext.write_spec.get(action)
        if not isinstance(rule, dict):
            return {"ok": False, "error": f"扩展 {ext_id} 没有动作 {action}"}

        entry = next((e for e in self.hid.enumerate() if ext.matches(e)), None)
        if entry is None:
            return {"ok": False, "error": "设备没插着"}

        template = rule.get("request") or rule.get("command")
        body = _template(template, payload or {})
        transport = rule.get("transport", "feature")
        data = body
        if transport != "razer":
            # 和读取一样，report_id 要拼在报文最前面（之前漏了这步，写入会被设备忽略）
            rid = _as_int(rule.get("report_id"))
            need = rid is not None and (not body or body[0] != rid)
            if need:
                data = bytes([rid]) + body
        handle, kernel32 = self._open(entry["path"], transport)
        if handle is None:
            return {"ok": False, "error": "打不开设备"}
        try:
            resp = self._xfer(handle, data, transport, _as_int(rule.get("read_size"), PKT_DEFAULT))
        finally:
            try:
                self._close(handle, kernel32)
            except Exception:
                pass
        if rule.get("expect_reply") and resp is None:
            return {"ok": False, "error": "设备没有响应"}
        return {"ok": True}


# ---------------------------------------------------------------- 加载

def load_extensions(*directories):
    """从若干目录加载 *.json，返回 (扩展列表, 错误列表)。"""
    extensions, errors = [], []
    seen = set()
    for directory in directories:
        if not directory:
            continue
        root = Path(directory)
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                errors.append(f"{path.name}: JSON 语法错误（第 {e.lineno} 行）: {e.msg}")
                continue
            except OSError as e:
                errors.append(f"{path.name}: 读不了（{e}）")
                continue
            problems = validate(data, path)
            if problems:
                errors.extend(problems)
                continue
            ext = Extension(data, path)
            if ext.id in seen:
                errors.append(f"{path.name}: id `{ext.id}` 重复，已跳过")
                continue
            seen.add(ext.id)
            extensions.append(ext)
    return extensions, errors
