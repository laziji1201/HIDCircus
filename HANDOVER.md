# HIDCircus 交接文档

> 更新时间：本会话末尾
> 状态：桌面应用已成型（tkinter + 托盘），三家电量 + ROG 控制跑通

---

## 1. 项目定位

多厂商外设统一控制面板：**一个后台程序替代 G HUB / Synapse / Armoury Crate 日常使用**。

- 直连 HID，不依赖厂商软件常驻
- 托盘常驻，点开看电量、改设置
- 与厂商软件**二选一**（它们运行时会占 HID 通道）
- 开源（MIT），一个厂商一个 provider，方便社区扩展

## 2. 当前状态

| 项 | 状态 |
|---|---|
| 三家电量读取 | ✅ ROG 56%、罗技 100%；雷蛇通道通但返回 failure |
| ROG 耳机控制 | ✅ 灯效读写闭环验证（50→80→读回80→恢复50） |
| tkinter 主窗口 | ✅ 已实现（电量卡片 / 电量条 / ROG 灯效控制） |
| 托盘 | ⚠️ 代码完成，需在你自己的桌面会话验证（见 §7） |
| 浏览器面板 | ✅ 保留（http://127.0.0.1:8777） |
| 打包脚本 | ✅ build.ps1（未实测，因本机 GUI 受限） |

### 未完成

| 项 | 优先级 | 说明 |
|---|---|---|
| 雷蛇电量 `failure` | 高 | 需管理员停 `Razer Elevation Service` 后重试 |
| 罗技控制项 | 中 | 灯效 `0x8071`、按键映射 `0x1B04` |
| 托盘实测 | 高 | 本会话无法验证 GUI，需用户双击 `run.bat` |
| 开机自启 | 中 | |
| 单实例锁 | 低 | |

## 3. 环境与运行

**必须用 Python 3.10**（项目内 `.venv` 已建好）。原因：pywebview 的 pythonnet 在 3.13 上加载失败；虽然最终改用 tkinter 不再需要 pywebview，但现有 venv 是 3.10，保持一致。

```powershell
# 双击运行
run.bat

# 调试（带控制台，能看错误）
debug.bat
```

依赖：`hidapi`、`pystray`、`Pillow`（见 requirements.txt）

## 4. 架构

```
app.py          桌面入口：托盘 + tkinter 窗口 + 启动 HTTP 服务
ui.py           tkinter 主界面（卡片 / 电量条 / 灯效控制）
server.py       本地 HTTP 服务（桌面与浏览器共用）
providers/
  base.py       Device 模型 + Provider 基类
  asus.py       ROG 耳机（0xCC 报文，0x12 读 / 0x41·0x51 写）
  logitech.py   HID++ 2.0（0x1004 读电量）
  razer.py      91 字节 feature report
web/index.html  浏览器版面板
run.bat / debug.bat / build.ps1
```

新增厂商 = 加 `providers/xxx.py` 实现 `scan()` / `control()`，在 `providers/__init__.py` 注册一行。

## 5. 三家协议（核心资产）

### 5.1 ROG PELTA

- `0B05:1B84`（2.4G）；`0B05:1B82`（有线）
- 接口：`usage_page=0xFF00`，`MI_03&Col03`，64 字节 output/input report
- 报文：`[0xCC, 命令, 子命令, 0, 0, 数据...]`，**不是 feature report**
- 回显必须 `resp[1]==cmd && resp[2]==sub`；`FF AA` = NAK

读（0x12）：`07` 电量→`resp[6]`；`08` 充电→`[5]==1`；`13` 灯效状态；`03` 灯效配置（`[5]`模式 `[6]`亮度 `[7,8,9]`RGB）；`21` EQ；`41 20` 降噪；`24`/`19` Sidetone

写：`51 28 [mode,bright,R,G,B]` 灯效；`51 10 [0/1]` 开关；`41 03/04/06` EQ；`41 02/10` 降噪；`41 11/61 11` Sidetone；`50 40` 恢复默认

### 5.2 罗技 PRO X TKL

- `046D:C352`（有线）；接收器 `046D:C547` 未做
- `usage_page=0xFF00` 两个接口：`usage=0x01` 短(7B) 发请求，`usage=0x02` 长(20B) 收响应
- 请求 `[0x10, 0xFF, featIdx, func|swId, ...]`，devIdx=`0xFF`
- 读电量：getFeature(0x1004) → getStatus → `resp[4]` 电量%，`resp[5]&1` 充电

### 5.3 雷蛇 Viper V3 Pro

- `1532:00C1`；`usage_page=0x0001 usage=0x0002`，feature report 91B
- 必须 `CreateFileW(dwDesiredAccess=0)` 绕过 mouclass 独占
- `[0]=0, [1]=状态, [2]=事务ID 0x1F, [7]=命令类 0x07, [8]=命令 0x80, [88]=XOR CRC`
- 电量在 `arguments[1]`（offset 10），0–255 → 0–100
- 当前返回 `0x03 FAILURE`，疑 Synapse 服务占用

## 6. 踩坑记录

1. ctypes `SetupDiGetClassDevsW` 必须显式 `restype=HANDLE`，否则 64 位句柄截断
2. `HidP_GetCaps` 第一个参数是 `PHIDP_PREPARSED_DATA`，要先 `HidD_GetPreparsedData`
3. `ctypes.wintypes` 没有 `NTSTATUS`，用 `c_long`
4. hidapi `open_path` 需要 bytes
5. 鼠标类设备 hidapi 打不开，要 ctypes + access=0
6. 罗技短接口写、长接口读，同接口读写会超时
7. PELTA 是 output/input report，feature report 读直接报错
8. G HUB / Synapse 运行时占通道
9. razer/logitech 服务 SYSTEM 权限，普通用户停不掉
10. Windows 不暴露 PELTA 的 `BatteryLevel`
11. **pywebview + pythonnet 在 Python 3.13 加载失败；coreclr 模式下又缺 `System.Windows.Forms`** → 最终放弃 WebView，改 tkinter
12. **pystray 在受限会话报 `WinError 5`（ChangeWindowMessageFilterEx）**，且 `_hwnd` 在抛异常前已赋值，不能用 `_hwnd` 判断托盘是否可用，要挂 `threading.excepthook`
13. **当前 DSH 会话启动的 GUI 进程，窗口不出现在桌面**（最小 tkinter 测试也复现），GUI 验证必须在用户自己的桌面会话做

## 7. 待验证（务必先做）

1. 双击 `run.bat`，看托盘图标是否出现、窗口是否打开
2. 点托盘图标能否唤起窗口；关闭窗口后是否还在托盘
3. 若托盘不可用，程序会退化为"直接显示窗口、关闭即退出"
4. 雷蛇仍失败的话，用管理员 PowerShell：
   ```powershell
   Stop-Service 'Razer Elevation Service' -Force
   ```
   然后重开程序看电量

## 8. 打包

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# 输出 dist\HIDCircus.exe
```

注意 PyInstaller 需要 `--add-data "web;web"`（已在脚本里）。

## 9. 合规

- MIT；协议为独立实现，未复制 GPL 项目代码（各 provider 文件头已注明）
- 不使用厂商商标/logo；README 有非官方免责声明
- 不涉及 DRM 绕过、固件刷写

## 10. 参考

- [Solaar](https://github.com/pwr-Solaar/Solaar)（GPL-2.0）— 罗技 HID++
- [OpenRazer](https://github.com/openrazer/openrazer)（GPL-2.0）— 雷蛇
- [viper-tray](https://github.com/damianyoko/viper-tray)（MIT）— 雷蛇 feature report
- [G-Helper](https://github.com/seerge/g-helper)（GPL-3.0）— ASUS 耳机
- [HaloBattery](https://github.com/HeyOkay/HaloBattery)（MIT）— provider 架构参考
