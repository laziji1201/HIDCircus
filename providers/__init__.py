"""provider 注册表。

新增厂商只需：
1. 在 providers/ 下加一个 xxx.py，实现 base.Provider
2. 在这里 import 并加入 build_providers()

顺序有意义：专属 provider 先扫，扩展次之，通用的 Windows 电池兜底排在最后。
"""

from .asus import AsusProvider
from .extension import ExtensionProvider, load_extensions
from .generic import GenericBatteryProvider
from .logitech import LogitechProvider
from .razer import RazerProvider

# 扩展加载结果（服务端用来展示"哪些扩展生效了、哪些写错了"）
EXTENSIONS = []
EXTENSION_ERRORS = []


def build_providers(hid_module, extension_dirs=()):
    global EXTENSIONS, EXTENSION_ERRORS
    EXTENSIONS, EXTENSION_ERRORS = load_extensions(*extension_dirs)
    providers = [
        AsusProvider(hid_module),
        LogitechProvider(hid_module),
        RazerProvider(hid_module),
    ]
    if EXTENSIONS:
        providers.append(ExtensionProvider(hid_module, EXTENSIONS))
    providers.append(GenericBatteryProvider(hid_module))
    return providers
