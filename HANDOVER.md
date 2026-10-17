# HIDCircus 交接文档

> 更新时间：2026-06-10（第二轮：UI 整体重写）
> 状态：界面已重做（WebView 级渲染 + 中英双语 + 亮暗 + 背景图）；三家电量、ROG 灯效、雷蛇 DPI/轮询率全部实测通过

---

## 1. 项目定位

多厂商外设统一控制台：**一个后台程序替代 G HUB / Synapse / Armoury Crate 日常使用**。

- 直连 HID，不依赖厂商软件常驻
- 托盘常驻，点开看电量、改设置
- 与厂商软件**二选一**（它们运行时会占 HID 通道）
- 开源（MIT），一个厂商一个 provider，方便社区扩展

## 2. 当前状态

| 项 | 状态 |
|---|---|
| 三家电量读取 | ✅ ROG 54%、罗技 100%、雷蛇 43% |
| ROG 耳机控制 | ✅ 灯效读写闭环（50→80→读回80→恢复50） |
| 雷蛇控制 | ✅ DPI / 轮询率读写闭环 |
| 界面 | ✅ 重写完成：侧栏 + 卡片 + 设置页，亮暗/中英/背景图 |
| 本地 HTTP 面板 | ✅ 串行扫描 + 2 秒缓存，端口占用自动顺延 |
| 桌面壳 | ✅ 服务 + 托盘 + Edge 应用窗口（见 §4） |
| 托盘实测 | ⚠️ 只能在用户自己的桌面会话验（见 §7） |
| 打包脚本 | ⚠️ build.ps1 未实测，需按新结构补 `docs` 以外无新增资源 |

### 未完成

| 项 | 优先级 | 说明 |
|---|---|---|
| 托盘实测 | 高 | 需用户双击 `run.bat` 确认 |
| 罗技控制项 | 中 | 灯效 `0x8071`、按键映射 `0x1B04`，工作量最大 |
| ROG EQ / 降噪界面 | 低 | 协议已验证（`0x12/0x21`、`0x41/0x20`），界面没做 |
| 雷蛇 DPI 档位 | 低 | 命令已摸清（`0x04/0x86` 读、`0x04/0x06` 写） |
| 单实例锁 / 开机自启 | 低 | |

## 3. 环境与运行

**必须用 Python 3.10**（项目内 `.venv` 已建好，其余版本未验证）。

```powershell
run.bat      # 服务 + 托盘 + 面板窗口
debug.bat    # 同上，带控制台
panel.bat    # 只开面板窗口
```

依赖：`hidapi`、`pystray`、`Pillow`。**不要引入 pywebview / pythonnet**，原因见 §6。

日志：`logs\app.log`（启动、端口、托盘是否就绪、窗口是否打开、未捕获异常都在里面）。

## 4. 架构

```
app.py          桌面入口：HTTP 服务 + 托盘 + 面板窗口 + 日志
server.py       本地 HTTP 服务：页面 / 设备 API / 设置 / 背景图
providers/      asus.py、logitech.py、razer.py、base.py
web/            index.html + app.css + app.js + i18n.js（无构建步骤）
docs/screenshots/  README 用的界面截图
config.json     用户设置（运行时生成，已 gitignore）
assets/background/  用户背景图（运行时生成，已 gitignore）
.runtime/       Edge 配置副本（运行时生成，已 gitignore）
```

### 窗口为什么用 Edge `--app`

内嵌 WebView（pywebview）在本机装不起来，见 §6。改用 **Edge 的 `--app=URL`**：
没有地址栏和标签页，就是一个独立窗口，Chromium 渲染，CSS 能力完整；而且和浏览器面板共用同一套页面，不用维护两份 UI。

`app.py` 的开窗逻辑要点：

1. 已有标题为 `HIDCircus` 的窗口 → 直接提到前台
2. 否则清理残留的旧浏览器实例（只按我们的配置目录匹配，不动用户浏览器）
3. 启动窗口并**等标题真的变成 `HIDCircus`**（加载失败时标题会是地址本身）
4. 等不到就清空 `.runtime/edge-profile` 重试一次，仍失败则记日志、服务继续跑

### 设置与接口

| 接口 | 说明 |
|---|---|
| `GET /api/devices` | 设备列表（带 `vendor_key`，客户端别用显示名分支） |
| `POST /api/control` | `{vendor, device_id, action, payload}` |
| `GET/POST /api/settings` | 读取/合并写入 `config.json` |
| `POST /api/background` | 原始图片字节（PNG/JPG/WebP/GIF，≤12MB） |
| `DELETE /api/background` | 删掉背景图 |
| `GET /web/*` | 静态资源（做了路径穿越拦截） |

设置项：`theme`(auto/dark/light)、`language`(zh/en)、`background`、`bg_dim`、`bg_blur`、`refresh_seconds`。

### 前端约定

- 文案全部走 `web/i18n.js` 的键，HTML 上用 `data-i18n="key"`，JS 里用 `t("key")`
- 颜色/圆角/动效都是 `app.css` 顶部的 CSS 变量，换主题只改 `html[data-theme]` 两组值
- 客户端分支判断用 `vendor_key`（`asus` / `razer` / `logitech`），不要匹配 `Razer` 这种显示名

## 5. 三家协议（核心资产）

### 5.1 ROG PELTA

- `0B05:1B84`（2.4G）；`0B05:1B82`（有线）
- 接口：`usage_page=0xFF00`，64 字节 output/input report（**不是 feature report**）
- 报文：`[0xCC, 命令, 子命令, 0, 0, 数据...]`
- 回显必须 `resp[1]==cmd && resp[2]==sub`；`FF AA` = NAK

读（0x12）：`07` 电量→`resp[6]`；`08` 充电→`[5]==1`；`13` 灯效状态；`03` 灯效配置（`[5]`模式 `[6]`亮度 `[7,8,9]`RGB）；`21` EQ；`41 20` 降噪；`24`/`19` Sidetone

写：`51 28 [mode,bright,R,G,B]` 灯效；`51 10 [0/1]` 开关；`41 03/04/06` EQ；`41 02/10` 降噪；`41 11/61 11` Sidetone；`50 40` 恢复默认

灯效模式：0 关闭、1 常亮、2 呼吸、3 闪烁、4 色彩循环

### 5.2 罗技 PRO X TKL

- `046D:C352`（有线）；接收器 `046D:C547` 未做
- `usage_page=0xFF00` 两个接口：`usage=0x01` 短(7B) 发请求，`usage=0x02` 长(20B) 收响应
- 请求 `[0x10, 0xFF, featIdx, func|swId, ...]`，devIdx=`0xFF`
- 读电量：getFeature(0x1004) → `resp[4]` 是 feature index → getStatus → `resp[4]` 电量%，`resp[5]&1` 充电

### 5.3 雷蛇 Viper V3 Pro

- `1532:00C1`（无线）；`usage_page=0x0001 usage=0x0002`，91 字节 feature report
- **只有 `MI_00`（interface_number=0）那个集合带 91 字节 feature report**
- 必须 `CreateFileW(dwDesiredAccess=0)` 打开，绕过 mouclass 独占
- 缓冲区首字节是 report ID，90 字节报文从 `buf[1]` 开始：

```
buf[1]      状态（请求填 0）
buf[2]      事务 ID（0x1F）
buf[3:5]    剩余包数
buf[5]      协议类型
buf[6]      数据长度
buf[7]      命令类
buf[8]      命令
buf[9:89]   参数 80 字节
buf[89]     校验
```

- **校验：对 `buf[3:89]` 做 XOR，结果写 `buf[89]`。**
  写成 `buf[2:88]` 或落到 `buf[88]`，设备会对**每条**命令回 `0x03 failure`——
  包括取序列号这种通用命令。这个现象极易误判成"被 Synapse 占用"，别上当。
- 发完 `SetFeature` 后要等约 80ms 再 `GetFeature`
- 响应 `buf[1]`：0 new、1 busy、2 success、3 failure、4 unsupported、5 timeout

已实测命令：

| 命令 | 参数 | 结果 |
|---|---|---|
| `0x07/0x80` 电量 | `[0,0]`，len 2 | `args[1]`（buf[10]）0–255 → 0–100% |
| `0x07/0x84` 充电 | `[0,0]`，len 2 | `args[1]` == 1 充电中 |
| `0x04/0x85` 读 DPI | 7 个 0，len 7 | `args[1..2]` X、`args[3..4]` Y，16 位大端 |
| `0x04/0x05` 写 DPI | `[0, xhi,xlo, yhi,ylo, 0,0]`，len 7 | 写完立刻读回可验证 |
| `0x00/0xC0` 读轮询率 | `[0]`，len 1 | `args[1]` 是**反比位掩码** |
| `0x00/0x40` 写轮询率 | `[flag, code]`，len 2 | **要连发两次，flag 依次 0x00、0x01** |
| `0x04/0x86` 读 DPI 档位 | len 0x26 | `args[1]`=当前档 `args[2]`=档数，之后每档 7 字节 |
| `0x00/0x82` 序列号 | len 0x16 | `args` ASCII |
| `0x00/0x84` 设备模式 | `[0,0]`，len 2 | 0 正常 / 3 驱动模式 |

轮询率编码是反比位掩码：`code = 8000 / 频率` → 8000→`0x01`、1000→`0x08`、125→`0x40`。

**这台鼠标没有 RGB**（官网规格「RGB 灯光效果：无」），`0x0F` 照明类命令一律 timeout，别浪费时间。

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
11. **pywebview 在这台机器上装不起来**：pythonnet 走 .NET Framework 时
    `Python.Runtime.Loader.Initialize` 解析失败；改 coreclr 又缺 `System.Windows.Forms`。
    折腾一轮后放弃内嵌 WebView，改用 Edge `--app`。别再试 pywebview。
12. **pystray 在受限令牌下报 `WinError 5`**（`ChangeWindowMessageFilterEx` 被拒），
    且 `_hwnd` 在抛异常前已赋值，不能用 `_hwnd` 单独判断，要挂 `threading.excepthook` 并落盘
13. **不要用 `Start-Process` 返回的 PID 查 `MainWindowHandle` 判断 GUI 有没有起来**：
    `.venv\Scripts\python.exe` 在 Windows 上是转发器，真正跑代码的是子进程，窗口挂在子进程上。
    用 `EnumWindows` 按标题找窗口才靠得住。杀掉转发器，真正的解释器可能还活着，要按命令行匹配着杀
14. 多线程同时扫 HID 会互相抢响应，必须串行 + 缓存
15. Windows 上 `HTTPServer.allow_reuse_address` 默认是 1，第二个进程能抢占同一端口，
    导致"端口顺延"永远不触发。Windows 下必须关掉
16. **Edge 的配置目录会被上次强杀留下的崩溃会话污染**：复用同一份配置启动时，窗口会停在
    错误页/崩溃页，标题变成地址（`127.0.0.1`）。处理办法：清会话文件 + 清残留实例，
    实在不行整份配置目录删掉重来（`app.py` 已实现自愈重试）
17. **在 DSH 会话里由 Python 拉起的 Edge，渲染进程会崩**（窗口标题变成 `127.0.0.1_/`），
    同一条命令用 PowerShell 直接 `Start-Process` 就正常。这是沙箱令牌的问题，不是代码 bug；
    用户自己双击 `run.bat` 不受影响。验证 GUI 时先看 `logs\app.log` 里有没有「已打开窗口」
18. 客户端不要靠厂商显示名（`Razer` / `ASUS/ROG`）分支，`to_dict()` 里已带 `vendor_key`
19. 浏览器 UA 的 `[hidden]` 会输给带 `display` 的类选择器，`app.css` 顶部统一加了
    `[hidden] { display: none !important }`
20. `-webkit-font-smoothing: antialiased` 在白底上会让文字明显变细发虚，只对深色主题启用

## 7. 待验证

**看 `logs\app.log` 就知道结果**：会写 HTTP 端口、托盘是否就绪、窗口是否打开、任何未捕获异常。

1. 双击 `run.bat`，确认：托盘出现电量图标、面板窗口打开、窗口里三张卡片有数据
2. 关掉窗口 → 托盘还在？点托盘 → 窗口回来？
3. 设置页四件事各点一遍：主题切换、语言切换、选一张背景图、改刷新间隔
4. 若托盘不可用，日志会写「托盘未建立」并附异常；程序会退化为「窗口关了就把进程收掉」

## 8. 打包

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# 输出 dist\HIDCircus.exe
```

注意 PyInstaller 需要 `--add-data "web;web"`（已在脚本里）；`docs/` 不用打包。

## 9. 合规

- MIT；协议为独立实现，未复制 GPL 项目代码（各 provider 文件头已注明）
- 不使用厂商商标/logo；README 有非官方免责声明
- 不涉及 DRM 绕过、固件刷写

## 10. 参考

- [Solaar](https://github.com/pwr-Solaar/Solaar)（GPL-2.0）— 罗技 HID++
- [OpenRazer](https://github.com/openrazer/openrazer)（GPL-2.0）— 雷蛇命令表
- [viper-tray](https://github.com/damianyoko/viper-tray)（MIT）— 雷蛇 feature report 的 Windows 实战实现
- [G-Helper](https://github.com/seerge/g-helper)（GPL-3.0）— ASUS 耳机
- [HaloBattery](https://github.com/HeyOkay/HaloBattery)（MIT）— provider 架构参考
