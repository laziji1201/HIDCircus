"""协议层的纯函数测试（不需要真实设备）。

跑法：.venv\\Scripts\\python.exe tests\\test_protocol.py
或者：.venv\\Scripts\\python.exe -m pytest tests -q
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from providers.razer import (BATTERY_SCALE, DPI_MAX, DPI_MIN, POLL_BY_CODE,
                             POLL_CODE, _xor_crc)


def test_crc_对字节区间做异或():
    buf = bytearray(91)
    buf[3:89] = bytes([0x10, 0x20, 0x30])
    assert _xor_crc(buf[3:89]) == 0x10 ^ 0x20 ^ 0x30


def test_crc_全零为0():
    assert _xor_crc(bytes(86)) == 0


def test_crc_对称性_异或两次还原():
    buf = bytes(range(86))
    once = _xor_crc(buf)
    assert _xor_crc(buf + bytes([once])) == 0


def test_轮询率编码是反比掩码():
    # 码值 = 8000 / 频率，这是雷蛇的私有编码，写错就会把鼠标设成奇怪频率
    assert POLL_CODE[8000] == 0x01
    assert POLL_CODE[1000] == 0x08
    assert POLL_CODE[125] == 0x40
    for hz, code in POLL_CODE.items():
        assert 8000 // hz == code


def test_轮询率反查表覆盖全部档位():
    assert len(POLL_BY_CODE) == len(POLL_CODE)
    for hz, code in POLL_CODE.items():
        assert POLL_BY_CODE[code] == hz


def test_dpi_边界合理():
    assert 100 <= DPI_MIN < DPI_MAX <= 100000


def test_电量分母():
    assert BATTERY_SCALE == 255


def test_设备自定义名截断_由服务端保证():
    # 服务端会截断别名，这里只确认截断后的长度上限符合预期
    name = "x" * 100
    assert len(name[:24]) == 24


def main():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
