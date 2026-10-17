"""provider 注册表。

新增厂商只需：
1. 在 providers/ 下加一个 xxx.py，实现 base.Provider
2. 在这里 import 并加入 build_providers()
"""

from .asus import AsusProvider
from .logitech import LogitechProvider
from .razer import RazerProvider


def build_providers(hid_module):
    return [
        AsusProvider(hid_module),
        LogitechProvider(hid_module),
        RazerProvider(hid_module),
    ]
