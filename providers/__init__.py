
from .asus import AsusProvider
from .extension import ExtensionProvider, load_extensions
from .generic import GenericBatteryProvider
from .logitech import LogitechProvider
from .razer import RazerProvider

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
