"""冒烟测试：模块能导入、关键入口函数还在。

这条测试的由来：一次大段代码重写时，`open_panel` 到 `close_panel` 之间的函数
（托盘面板、颜色表、页面请求处理）被整块删掉，编译能过、启动也"看起来正常"，
直到托盘点不动、页面按钮没反应才暴露。导入 + 属性检查就能拦住这类事故。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXPECTED_APP = [
    "main", "open_panel", "close_panel", "show_flyout", "close_flyout",
    "handle_ui_requests", "flyout_colors", "update_tray", "make_icon",
    "current_integrity", "start_device_watch", "find_browser", "page_alive",
]
EXPECTED_SERVER = [
    "create_server", "collect_devices", "load_settings", "save_settings",
    "do_control", "set_autostart", "autostart_enabled", "SESSION_TOKEN",
]


def test_模块可导入():
    import app, server, flyout, tray  # noqa: F401
    from providers import asus, logitech, razer, generic  # noqa: F401


def test_app_入口函数齐全():
    import app
    missing = [n for n in EXPECTED_APP if not hasattr(app, n)]
    assert not missing, f"app.py 缺少: {missing}"


def test_server_接口函数齐全():
    import server
    missing = [n for n in EXPECTED_SERVER if not hasattr(server, n)]
    assert not missing, f"server.py 缺少: {missing}"


def test_默认设置字段完整():
    import server
    for key in ("theme", "language", "palette", "motion", "device_order",
                "aliases", "refresh_seconds", "bg_dim", "bg_blur"):
        assert key in server.DEFAULT_SETTINGS, f"DEFAULT_SETTINGS 缺 {key}"
    assert server.DEFAULT_SETTINGS["palette"] == "silver"


def test_web_资源齐全():
    for rel in ("web/index.html", "web/app.js", "web/app.css", "web/i18n.js",
                "assets/icon.png", "assets/favicon.png", "assets/icon.ico"):
        assert (ROOT / rel).is_file(), f"缺文件: {rel}"


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
