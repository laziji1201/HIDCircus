"""HIDCircus 主窗口（tkinter 原生界面）。

不用 WebView，避免 pythonnet/.NET 依赖，打包体积也小得多。
布局：顶部标题栏 + 设备卡片列表（电量条 / 状态 / ROG 灯效控制）+ 底部状态。
"""

import threading
import time
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox

from server import collect_devices, do_control

BG = "#0f1115"
CARD = "#171a21"
LINE = "#262b36"
TEXT = "#e6e8ee"
MUTED = "#8b93a7"
ACCENT = "#4c8dff"
GOOD = "#3ddc84"
WARN = "#ffb020"
BAD = "#ff5c5c"

MODE_NAMES = {"常亮": 1, "呼吸": 2, "闪烁": 3, "色彩循环": 4}
MODE_BY_ID = {v: k for k, v in MODE_NAMES.items()}


def battery_color(p):
    if p is None:
        return MUTED
    if p <= 20:
        return BAD
    if p <= 50:
        return WARN
    return GOOD


class HIDCircusUI:
    def __init__(self, root: tk.Tk, api_url: str = ""):
        self.root = root
        self.api_url = api_url
        self.root.title("HIDCircus")
        self.root.geometry("960x760")
        self.root.minsize(720, 520)
        self.root.configure(bg=BG)

        self.devices = []
        self._scanning = False
        # 用户挑的颜色存在这里，不要每次刷新都重置（否则自动刷新会吞掉选择）
        self._picked = {}

        self._build_header()
        self._build_body()
        self._build_footer()

        self.refresh()
        self.root.after(10000, self._auto_refresh)

    # ---------- 布局 ----------

    def _build_header(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(bar, text="HIDCircus", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        tk.Label(bar, text="多厂商外设统一面板", bg=BG, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=10, pady=(4, 0))

        self.btn_refresh = tk.Button(bar, text="刷新", command=self.refresh,
                                     bg="#0f1218", fg=TEXT, relief="flat",
                                     activebackground=ACCENT, activeforeground=TEXT,
                                     font=("Microsoft YaHei UI", 9), padx=14, pady=3)
        self.btn_refresh.pack(side="right")

    def _build_body(self):
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", expand=True, padx=16, pady=6)

        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        self.cards = tk.Frame(canvas, bg=BG)
        self.cards.bind("<Configure>",
                        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.cards, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _build_footer(self):
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=16, pady=(4, 10))
        self.status = tk.Label(foot, text="", bg=BG, fg=MUTED,
                               font=("Microsoft YaHei UI", 8), anchor="w")
        self.status.pack(side="left")
        if self.api_url:
            tk.Label(foot, text=f"浏览器面板 {self.api_url}", bg=BG, fg=MUTED,
                     font=("Microsoft YaHei UI", 8)).pack(side="right")

    # ---------- 数据 ----------

    def refresh(self):
        if self._scanning:
            return
        self._scanning = True
        self.status.config(text="扫描中…")
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        try:
            devs = collect_devices()
        except Exception as e:
            devs = [{"id": "error", "name": "扫描失败", "vendor": "",
                     "kind": "", "battery": None, "note": str(e),
                     "extra": {}}]
        self.root.after(0, lambda: self._render(devs))

    def _auto_refresh(self):
        self.refresh()
        self.root.after(10000, self._auto_refresh)

    # ---------- 渲染 ----------

    def _render(self, devs):
        self.devices = devs
        self._scanning = False
        for w in self.cards.winfo_children():
            w.destroy()

        if not devs:
            tk.Label(self.cards, text="没有检测到设备\n请确认设备已连接，且厂商软件未占用 HID 通道",
                     bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 10),
                     justify="center").pack(pady=60)
        else:
            for d in devs:
                self._render_card(d)

        self.status.config(text=f"上次刷新: {time.strftime('%H:%M:%S')}")

    def _render_card(self, d):
        card = tk.Frame(self.cards, bg=CARD,
                        highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x", pady=6, padx=2)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=16, pady=14)

        top = tk.Frame(inner, bg=CARD)
        top.pack(fill="x")

        tk.Label(top, text=d.get("name", "?"), bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        meta = " · ".join(x for x in (d.get("vendor"), d.get("kind")) if x)
        tk.Label(top, text=meta, bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 8)).pack(side="left", padx=10, pady=(3, 0))

        battery = d.get("battery")
        txt = f"{battery}%" if battery is not None else "—"
        tk.Label(top, text=txt, bg=CARD, fg=battery_color(battery),
                 font=("Consolas", 20, "bold")).pack(side="right")

        # 电量条
        bar = tk.Canvas(inner, height=6, bg="#0b0d11", highlightthickness=0)
        bar.pack(fill="x", pady=(10, 8))

        def draw_bar(event=None):
            bar.delete("all")
            w = bar.winfo_width()
            if battery is not None and w > 1:
                bar.create_rectangle(0, 0, int(w * battery / 100), 6,
                                     fill=battery_color(battery), outline="")
        bar.bind("<Configure>", draw_bar)

        # 状态行
        extra = d.get("extra") or {}
        note = d.get("note", "")
        charging = d.get("charging")
        if note:
            state, color = note, BAD
        elif charging is True:
            state, color = "充电中", WARN
        elif d.get("connected") is False:
            state, color = "未连接", MUTED
        else:
            state, color = "已连接", GOOD
        tk.Label(inner, text=state, bg=CARD, fg=color,
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w")

        # 雷蛇：DPI / 轮询率（控件自己会显示当前值）
        if d.get("vendor_key") == "razer" and extra.get("dpi"):
            self._render_razer(inner, d, extra)

        # ROG 灯效控制
        lighting = extra.get("lighting")
        if lighting and d.get("vendor_key") == "asus":
            self._render_lighting(inner, d, lighting, extra.get("lighting_on", True))

    def _render_razer(self, parent, d, extra):
        """鼠标控制：DPI 与轮询率"""
        box = tk.Frame(parent, bg=CARD)
        box.pack(fill="x", pady=(10, 0))

        dpi = extra.get("dpi") or {}
        dpi_max = extra.get("dpi_max", 35000)
        spin_kw = dict(bg="#0b0d11", fg=TEXT, relief="flat", width=7,
                       font=("Consolas", 9), buttonbackground="#22262f",
                       insertbackground=TEXT, justify="center")

        tk.Label(box, text="DPI", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 8)).grid(row=0, column=0, sticky="w", padx=(0, 12))
        x_var = tk.StringVar(value=str(dpi.get("x", 1000)))
        y_var = tk.StringVar(value=str(dpi.get("y", 1000)))
        tk.Spinbox(box, from_=100, to=dpi_max, increment=50,
                   textvariable=x_var, **spin_kw).grid(row=0, column=1, padx=2)
        tk.Label(box, text="×", bg=CARD, fg=MUTED).grid(row=0, column=2)
        tk.Spinbox(box, from_=100, to=dpi_max, increment=50,
                   textvariable=y_var, **spin_kw).grid(row=0, column=3, padx=2)
        tk.Button(box, text="应用", bg="#1a2b4d", fg=TEXT, relief="flat", padx=12,
                  command=lambda: self._apply_dpi(d, x_var, y_var)).grid(
            row=0, column=4, padx=4)

        rates = extra.get("poll_rates") or [125, 500, 1000, 2000, 4000, 8000]
        poll_var = tk.StringVar(value=str(extra.get("poll_rate") or ""))
        tk.Label(box, text="轮询率", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 8)).grid(row=1, column=0, sticky="w",
                                                      padx=(0, 12), pady=(8, 0))
        ttk.Combobox(box, values=[str(r) for r in rates], textvariable=poll_var,
                     width=7, state="readonly").grid(row=1, column=1, padx=2, pady=(8, 0))
        tk.Label(box, text="Hz", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 8)).grid(row=1, column=2, pady=(8, 0))
        tk.Button(box, text="应用", bg="#1a2b4d", fg=TEXT, relief="flat", padx=12,
                  command=lambda: self._apply_poll_rate(d, poll_var)).grid(
            row=1, column=4, padx=4, pady=(8, 0))

    def _apply_dpi(self, d, x_var, y_var):
        try:
            x, y = int(x_var.get()), int(y_var.get())
        except ValueError:
            messagebox.showerror("写入失败", "DPI 必须是数字")
            return
        res = do_control("razer", d["id"], "dpi", {"x": x, "y": y})
        if not res.get("ok"):
            messagebox.showerror("写入失败", res.get("error", "未知错误"))
        self.refresh()

    def _apply_poll_rate(self, d, poll_var):
        raw = poll_var.get().strip()
        if not raw.isdigit():
            return
        res = do_control("razer", d["id"], "poll_rate", {"hz": int(raw)})
        if not res.get("ok"):
            messagebox.showerror("写入失败", res.get("error", "未知错误"))
        self.refresh()

    def _render_lighting(self, parent, d, lighting, on):
        box = tk.Frame(parent, bg=CARD)
        box.pack(fill="x", pady=(10, 0))

        tk.Label(box, text="灯效", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 8)).grid(row=0, column=0, sticky="w", padx=(0, 12))

        # 模式
        mode_var = tk.StringVar(value=MODE_BY_ID.get(lighting.get("mode"), "呼吸"))
        combo = ttk.Combobox(box, values=list(MODE_NAMES), textvariable=mode_var,
                             width=9, state="readonly")
        combo.grid(row=0, column=1, padx=4)

        # 亮度
        bright_var = tk.IntVar(value=lighting.get("brightness", 100))
        tk.Scale(box, from_=0, to=100, orient="horizontal", variable=bright_var,
                 bg=CARD, fg=TEXT, highlightthickness=0, troughcolor="#0b0d11",
                 length=150, showvalue=True).grid(row=0, column=2, padx=8)

        # 颜色
        color = lighting.get("color", [255, 0, 0])
        hexcolor = self._picked.setdefault(d["id"], "#%02x%02x%02x" % tuple(color))
        swatch = tk.Button(box, text="颜色", bg=hexcolor, fg="white", relief="flat",
                           width=6, command=lambda: self._pick_color(d["id"], swatch))
        swatch.grid(row=0, column=3, padx=4)

        tk.Button(box, text="应用", bg="#1a2b4d", fg=TEXT, relief="flat",
                  padx=12,
                  command=lambda: self._apply_lighting(d, mode_var, bright_var)).grid(
            row=0, column=4, padx=4)

        tk.Button(box, text="关闭灯效" if on else "开启灯效", bg="#0f1218", fg=TEXT,
                  relief="flat", padx=10,
                  command=lambda: self._toggle_lighting(d, on)).grid(row=0, column=5, padx=4)

    def _pick_color(self, dev_id, swatch):
        _, hexcolor = colorchooser.askcolor(
            color=self._picked.get(dev_id, "#ff0000"), title="选择灯效颜色")
        if hexcolor:
            self._picked[dev_id] = hexcolor
            swatch.config(bg=hexcolor)

    def _apply_lighting(self, d, mode_var, bright_var):
        hexcolor = self._picked.get(d["id"], "#ff0000")
        color = [int(hexcolor[1:3], 16), int(hexcolor[3:5], 16), int(hexcolor[5:7], 16)]
        payload = {"mode": MODE_NAMES.get(mode_var.get(), 2),
                   "brightness": bright_var.get(), "color": color}
        res = do_control("asus", d["id"], "lighting", payload)
        if not res.get("ok"):
            messagebox.showerror("写入失败", res.get("error", "未知错误"))
        self.refresh()

    def _toggle_lighting(self, d, currently_on):
        action = "lighting_off" if currently_on else "lighting_on"
        res = do_control("asus", d["id"], action, {})
        if not res.get("ok"):
            messagebox.showerror("写入失败", res.get("error", "未知错误"))
        self.root.after(300, self.refresh)


def run_window():
    root = tk.Tk()
    ui = HIDCircusUI(root)
    return root, ui
