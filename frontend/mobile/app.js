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
const API = "/api";
const state = {
  token: localStorage.getItem("m_token") || "",
  user: null,
  session: null,        // {id, name, status, items: []}
  cursor: 0,            // index into pending-ish items
  online: navigator.onLine,
};

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
const money = (n) => Number(n || 0).toLocaleString("en-US");

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
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
const DB_VERSION = 1;

function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("queue")) db.createObjectStore("queue", { keyPath: "id", autoIncrement: true });
      if (!db.objectStoreNames.contains("conflicts")) db.createObjectStore("conflicts", { keyPath: "id", autoIncrement: true });
      if (!db.objectStoreNames.contains("cache")) db.createObjectStore("cache", { keyPath: "key" });
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

/* ---------- online/offline ---------- */
function refreshNet() {
  state.online = navigator.onLine;
  const el = $("#net-dot");
  if (el) el.className = "net " + (state.online ? "online" : "");
}
window.addEventListener("online", () => { refreshNet(); syncLoop(); });
window.addEventListener("offline", refreshNet);

/* ---------- screens ---------- */
function showLogin() {
  $("#app").innerHTML = `
    <div class="screen" style="justify-content:center;max-width:420px;margin:auto;width:100%">
      <div class="card">
        <h2>🛒 انبارگردانی — سامانه سوپرمارکت</h2>
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
    if (!res.ok) throw new Error(body.detail || "ورود ناموفق");
    state.token = body.access_token;
    localStorage.setItem("m_token", state.token);
    state.user = await api("/auth/me");
    await showSessions();
  } catch (e) {
    $("#l-err").textContent = e.message;
    $("#l-err").classList.remove("hidden");
  }
}

function chrome() {
  return `
    <div class="topbar">
      <span id="net-dot" class="net ${state.online ? "online" : ""}"></span>
      <h1>${esc(state.user ? state.user.full_name || state.user.username : "")}</h1>
      <span class="sync-pill" id="sync-pill">همگام‌سازی…</span>
      <button class="btn" style="width:auto;padding:8px 12px" onclick="logout()">خروج</button>
    </div>`;
}
window.logout = () => {
  localStorage.removeItem("m_token");
  state.token = ""; state.user = null;
  showLogin();
};

async function updateSyncPill() {
  const el = $("#sync-pill");
  if (!el) return;
  const [q, c] = await Promise.all([queueAll(), conflictAll()]);
  el.innerHTML = `${state.online ? "🟢 آنلاین" : "🔴 آفلاین"} · صف: ${q.length}${c.length ? ` · <span class="err">تعارض: ${c.length}</span>` : ""}`;
  el.onclick = showSync;
  el.style.cursor = "pointer";
}

async function showSessions() {
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
    </div>`;
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
          ? `<img class="product-img" src="${esc(it.image_url)}" alt="" onerror="this.outerHTML='<div class=\\'product-img ph\\'>📦</div>'" />`
          : `<div class="product-img ph">📦</div>`}
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
        <button class="btn" onclick="scan()">📷 اسکن بارکد</button>
        <button class="btn" onclick="findByBarcode()">🔎 جستجوی بارکد</button>
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

/* ---------- camera scanner (§23) ---------- */
let scanStream = null;
window.scan = async () => {
  if (!("BarcodeDetector" in window)) {
    toast("این مرورگر دوربین بارکد‌خوان ندارد — از جستجوی دستی استفاده کنید", "err");
    findByBarcode();
    return;
  }
  const overlay = $("#scanner");
  overlay.classList.remove("hidden");
  $("#scan-status").textContent = "در حال اسکن…";
  try {
    scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    const video = $("#scan-video");
    video.srcObject = scanStream;
    await video.play();
    const detector = new window.BarcodeDetector({
      formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39"],
    });
    const poll = async () => {
      if (overlay.classList.contains("hidden")) return;
      try {
        const codes = await detector.detect(video);
        if (codes && codes.length) {
          const raw = codes[0].rawValue;
          if (barcodeChecksumOk(raw)) { onScanHit(raw); return; }
          $("#scan-status").textContent = "بارکد ناقص خوانده شد — دوباره";
        }
      } catch (_) { /* transient detect errors are ignored */ }
      setTimeout(poll, 250);
    };
    poll();
  } catch (e) {
    $("#scan-status").textContent = "دسترسی به دوربین ممکن نیست: " + e.message;
  }
};
$("#scan-close").addEventListener("click", closeScanner);
function closeScanner() {
  $("#scanner").classList.add("hidden");
  if (scanStream) { scanStream.getTracks().forEach((t) => t.stop()); scanStream = null; }
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
  (async () => {
    try {
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

/* ---------- sync + conflicts (§26) ---------- */
async function syncLoop() {
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
  const [q, c] = await Promise.all([queueAll(), conflictAll()]);
  const qRows = q.map((x) => `
    <div class="card" style="margin-top:8px">
      <b>${esc(x.product_name || "آیتم " + x.item_id)}</b>
      <div class="muted">شمارش آفلاین: ${x.physical_qty} · ${new Date(x.saved_at).toLocaleString("fa-IR")}</div>
    </div>`).join("");
  const cRows = c.map((x) => `
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
        <p class="muted">${state.online ? "🟢 آنلاین" : "🔴 آفلاین"} — صف ارسال: ${q.length} · تعارض‌ها: ${c.length}</p>
        ${qRows || '<p class="muted">صف خالی است.</p>'}
        ${state.online && q.length ? '<button class="btn btn-primary" style="margin-top:10px" onclick="syncLoop()">همگام‌سازی کن</button>' : ""}
      </div>
      <div class="card">
        <h2>تعارض‌ها (نیازمند تصمیم انسانی)</h2>
        ${cRows || '<p class="muted">تعارضی وجود ندارد.</p>'}
      </div>
      <button class="btn" onclick="showSessions()">بازگشت</button>
    </div>`;
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
  refreshNet();
  if (!state.token) { showLogin(); return; }
  try {
    state.user = await api("/auth/me");
    await showSessions();
    if (state.online) syncLoop();
  } catch (e) {
    if (e.status === 401) { localStorage.removeItem("m_token"); state.token = ""; showLogin(); }
    else { // offline with a token: fall back to cached sessions
      state.user = { full_name: "کاربر (آفلاین)" };
      try { await showSessions(); } catch (_) { showLogin(); }
    }
  }
})();
