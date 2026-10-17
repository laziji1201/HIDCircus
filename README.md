# HIDCircus

多厂商外设统一控制台。后台常驻，点开就能看电量、直接改外设设置，不需要 G HUB / Synapse / Armoury Crate。

简体中文 · [English](README.en-US.md)

> **非官方项目**，与 Logitech、Razer、ASUS 均无关联。不含厂商商标与固件，仅通过 HID 做互操作性访问。

![设备页（深色）](docs/screenshots/devices-dark.png)

## 作者的话

这东西纯粹是自己嫌麻烦捣鼓出来的：桌面上 ROG、罗技、雷蛇三家的外设各要一套软件，懒得开。

所以先说清楚：

- **可能有 bug，而且不少**。我只在自己这台机器、这三台设备上验证过
- **不保证适配任何其它型号**。同品牌其它型号靠试探读，读到算运气，读不到是正常的
- **扩展机制做了，但完全不保证能用**。格式是我按三台设备反推的，冷门设备大概率要你自己调报文
- 崩了、读错了、把设备设置写坏了，作者概不负责；写操作前请自己确认

觉得能用就用，不能用就当一个参考实现。

## 适合谁

**为"桌面上同时有好几家的外设"这种人做的。**

典型场景：一台 ROG 耳机（灯效、EQ 在 Armoury Crate 里）、一把罗技键盘（电量在 G HUB 里）、
一只雷蛇鼠标（DPI 和轮询率在 Synapse 里）——为了看三个数字、关一个灯，要装三套软件，
每套都带更新器、后台服务、账号登录，还会互相抢 HID 通道导致谁都不准。

HIDCircus 解决的就是这件事：

| 你的情况 | 这里怎么做 |
|---|---|
| 3 家外设 = 3 个托盘图标、3 个后台服务 | 一个托盘图标，三台设备同屏显示 |
| 只想看"还剩多少电" | 托盘左键，一眼看完，不用开任何窗口 |
| 只想关掉耳机灯睡觉 | 面板上的开/关，一次点击 |
| 厂商软件互相抢 HID，读数时好时坏 | 直接走 HID，不装也不依赖厂商软件 |
| 想留着自己喜欢的工具，不想被绑架 | MIT 开源，本地服务只监听 127.0.0.1 |
| 买了个冷门型号没人适配 | 自己（或让 AI）写一份 JSON 扩展，还能导出回传给项目 |

**资源占用**：常驻一个 Python 进程（几十 MB 级），比三套厂商软件加起来小一个数量级；
不玩游戏时几乎不占 CPU（默认 10 秒轮询一次，可关）。

## 不适合谁

说清楚比说好听有用：

- **重度 RGB / 宏玩家**：逐键改色、宏编排、灯效分层、游戏内 profile 自动切换 —— 厂商软件做得更全，这里没做
- **需要固件升级**：本项目不做刷写
- **手柄用户**：Windows 没有统一的手柄电量接口，Xbox / DualSense 各是私有报文，目前未支持
- **只想要即插即用的普通用户**：如果你只有一家外设、且用厂商软件挺顺手，那没必要换

## 当前状态

| 厂商 | 设备 | 电量 | 控制 |
|---|---|---|---|
| ASUS/ROG | ROG PELTA | ✅ | 灯效（已实测）／EQ、降噪协议已通 |
| Logitech | PRO X TKL | ✅ | 规划中 |
| Razer | Viper V3 Pro | ✅ | DPI / 轮询率（读写闭环已实测） |

## 快速上手

**便携版**

1. 解压 `HIDCircus-win-x64.zip` 到任意可写目录
2. 双击 `HIDCircus.exe`（首次可能弹一次 UAC，用于创建托盘图标）
3. 托盘左键 = 原生面板，右键 = 菜单（主面板 / 刷新 / 退出）

> 启动后**不会自动打开浏览器**。只有点「主面板」时才打开网页版详细设置。

**源码运行**

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## 界面

| 托盘原生面板（左键） | 主面板 |
|---|---|
| ![原生面板](docs/screenshots/panel-native.png) | ![主面板](docs/screenshots/devices-dark.png) |

| 设置 · 扩展与系统 | 配色预设 |
|---|---|
| ![设置](docs/screenshots/settings-extensions.png) | ![配色](docs/screenshots/palette-silver.png) |

- **托盘原生面板**：左键弹出，显示三台设备的电量、状态，耳机灯效可直接开关；不依赖浏览器
- **环形电量**：每张卡片一个进度环，剩下的空间留给设备设置项
- **亮 / 暗 / 跟随系统**三档主题 + **四套配色预设**（黑银（默认）/ 琥珀 / 薄樱粉 / 撞色）
- **中英双语**切换（`web/i18n.js` 加一份语言即可扩展）
- 启动有加载页，数据就绪后淡入主面板
- **动效**可设「跟随系统 / 始终开启」：系统关掉动画时也能保留过渡
- **自定义背景图**，可调遮罩强度与模糊；侧栏与卡片是毛玻璃
- **长按卡片拖动排序**、**双击设备名改别名**、**配置导入导出**
- **开机自启开关**：设置页一键注册/取消计划任务（普通权限即可）
- 自动刷新间隔可设（5s / 10s / 30s / 关）；插拔设备会立刻刷新

## 托盘

- **左键**：原生面板（电量 + 灯效开关），再点一次收起
- **右键**：菜单 —— 打开面板 / 主面板 / 刷新电量 / 退出

## 扩展：自己适配冷门外设

没有原版设备就没法盲写适配，所以读取部分做成了**声明式 JSON 扩展**：
有设备的用户（或他的 AI agent）照着协议填一份 JSON 放进 `extensions/` 就生效。

- 格式说明与调试方法：[extensions/README.md](extensions/README.md)
- 参考实现：[extensions/examples/](extensions/examples/)
- 适配好了可以在「设置 → 扩展」里**一键导出**，回传给项目做更广的适配
- 没适配的设备也能点「导出设备探测报告」，把接口信息发回来

## 关于"支持更多设备"

**同品牌的其它型号**：能读到多少算多少。已知型号表只提供名字，其它型号会用同一套命令逐项试探
（电量 → 充电 → 灯效 / DPI / 轮询率），读到就展示，读不到就标"该型号尚未适配"。

**不同品牌**：每家都是私有协议（罗技 HID++、雷蛇 91 字节 feature report、ROG 0xCC 报文……），
不存在一套逻辑通吃。本项目分三层：

1. **专属 provider**（`providers/asus.py` / `logitech.py` / `razer.py`）：读得准、能控制，需要逐个适配
2. **JSON 扩展**（`extensions/`）：用户自己写，声明报文与取值规则，不用改代码
3. **通用兜底**（`providers/generic.py`）：走 Windows 电池接口，只能读电量、不能控制

**手柄**：Windows 没有统一的手柄电量接口，Xbox / DualSense 各是一套私有报文，需要单独适配且有硬件验证，目前未做。

## 一次性配置（可选）

双击 `setup.bat`：注册开机自启 + 桌面快捷方式。

```powershell
setup.bat              # 安装
setup.bat uninstall    # 卸载
```

> 本工具**不需要管理员权限**，普通用户权限即可。只有会话被降权（例如从沙箱工具的文件管理器启动）时，
> 才需要通过 UAC 提权一次——程序会自动处理。

## 打包

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# 输出 dist\HIDCircus\HIDCircus.exe 与 dist\HIDCircus-win-x64.zip
```

> 用 onedir 而不是 onefile：单文件版启动要解压到 `%TEMP%`，在受限环境会直接报
> `Could not create temporary directory!`。

## 架构

```
app.py          桌面入口：本地服务 + 托盘 + 原生面板 + 浏览器窗口
server.py       本地 HTTP 服务（页面、设备 API、设置、背景图、鉴权）
flyout.py       原生面板（GDI 自绘，不依赖浏览器）
tray.py         托盘图标（Shell_NotifyIcon）
providers/
  base.py       统一设备模型 + Provider 基类
  asus.py       ROG 耳机（0xCC 报文，0x12 读 / 0x41·0x51 写）
  logitech.py   HID++ 2.0（0x1004 读电量）
  razer.py      91 字节 feature report
  extension.py  声明式 JSON 扩展加载器
  generic.py    Windows 电池接口兜底
web/            页面骨架 / 视觉系统 / 状态与渲染 / 中英文案
tests/          协议层、扩展加载、冒烟测试
extensions/     扩展格式说明与示例
```

新增厂商 = 加一个 `providers/xxx.py` 实现 `scan()` / `control()`，在 `providers/__init__.py` 注册一行；
或者写一份 JSON 放进 `extensions/`，不动代码。

## 合规

- MIT；协议为独立实现，未复制 GPL 项目代码（各 provider 文件头已注明）
- 不使用厂商商标/logo；本 README 有非官方免责声明
- 不涉及 DRM 绕过、固件刷写
- 所有接口只监听 `127.0.0.1`，写入接口需要启动时生成的随机 token

## 借鉴与致谢

**没有复制任何代码**，但协议行为、交互设计参考了下面这些项目/作品的公开信息：

| 项目 | 许可证 | 借鉴了什么 |
|---|---|---|
| [Solaar](https://github.com/pwr-Solaar/Solaar) | GPL-2.0 | 罗技 HID++ 的 feature 编号与报文结构（`0x1004` 电量） |
| [OpenRazer](https://github.com/openrazer/openrazer) | GPL-2.0 | 雷蛇 91 字节报文的整体布局与电量命令 |
| [viper-tray](https://github.com/damianyoko/viper-tray) | MIT | 雷蛇 feature report 的收发细节 |
| [G-Helper](https://github.com/seerge/g-helper) | GPL-3.0 | ASUS 耳机 `0xCC` 报文的命令表 |
| [AF Media Bar](https://github.com/Fervent-Tempo/AF-Media-Bar) | 见其仓库 | 托盘弹窗的交互形态（原生小窗、点空白处收起）——没有用它的代码，只是照着这个体验做的 |

各 provider 文件顶部保留了对应的来源标注。

## 协议来源

协议行为参考了以下开源项目的公开观察结果，本仓库为独立实现，未复制其代码：

- [Solaar](https://github.com/pwr-Solaar/Solaar)（GPL-2.0）— 罗技 HID++
- [OpenRazer](https://github.com/openrazer/openrazer)（GPL-2.0）— 雷蛇
- [viper-tray](https://github.com/damianyoko/viper-tray)（MIT）— 雷蛇 feature report
- [G-Helper](https://github.com/seerge/g-helper)（GPL-3.0）— ASUS 耳机

## 注意

- 厂商软件（G HUB / Synapse / Armoury Crate）运行时可能占用 HID 通道，建议关闭后使用本工具
- 写操作会直接改设备设置（DPI、轮询率、灯效），请自行确认后再操作
- 本项目不涉及固件刷写

详细开发记录与踩坑清单见 [HANDOVER.md](HANDOVER.md)，版本变更见 [CHANGELOG.md](CHANGELOG.md)。
