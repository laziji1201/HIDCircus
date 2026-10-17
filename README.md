# HIDCircus

多厂商外设统一控制台。后台常驻，点开就能看电量、直接改外设设置，不需要 G HUB / Synapse / Armoury Crate。

> **非官方项目**，与 Logitech、Razer、ASUS 均无关联。不含厂商商标与固件，仅通过 HID 做互操作性访问。

![设备页（深色）](docs/screenshots/devices-dark.png)

## 当前状态

| 厂商 | 设备 | 电量 | 控制 |
|---|---|---|---|
| ASUS/ROG | ROG PELTA | ✅ | 灯效（已实测）／EQ、降噪协议已通 |
| Logitech | PRO X TKL | ✅ | 规划中 |
| Razer | Viper V3 Pro | ✅ | DPI / 轮询率（读写闭环已实测） |

## 界面

| | |
|---|---|
| ![浅色](docs/screenshots/devices-light.png) | ![设置](docs/screenshots/settings-dark.png) |

- **亮 / 暗 / 跟随系统**三档主题
- **中英双语**切换（`web/i18n.js` 加一份语言即可扩展）
- **自定义背景图**，可调遮罩强度与模糊
- 自动刷新间隔可设（5s / 10s / 30s / 关）

## 运行

双击 `run.bat`：起本地服务 + 托盘 + 面板窗口。窗口关掉服务还在，托盘菜单里可以再打开或退出。

```powershell
run.bat      # 无控制台
debug.bat    # 带控制台，能看错误
panel.bat    # 只开面板窗口（服务已在跑时用）
```

首次使用需要装依赖（已建好 `.venv` 可跳过）：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

启动情况、托盘是否就绪、任何异常都记在 `logs\app.log`。

> 窗口用的是 Edge 的 `--app` 模式：没有地址栏和标签页，本质是一个独立窗口，
> 前端跑在 Chromium 上，所以 CSS 能力完整，和浏览器面板是同一套页面。

## 打包

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# 输出 dist\HIDCircus.exe
```

## 架构

```
app.py          桌面入口：本地服务 + 托盘 + 面板窗口
server.py       本地 HTTP 服务（页面、设备 API、设置、背景图）
providers/
  base.py       统一设备模型 + Provider 基类
  asus.py       ROG 耳机（0xCC 报文，0x12 读 / 0x41·0x51 写）
  logitech.py   HID++ 2.0（0x1004 读电量）
  razer.py      91 字节 feature report
web/
  index.html    页面骨架
  app.css       视觉系统（设计变量 / 组件 / 主题）
  app.js        状态、渲染、设置持久化
  i18n.js       中英文案
run.bat / debug.bat / panel.bat / build.ps1
```

新增厂商 = 加一个 `providers/xxx.py`，实现 `scan()` / `control()`，再在 `providers/__init__.py` 注册一行。

## 合规

- MIT；协议为独立实现，未复制 GPL 项目代码（各 provider 文件头已注明）
- 不使用厂商商标/logo；README 有非官方免责声明
- 不涉及 DRM 绕过、固件刷写

## 协议来源

协议行为参考了以下开源项目的公开观察结果，本仓库为独立实现，未复制其代码：

- [Solaar](https://github.com/pwr-Solaar/Solaar)（GPL-2.0）— 罗技 HID++
- [OpenRazer](https://github.com/openrazer/openrazer)（GPL-2.0）— 雷蛇
- [viper-tray](https://github.com/damianyoko/viper-tray)（MIT）— 雷蛇 feature report
- [G-Helper](https://github.com/seerge/g-helper)（GPL-3.0）— ASUS 耳机

## 注意

- 厂商软件（G HUB / Synapse）运行时可能占用 HID 通道，建议关闭后使用本工具
- 写操作会直接改设备设置（DPI、轮询率、灯效），请自行确认后再操作
- 本项目不涉及固件刷写

详细开发记录见 [HANDOVER.md](HANDOVER.md)。
