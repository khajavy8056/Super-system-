/* Mobile stocktaking app (§21–25).
 * - Every count is saved IMMEDIATELY (§25): online -> server, offline -> local queue.
 * - Offline queue in IndexedDB; sync on reconnect with conflict detection (§26):
 *   if the server item changed (system_qty moved / session closed) the queued
 *   count becomes a CONFLICT for human resolution — never silently overwritten.
 * - Camera scanning uses the native BarcodeDetector API where available
 *   (Android Chrome). Browsers without it fall back to manual entry — reported
 *   honestly, never faked.
 */
"use strict";

const $ = (s) => document.querySelector(s);
/* v1.6 — inside the Android shell the web app is served from https://app.local and
 * talks to the shop PC at the paired address (Prefs/localStorage "m_server").
 * In a browser tab (LAN PWA) it stays relative. */
const NATIVE = window.SupermarketAndroid || null;
const SERVER = (NATIVE && NATIVE.getServerUrl && NATIVE.getServerUrl()) || localStorage.getItem("m_server") || "";
if (NATIVE && NATIVE.getDeviceToken && NATIVE.getDeviceToken() && !localStorage.getItem("m_token")) localStorage.setItem("m_token", NATIVE.getDeviceToken());
const API = (SERVER ? SERVER : "") + "/api";
const STANDALONE = /standalone\.invalid/.test(SERVER) || localStorage.getItem("m_standalone") === "1";
const DEVICE_ID = (NATIVE && NATIVE.getDeviceId && NATIVE.getDeviceId()) || localStorage.getItem("m_device") || "";
window.SM_MOBILE = { API, SERVER, DEVICE_ID, native: !!NATIVE };
const state = {
  token: localStorage.getItem("m_token") || "",
  user: null,
  session: null,        // {id, name, status, items: []}
  cursor: 0,            // index into pending-ish items
  online: navigator.onLine,
  view: "home",
  currency: { code: "IRT", label: "تومان" },
  units: [],
  cart: [],             // mobile POS cart
};


/* ---------------------------------------------------------------------------
 * Inline SVG icon set. Emoji were replaced because they render as tofu boxes
 * on devices/kiosks without an emoji font and look consumer-grade; these are
 * font-independent, inherit currentColor, and match the desktop panel.
 * ------------------------------------------------------------------------ */
const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
  pos: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h5"/>',
  clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="M9 10h6M9 14h4"/>',
  warehouse: '<path d="M3 21V9l9-5 9 5v12"/><path d="M8 21v-7h8v7"/>',
  more: '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
  camera: '<path d="M4 7h3l1.5-2h7L17 7h3v13H4z"/><circle cx="12" cy="13" r="3.6"/>',
  box: '<path d="M3 8l9-5 9 5v8l-9 5-9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
  user: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"/>',
  gift: '<rect x="3" y="9" width="18" height="12" rx="1.5"/><path d="M3 13h18M12 9v12"/><path d="M12 9C10 9 8 8 8 6.5S9.5 4 12 9zM12 9c2 0 4-1 4-2.5S14.5 4 12 9z"/>',
  invoice: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
  chart: '<path d="M4 20V4"/><path d="M4 20h16"/><path d="M8 16v-5M12 16V7M16 16v-8"/>',
  sync: '<path d="M20 12a8 8 0 0 1-13.7 5.6M4 12a8 8 0 0 1 13.7-5.6"/><path d="M4 18v-4h4M20 6v4h-4"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/>',
  exit: '<path d="M14 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4"/><path d="M9 8l-4 4 4 4M5 12h9"/>',
  inbox: '<path d="M4 13h4l1.5 3h5L16 13h4"/><path d="M4 13 6.5 5h11L20 13v6H4z"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
  cart: '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/><path d="M3 4h2.5l2.6 11h10L21 7H6"/>',
  check: '<path d="M4 12.5l5 5L20 6.5"/>',
  back: '<path d="M14 5l7 7-7 7"/><path d="M21 12H4"/>',
  minus: '<path d="M5 12h14"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
};

/* size: px; the stroke scales with it so icons stay crisp at any tab size. */
const icon = (name, size = 20) =>
  `<svg class="ic" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none"
     stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
     stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;

/* ---------- tiny helpers ---------- */
function toast(msg, kind = "ok") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast " + kind;
  el.classList.remove("hidden");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 3000);
}
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtNum = (n) => {
  const v = Number(n || 0);
  return Number.isInteger(v) ? v.toLocaleString("en-US")
                             : parseFloat(v.toFixed(3)).toLocaleString("en-US");
};
/* v1.7.1: every timestamp from the PC is naive UTC → show it in the store timezone (Tehran, +03:30) */
const STORE_TZ = () => localStorage.getItem("m_tz") || "Asia/Tehran";
const faDT = (iso, withTime = true) => {
  if (!iso) return "—";
  const str = String(iso); const d = new Date(/[Zz]|[+-]\d\d:?\d\d$/.test(str) ? str : str + "Z");
  if (isNaN(d)) return "—";
  const o = { year: "numeric", month: "2-digit", day: "2-digit", timeZone: STORE_TZ() }; if (withTime) { o.hour = "2-digit"; o.minute = "2-digit"; }
  try { return new Intl.DateTimeFormat("fa-IR-u-ca-persian", o).format(d); } catch (_) { return d.toLocaleString("fa-IR"); }
};
window.faDT = faDT;
const money = (n) => fmtNum(Math.round(Number(n || 0))) + " " + (state.currency.label || "");
const qtyFmt = (n) => fmtNum(n);
const unitById = (id) => state.units.find((u) => u.id === id) || null;

async function api(path, opts = {}) {
  const headers = { ...(opts.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...(opts.headers || {}) };
  if (state.token) headers.Authorization = "Bearer " + state.token;
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 204) return null;
  let body = null;
  try { body = await res.json(); } catch (_) {}
  if (!res.ok) {
    const d = body && body.detail;
    const msg = typeof d === "object" ? (d.message || d.code || JSON.stringify(d)) : (d || res.statusText);
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return body;
}

/* GS1 checksum (same rules as the backend) — reject mis-scans before any I/O */
function barcodeChecksumOk(bc) {
  if (!bc || !/^\d+$/.test(bc)) return false;
  if (![8, 12, 13, 14].includes(bc.length)) return false;
  let total = 0;
  const rev = bc.split("").reverse();
  for (let i = 0; i < rev.length; i++) {
    let n = Number(rev[i]);
    if (i % 2 === 1) n *= 3;
    total += n;
  }
  return total % 10 === 0;
}

/* ---------- IndexedDB (offline queue + session cache + conflicts) ---------- */
const DB_NAME = "supermarket_mobile";
const DB_VERSION = 2;

function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("queue")) db.createObjectStore("queue", { keyPath: "id", autoIncrement: true });
      if (!db.objectStoreNames.contains("conflicts")) db.createObjectStore("conflicts", { keyPath: "id", autoIncrement: true });
      if (!db.objectStoreNames.contains("cache")) db.createObjectStore("cache", { keyPath: "key" });
      if (!db.objectStoreNames.contains("ops")) db.createObjectStore("ops", { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbTx(store, mode, fn) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const st = tx.objectStore(store);
    const out = fn(st);
    tx.oncomplete = () => resolve(out && out.result !== undefined ? out.result : out);
    tx.onerror = () => reject(tx.error);
  });
}
const queueAdd = (entry) => idbTx("queue", "readwrite", (st) => st.add(entry));
const queueAll = () => idbTx("queue", "readonly", (st) => st.getAll());
const queueDelete = (id) => idbTx("queue", "readwrite", (st) => st.delete(id));
const conflictAdd = (entry) => idbTx("conflicts", "readwrite", (st) => st.add(entry));
const conflictAll = () => idbTx("conflicts", "readonly", (st) => st.getAll());
const conflictDelete = (id) => idbTx("conflicts", "readwrite", (st) => st.delete(id));
const cachePut = (key, value) => idbTx("cache", "readwrite", (st) => st.put({ key, value }));
const cacheGet = (key) => idbTx("cache", "readonly", (st) => st.get(key));
/* v1.6 — generic store-and-forward operation queue (sales, receipts, …) replayed via POST /api/mobile/sync */
const opsAll = () => idbTx("ops", "readonly", (st) => st.getAll());
const opsDelete = (id) => idbTx("ops", "readwrite", (st) => st.delete(id));
async function opQueueAdd(type, payload, label, local_no) {
  const id = "op" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  await idbTx("ops", "readwrite", (st) => st.add({ id, type, payload, label, local_no: local_no || null, created_at: new Date().toISOString() }));
  updateSyncPill();
  return id;
}
window.mobileSync = mobileSync; window.opQueueAdd = opQueueAdd; window.opsAll = opsAll; window.conflictAll = conflictAll;
/* v1.7 — internet path: when the shop PC is not reachable but the phone has
 * internet and the pairing carried a cloud mailbox (same Google account as the
 * PC), drop the queued ops there and refresh the cache from the PC's snapshot. */
const cloudCfg = () => { try { return JSON.parse(localStorage.getItem("m_cloud") || "null"); } catch (_) { return null; } };
async function cloudToken(c) {
  const cached = JSON.parse(localStorage.getItem("m_cloud_tok") || "null");
  if (cached && cached.exp > Date.now()) return cached.t;
  const r = await fetch(c.token_url, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: c.client_id, client_secret: c.client_secret, refresh_token: c.refresh_token, grant_type: "refresh_token" }).toString() });
  const j = await r.json(); if (!j.access_token) throw new Error("اتصال ابری برقرار نشد");
  localStorage.setItem("m_cloud_tok", JSON.stringify({ t: j.access_token, exp: Date.now() + (j.expires_in - 60) * 1000 }));
  return j.access_token;
}
async function cloudSync(showToast) {
  const c = cloudCfg(); if (!c || !navigator.onLine) return false;
  const ops = await opsAll();
  try {
    const tok = await cloudToken(c); const H = { Authorization: "Bearer " + tok };
    if (ops.length) {
      const name = `ops-${DEVICE_ID || "phone"}-${Date.now()}.json`;
      const boundary = "smkt-b"; const meta = JSON.stringify({ name, parents: ["appDataFolder"] });
      const body = `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${meta}\r\n--${boundary}\r\nContent-Type: application/json\r\n\r\n${JSON.stringify({ device_id: DEVICE_ID, token: state.token, push: ops.map((o) => ({ id: o.id, type: o.type, payload: cleanLocalIds(o.payload), created_at: o.created_at })) })}\r\n--${boundary}--`;
      const up = await fetch(`${c.upload_url}/files?uploadType=multipart`, { method: "POST", headers: { ...H, "Content-Type": `multipart/related; boundary=${boundary}` }, body });
      if (!up.ok) throw new Error("ارسال به فضای ابری ناموفق بود");
      for (const o of ops) await opsDelete(o.id);
      localStorage.setItem("m_cloud_push", new Date().toISOString());
    }
    const lst = await (await fetch(`${c.api_url}/files?spaces=appDataFolder&q=${encodeURIComponent("name = 'snapshot.json' and trashed = false")}&fields=files(id,modifiedTime)`, { headers: H })).json();
    const f = (lst.files || [])[0];
    if (f && f.modifiedTime !== localStorage.getItem("m_cloud_snap")) {
      const snap = await (await fetch(`${c.api_url}/files/${f.id}?alt=media`, { headers: H })).json();
      await cachePut("products", snap.products || []); await cachePut("batches", snap.batches || []); await cachePut("customers", snap.customers || []);
      if (window.Local) await Local.applyPull(snap, true);
      localStorage.setItem("m_cloud_snap", f.modifiedTime); localStorage.setItem("m_cloud_pull", new Date().toISOString());
    }
    if (showToast) toast(`همگام‌سازی اینترنتی انجام شد${ops.length ? ` (${ops.length} عملیات ارسال شد)` : ""}`);
    updateSyncPill(); return true;
  } catch (e) { if (showToast) toast(e.message, "err"); return false; }
}
window.cloudSync = cloudSync;
/* temporary negative ids (created offline) must not reach the PC — it matches by barcode instead */
function cleanLocalIds(p) {
  const c = JSON.parse(JSON.stringify(p || {}));
  if (Array.isArray(c.items)) c.items = c.items.map((it) => ({ ...it, product_id: it.product_id < 0 ? undefined : it.product_id, batch_id: (it.batch_id || 0) < 0 ? undefined : it.batch_id, barcode: it.barcode || undefined }));
  if (c.product_id < 0) delete c.product_id;
  return c;
}
window.cleanLocalIds = cleanLocalIds;
async function mobileSync(showToast) {
  const ops = await opsAll();
  let applied = 0, rejected = 0;
  try {
    const r = await api("/mobile/sync", { method: "POST", body: JSON.stringify({
      device_id: DEVICE_ID || null, cursor: localStorage.getItem("m_cursor") || null,
      push: ops.map((o) => ({ id: o.id, type: o.type, payload: cleanLocalIds(o.payload), created_at: o.created_at })), pull: true }) });
    for (const a of r.applied || []) {
      if (a.status === "APPLIED" || a.status === "DUPLICATE") { await opsDelete(a.id); applied++; }
      else { rejected++; await conflictAdd({ op_id: a.id, product_name: (ops.find((o) => o.id === a.id) || {}).label, server_message: a.error, at: new Date().toISOString(), kind: "op" }); await opsDelete(a.id); }
    }
    if (r.pull) { await cachePut("products", r.pull.products || []); await cachePut("batches", r.pull.batches || []); await cachePut("customers", r.pull.customers || []);
      if (window.Local) await Local.applyPull(r.pull, !localStorage.getItem("m_cursor")); }
    for (const a of r.applied || []) { if (a.status === "APPLIED" && a.result && a.result.invoice_number && window.Local) { const o = ops.find((x) => x.id === a.id); if (o && o.local_no) await Local.markInvoiceSynced(o.local_no, a.result.invoice_number); } }
    localStorage.setItem("m_cursor", r.cursor); localStorage.setItem("m_last_sync", new Date().toISOString());
    if (showToast || applied || rejected) toast(`همگام‌سازی با رایانه: ${applied} ثبت شد${rejected ? ` · ${rejected} رد شد` : ""}`, rejected ? "err" : "ok");
  } catch (e) {
    // PC unreachable (different network) → try the internet mailbox instead
    if (await cloudSync(false)) { if (showToast) toast("رایانه در شبکه نیست؛ از طریق اینترنت همگام شد"); }
    else if (showToast) toast("رایانه در دسترس نیست: " + e.message, "err");
  }
  updateSyncPill();
}

/* ---------- online/offline ---------- */
/* "online" = the shop PC answers (not merely "the phone has internet").
   A cheap /health probe every 20 s + on every network change keeps it honest. */
function refreshNet() {
  state.online = navigator.onLine && state.serverUp !== false;
  const el = $("#net-dot");
  if (el) el.className = "net " + (state.online ? "online" : "");
}
async function probeServer() {
  if (STANDALONE || !navigator.onLine) { state.serverUp = false; refreshNet(); return false; }
  const c = new AbortController(); const t = setTimeout(() => c.abort(), 3500);
  try { const r = await fetch((SERVER || "") + "/health", { signal: c.signal, cache: "no-store" }); state.serverUp = r.ok; }
  catch (_) { state.serverUp = false; } finally { clearTimeout(t); }
  const was = state.online; refreshNet();
  if (!was && state.online) syncLoop();
  return state.online;
}
window.probeServer = probeServer;
setInterval(probeServer, 20000);
window.addEventListener("online", () => { probeServer(); });
window.addEventListener("offline", refreshNet);

/* ---------- screens ---------- */
function showLogin() {
  $("#app").innerHTML = `
    <div class="screen" style="justify-content:center;max-width:420px;margin:auto;width:100%">
      <div class="card">
        <h2 class="brand">${icon("cart", 22)} سامانه سوپرمارکت</h2>
        <label>نام کاربری</label><input id="l-user" autocomplete="username" />
        <label>رمز عبور</label><input id="l-pass" type="password" autocomplete="current-password" />
        <button id="l-go" class="btn btn-primary" style="margin-top:14px">ورود</button>
        <p id="l-err" class="err hidden"></p>
      </div>
    </div>`;
  $("#l-go").addEventListener("click", doLogin);
  $("#l-pass").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
}

async function doLogin() {
  try {
    const form = new URLSearchParams({ username: $("#l-user").value.trim(), password: $("#l-pass").value });
    const res = await fetch(API + "/auth/login", { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) { const d = body && body.detail; throw new Error(typeof d === "object" ? (d.message || d.code) : (d || "ورود ناموفق")); }
    state.token = body.access_token;
    localStorage.setItem("m_token", state.token);
    state.user = await api("/auth/me");
    await loadConfig();
    showHome();
  } catch (e) {
    $("#l-err").textContent = e.message;
    $("#l-err").classList.remove("hidden");
  }
}

function chrome(title, backFn) {
  return `
    <div class="topbar">
      ${backFn ? `<button class="icon-btn" onclick="${backFn}" aria-label="بازگشت">${icon("back", 18)}</button>` : ""}
      <span id="net-dot" class="net ${state.online ? "online" : ""}"></span>
      <h1>${esc(title || (state.user ? state.user.full_name || state.user.username : ""))}</h1>
      <span class="sync-pill" id="sync-pill">همگام‌سازی…</span>
    </div>`;
}

/* Bottom tab bar — thumb-reachable primary navigation (§10, §13). */
const TABS = [
  ["home", "home", "خانه", null],
  ["pos", "pos", "فروش", "pos.sell"],
  ["stocktake", "clipboard", "شمارش", "inventory.stocktake"],
  ["inventory", "warehouse", "انبار", "inventory.view"],
  ["more", "more", "بیشتر", null],
];

const can = (perm) => !perm || ((state.user && state.user.permissions) || []).includes(perm);

function tabbar() {
  return `<nav class="tabbar">${TABS.filter((t) => can(t[3])).map(([key, ico, label]) => `
    <button class="tab ${state.view === key ? "active" : ""}" onclick="goTab('${key}')">
      <span class="ti">${icon(ico, 22)}</span><span class="tl">${label}</span>
    </button>`).join("")}</nav>`;
}

window.goTab = (key) => {
  state.view = key;
  ({ home: showHome, pos: showPos, stocktake: showSessions,
     inventory: showInventory, more: showMore })[key]();
};

async function loadConfig() {
  try { state.currency = await api("/settings/currency"); localStorage.setItem("m_currency", JSON.stringify(state.currency)); } catch (e) {}
  try { state.units = await api("/units"); localStorage.setItem("m_units", JSON.stringify(state.units)); } catch (e) { state.units = JSON.parse(localStorage.getItem("m_units") || "[]"); }
  if (state.user) localStorage.setItem("m_user", JSON.stringify(state.user));
  try { const t = await api("/settings/time"); if (t && t.timezone) localStorage.setItem("m_tz", t.timezone); } catch (e) {}
}
window.unpairDevice = () => {
  if (!confirm(STANDALONE ? "برای اتصال به رایانهٔ فروشگاه به صفحهٔ اتصال می‌روید؛ داده‌های گوشی حفظ می‌شود." : "اتصال این گوشی به رایانه قطع شود؟ صف آفلاین حفظ می‌شود.")) return;
  ["m_server", "m_token", "m_device", "m_store", "m_cursor", "m_standalone"].forEach((k) => localStorage.removeItem(k));
  if (NATIVE && NATIVE.unpair) NATIVE.unpair(); else location.href = "/mobile/setup.html";
};
window.logout = () => {
  localStorage.removeItem("m_token");
  state.token = ""; state.user = null;
  showLogin();
};

async function updateSyncPill() {
  const el = $("#sync-pill");
  if (!el) return;
  const [q, c, o] = await Promise.all([queueAll(), conflictAll(), opsAll().catch(() => [])]);
  el.innerHTML = `<i class="dot ${state.online ? "on" : "off"}"></i>${state.online ? "آنلاین" : "آفلاین"} · صف: ${q.length + o.length}${c.length ? ` · <span class="err">تعارض: ${c.length}</span>` : ""}`;
  el.onclick = showSync;
  el.style.cursor = "pointer";
}


/* ============================================================================
 * Mobile screens (§10–13). Every module is reachable from the phone, but each
 * one is designed for a thumb + a camera — not a shrunk desktop table.
 * ==========================================================================*/

async function showHome() {
  state.view = "home";
  let d = null;
  try { d = await api("/reports/dashboard"); } catch (e) { /* offline */ }
  const active = await api("/inventory/stocktake-sessions/active").catch(() => []);
  const resume = active.find((s) => s.resumable);
  $("#app").innerHTML = chrome("خانه") + `
    <div class="screen">
      ${resume ? `
        <button class="card resume-card" onclick="openSession(${resume.id})">
          <div class="rc-title">${icon("clipboard", 15)} ادامه انبارگردانی</div>
          <div class="rc-name">${esc(resume.name)}</div>
          <div class="progress-wrap" style="margin-top:8px">
            <div class="progress"><div style="width:${resume.percent}%"></div></div>
            <span class="progress-num">${resume.counted}/${resume.total}</span>
          </div>
        </button>` : ""}
      ${!d && window.Local ? await localHomeCards() : ""}
      ${d ? `
      <div class="kpi-grid">
        <div class="kpi"><span class="k">فروش امروز</span><b>${money(d.sales.today)}</b>
          <span class="muted">${d.sales.invoice_count_today} فاکتور</span></div>
        <div class="kpi"><span class="k">سود امروز</span><b>${money(d.profit.today)}</b></div>
        <div class="kpi"><span class="k">ارزش موجودی</span><b>${money(d.inventory.value)}</b>
          <span class="muted">${d.inventory.product_count} کالا</span></div>
        <div class="kpi warn"><span class="k">کم‌موجودی</span><b>${d.inventory.low_stock_count}</b>
          <span class="muted">${d.inventory.no_stock_count} بدون موجودی</span></div>
      </div>
      <div class="card">
        <h2>هشدار انقضا</h2>
        ${expiryRows(d.expiry)}
      </div>` : ""}
      <div class="btn-row">
        <button class="btn" onclick="openScanForLookup()">${icon("camera", 18)} اسکن کالا</button>
        <button class="btn" onclick="goTab('pos')">${icon("pos", 18)} فروش سریع</button>
      </div>
    </div>` + tabbar();
  updateSyncPill();
}

async function localHomeCards() {
  const [c, t] = await Promise.all([Local.counts(), Local.todayStats()]);
  const last = c.last_pull ? faDT(c.last_pull, true) : "هنوز همگام نشده";
  return `<div class="card"><p class="muted">${NATIVE ? "رایانهٔ فروشگاه در دسترس نیست — برنامه با دادهٔ خودِ گوشی کار می‌کند و با اولین اتصال (وای‌فای یا اینترنت/ابر) همگام می‌شود." : "اتصال به سرور برقرار نیست — داده‌های محلی نمایش داده می‌شود."}</p></div>
    <div class="kpi-grid">
      <div class="kpi"><span class="k">فروش امروز (گوشی)</span><b>${money(t.total)}</b><span class="muted">${t.count} فاکتور${t.unsynced ? ` · ${t.unsynced} در انتظار همگام‌سازی` : ""}</span></div>
      <div class="kpi"><span class="k">کالاهای محلی</span><b>${c.products}</b><span class="muted">${c.batches} بچ · ${c.customers} مشتری</span></div>
      <div class="kpi"><span class="k">آخرین دریافت از رایانه</span><b style="font-size:13px">${last}</b></div>
    </div>`;
}
function expiryRows(exp) {
  const map = [["EXPIRED", "منقضی‌شده", "badge-red"], ["EXPIRING_TODAY", "امروز", "badge-red"],
               ["EXPIRING_3_DAYS", "تا ۳ روز", "badge-amber"], ["EXPIRING_7_DAYS", "تا ۷ روز", "badge-amber"],
               ["EXPIRING_30_DAYS", "تا ۳۰ روز", "badge-blue"]];
  const rows = map.map(([k, label, cls]) => {
    const n = (exp[k] || []).length;
    return `<div class="exp-row"><span>${label}</span><span class="badge ${cls}">${n}</span></div>`;
  }).join("");
  return rows;
}

/* v1.8.1 — register a product right from the phone (works offline: local id, replayed as PRODUCT_CREATE) */
window.offerNewProduct = (barcode) => {
  closeSheet();
  const units = (state.units || []).map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("");
  $("#app").insertAdjacentHTML("beforeend", `<div class="sheet" id="m-sheet"><div class="sheet-body">
      <h2>کالای جدید</h2><p class="muted">این بارکد در فهرست نیست. همین‌جا تعریفش کنید؛ با اتصال به رایانه به فهرست اصلی اضافه می‌شود.</p>
      <label>بارکد</label><input id="np-bc" class="ltr" value="${esc(barcode || "")}" />
      <label>نام کالا *</label><input id="np-name" />
      <label>واحد</label><select id="np-unit">${units || '<option value="">عدد</option>'}</select>
      <label>قیمت فروش (اختیاری — با موجودی اولیه)</label><input id="np-sell" inputmode="numeric" />
      <label>موجودی اولیه</label><input id="np-qty" inputmode="decimal" value="0" />
      <button class="btn btn-green" onclick="createProductM()">ثبت کالا</button><button class="btn" onclick="closeSheet()">انصراف</button>
    </div></div>`);
};
window.createProductM = async () => {
  const f = { barcode: $("#np-bc").value.trim() || null, name: $("#np-name").value.trim(), unit_id: Number($("#np-unit").value) || null };
  const sell = Number($("#np-sell").value || 0), qty = parseFloat($("#np-qty").value || "0");
  if (f.name.length < 2) { toast("نام کالا را بنویسید", "err"); return; }
  let p = null;
  try { if (!state.online) throw Object.assign(new Error("offline"), { status: 0 }); p = await api("/products", { method: "POST", body: JSON.stringify(f) }); }
  catch (e) {
    if (e.status && e.status < 500) { toast(e.message, "err"); return; }
    p = window.Local ? await Local.localProduct(f) : null;
    await opQueueAdd("PRODUCT_CREATE", f, `کالای جدید ${f.name}`);
  }
  if (p && qty > 0) {
    const b = { barcode: p.barcode, quantity_received: qty, buy_price: 0, sell_price: sell, consumer_price: sell };
    try { if (!state.online || p.id < 0) throw Object.assign(new Error("offline"), { status: 0 }); await api("/batches/receive", { method: "POST", body: JSON.stringify(b) }); }
    catch (e) { if (window.Local) await Local.localBatch(p.id, b); await opQueueAdd("STOCK_RECEIVE", b, `ورود کالا ${p.barcode}`); }
  }
  closeSheet(); toast(`کالا «${f.name}» ثبت شد${p && p.id < 0 ? " (آفلاین)" : ""}`);
  if (state.view === "pos") showPos(); else if (state.view === "inventory") showInventory();
};

/* ---------- Mobile POS (§11): scan → cart → pay, one thumb ---------- */
async function showPos() {
  state.view = "pos";
  const total = state.cart.reduce((a, i) => a + i.sell * i.qty, 0);
  $("#app").innerHTML = chrome("فروش") + `
    <div class="screen pos-screen-m">
      <div class="search-bar">
        <input id="m-search" placeholder="نام یا بارکد کالا…" autocomplete="off" />
        <button class="icon-btn big" onclick="openScanForPos()" aria-label="اسکن">${icon("camera", 22)}</button>
      </div>
      <div id="m-results"></div>
      <div class="card">
        <h2>سبد خرید (${state.cart.length})</h2>
        ${state.cart.length ? state.cart.map((i, idx) => `
          <div class="cart-line">
            <div class="cl-main"><b>${esc(i.name)}</b>
              <span class="muted">${money(i.sell)} × ${qtyFmt(i.qty)} ${esc(i.symbol || "")}</span></div>
            <div class="cl-qty">
              <button class="qbtn" onclick="mQty(${idx},-1)" aria-label="کاهش">${icon("minus", 16)}</button>
              <span>${qtyFmt(i.qty)}</span>
              <button class="qbtn" onclick="mQty(${idx},1)" aria-label="افزایش">${icon("plus", 16)}</button>
              <button class="qbtn del" onclick="mRemove(${idx})" aria-label="حذف">${icon("close", 15)}</button>
            </div>
          </div>`).join("") : `<p class="muted">سبد خالی است — کالا را اسکن یا جستجو کنید.</p>`}
      </div>
      ${state.cart.length ? `
        <div class="pay-bar">
          <div><span class="muted">قابل پرداخت</span><b>${money(total)}</b></div>
          <button class="btn" style="width:auto;padding:12px 14px" onclick="mHold()" title="نگه‌داشتن فاکتور">${icon("clipboard", 18)}</button>
          <button class="btn btn-green" style="width:auto;padding:14px 22px" onclick="mCheckout()">پرداخت</button>
        </div>` : ""}
      ${window.mHeldBar ? mHeldBar() : ""}
    </div>` + tabbar();
  const inp = $("#m-search");
  inp.addEventListener("input", debounceM(async () => {
    const q = inp.value.trim();
    if (q.length < 2) { $("#m-results").innerHTML = ""; return; }
    try {
      const r = await searchProducts(q, 8);
      $("#m-results").innerHTML = r.items.length ? r.items.map((i) => `
        <button class="result-row" onclick="mPick(${i.product_id})">
          <div class="rr-name">${esc(i.name)}</div>
          <div class="rr-meta">${esc(i.barcode)} · موجودی ${qtyFmt(i.available_qty)}
            ${i.price_count > 1 ? `· <span class="amber">${i.price_count} قیمت</span>` : ""}</div>
        </button>`).join("") : `<p class="muted">کالایی یافت نشد</p>`;
      state._lastResults = r.items;
    } catch (e) { $("#m-results").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  }, 250));
  updateSyncPill();
}

/* v1.8.1 — catalogue lookups: the phone's own copy first (instant, offline); server when online and nothing local */
async function searchProducts(q, limit) {
  const local = window.Local ? await Local.search(q, limit).catch(() => []) : [];
  if (local.length || !state.online) return { items: local };
  try { return await api(`/pos/search?q=${encodeURIComponent(q)}&limit=${limit}`); } catch (e) { if (local.length) return { items: local }; throw e; }
}
window.searchProducts = searchProducts;
const debounceM = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

window.mPick = (productId) => {
  const item = (state._lastResults || []).find((i) => i.product_id === productId);
  if (!item) return;
  const batches = item.batches || [];
  if (!batches.length) { toast("موجودی قابل فروش ندارد", "err"); return; }
  if (batches.length === 1) { mAskQty(item, batches[0]); return; }
  // multiple prices -> the cashier picks (§24)
  $("#app").insertAdjacentHTML("beforeend", `
    <div class="sheet" id="m-sheet">
      <div class="sheet-body">
        <h2>${esc(item.name)} — انتخاب قیمت</h2>
        ${batches.map((b, i) => `
          <button class="batch-pick" onclick="mPickBatch(${productId}, ${b.batch_id})">
            <b>${money(b.sell_price)}</b>
            <span class="muted">${esc(b.batch_number)} · موجودی ${qtyFmt(b.current_qty)}
              ${b.expiry_date ? "· انقضا " + (window.Jalali ? Jalali.fromIso(b.expiry_date) : esc(b.expiry_date)) : ""}</span>
            ${b.is_recommended ? `<span class="badge badge-green">پیشنهاد سیستم</span>` : ""}
          </button>`).join("")}
        <button class="btn" onclick="closeSheet()">انصراف</button>
      </div>
    </div>`);
};

window.closeSheet = () => { const s = $("#m-sheet"); if (s) s.remove(); };
window.mPickBatch = (productId, batchId) => {
  closeSheet();
  const item = (state._lastResults || []).find((i) => i.product_id === productId);
  const batch = item.batches.find((b) => b.batch_id === batchId);
  mAskQty(item, batch);
};

function mAskQty(item, batch) {
  const decimal = item.unit && item.unit.allow_decimal;
  if (!decimal) { mAdd(item, batch, 1); return; }
  $("#app").insertAdjacentHTML("beforeend", `
    <div class="sheet" id="m-sheet"><div class="sheet-body">
      <h2>${esc(item.name)}</h2>
      <p class="muted">واحد ${esc(item.unit.name)} — موجودی ${qtyFmt(batch.current_qty)}</p>
      <input id="m-qty" inputmode="decimal" value="1" class="big-input" />
      <button class="btn btn-green" onclick="mConfirmQty(${item.product_id}, ${batch.batch_id})">افزودن</button>
      <button class="btn" onclick="closeSheet()">انصراف</button>
    </div></div>`);
  setTimeout(() => { const el = $("#m-qty"); if (el) { el.focus(); el.select(); } }, 50);
}

window.mConfirmQty = (productId, batchId) => {
  const v = parseFloat($("#m-qty").value);
  if (!isFinite(v) || v <= 0) { toast("مقدار نامعتبر", "err"); return; }
  const item = (state._lastResults || []).find((i) => i.product_id === productId);
  const batch = item.batches.find((b) => b.batch_id === batchId);
  closeSheet();
  mAdd(item, batch, parseFloat(v.toFixed(3)));
};

function mAdd(item, batch, qty) {
  const existing = state.cart.find((c) => c.batch_id === batch.batch_id);
  if (existing) existing.qty = parseFloat((existing.qty + qty).toFixed(3));
  else state.cart.push({ product_id: item.product_id, batch_id: batch.batch_id, barcode: item.barcode || null,
    name: item.name, sell: batch.sell_price, qty,
    symbol: item.unit ? item.unit.symbol : "",
    decimal: !!(item.unit && item.unit.allow_decimal),
    available: batch.current_qty });
  toast("به سبد اضافه شد");
  showPos();
}

window.mQty = (idx, d) => {
  const line = state.cart[idx];
  const step = line.decimal ? 0.5 : 1;
  const next = parseFloat((line.qty + d * step).toFixed(3));
  if (next <= 0) { state.cart.splice(idx, 1); }
  else if (next > line.available) { toast(`حداکثر ${qtyFmt(line.available)}`, "err"); return; }
  else line.qty = next;
  showPos();
};
window.mRemove = (idx) => { state.cart.splice(idx, 1); showPos(); };

window.mCheckout = () => {
  const total = state.cart.reduce((a, i) => a + i.sell * i.qty, 0);
  $("#app").insertAdjacentHTML("beforeend", `
    <div class="sheet" id="m-sheet"><div class="sheet-body">
      <h2>پرداخت</h2>
      <div class="pay-total">${money(total)}</div>
      <label>موبایل مشتری (اختیاری)</label>
      <input id="m-phone" inputmode="numeric" placeholder="0912…" />
      <label>کد تخفیف (اختیاری)</label>
      <input id="m-coupon" placeholder="مثلاً WELCOME10" />
      <label>روش پرداخت</label>
      <select id="m-method"><option value="CASH">نقدی</option><option value="CARD">کارت</option></select>
      <button class="btn btn-green" onclick="mDoCheckout(${total})">ثبت فروش</button>
      <button class="btn" onclick="closeSheet()">انصراف</button>
    </div></div>`);
};

window.mDoCheckout = async (total) => {
  const phone = $("#m-phone").value.trim();
  const coupon = $("#m-coupon").value.trim();
  const method = $("#m-method").value;
  let payable = total;
  if (coupon) {
    try {
      const ev = await api("/marketing/coupons/validate", { method: "POST",
        body: JSON.stringify({ code: coupon, amount: total, customer_phone: phone || null }) });
      payable = total - ev.discount;
    } catch (e) { toast(e.message, "err"); return; }
  }
  const payload = {
      items: state.cart.map((i) => ({ product_id: i.product_id, batch_id: i.batch_id, quantity: i.qty, barcode: i.barcode || undefined })),
      payments: [{ method, amount: payable }],
      customer_phone: phone || null,
      coupon_code: coupon || null };
  try {
    const inv = await api("/pos/checkout", { method: "POST", body: JSON.stringify(payload) });
    closeSheet();
    state.cart = [];
    toast(`ثبت شد: ${inv.invoice_number}`);
    if (inv.issued_coupon) toast(`کوپن خرید بعدی: ${inv.issued_coupon.code}`);
    showPos();
  } catch (e) {
    if (!e.status || e.status >= 500) {   // offline / PC unreachable → apply locally + store-and-forward (v1.6/v1.8.1)
      const local_no = window.Local ? await Local.localSale(payload, payable) : null;
      await opQueueAdd("POS_CHECKOUT", payload, `فروش ${money(payable)} (${state.cart.length} قلم)`, local_no);
      closeSheet(); state.cart = [];
      toast(`فروش ${local_no || ""} ثبت شد (آفلاین) — با اتصال به رایانه همگام می‌شود`);
      showPos(); return;
    }
    toast(e.message, "err");
  }
};

/* ---------- Inventory on the phone (§11) ---------- */
async function showInventory() {
  state.view = "inventory";
  $("#app").innerHTML = chrome("انبار") + `
    <div class="screen">
      <div class="search-bar">
        <input id="inv-q" placeholder="جستجوی کالا…" />
        <button class="icon-btn big" onclick="openScanForLookup()" aria-label="اسکن">${icon("camera", 22)}</button>
      </div>
      <div class="btn-row">
        <button class="btn" onclick="showStockIn()">${icon("inbox", 18)} ورود کالا</button>
        <button class="btn" onclick="goTab('stocktake')">${icon("clipboard", 18)} انبارگردانی</button>
      </div>
      <div id="inv-list"><p class="muted">در حال بارگذاری…</p></div>
    </div>` + tabbar();
  const render = async (q) => {
    try {
      let rows; try { if (!state.online) throw new Error("offline"); rows = await api("/inventory/stock"); } catch (_) { rows = window.Local ? await Local.stockRows() : []; if (!rows.length) throw _; }
      const filtered = q ? rows.filter((r) => r.name.includes(q) || (r.barcode || "").includes(q)) : rows;
      $("#inv-list").innerHTML = filtered.slice(0, 60).map((r) => `
        <div class="stock-row">
          <div><b>${esc(r.name)}</b><div class="muted">${esc(r.barcode)}</div></div>
          <div class="sr-qty ${r.total_stock <= r.min_stock_alert ? "low" : ""}">${qtyFmt(r.total_stock)}</div>
        </div>`).join("") || `<p class="muted">کالایی یافت نشد</p>`;
    } catch (e) { $("#inv-list").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  };
  $("#inv-q").addEventListener("input", debounceM((e) => render($("#inv-q").value.trim()), 250));
  render("");
  updateSyncPill();
}

async function showStockIn() {
  $("#app").innerHTML = chrome("ورود کالا", "goTab('inventory')") + `
    <div class="screen">
      <div class="card">
        <h2>ثبت ورود کالا (بچ جدید)</h2>
        <label>بارکد</label>
        <div class="search-bar"><input id="si-barcode" inputmode="numeric" />
          <button class="icon-btn big" onclick="scanInto('si-barcode')" aria-label="اسکن">${icon("camera", 22)}</button></div>
        <div id="si-found" class="muted"></div>
        <label>مقدار</label><input id="si-qty" inputmode="decimal" value="1" />
        <label>قیمت خرید</label><input id="si-buy" inputmode="numeric" />
        <label>قیمت فروش</label><input id="si-sell" inputmode="numeric" />
        <label>تاریخ انقضا (شمسی)</label><input id="si-exp" type="date" />
        <button class="btn btn-green" style="margin-top:12px" onclick="doStockIn()">ثبت ورود</button>
      </div>
    </div>` + tabbar();
  if (window.Jalali) Jalali.attachAll($("#app"));
  $("#si-barcode").addEventListener("change", async () => {
    const code = $("#si-barcode").value.trim();
    let p = null;
    try { if (state.online) p = await api(`/products/barcode/${encodeURIComponent(code)}`); } catch (_) { p = null; }
    if (!p && window.Local) { const l = await Local.byBarcode(code); if (l) p = { id: l.product_id, name: l.name, barcode: l.barcode }; }
    if (p) { $("#si-found").innerHTML = `<span class="ok-line">${icon("check", 14)} ${esc(p.name)}</span>`; state._siProduct = p; }
    else { $("#si-found").innerHTML = `کالا یافت نشد — <a href="#" onclick="offerNewProduct('${esc(code)}');return false">ثبت کالای جدید</a>`; state._siProduct = null; }
  });
}

window.doStockIn = async () => {
  try {
    const r = await api("/batches/receive", { method: "POST", body: JSON.stringify({
      barcode: $("#si-barcode").value.trim(),
      quantity_received: parseFloat($("#si-qty").value),
      buy_price: Number($("#si-buy").value || 0),
      sell_price: Number($("#si-sell").value || 0),
      expiry_date: $("#si-exp").value || null })});
    toast(`بچ ${r.batch_number} ثبت شد`);
    showInventory();
  } catch (e) {
    if (!e.status || e.status >= 500) {
      const f = { barcode: $("#si-barcode").value.trim(), quantity_received: parseFloat($("#si-qty").value),
        buy_price: Number($("#si-buy").value || 0), sell_price: Number($("#si-sell").value || 0), expiry_date: $("#si-exp").value || null };
      if (window.Local && state._siProduct) await Local.localBatch(state._siProduct.id, f);
      await opQueueAdd("STOCK_RECEIVE", f, `ورود کالا ${f.barcode}`);
      toast("ورود کالا ثبت شد (آفلاین) — با اتصال به رایانه همگام می‌شود"); showInventory(); return;
    }
    toast(e.message, "err");
  }
};

/* ---------- More: products, customers, coupons, reports, diagnostics ---------- */
function showMore() {
  state.view = "more";
  $("#app").innerHTML = chrome("بیشتر") + `
    <div class="screen">
      <div class="menu-list">
        <button class="menu-item" onclick="showProducts()">${icon("box")} کالاها</button>
        <button class="menu-item" onclick="showCustomersM()">${icon("user")} مشتریان</button>
        <button class="menu-item" onclick="showCouponsM()">${icon("gift")} کوپن‌ها</button>
        <button class="menu-item" onclick="showInvoicesM()">${icon("invoice")} فاکتورها</button>
        <button class="menu-item" onclick="showReportsM()">${icon("chart")} گزارش‌ها</button>
        <button class="menu-item" onclick="showSync()">${icon("sync")} همگام‌سازی</button>
        <button class="menu-item" onclick="showSettingsM()">${icon("gear")} تنظیمات</button>
        <button class="menu-item danger" onclick="logout()">${icon("exit")} خروج</button>
      </div>
    </div>` + tabbar();
  updateSyncPill();
}

async function listScreen(title, loader, rowFn, extra) {
  $("#app").innerHTML = chrome(title, "goTab('more')") +
    `<div class="screen"><div id="ls-body"><p class="muted">در حال بارگذاری…</p></div>${extra || ""}</div>` + tabbar();
  try {
    const rows = await loader();
    $("#ls-body").innerHTML = rows.length ? rows.map(rowFn).join("")
      : `<p class="muted">موردی یافت نشد</p>`;
  } catch (e) { $("#ls-body").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  updateSyncPill();
}

window.showProducts = () => listScreen("کالاها",
  async () => { try { if (!state.online) throw new Error("offline"); return (await api("/products?limit=100")).items; } catch (e) { const l = window.Local ? await Local.products(200) : []; if (l.length) return l; throw e; } },
  // §5 on mobile — tapping a product opens its batch/price history, the same
  // truth the desktop shows. §16: an internal code is labelled as such so
  // staff do not expect an external lookup to resolve it.
  (p) => `<div class="stock-row" onclick="showProductBatches(${p.id})">
    <div><b>${esc(p.name)}</b>
    <div class="muted">${esc(p.barcode)}${p.has_own_barcode === false ? " (داخلی)" : ""}${p.sku ? " · " + esc(p.sku) : ""}</div></div>
    <div class="muted">${icon("back", 16)}</div></div>`);

/* §5 — product batches on a phone. Prices are per batch and never merged, so
 * the sheet lists each batch separately rather than showing one "the price". */
window.showProductBatches = async (productId) => {
  try {
    const d = await api(`/products/${productId}/detail`);
    const row = (b, dim) => `<div class="stock-row" style="${dim ? "opacity:.6" : ""}">
      <div><b>${esc(b.batch_number)}</b>
        <div class="muted">خرید ${money(b.buy_price)} · فروش ${money(b.sell_price)}
          ${b.expiry_date ? " · انقضا " + (window.Jalali ? Jalali.fromIso(b.expiry_date) : esc(b.expiry_date)) : ""}</div></div>
      <div><b>${qtyFmt(b.current_qty)}</b></div></div>`;
    closeSheet();
    $("#app").insertAdjacentHTML("beforeend", `
      <div class="sheet" id="m-sheet">
        <div class="sheet-body">
          <h2>${esc(d.product.name)}</h2>
          <p class="muted">${esc(d.product.barcode)}${d.product.has_own_barcode === false ? " (بارکد داخلی)" : ""}
            · موجودی کل ${qtyFmt(d.total_stock)} · ${d.batch_count} بچ</p>
          <h3>بچ‌های فعال</h3>
          ${d.active_batches.length ? d.active_batches.map((b) => row(b, false)).join("")
            : '<p class="muted">موجودی فعالی نیست.</p>'}
          ${d.depleted_batches.length ? "<h3>تمام‌شده (تاریخچهٔ قیمت)</h3>"
            + d.depleted_batches.map((b) => row(b, true)).join("") : ""}
          <button class="btn" onclick="closeSheet()">بستن</button>
        </div>
      </div>`);
  } catch (e) { toast(e.message, "err"); }
};

window.showCustomersM = () => listScreen("مشتریان",
  () => api("/customers"),
  (c) => `<div class="stock-row"><div><b>${esc(c.name)}</b>
    <div class="muted">${esc(c.phone || "—")}</div></div></div>`);

window.showCouponsM = () => listScreen("کوپن‌ها",
  () => api("/marketing/coupons?limit=50"),
  (c) => `<div class="stock-row"><div><b>${esc(c.code)}</b>
    <div class="muted">${c.discount_type === "PERCENT" ? c.discount_value + "٪" : money(c.discount_value)}
      · ${c.used_count}/${c.usage_limit}</div></div>
    <span class="badge ${c.status === "ACTIVE" ? "badge-green" : "badge-blue"}">${esc(c.status)}</span></div>`);

window.showInvoicesM = () => listScreen("فاکتورها",
  async () => (await api("/invoices")).items || [],
  (i) => `<div class="stock-row"><div><b>${esc(i.invoice_number)}</b>
    <div class="muted">${esc((i.created_at || "").slice(0, 16).replace("T", " "))}</div></div>
    <div class="sr-qty">${money(i.total_amount)}</div></div>`);

window.showReportsM = async () => {
  $("#app").innerHTML = chrome("گزارش‌ها", "goTab('more')") +
    `<div class="screen"><div id="rp"><p class="muted">در حال بارگذاری…</p></div></div>` + tabbar();
  try {
    const d = await api("/reports/dashboard");
    $("#rp").innerHTML = `
      <div class="kpi-grid">
        <div class="kpi"><span class="k">فروش امروز</span><b>${money(d.sales.today)}</b></div>
        <div class="kpi"><span class="k">فروش ماه</span><b>${money(d.sales.month)}</b></div>
        <div class="kpi"><span class="k">سود امروز</span><b>${money(d.profit.today)}</b></div>
        <div class="kpi"><span class="k">سود ماه</span><b>${money(d.profit.month)}</b></div>
        <div class="kpi"><span class="k">ارزش موجودی</span><b>${money(d.inventory.value)}</b></div>
        <div class="kpi"><span class="k">میانگین فاکتور</span><b>${money(d.sales.avg_invoice_today)}</b></div>
      </div>
      <div class="card"><h2>انقضا</h2>${expiryRows(d.expiry)}</div>`;
  } catch (e) { $("#rp").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  updateSyncPill();
};

window.showSettingsM = async () => {
  const s = state.currency;
  $("#app").innerHTML = chrome("تنظیمات", "goTab('more')") + `
    <div class="screen">
      <div class="card">
        <h2>حساب کاربری</h2>
        <p>${esc(state.user ? state.user.full_name || state.user.username : "")}</p>
        <p class="muted">${esc(((state.user && state.user.roles) || []).join("، "))}</p>
      </div>
      <div class="card">
        <h2>واحد پول</h2>
        <p><b>${esc(s.label)}</b> (${esc(s.code)})</p>
        <p class="muted">مبالغ با همین واحد ذخیره می‌شوند؛ تغییر آن در پنل مدیریت انجام می‌شود
          و مقادیر ثبت‌شده را تبدیل نمی‌کند.</p>
      </div>
      <div class="card">
        <h2>اتصال</h2>
        <p><i class="dot ${state.online ? "on" : "off"}"></i>${state.online ? "آنلاین" : "آفلاین"}</p>
        <p class="muted">آدرس سرور: ${esc(SERVER || location.origin)}${NATIVE ? ` · نسخهٔ اپ ${esc(NATIVE.version())}` : ""}</p>
        <button class="btn" onclick="showSync()">وضعیت صف همگام‌سازی</button>
        ${STANDALONE ? `<p class="muted">حالت مستقل: این گوشی هنوز به رایانهٔ فروشگاه متصل نیست؛ همهٔ داده‌ها روی خود گوشی است.</p><button class="btn btn-primary" style="margin-top:8px" onclick="unpairDevice()">اتصال به رایانهٔ فروشگاه (اسکن QR)</button>` :
          NATIVE || localStorage.getItem("m_server") ? `<button class="btn" style="margin-top:8px" onclick="unpairDevice()">قطع اتصال از این رایانه (اسکن مجدد)</button>` : ""}
      </div>
    </div>` + tabbar();
  updateSyncPill();
};

/* Standalone camera lookup (not tied to a stocktaking session) */
window.openScanForLookup = () => { state._scanMode = "lookup"; scan(); };
window.openScanForPos = () => { state._scanMode = "pos"; scan(); };
window.scanInto = (inputId) => { state._scanMode = "input:" + inputId; scan(); };

async function showSessions() {
  state.view = "stocktake";
  let sessions = [];
  let offlineMode = false;
  try {
    sessions = await api("/inventory/stocktakes");
    await cachePut("sessions", sessions);
  } catch (e) {
    const cached = await cacheGet("sessions");
    sessions = (cached && cached.value) || [];
    offlineMode = sessions.length > 0;
  }
  const rows = sessions.map((s) => `
    <div class="session-item" onclick="openSession(${s.id})">
      <div class="t"><b>${esc(s.name)}</b>
        <span class="muted">${s.started_at ? esc(s.started_at.slice(0, 10)) : ""} · ${s.items} آیتم</span></div>
      <span class="badge ${s.status === "ADJUSTED" ? "badge-green" : s.status === "PENDING_APPROVAL" ? "badge-amber" : s.status === "CANCELLED" ? "badge-red" : "badge-blue"}">${esc(s.status)}</span>
    </div>`).join("");
  $("#app").innerHTML = chrome() + `
    <div class="screen">
      <div class="card">
        <h2>جلسات انبارگردانی</h2>
        ${rows || '<p class="muted">جلسه‌ای وجود ندارد.</p>'}
        ${offlineMode ? '<p class="err">آفلاین — فهرست از حافظه محلی</p>' : ""}
      </div>
      <button class="btn" onclick="showSync()">وضعیت همگام‌سازی و تعارض‌ها</button>
    </div>` + tabbar();
  updateSyncPill();
}

window.openSession = async (id) => {
  let st = null;
  try {
    st = await api(`/inventory/stocktakes/${id}`);
    await cachePut("session_" + id, st);
  } catch (e) {
    const cached = await cacheGet("session_" + id);
    if (!cached) { toast("آفلاین و بدون نسخه ذخیره‌شده", "err"); return; }
    st = cached.value;
    toast("حالت آفلاین — آخرین نسخه ذخیره‌شده", "err");
  }
  state.session = st;
  state.cursor = st.items.findIndex((i) => i.status === "PENDING");
  if (state.cursor < 0) state.cursor = 0;
  showCount();
};

function currentItem() {
  return state.session.items[state.cursor];
}

function pendingCount() {
  return state.session.items.filter((i) => i.status === "PENDING").length;
}

function showCount() {
  const st = state.session;
  const total = st.items.length;
  const done = total - pendingCount();
  const pct = total ? Math.round((done / total) * 100) : 0;
  const it = currentItem();
  if (!it) {
    $("#app").innerHTML = chrome() + `
      <div class="screen"><div class="card" style="text-align:center">
        <h2>آیتمی برای شمارش نیست</h2>
        <p class="muted">وضعیت جلسه: ${esc(st.status)}</p>
        <button class="btn btn-primary" style="margin-top:10px" onclick="finishSession()">پایان شمارش (ارسال برای تأیید)</button>
        <button class="btn" style="margin-top:8px" onclick="showSessions()">بازگشت</button>
      </div></div>`;
    updateSyncPill();
    return;
  }
  $("#app").innerHTML = chrome() + `
    <div class="screen">
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>${esc(st.name)}</b>
          <span class="badge badge-blue">#${st.id}</span>
        </div>
        <div class="progress-wrap" style="margin-top:8px">
          <div class="progress"><div style="width:${pct}%"></div></div>
          <span class="progress-num">${done} / ${total}</span>
        </div>
      </div>

      <div class="card product-card">
        ${it.image_url
          ? `<img class="product-img" src="${esc(it.image_url)}" alt="" onerror="this.outerHTML='<div class=\\'product-img ph\\'></div>'" />`
          : `<div class="product-img ph">${icon("box", 44)}</div>`}
        <div class="product-name">${esc(it.product_name || "#" + it.product_id)}</div>
        <div class="product-barcode">${esc(it.barcode || "—")}</div>
        ${it.batch_id ? `<div class="muted">Batch: ${it.batch_id}</div>` : ""}
        <div class="qty-row">
          <div class="qty-box"><div class="muted">موجودی سیستم</div><div class="v">${it.system_qty}</div></div>
          <div class="qty-box"><div class="muted">موجودی واقعی</div>
            <input id="real-qty" type="number" inputmode="numeric" min="0" value="${it.physical_qty ?? ""}" placeholder="؟" /></div>
        </div>
        ${it.status !== "PENDING" ? `<div style="margin-top:8px"><span class="badge badge-green">قبلاً شمرده شده: ${it.physical_qty} (اختلاف ${it.difference})</span></div>` : ""}
      </div>

      <div class="btn-row">
        <button class="btn" onclick="scan()">${icon("camera", 18)} اسکن بارکد</button>
        <button class="btn" onclick="findByBarcode()">${icon("search", 18)} جستجوی بارکد</button>
      </div>
      <button class="btn btn-green" onclick="saveAndNext()">ذخیره و بعدی ⏎</button>
      <div class="btn-row">
        <button class="btn" onclick="moveCursor(-1)">⇤ قبلی</button>
        <button class="btn" onclick="moveCursor(1)">بعدی ⇥</button>
      </div>
      <button class="btn btn-danger" onclick="finishSession()">پایان شمارش</button>
    </div>`;
  $("#real-qty").focus();
  $("#real-qty").select();
  $("#real-qty").addEventListener("keydown", (e) => { if (e.key === "Enter") saveAndNext(); });
  updateSyncPill();
}

window.moveCursor = (d) => {
  const items = state.session.items;
  if (d > 0) {
    // jump to next PENDING after cursor (skip counted) — resume semantics
    for (let i = state.cursor + 1; i < items.length; i++) {
      if (items[i].status === "PENDING") { state.cursor = i; showCount(); return; }
    }
    state.cursor = Math.min(items.length - 1, state.cursor + 1);
  } else {
    state.cursor = Math.max(0, state.cursor - 1);
  }
  showCount();
};

async function saveCount(it, physicalQty, reason) {
  if (!state.online) {
    await queueAdd({
      stocktake_id: state.session.id, item_id: it.id,
      physical_qty: physicalQty, snapshot_system_qty: it.system_qty,
      snapshot_status: it.status, product_name: it.product_name,
      saved_at: new Date().toISOString(), reason: reason || null,
    });
    it.physical_qty = physicalQty;
    it.difference = physicalQty - it.system_qty;
    it.status = "COUNTED";
    await cachePut("session_" + state.session.id, state.session);
    toast("ذخیره محلی (آفلاین) — با اتصال همگام می‌شود", "ok");
    return true;
  }
  try {
    await api("/inventory/stocktakes/count", {
      method: "POST",
      body: JSON.stringify({ item_id: it.id, physical_qty: physicalQty, reason: reason || undefined }),
    });
    it.physical_qty = physicalQty;
    it.difference = physicalQty - it.system_qty;
    it.status = "COUNTED";
    await cachePut("session_" + state.session.id, state.session);
    return true;
  } catch (e) {
    // network failed mid-request -> queue it for retry
    if (!e.status || e.status >= 500) {
      await queueAdd({
        stocktake_id: state.session.id, item_id: it.id, physical_qty: physicalQty,
        snapshot_system_qty: it.system_qty, snapshot_status: it.status,
        product_name: it.product_name, saved_at: new Date().toISOString(), reason: reason || null,
      });
      it.physical_qty = physicalQty; it.difference = physicalQty - it.system_qty; it.status = "COUNTED";
      await cachePut("session_" + state.session.id, state.session);
      toast("شبکه قطع شد — در صف محلی", "ok");
      return true;
    }
    throw e;
  }
}

window.saveAndNext = async () => {
  const it = currentItem();
  if (!it) return;
  const v = parseInt($("#real-qty").value, 10);
  if (isNaN(v) || v < 0) { toast("تعداد را وارد کنید", "err"); return; }
  try {
    await saveCount(it, v);
    moveCursor(1);
  } catch (e) {
    toast(e.message, "err"); // business rejection (e.g. session closed) — do not queue
  }
};

window.finishSession = async () => {
  if (!state.online) { toast("برای پایان شمارش باید آنلاین باشید", "err"); return; }
  if (!confirm("شمارش پایان یابد و برای تأیید مدیر ارسال شود؟")) return;
  try {
    await api(`/inventory/stocktakes/${state.session.id}/complete`, { method: "POST" });
    toast("ارسال شد — در انتظار تأیید مدیر");
    showSessions();
  } catch (e) { toast(e.message, "err"); }
};

/* ---------- barcode find (manual) ---------- */
window.findByBarcode = () => {
  const it = currentItem();
  $("#app").innerHTML = chrome() + `
    <div class="screen">
      <div class="card">
        <h2>جستجوی کالا با بارکد</h2>
        <label>بارکد</label>
        <input id="f-bc" inputmode="numeric" value="${esc(it ? it.barcode || "" : "")}" />
        <button class="btn btn-primary" style="margin-top:12px" id="f-go">یافتن</button>
        <div id="f-out" style="margin-top:10px"></div>
        <button class="btn" style="margin-top:10px" onclick="showCount()">بازگشت</button>
      </div>
    </div>`;
  $("#f-bc").focus();
  $("#f-go").addEventListener("click", async () => {
    const bc = $("#f-bc").value.trim();
    if (!barcodeChecksumOk(bc)) { $("#f-out").innerHTML = '<p class="err">بارکد نامعتبر (checksum)</p>'; return; }
    try {
      const r = await api(`/inventory/stocktakes/${state.session.id}/item-by-barcode/${encodeURIComponent(bc)}`);
      const first = r.items[0];
      const idx = state.session.items.findIndex((i) => i.id === first.id);
      if (idx >= 0) { state.cursor = idx; showCount(); toast(r.product.name); }
    } catch (e) { $("#f-out").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  });
};

/* ---------- camera scanner (§23) ----------
 * v1.7.1: fast, reliable scanning on every phone.
 *  - native BarcodeDetector (Chrome/WebView with Google Play services) when it
 *    really works (it is probed once; some WebViews expose the API but never
 *    detect anything), otherwise
 *  - ZXing (Apache-2.0, /mobile/vendor/zxing.min.js) decoding video frames on a
 *    canvas ~15×/s with TRY_HARDER + all retail formats.
 *  - continuous autofocus, torch button, 1280×720 rear camera, haptic + beep. */
let scanStream = null, scanRAF = null, scanTrack = null;
const SCAN_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "itf", "qr_code", "data_matrix"];
function zxReader() {
  const Z = window.ZXing; if (!Z) return null;
  const hints = new Map();
  hints.set(Z.DecodeHintType.TRY_HARDER, true);
  hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.UPC_E,
    Z.BarcodeFormat.CODE_128, Z.BarcodeFormat.CODE_39, Z.BarcodeFormat.ITF, Z.BarcodeFormat.QR_CODE, Z.BarcodeFormat.DATA_MATRIX]);
  const r = new Z.MultiFormatReader(); r.setHints(hints); return r;
}
function scanBeep() {
  try { const ac = new (window.AudioContext || window.webkitAudioContext)(); const o = ac.createOscillator(); const g = ac.createGain();
    o.frequency.value = 1760; g.gain.value = 0.08; o.connect(g); g.connect(ac.destination); o.start(); o.stop(ac.currentTime + 0.08); } catch (_) {}
}
/* v1.8.1 — inside the Android app: NATIVE Camera2 + ZXing scanner (ScanActivity), result via __nativeScan */
window.__nativeScan = (code, fmt) => { const raw = String(code || "").trim(); if (!raw) return; state._lastScanFormat = fmt; onScanHit(raw); };
window.__nativeScanCancel = () => { state._scanMode = null; };
window.scan = async () => {
  if (NATIVE && NATIVE.hasNativeScanner && NATIVE.hasNativeScanner()) {
    try { NATIVE.scan(state._scanMode === "pos" ? "اسکن کالا برای فروش" : state._scanMode === "lookup" ? "جستجوی کالا" : "اسکن بارکد"); return; } catch (_) { /* fall through to WebView scanner */ }
  }
  return webScan();
};
async function webScan() {
  const overlay = $("#scanner");
  overlay.classList.remove("hidden");
  $("#scan-status").textContent = "دوربین را روی بارکد بگیرید…";
  $("#scan-manual").value = "";
  try {
    scanStream = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
      facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } } });
    const video = $("#scan-video");
    video.setAttribute("playsinline", ""); video.muted = true;
    video.srcObject = scanStream;
    await video.play();
    scanTrack = scanStream.getVideoTracks()[0];
    try {
      const caps = scanTrack.getCapabilities ? scanTrack.getCapabilities() : {};
      const adv = [];
      if (caps.focusMode && caps.focusMode.includes("continuous")) adv.push({ focusMode: "continuous" });
      if (caps.zoom && caps.zoom.min !== undefined) adv.push({ zoom: Math.min(caps.zoom.max, Math.max(caps.zoom.min, 1.5)) });
      if (adv.length) await scanTrack.applyConstraints({ advanced: adv }).catch(() => {});
      const tb = $("#scan-torch"); if (tb) tb.classList.toggle("hidden", !caps.torch);
    } catch (_) {}
    let detector = null;
    if ("BarcodeDetector" in window) {
      try { const sup = await window.BarcodeDetector.getSupportedFormats(); if (sup && sup.includes("ean_13")) detector = new window.BarcodeDetector({ formats: SCAN_FORMATS.filter((f) => sup.includes(f)) }); } catch (_) { detector = null; }
    }
    const zx = zxReader();
    if (!detector && !zx) { $("#scan-status").textContent = "این دستگاه اسکن با دوربین ندارد — بارکد را دستی وارد کنید"; return; }
    const canvas = document.createElement("canvas"); const ctx = canvas.getContext("2d", { willReadFrequently: true });
    let busy = false, nativeMisses = 0, useNative = !!detector, lastHit = 0;
    const hit = (raw) => {
      raw = String(raw || "").trim(); if (!raw || Date.now() - lastHit < 1200) return false;
      if (!barcodeChecksumOk(raw) && /^\d{8}$|^\d{12,13}$/.test(raw)) { $("#scan-status").textContent = "بارکد ناقص خوانده شد — کمی نزدیک‌تر"; return false; }
      lastHit = Date.now(); scanBeep(); onScanHit(raw); return true;
    };
    const tick = async () => {
      if (overlay.classList.contains("hidden")) return;
      if (!busy && video.readyState >= 2) {
        busy = true;
        try {
          if (useNative) {
            const codes = await detector.detect(video);
            if (codes && codes.length) { nativeMisses = 0; if (hit(codes[0].rawValue)) { busy = false; return; } }
            else if (zx && ++nativeMisses > 90) { useNative = false; } // ~6 s without a single detection → fall back to ZXing
          }
          if (!useNative && zx) {
            // decode the central band (where the frame is) at reduced size — fast and accurate
            const vw = video.videoWidth, vh = video.videoHeight;
            const cw = Math.min(800, vw), ch = Math.round(cw * (vh / vw));
            canvas.width = cw; canvas.height = ch; ctx.drawImage(video, 0, 0, cw, ch);
            const bandY = Math.round(ch * 0.25), bandH = Math.round(ch * 0.5);
            const img = ctx.getImageData(0, bandY, cw, bandH);
            const Z = window.ZXing;
            const lum = new Z.RGBLuminanceSource(toLuminance(img.data, cw * bandH), cw, bandH);
            let res = null;
            try { res = zx.decode(new Z.BinaryBitmap(new Z.HybridBinarizer(lum))); } catch (_) { try { zx.reset(); res = zx.decode(new Z.BinaryBitmap(new Z.HybridBinarizer(lum.invert()))); } catch (_) { res = null; } }
            zx.reset();
            if (res && hit(res.getText())) { busy = false; return; }
          }
        } catch (_) { /* transient frame error */ }
        busy = false;
      }
      scanRAF = requestAnimationFrame(() => setTimeout(tick, 60));
    };
    tick();
  } catch (e) {
    $("#scan-status").textContent = "دسترسی به دوربین ممکن نیست: " + (e && e.name === "NotAllowedError" ? "اجازهٔ دوربین داده نشده است" : (e.message || e));
  }
}
function toLuminance(rgba, n) {
  const out = new Uint8ClampedArray(n);
  for (let i = 0, j = 0; j < n; i += 4, j++) out[j] = (rgba[i] * 77 + rgba[i + 1] * 151 + rgba[i + 2] * 28) >> 8;
  return out;
}
window.scanTorch = async () => {
  if (!scanTrack) return;
  try { const cur = scanTrack.getSettings().torch; await scanTrack.applyConstraints({ advanced: [{ torch: !cur }] }); } catch (_) { toast("چراغ قوه در این دستگاه در دسترس نیست", "err"); }
};
$("#scan-close").addEventListener("click", closeScanner);
function closeScanner() {
  $("#scanner").classList.add("hidden");
  if (scanRAF) { cancelAnimationFrame(scanRAF); scanRAF = null; }
  if (scanStream) { scanStream.getTracks().forEach((t) => t.stop()); scanStream = null; scanTrack = null; }
}
$("#scan-manual").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const v = e.target.value.trim();
    if (barcodeChecksumOk(v)) onScanHit(v);
    else $("#scan-status").textContent = "بارکد نامعتبر (checksum)";
  }
});
function onScanHit(raw) {
  closeScanner();
  navigator.vibrate && navigator.vibrate(80);
  $("#scan-manual").value = "";
  const mode = state._scanMode || "stocktake";
  state._scanMode = null;

  if (mode.startsWith("input:")) {
    const el = document.getElementById(mode.slice(6));
    if (el) { el.value = raw; el.dispatchEvent(new Event("change")); }
    return;
  }

  (async () => {
    try {
      if (mode === "pos") {
        const r = await searchProducts(raw, 5);
        if (!r.items.length) { toast("کالا یافت نشد: " + raw, "err"); if (window.offerNewProduct) offerNewProduct(raw); return; }
        state._lastResults = r.items;
        mPick(r.items[0].product_id);
        return;
      }
      if (mode === "lookup") {
        const r = await searchProducts(raw, 1);
        if (!r.items.length) { toast("کالا یافت نشد: " + raw, "err"); if (window.offerNewProduct) offerNewProduct(raw); return; }
        showProductSheet(r.items[0]);
        return;
      }
      // stocktake: jump the cursor to the scanned item in the open session
      const r = await api(`/inventory/stocktakes/${state.session.id}/item-by-barcode/${encodeURIComponent(raw)}`);
      const first = r.items[0];
      const idx = state.session.items.findIndex((i) => i.id === first.id);
      if (idx >= 0) {
        state.cursor = idx;
        showCount();
        toast("یافت شد: " + r.product.name);
      }
    } catch (e) {
      toast(e.message, "err");
    }
  })();
}

/* Scan-to-inspect: what the phone should show when you point it at a shelf item. */
window.showProductSheet = (item) => {
  closeSheet();
  $("#app").insertAdjacentHTML("beforeend", `
    <div class="sheet" id="m-sheet"><div class="sheet-body">
      <h2>${esc(item.name)}</h2>
      <p class="muted">${esc(item.barcode)} · موجودی کل ${qtyFmt(item.available_qty)} ${esc(item.unit ? item.unit.symbol : "")}</p>
      ${(item.batches || []).map((b) => `
        <div class="batch-info">
          <div><b>${money(b.sell_price)}</b> <span class="muted">مصرف‌کننده ${money(b.consumer_price)}</span></div>
          <div class="muted">${esc(b.batch_number)} · موجودی ${qtyFmt(b.current_qty)}
            ${b.expiry_date ? `· انقضا ${window.Jalali ? Jalali.fromIso(b.expiry_date) : esc(b.expiry_date)} (${b.days_left} روز)` : ""}</div>
        </div>`).join("") || `<p class="muted">بچ فعالی ندارد</p>`}
      ${item.price_count > 1 ? `<p class="amber">این کالا ${item.price_count} قیمت فعال دارد.</p>` : ""}
      <button class="btn" onclick="closeSheet()">بستن</button>
    </div></div>`);
};

/* ---------- sync + conflicts (§26) ---------- */
async function syncLoop() {
  if (state.online) await mobileSync(false);   // v1.6 LAN; v1.7 falls back to the internet mailbox
  const q = await queueAll();
  if (!q.length || !state.online) { updateSyncPill(); return; }
  let sent = 0, conflicted = 0;
  for (const entry of q) {
    try {
      await api("/inventory/stocktakes/count", {
        method: "POST",
        body: JSON.stringify({ item_id: entry.item_id, physical_qty: entry.physical_qty,
                               reason: (entry.reason || "") + " (sync از حالت آفلاین)" }),
      });
      await queueDelete(entry.id);
      sent++;
    } catch (e) {
      if (e.status === 404 || e.status === 422) {
        // item/session changed since the offline snapshot -> CONFLICT, human decides
        await conflictAdd({ ...entry, server_message: e.message, at: new Date().toISOString() });
        await queueDelete(entry.id);
        conflicted++;
      }
      // 5xx / network: keep in queue for the next round
    }
  }
  toast(`همگام‌سازی: ${sent} ارسال شد${conflicted ? ` · ${conflicted} تعارض` : ""}`, conflicted ? "err" : "ok");
  updateSyncPill();
}

window.showSync = async () => {
  const [q, c, ops] = await Promise.all([queueAll(), conflictAll(), opsAll().catch(() => [])]);
  const oRows = ops.map((x) => `
    <div class="card" style="margin-top:8px">
      <b>${esc(x.label || x.type)}</b>
      <div class="muted">${x.type === "POS_CHECKOUT" ? "فروش آفلاین" : x.type === "STOCK_RECEIVE" ? "ورود کالای آفلاین" : x.type} · ${faDT(x.created_at)}</div>
    </div>`).join("");
  const qRows = oRows + q.map((x) => `
    <div class="card" style="margin-top:8px">
      <b>${esc(x.product_name || "آیتم " + x.item_id)}</b>
      <div class="muted">شمارش آفلاین: ${x.physical_qty} · ${faDT(x.saved_at)}</div>
    </div>`).join("");
  const cRows = c.map((x) => x.kind === "op" ? `
    <div class="card conflict" style="margin-top:8px">
      <b>${esc(x.product_name || "عملیات آفلاین")}</b>
      <div class="err">رایانه این عملیات را نپذیرفت: ${esc(x.server_message)}</div>
      <div class="muted">${faDT(x.at)}</div>
      <button class="btn btn-danger" style="margin-top:6px" onclick="resolveConflict(${x.id},'drop')">متوجه شدم (حذف از فهرست)</button>
    </div>` : `
    <div class="card conflict" style="margin-top:8px">
      <b>${esc(x.product_name || "آیتم " + x.item_id)}</b>
      <div class="muted">شمارش شما: ${x.physical_qty} (نظام در زمان اسکن: ${x.snapshot_system_qty})</div>
      <div class="err">سرور: ${esc(x.server_message)}</div>
      <div class="btn-row" style="margin-top:8px">
        <button class="btn" onclick="resolveConflict(${x.id},'keep')">شمارش من معتبر است (ارسال مجدد)</button>
        <button class="btn btn-danger" onclick="resolveConflict(${x.id},'drop')">صرف‌نظر</button>
      </div>
    </div>`).join("");
  $("#app").innerHTML = chrome() + `
    <div class="screen">
      <div class="card">
        <h2>همگام‌سازی</h2>
        <p class="muted"><i class="dot ${state.online ? "on" : "off"}"></i>${state.online ? "آنلاین" : "آفلاین"} — صف ارسال: ${q.length + ops.length} · تعارض‌ها: ${c.length}</p>
        <p class="muted">آخرین همگام‌سازی با رایانه: ${localStorage.getItem("m_last_sync") ? faDT(localStorage.getItem("m_last_sync")) : "هنوز انجام نشده"}</p>
        ${qRows || '<p class="muted">صف خالی است.</p>'}
        <button class="btn btn-primary" style="margin-top:10px" onclick="mobileSync(true).then(syncLoop)">همگام‌سازی با رایانه</button>
      </div>
      <div class="card">
        <h2>تعارض‌ها (نیازمند تصمیم انسانی)</h2>
        ${cRows || '<p class="muted">تعارضی وجود ندارد.</p>'}
      </div>
      <button class="btn" onclick="showSessions()">بازگشت</button>
    </div>` + tabbar();
  updateSyncPill();
};

window.resolveConflict = async (id, action) => {
  const c = (await conflictAll()).find((x) => x.id === id);
  if (!c) return;
  if (action === "keep") {
    // user insists: accepted only if the item is still open on the server
    try {
      await api("/inventory/stocktakes/count", {
        method: "POST",
        body: JSON.stringify({ item_id: c.item_id, physical_qty: c.physical_qty, reason: "رفع تعارض: شمارش انباردار" }),
      });
      toast("ثبت شد");
    } catch (e) { toast("سرور رد کرد: " + e.message, "err"); }
    await conflictDelete(id);
    showSync();
  } else {
    await conflictDelete(id);
    toast("تعارض صرف‌نظر شد");
    showSync();
  }
};

/* ---------- boot ---------- */
(async function boot() {
  await probeServer();
  if (NATIVE && !SERVER) { location.href = "/mobile/setup.html"; return; }
  if (!state.token) { showLogin(); return; }
  try {
    state.user = await api("/auth/me");
    await loadConfig();
    showHome();
    if (state.online) syncLoop();
  } catch (e) {
    if (e.status === 401) { localStorage.removeItem("m_token"); state.token = ""; showLogin(); }
    else { // offline with a token: the app keeps working on the phone's own data
      try { state.user = JSON.parse(localStorage.getItem("m_user") || "null") || { full_name: "کاربر (آفلاین)", roles: ["ADMIN"], permissions: ["*"] }; } catch (_) { state.user = { full_name: "کاربر (آفلاین)" }; }
      state.currency = JSON.parse(localStorage.getItem("m_currency") || "null") || state.currency;
      state.units = JSON.parse(localStorage.getItem("m_units") || "[]");
      try { await showHome(); } catch (_) { try { await showSessions(); } catch (__) { showLogin(); } }
    }
  }
})();
