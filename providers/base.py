
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Device:
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

    VENDOR = ""
    LABEL = ""

    def scan(self) -> list[Device]:
        raise NotImplementedError

    def control(self, device_id: str, action: str, payload: dict) -> dict:
        return {"ok": False, "error": f"{self.LABEL} 暂不支持控制"}
