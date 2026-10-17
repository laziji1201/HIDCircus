"""provider 注册表。

新增厂商只需：
1. 在 providers/ 下加一个 xxx.py，实现 base.Provider
2. 在这里 import 并加入 build_providers()

顺序有意义：专属 provider 先扫，通用的 Windows 电池兜底排在最后。
"""

from .asus import AsusProvider
from .generic import GenericBatteryProvider
from .logitech import LogitechProvider
from .razer import RazerProvider


def build_providers(hid_module):
    return [
        AsusProvider(hid_module),
        LogitechProvider(hid_module),
        RazerProvider(hid_module),
        GenericBatteryProvider(hid_module),
    ]
