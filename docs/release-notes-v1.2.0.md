## HIDCircus v1.2.0

一个托盘常驻的多厂商外设控制台：看电量、开关灯效、改 DPI，不用装 G HUB / Synapse / Armoury Crate。

### 下载

- **便携版**：`HIDCircus-win-x64.zip` —— 解压到可写目录，双击 `HIDCircus.exe`
- 首次启动可能弹一次 UAC（创建托盘图标需要）
- 想开机自启 / 建桌面快捷方式：双击包里的 `setup.bat`

### 这个版本能做什么

| | |
|---|---|
| 托盘左键 | 原生面板（GDI 绘制，不依赖浏览器）：电量、状态、耳机灯效开关 |
| 托盘右键 | 主面板（网页版详细设置）/ 刷新 / 退出 |
| 主面板 | 环形电量、配色预设、背景图、拖动排序、中英双语 |
| 控制 | ROG PELTA 灯效（已实测）、Razer DPI / 轮询率（已实测） |
| 扩展 | 声明式 JSON 适配冷门外设，可导出回传 |

### 已验证的设备

- ASUS/ROG **ROG PELTA** —— 电量、充电状态、灯效开关
- Logitech **PRO X TKL** —— 电量
- Razer **Viper V3 Pro** —— 电量、DPI、轮询率

### 已知问题

- **只测过上面三台设备**。其它型号可能读不到，这属于正常情况，不是 bug 报告里的"不能用"
- 某些环境（沙箱、远程会话）下进程会被降权，托盘和窗口无法创建；程序会自动尝试提权一次
- 手柄（Xbox / DualSense）暂不支持
- 扩展格式是照着三台设备反推的，冷门设备大概率需要自己调报文

### 需要帮忙

如果你手上有**别的型号**，欢迎试一下并反馈：

- 读不到 → 「设置 → 扩展 → 导出设备探测报告」，把 JSON 发出来即可
- 能读但想控制（灯效 / DPI）→ 按 `extensions/README.md` 写一份 JSON，能用了可以导出回传

**完整说明**：[README](https://github.com/laziji1201/HIDCircus/blob/main/README.md) ｜ **变更记录**：[CHANGELOG](https://github.com/laziji1201/HIDCircus/blob/main/CHANGELOG.md)
