
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Device:
    """面板展示用的统一设备模型"""
    id: str
    name: str
    vendor: str
    kind: str = "unknown"                                      
    battery: Optional[int] = None                   
    charging: Optional[bool] = None
    connected: bool = True
    note: str = ""                            
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
        return {"ok": False, "error": f"{self.LABEL} 暂不支持控制"}
