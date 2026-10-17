# 扩展格式说明（v1）

HIDCircus 不可能预先适配所有外设。所以读取部分做成**声明式 JSON**：
有设备的用户（或他的 AI agent）照着协议查清楚"发什么、读第几个字节"，写成一份 JSON 放进
`extensions/` 就生效，不需要改 Python 代码，也不需要等我们更新。

> 为什么不是插件代码：加载扩展**不会执行任何代码**，只解析固定字段。
> 写错最多是读不到电量，不会把奇怪的报文发给你的设备。

---

## 放哪里

| 运行方式 | 目录 |
|---|---|
| 源码运行 | `项目目录/extensions/*.json` |
| 打包版 | `HIDCircus.exe 同级的 extensions/*.json` |

文件加载后可以在「设置 → 扩展」里看到是否生效，以及每条错误写在哪一行。

---

## 最小可用示例

```json
{
  "spec": 1,
  "id": "my-mouse-battery",
  "name": "我的鼠标（电量）",
  "match": { "vid": "0x046D", "pid": ["0xC548"], "usage_page": "0xFF00" },
  "device": { "name": "MX Master 3S", "kind": "mouse", "vendor_label": "Logitech" },
  "read": {
    "battery": {
      "transport": "feature",
      "report_id": "0x51",
      "request": "0x28 0x00",
      "value": { "offset": 6, "size": 1 }
    }
  }
}
```

---

## 字段说明

### 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `spec` | | 格式版本，目前固定 `1` |
| `id` | ✅ | 唯一标识，建议 `厂商-型号` 小写短横线 |
| `name` | ✅ | 显示给人看的名字 |
| `author` | | 作者署名，会显示在扩展列表里 |
| `match` | ✅ | 怎么认出这台设备，见下 |
| `device` | | 卡片上显示的信息：`name` / `kind`（mouse/keyboard/headset/unknown）/ `vendor_label` |
| `read` | | 读哪些状态：目前支持 `battery`（0-100）、`charging`（布尔） |
| `write` | | 可执行的动作，见下 |

### match：怎么认设备

```json
"match": {
  "vid": "0x046D",          // 厂商号，必填
  "pid": ["0xC548"],        // 产品号，可单个也可数组
  "usage_page": "0xFF00",   // 可选：只匹配这个用途页（避免匹配到键盘/媒体接口）
  "usage": "0x0002"         // 可选：进一步限定
}
```

厂商号和产品号用设备管理器 →「硬件 ID」里能看到，例如 `HID\VID_046D&PID_C548`。
**建议都带上 `usage_page`**：同一个设备常有好几个 HID 接口，只有一个是控制接口。

### read：怎么读

```json
"read": {
  "battery": { ... },
  "charging": { ... }
}
```

`battery` 的结果会被当作 0-100 显示；`charging` 当成布尔。

每条读取规则：

| 字段 | 说明 |
|---|---|
| `transport` | `feature`（默认，send_feature_report）/ `output`（write 原始报文）/ `razer`（雷蛇 91 字节 + 自动 CRC） |
| `report_id` | 报文首字节，例如 `0x51`、`0xCC` |
| `request` | 后面跟的数据，空格分隔十六进制，例如 `"0x28 0x00"` |
| `read_size` | 读回多少字节，默认 64（雷蛇固定 91） |
| `reply_check` | 可选：判断"这是不是我要的那条响应"，例如 `{"offset": 1, "equals": "0x12"}` |
| `value` | 怎么从响应里取值，见下 |

### value：怎么取字节

```json
"value": { "offset": 6, "size": 1, "scale": 1, "round": true, "min": 0, "max": 100 }
```

| 字段 | 说明 |
|---|---|
| `offset` | 从第几个字节开始（0 起） |
| `size` | 取几个字节，1-4，小端序 |
| `scale` | 乘以多少；例如原始值 0-255 要显示百分比就写 `0.392`（=100/255） |
| `round` | 取整，默认 `true` |
| `min` / `max` | 夹紧到合理区间，防止设备返回垃圾值把界面画崩 |
| `equals` | 不给 `value` 时用它做布尔判断：`{"offset": 5, "equals": "1"}` = 充电中 |

### write：能写什么

```json
"write": {
  "set_dpi": {
    "label": "设置 DPI",
    "transport": "feature",
    "report_id": "0x04",
    "request": "0x05 {le16:x} {le16:y}",
    "expect_reply": true
  }
}
```

模板里的 `{...}` 会被页面传来的值替换：

- `{u8:名字}` 或 `{名字}` → 一个字节
- `{le16:名字}` → 2 字节小端
- `{le32:名字}` → 4 字节小端

---

## 调试方法

1. 保存 JSON → 面板「刷新」或重启
2. 「设置 → 扩展」看是否加载成功；写错会直接告诉你 `文件名: 第几行: 什么错`
3. 想看真实收发字节：`set HIDCIRCUS_DEBUG=1` 再启动，请求会写进 `logs/requests.log`
4. 还是不行就看 `logs/app.log`，扩展读取失败会记为「未读到: battery:无响应」之类

---

## 给 AI agent 的说明（可以直接照这个顺序做）

1. 用 `hid.enumerate()` 拿到设备的 `vendor_id / product_id / usage_page / usage / path`
2. 找到**控制接口**（通常是 `usage_page=0xFF00`，或者 product_string 带型号的那个）
3. 查该型号的协议（厂商公开文档、社区逆向、Wireshark USB 抓包对比官方软件）
4. 确定：发什么报文、响应第几字节是电量、量程是多少（0-100 直接就是百分比，0-255 要乘 0.392）
5. 按上面格式写 JSON，放进 `extensions/`
6. 反复调整 `offset` / `scale`，直到面板显示的数字跟官方软件一致
7. 验证通过后可以提 issue/PR，我们会放进 `extensions/examples/`

---

## 把你的适配回传（重要）

写好的扩展可以直接导出来发给维护者，不需要会 git：

1. **导出单个扩展**：「设置 → 扩展」里每条右边有「导出」，下载到 `xx.json`
2. **设备还没适配**：点「导出设备探测报告」，得到的 JSON 里有
   - 这台设备所有 HID 接口（vid/pid/usage_page/产品名/接口号）
   - 一份填好骨架的扩展草稿（`draft` 字段）
   - 已经适配过的 vid:pid 列表（方便对照）
3. 把文件贴到 issue / 发给维护者，或者直接放进 `extensions/` 自己用

这样一台冷门外设只需要**一个用户**写一次，之后所有人都能用。

> 探测报告只枚举接口、不向设备发任何报文，所以对未知设备是安全的。

---

## 常见坑

- **读不到 ≠ 报文错**：先确认设备没被官方软件（G HUB / Armoury Crate）独占，它们会占 HID 通道
- **`usage_page` 写错**：同一设备有多个接口，匹配到键盘接口就永远读不到电量
- **`reply_check` 别忘了**：有些设备会把上一条命令的响应留在缓冲区里，不校验会把旧值当新值
- **`scale` 量程搞错**：0-255 直接当百分比显示，会得到 255% 这种离谱数字（已被 `max` 夹住）
- **两个接口都要开**：少数设备（罗技）电量在短报文接口、控制在长报文接口，`read` 里可以分别指定 `report_id`
