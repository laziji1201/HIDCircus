/* HIDCircus 前端逻辑：状态、渲染、设置持久化。无构建步骤，直接跑。 */
(() => {
  "use strict";

  const VENDOR_HUE = { asus: "#ff5a5a", logitech: "#5ab8ff", razer: "#7ce38b" };
  const MODES = [1, 2, 3, 4];

  const state = {
    settings: null,
    devices: null,
    page: "devices",
    busy: false,
    lastUpdate: null,
    timer: null,
    firstLoad: true,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

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

  /* ---------------- 接口 ---------------- */

  async function api(path, options) {
    const res = await fetch(path, options);
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
    return `
      <div class="ctl">
        <div class="ctl-title">${esc(t("ctl.lighting"))}</div>
        <div class="ctl-row">
          <span class="ctl-label">${esc(t("ctl.mode"))}</span>
          <span class="selwrap">
            <select class="sel" data-f="mode" ${on ? "" : "disabled"}>
              ${MODES.map((m) => `<option value="${m}" ${m === mode ? "selected" : ""}>${esc(t("mode." + m))}</option>`).join("")}
            </select>
          </span>
          <button class="btn btn-ghost" data-act="lighting-toggle" data-on="${on ? "1" : "0"}">
            ${esc(on ? t("action.off") : t("action.on"))}
          </button>
        </div>
        <div class="ctl-row">
          <span class="ctl-label">${esc(t("ctl.brightness"))}</span>
          <input type="range" min="0" max="100" step="1" value="${bright}" data-f="brightness" ${on ? "" : "disabled"}>
          <span class="ctl-val">${bright}</span>
        </div>
        <div class="ctl-row">
          <span class="ctl-label">${esc(t("ctl.color"))}</span>
          <input type="color" value="${color}" data-f="color" ${on ? "" : "disabled"}>
          <button class="btn btn-primary" data-act="lighting" ${on ? "" : "disabled"}>${esc(t("action.apply"))}</button>
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

    return `
      <article class="card ${batteryClass(value)}" data-id="${esc(d.id)}" data-vendor="${esc(d.vendor_key || "")}">
        <div class="card-head">
          <i class="vdot" style="background:${hue};box-shadow:0 0 0 3px ${hue}22"></i>
          <span class="card-name">${esc(d.name)}</span>
          <span class="card-kind">${esc(kind)}</span>
          <span class="pill ${status.kind}">${esc(status.text)}</span>
        </div>
        <div class="battery">
          <span class="pct">${pct}</span><span class="unit">%</span>
        </div>
        <div class="track"><i style="width:${width}%;background:${batteryHue(value)}"></i></div>
        ${d.note && d.battery == null ? `<div class="note"><svg class="ico"><use href="#i-alert"/></svg><span>${esc(d.note)}</span></div>` : ""}
        ${body}
      </article>`;
  }

  function renderDevices() {
    const grid = $("#deviceGrid");
    const list = state.devices || [];
    renderStat(list);
    grid.innerHTML = list.map(cardHTML).join("");
    if (state.page === "settings") renderSettingsState();
    $("#emptyState").hidden = list.length > 0;
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

  /* ---------------- 事件 ---------------- */

  function wire() {
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

    $("#refreshSeg").addEventListener("click", async (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      await saveSettings({ refresh_seconds: Number(btn.dataset.value) });
      renderSettingsState();
      startTimer();
    });

    $("#bgPick").addEventListener("click", () => $("#bgFile").click());
    $("#bgFile").addEventListener("change", async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      if (file.size > 12 * 1024 * 1024) { toast(t("toast.tooBig"), "bad"); return; }
      const res = await fetch("/api/background", {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
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

    // 卡片内控件
    const grid = $("#deviceGrid");
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

  /* ---------------- 启动 ---------------- */

  async function boot() {
    if (localStorage.getItem("railCollapsed") === "1") {
      document.body.classList.add("rail-collapsed");
    }
    wire();
    if (location.hash === "#settings") state.page = "settings";
    try {
      await loadSettings();
    } catch (err) {
      state.settings = { theme: "auto", language: "zh", background: "", bg_dim: 0.55, bg_blur: 0, refresh_seconds: 10 };
    }
    applyTheme();
    applyLang();
    applyBackground();
    renderSettingsState();
    await loadDevices();
    startTimer();
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
