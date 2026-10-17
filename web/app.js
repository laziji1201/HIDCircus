/* HIDCircus 前端逻辑：状态、渲染、设置持久化。无构建步骤，直接跑。 */
(() => {
  "use strict";

  const VENDOR_HUE = { asus: "#ff5a5a", logitech: "#5ab8ff", razer: "#7ce38b" };
  const MODES = [1, 2, 3, 4];

  const PALETTES = [
    { id: "amber", key: "palette.amber", colors: ["#f2a33c", "#ffc46b"] },
    { id: "silver", key: "palette.silver", colors: ["#c9c9d3", "#ff5d13"] },
    { id: "sakura", key: "palette.sakura", colors: ["#fbb1c5", "#f1f0ed"] },
    { id: "neon", key: "palette.neon", colors: ["#52ffe9", "#ff3566"] },
  ];

  const state = {
    settings: null,
    devices: null,
    page: "devices",
    busy: false,
    lastUpdate: null,
    timer: null,
    firstLoad: true,
    pendingRender: false,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* 出错时不要白屏：把错误怼到页面上，省得只能靠日志猜 */
  function showFatal(msg) {
    let box = document.getElementById("fatalBox");
    if (!box) {
      box = document.createElement("pre");
      box.id = "fatalBox";
      document.body.appendChild(box);
    }
    box.textContent = String(msg).slice(0, 800);
    box.hidden = false;
  }
  window.addEventListener("error", (e) => showFatal(`${e.message}  @${e.filename || "?"}:${e.lineno}`));
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason;
    showFatal("Promise: " + (r && (r.stack || r.message) || r));
  });

  /* ---------------- 小工具 ---------------- */

  function t(key, vars) {
    const lang = (state.settings && state.settings.language) || "zh";
    const dict = window.I18N[lang] || window.I18N.zh;
    let text = dict[key] != null ? dict[key] : (window.I18N.zh[key] ?? key);
    if (vars) {
      for (const k in vars) text = text.replace(`{${k}}`, vars[k]);
    }
    return text;
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function pad2(n) { return String(n).padStart(2, "0"); }

  function nowHM() {
    const d = new Date();
    return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  }

  function hexToRgb(hex) {
    const v = String(hex || "#000000").replace("#", "");
    return [parseInt(v.slice(0, 2), 16) || 0,
            parseInt(v.slice(2, 4), 16) || 0,
            parseInt(v.slice(4, 6), 16) || 0];
  }

  function rgbToHex(rgb) {
    return "#" + (rgb || [0, 0, 0]).map((n) => pad2(Math.max(0, Math.min(255, n)).toString(16))).join("");
  }

  /* ---------------- 接口 ----------------
     写入类接口要求带 token：它是服务端启动时生成的，
     只有这个页面能拿到（注入在 HTML 里），别的本机程序调不动。 */

  const TOKEN = window.__TOKEN__ || "";

  async function api(path, options) {
    const opts = Object.assign({}, options);
    const method = (opts.method || "GET").toUpperCase();
    if (method !== "GET") {
      opts.headers = Object.assign({}, opts.headers, {
        "X-HIDCircus-Token": TOKEN,
      });
    }
    const res = await fetch(path, opts);
    if (!res.ok && res.status >= 500) throw new Error(`HTTP ${res.status}`);
    return res.json().catch(() => ({}));
  }

  async function loadSettings() {
    state.settings = await api("/api/settings");
  }

  async function saveSettings(patch) {
    const out = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (out && out.settings) state.settings = out.settings;
    return state.settings;
  }

  async function loadDevices(force = false) {
    if (state.busy) return;
    state.busy = true;
    setSync("busy");
    try {
      if (!state.devices) renderSkeleton();
      const out = await api("/api/devices" + (force ? "?_=" + Date.now() : ""));
      state.devices = out.devices || [];
      state.lastUpdate = new Date();
      renderDevices();
      setSync("live");
    } catch (err) {
      setSync("failed");
      if (!state.devices) {
        state.devices = [];
        renderDevices();
      }
    } finally {
      state.busy = false;
      if (state.firstLoad) hideLoader();   // 第一次不管成没成都把加载页收掉
      state.firstLoad = false;
    }
  }

  async function control(vendor, id, action, payload) {
    const out = await api("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vendor, device_id: id, action, payload }),
    });
    if (out && out.ok) {
      toast(t("toast.applied"), "ok");
      setTimeout(() => loadDevices(true), 180);
    } else {
      toast(`${t("toast.failed")}: ${(out && out.error) || "?"}`, "bad");
    }
    return out;
  }

  /* ---------------- 主题 / 语言 / 背景 ---------------- */

  function prefersDark() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function applyTheme() {
    const mode = (state.settings && state.settings.theme) || "auto";
    const dark = mode === "dark" || (mode === "auto" && prefersDark());
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    const icon = $("#themeIcon use");
    if (icon) icon.setAttribute("href", dark ? "#i-sun" : "#i-moon");
    const code = $("#themeCode");
    if (code) code.textContent = mode === "auto" ? t("theme.auto") : (dark ? t("theme.dark") : t("theme.light"));
  }

  function applyLang() {
    const lang = (state.settings && state.settings.language) || "zh";
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    const code = $("#langCode");
    if (code) code.textContent = lang === "en" ? "EN" : "中";
    renderPageHead();
    renderSettingsState();
    if (state.devices) renderDevices();
  }

  function applyMotion() {
    const mode = (state.settings && state.settings.motion) || "auto";
    document.documentElement.dataset.motion = mode === "on" ? "on" : "auto";
  }

  function applyPalette() {
    const id = (state.settings && state.settings.palette) || "amber";
    document.documentElement.dataset.palette = PALETTES.some((p) => p.id === id) ? id : "amber";
  }

  function applyBackground() {
    const s = state.settings || {};
    const has = !!s.background;
    const root = document.documentElement.style;
    root.setProperty("--bg-image", has ? `url("/assets/background/${encodeURIComponent(s.background)}?v=${Date.now()}")` : "none");
    root.setProperty("--bg-image-opacity", has ? "1" : "0");
    root.setProperty("--bg-dim", String(has ? (s.bg_dim ?? 0.55) : 0));
    root.setProperty("--bg-blur", `${has ? (s.bg_blur ?? 0) : 0}px`);
    const preview = $("#bgPreview");
    if (preview) {
      preview.style.backgroundImage = has ? `url("/assets/background/${encodeURIComponent(s.background)}?v=${Date.now()}")` : "";
      preview.textContent = has ? "" : t("settings.background.none");
    }
  }

  /* ---------------- 页面头 / 导航 ---------------- */

  function renderPageHead() {
    const isSettings = state.page === "settings";
    const title = $("#pageTitle");
    const sub = $("#pageSub");
    title.dataset.i18n = isSettings ? "page.settings" : "page.devices";
    sub.dataset.i18n = isSettings ? "page.settings.sub" : "page.devices.sub";
    title.textContent = t(title.dataset.i18n);
    sub.textContent = t(sub.dataset.i18n);
    $("#pageDevices").hidden = isSettings;
    $("#pageSettings").hidden = !isSettings;
    $$(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.page === state.page));
    $("#refreshBtn").style.visibility = isSettings ? "hidden" : "visible";
  }

  function setPage(page) {
    state.page = page === "settings" ? "settings" : "devices";
    if (location.hash !== "#" + state.page) {
      history.replaceState(null, "", "#" + state.page);
    }
    renderPageHead();
  }

  const BOOT_AT = performance.now();

  function hideLoader() {
    // 数据到得太快的话加载页会一闪而过，反而显得闪屏；至少留 650ms
    const wait = Math.max(0, 650 - (performance.now() - BOOT_AT));
    setTimeout(() => {
      const el = $("#loader");
      document.body.classList.remove("is-booting");
      if (!el) return;
      el.classList.add("is-hidden");
      setTimeout(() => el.remove(), 620);
    }, wait);
  }

  function setSync(kind) {
    const el = $("#sync");
    if (!el) return;
    el.classList.toggle("is-busy", kind === "busy");
    el.classList.toggle("is-live", kind === "live");
    const em = el.querySelector("em");
    if (kind === "busy") em.textContent = t("sync.busy");
    else if (kind === "live") em.textContent = t("sync.live", { time: state.lastUpdate ? `${pad2(state.lastUpdate.getHours())}:${pad2(state.lastUpdate.getMinutes())}` : nowHM() });
    else if (kind === "failed") em.textContent = t("sync.failed");
    else em.textContent = t("sync.idle");
  }

  /* ---------------- 设备渲染 ---------------- */

  function renderSkeleton() {
    const grid = $("#deviceGrid");
    grid.innerHTML = Array.from({ length: 3 }).map(() => `
      <article class="card skeleton">
        <div class="sk sk-line w40"></div>
        <div class="sk sk-big"></div>
        <div class="sk sk-bar"></div>
        <div class="sk sk-line w70" style="margin-top:16px"></div>
      </article>`).join("");
    $("#emptyState").hidden = true;
  }

  function batteryClass(value) {
    if (value == null) return "";
    if (value <= 20) return "is-low";
    if (value <= 50) return "is-mid";
    return "";
  }

  function batteryHue(value) {
    if (value == null) return "var(--text-3)";
    if (value <= 20) return "var(--bad)";
    if (value <= 50) return "var(--warn)";
    return "var(--ok)";
  }

  function statusOf(d) {
    if (d.note) return { kind: "is-bad", text: d.note };
    if (d.charging === true) return { kind: "is-warn", text: t("card.charging") };
    if (d.connected === false) return { kind: "is-bad", text: t("card.offline") };
    return { kind: "is-ok", text: t("card.connected") };
  }

  function lightingHTML(d) {
    const extra = d.extra || {};
    const light = extra.lighting;
    if (!light) return "";
    const on = extra.lighting_on !== false;
    const mode = Number(light.mode) || 2;
    const bright = Number(light.brightness) || 0;
    const color = rgbToHex(light.color);
    // 控件永远可改：灯效关着也能预设模式和颜色，按"应用"会顺手点亮
    return `
      <div class="ctl">
        <div class="ctl-head">
          <span class="ctl-title">${esc(t("ctl.lighting"))}</span>
          <button class="switch ${on ? "is-on" : ""}" data-act="lighting-toggle"
                  data-on="${on ? "1" : "0"}" aria-pressed="${on}">
            <i></i><span>${esc(on ? t("action.on") : t("action.off"))}</span>
          </button>
        </div>
        <div class="ctl-row">
          <span class="ctl-label">${esc(t("ctl.mode"))}</span>
          <span class="selwrap">
            <select class="sel" data-f="mode">
              ${MODES.map((m) => `<option value="${m}" ${m === mode ? "selected" : ""}>${esc(t("mode." + m))}</option>`).join("")}
            </select>
          </span>
        </div>
        <div class="ctl-row">
          <span class="ctl-label">${esc(t("ctl.brightness"))}</span>
          <input type="range" min="0" max="100" step="1" value="${bright}" data-f="brightness">
          <span class="ctl-val">${bright}</span>
        </div>
        <div class="ctl-row">
          <span class="ctl-label">${esc(t("ctl.color"))}</span>
          <input type="color" value="${color}" data-f="color">
          <button class="btn btn-primary" data-act="lighting">${esc(t("action.apply"))}</button>
        </div>
      </div>`;
  }

  function mouseHTML(d) {
    const extra = d.extra || {};
    if (!extra.dpi) return "";
    const rates = extra.poll_rates || [125, 500, 1000, 2000, 4000, 8000];
    const dpiMax = extra.dpi_max || 35000;
    const cur = extra.poll_rate;
    return `
      <div class="ctl">
        <div class="ctl-title">${esc(t("ctl.mouse"))}</div>
        <div class="ctl-row">
          <span class="ctl-label">${esc(t("ctl.dpi"))}</span>
          <input class="num" type="number" min="100" max="${dpiMax}" step="50" value="${Number(extra.dpi.x) || 0}" data-f="dpi-x">
          <span class="ctl-label" style="width:auto;color:var(--text-3)">×</span>
          <input class="num" type="number" min="100" max="${dpiMax}" step="50" value="${Number(extra.dpi.y) || 0}" data-f="dpi-y">
          <button class="btn btn-primary" data-act="dpi">${esc(t("action.apply"))}</button>
        </div>
        <div class="ctl-row">
          <span class="ctl-label">${esc(t("ctl.pollRate"))}</span>
          <span class="selwrap">
            <select class="sel" data-f="poll">
              ${rates.map((r) => `<option value="${r}" ${r === cur ? "selected" : ""}>${r} Hz</option>`).join("")}
            </select>
          </span>
          <button class="btn btn-primary" data-act="poll-rate">${esc(t("action.apply"))}</button>
        </div>
      </div>`;
  }

  function ringHTML(value) {
    const pct = value == null ? 0 : Math.max(0, Math.min(100, value));
    const hue = value == null ? "var(--text-3)"
      : value <= 20 ? "var(--bad)" : value <= 50 ? "var(--warn)" : "var(--ok)";
    const r = 19;
    const circ = 2 * Math.PI * r;
    const dash = (circ * pct) / 100;
    return `
      <div class="ring" style="--ring-hue:${hue}">
        <svg viewBox="0 0 44 44" aria-hidden="true">
          <circle class="ring-track" cx="22" cy="22" r="${r}"/>
          <circle class="ring-fill" cx="22" cy="22" r="${r}"
                  stroke-dasharray="${dash.toFixed(1)} ${circ.toFixed(1)}"/>
        </svg>
        <span class="ring-num"><span class="n">${value == null ? "—" : value}<em>%</em></span></span>
      </div>`;
  }

  function deviceIcon(kind) {
    if (kind === "headset") return "i-headset";
    if (kind === "keyboard") return "i-keyboard";
    if (kind === "mouse") return "i-mouse";
    return "i-devices";
  }

  function cardHTML(d) {
    const value = d.battery;
    const status = statusOf(d);
    const hue = VENDOR_HUE[d.vendor_key] || "var(--text-3)";
    const kind = t("kind." + (d.kind || "unknown"));
    const width = value == null ? 0 : Math.max(2, value);
    const pct = value == null ? "—" : value;
    const extra = d.extra || {};

    const hasLighting = d.vendor_key === "asus" && !!extra.lighting;
    const hasMouse = d.vendor_key === "razer" && !!extra.dpi;
    const controls = (hasLighting ? lightingHTML(d) : "") +
                     (hasMouse ? mouseHTML(d) : "");
    const body = controls ||
      `<div class="ctl-empty">${esc(t("ctl.none"))}</div>`;

    // 环形进度只占一小块，腾出来的垂直空间给下面的设置项
    const facts = [];
    if (extra.dpi) facts.push(`DPI  X ${Number(extra.dpi.x) || "—"} · Y ${Number(extra.dpi.y) || "—"}`);
    if (extra.poll_rate) facts.push(`${extra.poll_rate} Hz`);

    return `
      <article class="card ${batteryClass(value)}" data-id="${esc(d.id)}" data-vendor="${esc(d.vendor_key || "")}">
        <div class="card-head">
          <i class="vdot" style="background:${hue};box-shadow:0 0 0 3px ${hue}22"></i>
          <span class="card-name" data-alias="${esc(d.id)}" title="${esc(t("alias.prompt"))}">${esc(d.name)}</span>
          <span class="card-kind">${esc(kind)}</span>
          <span class="pill ${status.kind}">${esc(status.text)}</span>
        </div>
        <div class="battery-row">
          ${ringHTML(value)}
          <div class="battery-meta">
            ${d.charging === true ? `<span class="state is-warn">${esc(t("card.charging"))}</span>` : ""}
            ${facts.length ? `<span class="facts">${esc(facts.join(" · "))}</span>` : ""}
            ${d.note && d.battery == null ? `<span class="facts" style="color:var(--bad)">${esc(d.note)}</span>` : ""}
          </div>
        </div>
        ${body}
      </article>`;
  }

  function ordered(list) {
    const order = (state.settings && state.settings.device_order) || [];
    if (!order.length) return list;
    const rank = new Map(order.map((id, i) => [id, i]));
    return list.slice().sort((a, b) => {
      const ra = rank.has(a.id) ? rank.get(a.id) : 1e9;
      const rb = rank.has(b.id) ? rank.get(b.id) : 1e9;
      return ra - rb;
    });
  }

  function renderDevices() {
    const grid = $("#deviceGrid");
    if (drag.active) {                 // 拖拽过程中别重排，等放手再刷
      state.pendingRender = true;
      return;
    }
    const list = ordered(state.devices || []);
    renderStat(list);
    grid.innerHTML = list.map(cardHTML).join("");
    if (state.page === "settings") renderSettingsState();
    $("#emptyState").hidden = list.length > 0;
    const hint = $("#dragHint");
    if (hint) hint.hidden = list.length < 2;
  }

  function renderStat(list) {
    const el = $("#topStat");
    if (!el) return;
    const values = list.map((d) => d.battery).filter((v) => typeof v === "number");
    if (!list.length) { el.hidden = true; return; }
    el.hidden = false;
    const low = values.length ? Math.min(...values) : null;
    el.innerHTML = low == null
      ? `${list.length}<b>${esc(t("stat.unit"))}</b>`
      : `${list.length}<b>${esc(t("stat.unit"))}</b>· ${esc(t("stat.low"))}<b>${low}%</b>`;
  }

  /* ---------------- 设置页状态 ---------------- */

  function renderSettingsState() {
    const s = state.settings || {};
    const mark = (sel, value) => {
      $$(`${sel} button`).forEach((b) =>
        b.classList.toggle("is-active", String(b.dataset.value) === String(value)));
    };
    mark("#themeSeg", s.theme || "auto");
    mark("#langSeg", s.language || "zh");
    mark("#refreshSeg", String(s.refresh_seconds ?? 10));
    mark("#motionSeg", s.motion || "auto");
    renderPalettes(s.palette || "silver");
    renderExtensions();
    renderExtHelp();

    const dim = Math.round((s.bg_dim ?? 0.55) * 100);
    const blur = Math.round(s.bg_blur ?? 0);
    const dimInput = $("#bgDim"), blurInput = $("#bgBlur");
    if (dimInput && document.activeElement !== dimInput) dimInput.value = dim;
    if (blurInput && document.activeElement !== blurInput) blurInput.value = blur;
    $("#bgDimOut").textContent = `${dimInput ? dimInput.value : dim}%`;
    $("#bgBlurOut").textContent = `${blurInput ? blurInput.value : blur}px`;

    const vendors = Array.from(new Set((state.devices || []).map((d) => d.vendor))).filter(Boolean);
    $("#aboutProviders").textContent = vendors.length ? vendors.join(" / ") : "—";
    $("#aboutUrl").textContent = location.origin;
    api("/api/autostart").then((st) => {
      mark("#autostartSeg", st && st.enabled ? "on" : "off");
    }).catch(() => {});
    api("/api/status").then((st) => {
      const tray = $("#aboutTray");
      if (tray && st) {
        if (st.tray === true) { tray.textContent = t("about.trayOk"); tray.style.color = "var(--ok)"; }
        else if (st.tray === false) { tray.textContent = t("about.trayOff"); tray.style.color = "var(--warn)"; }
        else tray.textContent = "—";
      }
      const logEl = $("#aboutLog");
      if (logEl && st && st.log) logEl.textContent = st.log.replace(/^.*[\\/]/, "logs/");
    }).catch(() => {});
  }

  const EXT_TEMPLATE = {
    spec: 1,
    id: "vendor-model",
    name: "厂商 型号（电量）",
    author: "你的名字",
    match: { vid: "0x046D", pid: ["0xC548"], usage_page: "0xFF00" },
    device: { name: "型号", kind: "mouse", vendor_label: "厂商" },
    read: {
      battery: {
        transport: "feature",
        report_id: "0x51",
        request: "0x28 0x00",
        read_size: 64,
        reply_check: { offset: 1, equals: "0x51" },
        value: { offset: 6, size: 1, scale: 1, min: 0, max: 100 },
      },
      charging: {
        transport: "feature",
        report_id: "0x51",
        request: "0x28 0x01",
        value: { offset: 5, equals: "1" },
      },
    },
  };

  function renderExtHelp() {
    const pre = $("#extTemplate");
    if (!pre || pre.dataset.filled === "1") return;
    pre.textContent = JSON.stringify(EXT_TEMPLATE, null, 2);
    pre.dataset.filled = "1";

    const copy = $("#extCopy");
    if (copy) {
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(pre.textContent);
          toast(t("ext.copied"), "ok");
        } catch (_) {
          toast(t("toast.failed"), "bad");
        }
      });
    }
    const openDir = $("#extOpenDir");
    if (openDir) {
      openDir.addEventListener("click", async () => {
        const out = await api("/api/extensions/open-dir", { method: "POST" })
          .catch(() => ({ ok: false }));
        if (!out.ok) toast(`${t("toast.failed")}: ${out.error || "?"}`, "bad");
      });
    }
  }

  async function renderExtensions() {
    const box = $("#extList");
    if (!box) return;
    const data = await api("/api/extensions").catch(() => null);
    if (!data) { box.innerHTML = ""; return; }
    const rows = [];
    (data.loaded || []).forEach((e) => {
      rows.push(`
        <div class="ext-row">
          <i class="vdot" style="background:var(--ok)"></i>
          <span class="ext-name">${esc(e.name)}</span>
          <span class="ext-meta">${esc(e.vid)}/${esc(e.pids.join(" "))} · ${esc(e.file)}</span>
          <a class="ext-export" href="/api/extensions/export?id=${encodeURIComponent(e.id)}"
             download>${esc(t("ext.export"))}</a>
        </div>`);
    });
    (data.errors || []).forEach((msg) => {
      rows.push(`
        <div class="ext-row is-error">
          <i class="vdot" style="background:var(--bad)"></i>
          <span class="ext-name">${esc(msg)}</span>
        </div>`);
    });
    if (!rows.length) {
      rows.push(`<div class="ext-empty">${esc(t("ext.empty"))}</div>`);
    }
    rows.push(`
      <button class="btn btn-ghost" id="extReport" style="margin-top:6px">
        ${esc(t("ext.report"))}
      </button>`);
    box.innerHTML = rows.join("");
    const report = $("#extReport");
    if (report) {
      report.addEventListener("click", () => {
        const a = document.createElement("a");
        a.href = "/api/hid-report";
        a.download = "hidcircus-hid-report.json";
        a.click();
      });
    }
    const dir = $("#extDir");
    if (dir) dir.textContent = (data.dirs || []).join("  ·  ");
  }

  function renderPalettes(active) {
    const box = $("#paletteSeg");
    if (!box) return;
    // 文案跟着语言走：语言变了就重建按钮；点击事件只绑一次，避免重复累积
    const lang = (state.settings && state.settings.language) || "zh";
    if (box.dataset.built !== lang) {
      box.innerHTML = PALETTES.map((p) => `
        <button class="palette-item" data-value="${p.id}">
          <span class="swatch" style="background:linear-gradient(140deg, ${p.colors[0]}, ${p.colors[1]})"></span>
          <span>${esc(t(p.key))}</span>
        </button>`).join("");
      box.dataset.built = lang;
    }
    if (box.dataset.bound !== "1") {
      box.dataset.bound = "1";
      box.addEventListener("click", async (e) => {
        const btn = e.target.closest("button[data-value]");
        if (!btn) return;
        await saveSettings({ palette: btn.dataset.value });
        applyPalette();
        renderSettingsState();
      });
    }
    Array.from(box.querySelectorAll("button[data-value]")).forEach((b) =>
      b.classList.toggle("is-active", b.dataset.value === active));
  }

  /* ---------------- 配置备份 ---------------- */

  const PORTABLE_KEYS = ["theme", "language", "palette", "motion", "bg_dim",
                         "bg_blur", "refresh_seconds", "device_order", "aliases"];

  function exportSettings() {
    const s = state.settings || {};
    const out = {};
    PORTABLE_KEYS.forEach((k) => { if (s[k] !== undefined) out[k] = s[k]; });
    out._app = "HIDCircus";
    out._version = 1;
    const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "hidcircus-settings.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    toast(t("toast.exported"), "ok");
  }

  async function importSettings(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    let data;
    try {
      data = JSON.parse(await file.text());
    } catch (_) {
      toast(t("toast.importFailed"), "bad");
      return;
    }
    const patch = {};
    PORTABLE_KEYS.forEach((k) => { if (data[k] !== undefined) patch[k] = data[k]; });
    if (!Object.keys(patch).length) {
      toast(t("toast.importFailed"), "bad");
      return;
    }
    const out = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (out.ok) {
      state.settings = out.settings;
      applyTheme(); applyPalette(); applyMotion(); applyLang(); applyBackground();
      renderSettingsState(); renderDevices();
      toast(t("toast.imported"), "ok");
    } else {
      toast(`${t("toast.failed")}: ${out.error || "?"}`, "bad");
    }
  }

  /* ---------------- 设备别名 ---------------- */

  async function renameDevice(id, current) {
    const name = window.prompt(t("alias.prompt"), current || "");
    if (name === null) return;
    const aliases = Object.assign({}, (state.settings && state.settings.aliases) || {});
    if (name.trim()) aliases[id] = name.trim();
    else delete aliases[id];
    const out = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ aliases }),
    });
    if (out.ok) {
      state.settings = out.settings;
      await loadDevices(true);
      toast(t("toast.aliasSaved"), "ok");
    } else {
      toast(`${t("toast.failed")}: ${out.error || "?"}`, "bad");
    }
  }

  /* ---------------- 提示 ---------------- */

  function toast(message, kind) {
    const box = $("#toasts");
    const el = document.createElement("div");
    el.className = `toast ${kind ? "is-" + kind : ""}`;
    el.innerHTML = `<svg class="ico"><use href="#${kind === "bad" ? "i-alert" : "i-check"}"/></svg><span>${esc(message)}</span>`;
    box.appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity 200ms, transform 200ms";
      el.style.opacity = "0";
      el.style.transform = "translateY(6px)";
      setTimeout(() => el.remove(), 220);
    }, 2600);
  }

  /* ---------------- 拖拽排序（长按 320ms 进入） ---------------- */

  const drag = { active: false, card: null, ph: null, offX: 0, offY: 0,
                 timer: null, sx: 0, sy: 0 };

  function gridCards() {
    return Array.from($("#deviceGrid").children).filter((el) => el.matches(".card"));
  }

  function cancelArm() {
    if (drag.timer) { clearTimeout(drag.timer); drag.timer = null; }
    if (drag.card) drag.card.classList.remove("is-armed");
    drag.card = null;
  }

  function beginDrag() {
    const card = drag.card;
    if (!card || drag.active) return;
    drag.timer = null;
    drag.active = true;

    const rect = card.getBoundingClientRect();
    const ph = document.createElement("div");
    ph.className = "card-placeholder";
    ph.style.width = `${rect.width}px`;
    ph.style.height = `${rect.height}px`;
    card.after(ph);
    drag.ph = ph;
    drag.offX = drag.sx - rect.left;
    drag.offY = drag.sy - rect.top;

    card.classList.remove("is-armed");
    card.classList.add("is-dragging");
    Object.assign(card.style, {
      position: "fixed",
      left: `${rect.left}px`,
      top: `${rect.top}px`,
      width: `${rect.width}px`,
      height: `${rect.height}px`,
      margin: "0",
    });
    document.body.classList.add("is-dragging");
  }

  function moveDrag(x, y) {
    const card = drag.card;
    if (!drag.active || !card) return;
    card.style.left = `${x - drag.offX}px`;
    card.style.top = `${y - drag.offY}px`;

    // 找离指针最近的槽位，把占位块挪过去
    let best = null;
    let bestDist = Infinity;
    for (const el of $("#deviceGrid").children) {
      if (el === card) continue;
      const r = el.getBoundingClientRect();
      const d = (x - (r.left + r.width / 2)) ** 2 + (y - (r.top + r.height / 2)) ** 2;
      if (d < bestDist) { bestDist = d; best = el; }
    }
    if (!best || best === drag.ph) return;
    const r = best.getBoundingClientRect();
    if (x > r.left + r.width / 2) best.after(drag.ph);
    else best.before(drag.ph);
  }

  async function endDrag() {
    if (!drag.active) { cancelArm(); return; }
    const card = drag.card;
    const ph = drag.ph;
    card.classList.remove("is-dragging");
    card.removeAttribute("style");
    ph.replaceWith(card);
    drag.active = false;
    drag.card = null;
    drag.ph = null;
    document.body.classList.remove("is-dragging");

    const ids = gridCards().map((el) => el.dataset.id);
    await saveSettings({ device_order: ids });
    if (state.pendingRender) {
      state.pendingRender = false;
      renderDevices();
    }
    toast(t("toast.orderSaved"), "ok");
  }
  /* ---------------- 事件 ---------------- */

  function wire() {
    const grid = $("#deviceGrid");

    $$(".nav-item").forEach((btn) =>
      btn.addEventListener("click", () => setPage(btn.dataset.page)));

    $("#refreshBtn").addEventListener("click", () => loadDevices(true));

    $("#railToggle").addEventListener("click", () => {
      document.body.classList.toggle("rail-collapsed");
      localStorage.setItem("railCollapsed", document.body.classList.contains("rail-collapsed") ? "1" : "0");
    });

    $("#themeBtn").addEventListener("click", async () => {
      const order = ["auto", "dark", "light"];
      const cur = (state.settings && state.settings.theme) || "auto";
      const next = order[(order.indexOf(cur) + 1) % order.length];
      await saveSettings({ theme: next });
      applyTheme();
      renderSettingsState();
    });

    $("#langBtn").addEventListener("click", async () => {
      const next = ((state.settings && state.settings.language) === "en") ? "zh" : "en";
      await saveSettings({ language: next });
      applyLang();
    });

    $("#themeSeg").addEventListener("click", async (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      await saveSettings({ theme: btn.dataset.value });
      applyTheme();
      renderSettingsState();
    });

    $("#langSeg").addEventListener("click", async (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      await saveSettings({ language: btn.dataset.value });
      applyLang();
    });

    $("#autostartSeg").addEventListener("click", async (e) => {
      const btn = e.target.closest("button[data-value]");
      if (!btn) return;
      const on = btn.dataset.value === "on";
      const out = await api("/api/autostart", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on }),
      });
      if (out.ok) {
        toast(on ? t("toast.autostartOn") : t("toast.autostartOff"), "ok");
        mark("#autostartSeg", on ? "on" : "off");
      } else {
        toast(`${t("toast.failed")}: ${out.error || out.message || "?"}`, "bad");
      }
    });

    // 双击设备名 = 改别名（留空恢复原厂名）
    $("#deviceGrid").addEventListener("dblclick", (e) => {
      const el = e.target.closest("[data-alias]");
      if (!el) return;
      const id = el.dataset.alias;
      const dev = (state.devices || []).find((d) => d.id === id);
      renameDevice(id, dev ? (dev.raw_name === dev.name ? "" : dev.name) : "");
    });

    $("#exportSettings").addEventListener("click", exportSettings);
    $("#importSettings").addEventListener("click", () => $("#importFile").click());
    $("#importFile").addEventListener("change", importSettings);

    $("#refreshSeg").addEventListener("click", async (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      await saveSettings({ refresh_seconds: Number(btn.dataset.value) });
      renderSettingsState();
      startTimer();
    });

    $("#motionSeg").addEventListener("click", async (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      await saveSettings({ motion: btn.dataset.value });
      applyMotion();
      renderSettingsState();
    });

    $("#bgPick").addEventListener("click", () => $("#bgFile").click());
    $("#bgFile").addEventListener("change", async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      if (file.size > 12 * 1024 * 1024) { toast(t("toast.tooBig"), "bad"); return; }
      const res = await fetch("/api/background", {
        method: "POST",
        headers: {
          "Content-Type": file.type || "application/octet-stream",
          "X-HIDCircus-Token": TOKEN,
        },
        body: file,
      });
      const out = await res.json().catch(() => ({}));
      if (out.ok) {
        state.settings = out.settings;
        applyBackground();
        renderSettingsState();
        toast(t("toast.bgSet"), "ok");
      } else {
        toast(`${t("toast.failed")}: ${out.error || "?"}`, "bad");
      }
      e.target.value = "";
    });

    $("#bgClear").addEventListener("click", async () => {
      const out = await api("/api/background", { method: "DELETE" });
      if (out && out.settings) state.settings = out.settings;
      applyBackground();
      renderSettingsState();
      toast(t("toast.bgCleared"), "ok");
    });

    const dim = $("#bgDim"), blur = $("#bgBlur");
    dim.addEventListener("input", () => {
      $("#bgDimOut").textContent = `${dim.value}%`;
      document.documentElement.style.setProperty("--bg-dim", (dim.value / 100).toFixed(2));
    });
    dim.addEventListener("change", () => saveSettings({ bg_dim: Number(dim.value) / 100 }));
    blur.addEventListener("input", () => {
      $("#bgBlurOut").textContent = `${blur.value}px`;
      document.documentElement.style.setProperty("--bg-blur", `${blur.value}px`);
    });
    blur.addEventListener("change", () => saveSettings({ bg_blur: Number(blur.value) }));

    // 长按卡片进入拖拽排序
    grid.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || drag.active) return;
      if (e.target.closest("input, button, select, textarea, a, label")) return;
      const card = e.target.closest(".card");
      if (!card) return;
      drag.card = card;
      drag.sx = e.clientX;
      drag.sy = e.clientY;
      card.classList.add("is-armed");
      drag.timer = setTimeout(beginDrag, 320);
    });

    window.addEventListener("pointermove", (e) => {
      if (!drag.active) {
        if (!drag.card) return;
        if (Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) > 8) cancelArm();
        return;
      }
      drag.sx = e.clientX;
      drag.sy = e.clientY;
      moveDrag(e.clientX, e.clientY);
    });

    window.addEventListener("pointerup", () => { endDrag(); });
    window.addEventListener("pointercancel", () => { endDrag(); });
    // 卡片内控件
    grid.addEventListener("input", (e) => {
      const el = e.target;
      if (el.matches('input[type="range"][data-f="brightness"]')) {
        const val = el.parentElement.querySelector(".ctl-val");
        if (val) val.textContent = el.value;
      }
    });

    grid.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-act]");
      if (!btn) return;
      const card = btn.closest(".card");
      if (!card) return;
      const id = card.dataset.id;
      const vendor = card.dataset.vendor;
      const get = (f) => card.querySelector(`[data-f="${f}"]`);

      if (btn.dataset.act === "lighting") {
        const color = hexToRgb(get("color").value);
        const toggle = card.querySelector('[data-act="lighting-toggle"]');
        // 灯效关着的时候改模式/颜色，顺手点亮，否则用户看不到效果
        if (toggle && toggle.dataset.on !== "1") {
          await control(vendor, id, "lighting_on", {});
        }
        await control(vendor, id, "lighting", {
          mode: Number(get("mode").value),
          brightness: Number(get("brightness").value),
          color,
        });
      } else if (btn.dataset.act === "lighting-toggle") {
        const on = btn.dataset.on === "1";
        await control(vendor, id, on ? "lighting_off" : "lighting_on", {});
      } else if (btn.dataset.act === "dpi") {
        await control(vendor, id, "dpi", {
          x: Number(get("dpi-x").value),
          y: Number(get("dpi-y").value),
        });
      } else if (btn.dataset.act === "poll-rate") {
        await control(vendor, id, "poll_rate", { hz: Number(get("poll").value) });
      }
    });

    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (((state.settings && state.settings.theme) || "auto") === "auto") {
        applyTheme();
        renderSettingsState();
      }
    });
  }

  function startTimer() {
    if (state.timer) clearInterval(state.timer);
    const seconds = Number((state.settings && state.settings.refresh_seconds) ?? 10);
    if (!seconds) return;
    state.timer = setInterval(() => {
      if (state.page === "devices" && document.visibilityState === "visible") loadDevices();
    }, Math.max(3, seconds) * 1000);
  }

  /* ---------------- 心跳 ----------------
     桌面端靠它判断"面板还开着"，没有托盘时决定进程要不要退出。
     任何浏览器、有无边框都不影响。 */

  function startHeartbeat() {
    const ping = () => {
      fetch("/api/ping", { method: "POST", keepalive: true }).catch(() => {});
    };
    ping();
    setInterval(ping, 4000);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") ping();
    });
  }

  /* ---------------- 启动 ---------------- */

  async function boot() {
    if (localStorage.getItem("railCollapsed") === "1") {
      document.body.classList.add("rail-collapsed");
    }
    wire();
    startHeartbeat();
    if (location.hash === "#settings") state.page = "settings";
    try {
      await loadSettings();
    } catch (err) {
      state.settings = { theme: "auto", language: "zh", background: "", bg_dim: 0.72,
                         bg_blur: 0, refresh_seconds: 10, palette: "amber", device_order: [] };
    }
    applyTheme();
    applyPalette();
    applyMotion();
    applyLang();
    applyBackground();
    renderSettingsState();
    await loadDevices();
    startTimer();
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
