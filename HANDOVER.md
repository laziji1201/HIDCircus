# HIDCircus 交接文档

> 更新时间：2026-06-10（接手会话第一轮）
> 状态：三家电量全部跑通；桌面壳可运行；ROG 控制已实测；托盘待用户桌面会话确认

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
| 三家电量读取 | ✅ ROG 56%、罗技 100%、雷蛇 44%（第一轮接手时修好） |
| ROG 耳机控制 | ✅ 灯效读写闭环验证（50→80→读回80→恢复50） |
| 雷蛇 DPI 读取 | ✅ 1000 × 1000 |
| tkinter 主窗口 | ✅ 冒烟测试通过（3 张卡片正常渲染） |
| 本地 HTTP 面板 | ✅ 串行扫描 + 2 秒缓存，端口占用自动顺延 |
| 桌面程序启动 | ✅ 无控制台报错，进程稳定 |
| 托盘实测 | ⚠️ 代码完成，需在用户自己的桌面会话看图标（见 §7） |
| 打包脚本 | ✅ build.ps1（未实测） |

### 未完成

| 项 | 优先级 | 说明 |
|---|---|---|
| 托盘实测 | 高 | 需用户双击 `run.bat` 确认图标与交互 |
| 罗技控制项 | 中 | 灯效 `0x8071`、按键映射 `0x1B04`，工作量最大 |
| 雷蛇控制项 | 中 | 灯效 / DPI 写入（读已通，写命令结构相同） |
| ROG EQ / 降噪界面 | 低 | 协议已验证，界面还没做 |
| 开机自启 / 单实例 | 低 | |

## 3. 环境与运行

**必须用 Python 3.10**（项目内 `.venv` 已建好）。原因：pywebview 的 pythonnet 在 3.13 上加载失败；虽然最终改用 tkinter 不再需要 pywebview，但现有 venv 是 3.10，保持一致。

```powershell
run.bat      # 双击，无控制台
debug.bat    # 带控制台，能看错误
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

**并发约定**：`collect_devices()` 会被托盘线程、UI 线程、HTTP 线程同时调用，同一个 HID 设备被两处同时打开会互相抢响应。所以 `server.py` 里用全局锁串行化 + 2 秒缓存合并重复请求。新增 provider 时不要在模块层做自己的线程或后台轮询。

**线程约定**：Tk 只能在主线程操作，pystray 回调在它自己的线程里。`app.py` 用 `_ui_queue` + 主线程 `_pump()` 把托盘动作投递回主线程，不要直接在回调里碰 `_root`。

## 5. 三家协议（核心资产）

### 5.1 ROG PELTA

- `0B05:1B84`（2.4G）；`0B05:1B82`（有线）
- 接口：`usage_page=0xFF00`，`MI_03&Col03`，64 字节 output/input report
- 报文：`[0xCC, 命令, 子命令, 0, 0, 数据...]`，**不是 feature report**
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

- `1532:00C1`；`usage_page=0x0001 usage=0x0002`，91 字节 feature report
- **只有 `MI_00`（interface_number=0）那个鼠标集合带 91 字节 feature report**，其它集合 feature 长度是 0，别乱开
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
  写成 `buf[2:88]` 或落到 `buf[88]`，设备会对**每条**命令回 `0x03 failure`——包括取序列号、取设备模式这种通用命令。这个现象极易误判成"被 Synapse 占用"，实际是自己 CRC 算错了。第一轮接手就是踩这个坑。
- 发完 `SetFeature` 后要等约 80ms 再 `GetFeature`
- 响应 `buf[1]`：0 new、1 busy、2 success、3 failure、4 unsupported、5 timeout

已实测命令（全部 success）：

| 命令 | 参数 | 结果 |
|---|---|---|
| `0x07/0x80` 电量 | `[0,0]`，len 2 | `args[1]`（buf[10]）0–255 → 0–100% |
| `0x07/0x84` 充电 | `[0,0]`，len 2 | `args[1]` == 1 充电中 |
| `0x04/0x85` DPI | 7 个 0，len 7 | `args[1..2]` X、`args[3..4]` Y，各 16 位大端 |
| `0x00/0x82` 序列号 | len 0x16 | `args` ASCII，本机 `PM2547H32300795` |
| `0x00/0x84` 设备模式 | `[0,0]`，len 2 | 0 正常 / 3 驱动模式 |

`0x00/0x85` 读轮询率在本机 timeout（该型号不走这条），别浪费时间。

### 5.4 设备发现规则

| 厂商 | 筛选条件 |
|---|---|
| ASUS | `enumerate(0x0B05, pid)` 且 `usage_page == 0xFF00` |
| Logitech | `enumerate(0x046D, pid)` 且 `usage_page == 0xFF00`，区分 usage 1/2 |
| Razer | `enumerate(0x1532, pid)` 且 `usage_page==0x0001 && usage==0x0002`，优先 `interface_number == 0` |

## 6. 踩坑记录

1. ctypes `SetupDiGetClassDevsW` 必须显式 `restype=HANDLE`，否则 64 位句柄截断
2. `HidP_GetCaps` 第一个参数是 `PHIDP_PREPARSED_DATA`，要先 `HidD_GetPreparsedData`
3. `ctypes.wintypes` 没有 `NTSTATUS`，用 `c_long`
4. hidapi `open_path` 需要 bytes
5. 鼠标类设备 hidapi 打不开，要 ctypes + access=0
6. 罗技短接口写、长接口读，同接口读写会超时
7. PELTA 是 output/input report，feature report 读直接报错
8. G HUB / Synapse 运行时占通道
9. razer/logitech 服务以 SYSTEM 权限运行，普通用户停不掉
10. Windows 不暴露 PELTA 的 `BatteryLevel`
11. pywebview + pythonnet 在 Python 3.13 加载失败；coreclr 模式又缺 `System.Windows.Forms` → 放弃 WebView，改 tkinter
12. pystray 在受限会话报 `WinError 5`（ChangeWindowMessageFilterEx），且 `_hwnd` 在抛异常前已赋值，不能用 `_hwnd` 判断托盘是否可用，要挂 `threading.excepthook`
13. DSH 会话启动的 GUI 进程，窗口不出现在桌面（最小 tkinter 测试也复现）；但 `tkinter.Tk()` 能正常构造，可以拿来做冒烟测试。GUI 视觉验证必须在用户自己的桌面会话做
14. **雷蛇 CRC 偏移一位会让所有命令返回 failure**，见 §5.3。排查顺序：先怀疑自己的 CRC/偏移，再怀疑厂商软件占用
15. 雷蛇同样要确认打开的是 `MI_00` 那个集合，其它集合 feature 长度为 0，`SetFeature` 会失败或设备不回话
16. 雷蛇 `SetFeature` 后立刻 `GetFeature` 会偶发读到上一次的响应，固定等 80ms
17. 多线程同时扫 HID 会互相抢响应，必须串行 + 缓存
18. Windows 上 `HTTPServer.allow_reuse_address` 默认是 1，含义和 Unix 不同：第二个进程能抢占同一端口，导致"端口顺延"逻辑永远不触发。Windows 下必须关掉，占用才会报错
19. 端口顺延后浏览器书签可能失效，所以主窗口底部直接显示了真实的面板地址

## 7. 待验证（务必先做）

1. 双击 `run.bat`，看托盘图标是否出现、窗口是否打开
2. 点托盘图标能否唤起窗口；关闭窗口后是否还在托盘；右键菜单「刷新」是否生效
3. 若托盘不可用，程序会退化为"直接显示窗口、关闭即退出"

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
- [OpenRazer](https://github.com/openrazer/openrazer)（GPL-2.0）— 雷蛇命令表
- [viper-tray](https://github.com/damianyoko/viper-tray)（MIT）— 雷蛇 feature report 的 Windows 实战实现（CRC 落在 `buf[89]` 这条就是对照它确认的）
- [G-Helper](https://github.com/seerge/g-helper)（GPL-3.0）— ASUS 耳机
- [HaloBattery](https://github.com/HeyOkay/HaloBattery)（MIT）— provider 架构参考
