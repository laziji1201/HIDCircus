"""统一设备抽象层。

设计原则：
- 一个厂商一个 provider，核心不关心具体协议
- provider 只做两件事：发现问题设备、把协议翻译成统一语义
- 新增厂商 = 新增一个 provider 文件 + 在 registry 里注册一行
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Device:
    """面板展示用的统一设备模型"""
    id: str
    name: str
    vendor: str
    kind: str = "unknown"          # mouse / keyboard / headset
    battery: Optional[int] = None  # 0-100，None 表示未知
    charging: Optional[bool] = None
    connected: bool = True
    note: str = ""                 # 读取失败等补充说明
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "vendor": self.vendor,
            "kind": self.kind, "battery": self.battery,
            "charging": self.charging, "connected": self.connected,
            "note": self.note, "extra": self.extra,
        }


class Provider:
    """所有厂商 provider 的基类"""

    VENDOR = ""
    LABEL = ""

    def scan(self) -> list[Device]:
        """枚举该厂商当前连接的设备并读取状态"""
        raise NotImplementedError

    def control(self, device_id: str, action: str, payload: dict) -> dict:
        """执行一次控制写入。

        返回 {"ok": bool, "error": str}
        """
        return {"ok": False, "error": f"{self.LABEL} 暂不支持控制"}
