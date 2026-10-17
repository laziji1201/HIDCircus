# HIDCircus

多厂商外设统一控制面板。后台托盘常驻，点开就能看电量、直接改外设设置，不需要 G HUB / Synapse / Armoury Crate。

> **非官方项目**，与 Logitech、Razer、ASUS 均无关联。不含厂商商标与固件，仅通过 HID 做互操作性访问。

## 当前状态

| 厂商 | 设备 | 电量 | 控制 |
|---|---|---|---|
| ASUS/ROG | ROG PELTA | ✅ | 灯效 / EQ / 降噪（灯效已实测） |
| Logitech | PRO X TKL | ✅ | 规划中 |
| Razer | Viper V3 Pro | ✅ | 规划中（DPI 已可读） |

## 运行

双击 `run.bat`（无控制台）。调试用 `debug.bat`（有控制台，能看到错误）。

首次使用需要装依赖（已建好 `.venv` 可跳过）：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

启动后：

- 系统托盘出现圆环图标，中间是当前最低电量
- 左键点图标 → 打开主面板
- 右键 → 打开面板 / 刷新 / 退出
- 关闭主窗口只是隐藏，托盘继续常驻

> 若当前环境不允许托盘，程序会自动退化为「直接显示窗口、关闭即退出」。

只想用浏览器看面板：

```powershell
.\.venv\Scripts\python server.py
# 打开 http://127.0.0.1:8777
```

## 打包

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# 输出 dist\HIDCircus.exe
```

## 架构

```
app.py          桌面入口：托盘 + tkinter 窗口 + 启动本地服务
ui.py           tkinter 主界面（设备卡片 / 电量条 / 灯效控制）
server.py       本地 HTTP 服务（桌面与浏览器共用，串行扫描 + 短时缓存）
providers/
  base.py       统一设备模型 + Provider 基类
  asus.py       ROG 耳机（0xCC 报文，0x12 读 / 0x41·0x51 写）
  logitech.py   HID++ 2.0（0x1004 读电量）
  razer.py      91 字节 feature report
web/index.html  浏览器版面板
run.bat         双击启动
debug.bat       带控制台的调试启动
build.ps1       PyInstaller 打包
```

新增厂商 = 加一个 `providers/xxx.py`，实现 `scan()` / `control()`，再在 `providers/__init__.py` 注册一行。

## 协议来源

协议行为参考了以下开源项目的公开观察结果，本仓库为独立实现，未复制其代码：

- [Solaar](https://github.com/pwr-Solaar/Solaar)（GPL-2.0）— 罗技 HID++
- [OpenRazer](https://github.com/openrazer/openrazer)（GPL-2.0）— 雷蛇
- [viper-tray](https://github.com/damianyoko/viper-tray)（MIT）— 雷蛇 feature report
- [G-Helper](https://github.com/seerge/g-helper)（GPL-3.0）— ASUS 耳机

## 注意

- 厂商软件（G HUB / Synapse）运行时可能占用 HID 通道，建议关闭后使用本工具
- 写操作会直接改设备设置，请自行确认后再操作
- 本项目不涉及固件刷写

详细开发记录见 [HANDOVER.md](HANDOVER.md)。
