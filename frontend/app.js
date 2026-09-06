/* Supermarket System — Web Panel (vanilla JS SPA) */
const $ = (sel) => document.querySelector(sel);
const API = "/api";

const state = {
  token: localStorage.getItem("token") || "",
  user: null,
  view: "dashboard",
  kiosk: localStorage.getItem("kiosk") === "1",
  kioskShortcut: "Ctrl+Shift+L",
  currency: { code: "IRT", label: "تومان" },
  units: [],
};

/* ---------- helpers ---------- */
const fmt = (n) => {
  const v = Number(n || 0);
  return (Math.abs(v) < 1000 && v % 1 !== 0)
    ? v.toLocaleString("en-US", { maximumFractionDigits: 3 })
    : Math.round(v).toLocaleString("en-US");
};
/* Currency label comes from the server: amounts are STORED in the configured
   base unit, the UI only labels them (§39 — no silent rial/toman conversion). */
const money = (n) => fmt(n) + " " + (state.currency ? state.currency.label : "");
/* Quantity formatter — keeps 12.5 kg readable and 3 pcs clean (§25) */
const qty = (n) => {
  const v = Number(n || 0);
  return Number.isInteger(v) ? String(v) : String(parseFloat(v.toFixed(3)));
};

function toast(msg, kind = "ok") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast " + (kind === "ok" ? "ok" : "err");
  el.classList.remove("hidden");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 3200);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 204) return null;
  let body = null;
  try { body = await res.json(); } catch (_) {}
  if (!res.ok) {
    const detail = body && body.detail;
    const msg = typeof detail === "object" ? (detail.message || detail.code || JSON.stringify(detail)) : (detail || res.statusText);
    throw new Error(msg);
  }
  return body;
}

/* Timestamps arrive as naive UTC ISO strings. Append the Z so the browser does
 * not silently read them as local time, then render in the Jalali calendar.
 * A missing/NULL timestamp must show "—", never epoch-ish 1348/10/11. */
function faDateTime(iso, withTime = true) {
  if (!iso) return "—";
  const s = String(iso);
  const d = new Date(/[Zz]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
  if (isNaN(d)) return "—";
  const opts = { year: "numeric", month: "2-digit", day: "2-digit" };
  if (withTime) { opts.hour = "2-digit"; opts.minute = "2-digit"; }
  try {
    return new Intl.DateTimeFormat("fa-IR-u-ca-persian", opts).format(d);
  } catch (e) { return d.toLocaleString("fa-IR"); }
}

function openModal(html) {
  const m = $("#modal");
  m.innerHTML = `<div class="modal">${html}</div>`;
  m.classList.remove("hidden");
}
function closeModal() { $("#modal").classList.add("hidden"); $("#modal").innerHTML = ""; }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

/* ---------- auth ---------- */
function showLogin() {
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
}
function showApp() {
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("#login-username").value.trim();
  const password = $("#login-password").value;
  try {
    const form = new URLSearchParams({ username, password });
    const res = await fetch(API + "/auth/login", { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "ورود ناموفق");
    state.token = body.access_token;
    localStorage.setItem("token", state.token);
    const me = await api("/auth/me");
    state.user = me;
    await loadRuntimeConfig();
    showApp();
    buildNav();
    await applyTheme();
    startStatusBar();
    if (state.kiosk) enterKiosk(); else go("dashboard");
  } catch (err) {
    $("#login-error").textContent = err.message;
    $("#login-error").classList.remove("hidden");
  }
});

$("#logout").addEventListener("click", () => {
  localStorage.removeItem("token");
  state.token = ""; state.user = null;
  showLogin();
});

/* ---------- security helpers ---------- */
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------- navigation (permission-aware) ---------- */
/* ---------------------------------------------------------------------------
 * Inline SVG icon set (shared vocabulary with the mobile app). Emoji were
 * replaced because they render as empty boxes on Windows POS machines without
 * an emoji font, and look consumer-grade on a commercial till.
 * ------------------------------------------------------------------------ */
const ICONS = {
  dashboard: '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="10" width="8" height="11" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/>',
  pos: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h5"/>',
  box: '<path d="M3 8l9-5 9 5v8l-9 5-9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
  inbox: '<path d="M4 13h4l1.5 3h5L16 13h4"/><path d="M4 13 6.5 5h11L20 13v6H4z"/>',
  warehouse: '<path d="M3 21V9l9-5 9 5v12"/><path d="M8 21v-7h8v7"/>',
  invoice: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
  user: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"/>',
  gift: '<rect x="3" y="9" width="18" height="12" rx="1.5"/><path d="M3 13h18M12 9v12"/><path d="M12 9C10 9 8 8 8 6.5S9.5 4 12 9zM12 9c2 0 4-1 4-2.5S14.5 4 12 9z"/>',
  chart: '<path d="M4 20V4"/><path d="M4 20h16"/><path d="M8 16v-5M12 16V7M16 16v-8"/>',
  printer: '<path d="M7 8V3h10v5"/><rect x="3" y="8" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
  users: '<circle cx="9" cy="8" r="3.2"/><path d="M2 20c0-3.3 3-5.6 7-5.6s7 2.3 7 5.6"/><path d="M17 8.5a3 3 0 1 0 0-1M18 20c0-2.6-1-4.3-2.5-5.2"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/>',
  stethoscope: '<path d="M6 3v6a4 4 0 0 0 8 0V3"/><path d="M6 3H4M14 3h2"/><path d="M10 13v2a5 5 0 0 0 10 0v-1"/><circle cx="20" cy="12" r="2"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.4 8.3-8 9-4.6-.7-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  cart: '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/><path d="M3 4h2.5l2.6 11h10L21 7H6"/>',
};

const icon = (name, size = 18) =>
  `<svg class="ic" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none"
     stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
     stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;

const NAV = [
  ["dashboard", "داشبورد", "reports.view", "dashboard"],
  ["pos", "صندوق (POS)", "pos.sell", "pos"],
  ["products", "کالاها", "products.view", "box"],
  ["batches", "ورود کالا", "batches.manage", "inbox"],
  ["inventory", "انبار و انبارگردانی", "inventory.view", "warehouse"],
  ["invoices", "فاکتورها", "reports.view", "invoice"],
  ["customers", "مشتریان", "pos.sell", "user"],
  ["marketing", "جشنواره و کوپن", "reports.view", "gift"],
  ["reports", "گزارش‌ها", "reports.view", "chart"],
  ["hardware", "سخت‌افزار", "settings.manage", "printer"],
  ["users", "کاربران", "users.manage", "users"],
  ["settings", "تنظیمات", "settings.manage", "gear"],
  ["diagnostics", "تست اتصالات", "settings.manage", "stethoscope"],
  ["audit", "لاگ‌ها", "audit.view", "shield"],
];

function can(perm) {
  if (!state.user) return false;
  return (state.user.permissions || []).includes(perm);
}

function buildNav() {
  const nav = $("#nav");
  nav.innerHTML = "";
  NAV.forEach(([key, label, perm, ico]) => {
    if (!can(perm)) return;
    const btn = el("button", { class: "nav-item" + (state.view === key ? " active" : ""),
      onclick: () => go(key) });
    btn.innerHTML = `${icon(ico, 18)}<span>${esc(label)}</span>`;
    nav.append(btn);
  });
  $("#whoami").textContent = state.user ? `${state.user.full_name} (${state.user.roles.join(", ")})` : "";
}

async function go(view) {
  state.view = view;
  buildNav();
  const titles = Object.fromEntries(NAV.map(([k, v]) => [k, v]));
  $("#view-title").textContent = titles[view] || view;
  $("#topbar-actions").innerHTML = "";
  const viewEl = $("#view");
  viewEl.innerHTML = `<div class="muted">در حال بارگذاری…</div>`;
  try {
    await RENDER[view]();
  } catch (err) {
    viewEl.innerHTML = `<div class="card"><p class="error">خطا: ${err.message}</p></div>`;
  }
}

/* ---------- views ---------- */
const RENDER = {};

RENDER.dashboard = async () => {
  const d = await api("/reports/dashboard");
  const v = $("#view");
  v.innerHTML = "";
  v.append(
    el("div", { class: "grid grid-4" },
      statCard("فروش امروز", money(d.sales.today), `${d.sales.invoice_count_today} فاکتور`),
      statCard("فروش دیروز", money(d.sales.yesterday), ""),
      statCard("فروش ماه", money(d.sales.month), `میانگین فاکتور: ${money(d.sales.avg_invoice_today)}`),
      statCard("سود امروز", money(d.profit.today), `سود ماه: ${money(d.profit.month)}`),
      statCard("ارزش موجودی", money(d.inventory.value), `${d.inventory.product_count} کالا`),
      statCard("کم‌موجودی", d.inventory.low_stock_count, `${d.inventory.no_stock_count} بدون موجودی`),
    ),
    el("div", { class: "grid grid-2", style: "margin-top:14px" },
      expiryCard("انقضا", d.expiry),
      priceCard("تعارض قیمت (قدیم/جدید)", d.pricing),
    ),
    el("div", { class: "grid grid-3 dash-block" },
      receivCard("مطالبات و بدهی", d.receivables),
      smsCard("وضعیت پیامک", d.sms),
      systemCard("سلامت سیستم", d.system),
    ),
  );
};

function statCard(label, value, sub) {
  return el("div", { class: "card stat" },
    el("span", { class: "label", text: label }),
    el("span", { class: "value", text: value }),
    el("span", { class: "sub", text: sub || "" }),
  );
}

function expiryCard(title, buckets) {
  const rows = [];
  const map = { EXPIRED: ["منقضی", "badge-red"], EXPIRING_TODAY: ["امروز", "badge-red"],
    EXPIRING_3_DAYS: ["کمتر از ۳ روز", "badge-amber"], EXPIRING_7_DAYS: ["کمتر از ۷ روز", "badge-amber"],
    EXPIRING_30_DAYS: ["کمتر از ۳۰ روز", "badge-blue"] };
  for (const [k, items] of Object.entries(buckets)) {
    const [label, cls] = map[k] || [k, "badge-gray"];
    rows.push(el("tr", {},
      el("td", {}, el("span", { class: "badge " + cls, text: label })),
      el("td", { text: items.length + " مورد" }),
    ));
  }
  return el("div", { class: "card" },
    el("h3", { text: title }),
    el("table", {}, el("tbody", {}, ...rows)),
  );
}

function priceCard(title, pricing) {
  const rows = pricing.price_conflicts.map((p) =>
    el("tr", {}, el("td", { text: p.name }), el("td", { text: p.prices.map(fmt).join(" / ") })));
  return el("div", { class: "card" },
    el("h3", { text: title + ` (${pricing.price_conflict_count})` }),
    el("table", {}, el("thead", {}, el("tr", {}, el("th", { text: "کالا" }), el("th", { text: "قیمت‌ها" }))),
      el("tbody", {}, ...rows)),
  );
}

/* ---------- POS — dedicated terminal screen (§6) + Kiosk lock (§7) ---------- */
function cardHtml(html) {
  const node = document.createElement("div");
  node.className = "card dash-block";
  node.innerHTML = html;
  return node;
}

function receivCard(title, r) {
  if (!r) return el("div", { class: "card" });
  const debtors = (r.top_debtors || [])
    .map((t) => `<li>${esc(t.name)} <b>${money(t.balance)}</b></li>`).join("");
  return cardHtml(
    `<h3>${esc(title)}</h3>
     <div class="grid grid-2">
       <div class="mini-stat"><b>${money(r.customer_debt)}</b><span>بدهی مشتریان · ${r.debtor_count} نفر</span></div>
       <div class="mini-stat"><b>${money(r.pending_amount)}</b><span>در انتظار تسویه · ${r.pending_count} فاکتور</span></div>
     </div>
     ${debtors
       ? `<ul class="compact-list" style="margin-top:10px">${debtors}</ul>`
       : `<div class="muted" style="margin-top:10px">مطلبی ثبت نشده است</div>`}`
  );
}

function smsCard(title, m) {
  if (!m) return el("div", { class: "card" });
  const badge = m.configured
    ? `<span class="sys-pill ok">فعال: ${esc(m.provider)}</span>`
    : `<span class="sys-pill warn">تنظیم نشده</span>`;
  return cardHtml(
    `<h3>${esc(title)}</h3>
     <div>${badge}</div>
     <div class="grid grid-3" style="margin-top:10px">
       <div class="mini-stat"><b>${m.sent}</b><span>ارسال‌شده</span></div>
       <div class="mini-stat"><b>${m.pending}</b><span>در صف</span></div>
       <div class="mini-stat"><b>${m.failed}</b><span>ناموفق</span></div>
     </div>
     ${m.last_error ? `<div class="muted" style="margin-top:8px">آخرین خطا: ${esc(m.last_error)}</div>` : ""}`
  );
}

function systemCard(title, sys) {
  if (!sys) return el("div", { class: "card" });
  const cls = sys.status === "OK" ? "ok" : "warn";
  const hw = Object.entries(sys.hardware || {}).map(([k, v]) => {
    const on = v === "CONNECTED";
    return `<span class="sb-item"><i class="hw-dot" style="background:${on ? "var(--green)" : "var(--muted)"}"></i>${esc(k)}</span>`;
  }).join(" ") || `<span class="muted">سخت‌افزاری تعریف نشده</span>`;
  const diag = sys.last_diagnostics
    ? `آخرین تست اتصال: ${sys.last_diagnostics.passed}/${sys.last_diagnostics.total} موفق`
    : "تست اتصال اجرا نشده";
  const issues = (sys.issues || []).map((i) => `<li>${esc(i)}</li>`).join("");
  return cardHtml(
    `<h3>${esc(title)}</h3>
     <div><span class="sys-pill ${cls}">${sys.status === "OK" ? "سالم" : "نیازمند بررسی"}</span> <span class="muted">نسخهٔ ${esc(sys.version)}</span></div>
     <div style="margin-top:10px">${hw}</div>
     <div class="muted" style="margin-top:8px">${diag}${sys.disk_free_gb != null ? ` · ${sys.disk_free_gb} گیگ فضا` : ""}</div>
     ${issues ? `<ul class="compact-list" style="margin-top:8px">${issues}</ul>` : ""}`
  );
}

const posState = { cart: [], customer: null, coupon: null, couponInfo: null };

function posGross(it) { return (it.unit_sell_price || 0) * it.quantity; }

function renderPosCart() {
  const tbl = $("#pos-cart-table");
  if (!tbl) return;
  if (!posState.cart.length) {
    tbl.innerHTML = `<tbody><tr><td class="muted" style="padding:24px;text-align:center">سبد خالی است — بارکد را اسکن کنید</td></tr></tbody>`;
  } else {
    const showCost = can("pricing.view_cost");
    const rows = posState.cart.map((it, idx) => `
      <tr>
        <td>${esc(it.product_name)}<div class="muted" style="font-size:11px">${esc(it.batch_number || "")}${it.expiry_date ? " · انقضا " + esc(it.expiry_date) : ""}</div></td>
        <td class="qty"><button class="btn btn-sm" onclick="posQty(${idx},1)">+</button>
          <input inputmode="decimal" value="${qty(it.quantity)}" onchange="posQty(${idx},0,this.value)" />
          <button class="btn btn-sm" onclick="posQty(${idx},-1)">−</button>
          ${it.unit_symbol ? `<span class="unit-tag">${esc(it.unit_symbol)}</span>` : ""}</td>
        <td>${money(it.unit_sell_price)}</td>
        <td>${it.discount ? "<div class=\"muted\" style=\"font-size:11px\">−" + money(it.discount) + "</div>" : ""}${money(posGross(it) - (it.discount || 0))}</td>
        <td><button class="btn btn-sm btn-danger" onclick="posRemove(${idx})">✕</button></td>
      </tr>`).join("");
    tbl.innerHTML = `<thead><tr><th>کالا</th><th>تعداد</th><th>فی</th><th>جمع</th><th></th></tr></thead><tbody>${rows}</tbody>`;
  }
  // totals
  const gross = posState.cart.reduce((a, it) => a + posGross(it), 0);
  const disc = posState.cart.reduce((a, it) => a + (it.discount || 0), 0);
  const count = posState.cart.reduce((a, it) => a + Number(it.quantity), 0);
  const coupon = posState.couponInfo && posState.couponInfo.ok ? posState.couponInfo.discount : 0;
  const showCost = can("pricing.view_cost");
  const profit = posState.cart.reduce((a, it) => a + (posGross(it) - (it.discount || 0) - (it.unit_buy_price || 0) * it.quantity), 0) - coupon;
  $("#pos-totals").innerHTML = `
    <div class="row"><span class="muted">تعداد کالا</span><strong>${count}</strong></div>
    <div class="row"><span class="muted">جمع</span><span>${money(gross)}</span></div>
    ${disc ? `<div class="row"><span class="muted">تخفیف</span><span class="err">−${money(disc)}</span></div>` : ""}
    ${coupon ? `<div class="row"><span class="muted">کوپن ${esc(posState.coupon)}</span><span class="err">−${money(coupon)}</span></div>` : ""}
    <div class="row grand"><span>قابل پرداخت</span><span>${money(gross - disc - coupon)}</span></div>
    ${showCost ? `<div class="row"><span class="muted">سود تخمینی</span><span class="ok">${money(profit)}</span></div>` : ""}`;
  const cpEl = $("#pos-coupon-state");
  if (cpEl) {
    cpEl.innerHTML = posState.couponInfo
      ? (posState.couponInfo.ok
          ? `<span class="badge badge-green">🎁 ${esc(posState.coupon)} — ${money(posState.couponInfo.discount)}</span>
             <button class="btn btn-sm" onclick="posClearCoupon()">✕</button>`
          : `<span class="badge badge-red">${esc(posState.couponInfo.message || "کوپن نامعتبر")}</span>
             <button class="btn btn-sm" onclick="posClearCoupon()">✕</button>`)
      : `<span class="muted">بدون کوپن (F9)</span>`;
  }
  $("#pos-customer").innerHTML = posState.customer
    ? `👤 ${esc(posState.customer.name)} ${posState.customer.phone ? "· " + esc(posState.customer.phone) : ""} <button class="btn btn-sm" onclick="posClearCustomer()">✕</button>`
    : `<span class="muted">بدون مشتری (F8)</span>`;
}

window.posQty = (idx, delta, direct) => {
  const it = posState.cart[idx];
  if (!it) return;
  const u = unitById(it.unit_id);
  const step = u && u.allow_decimal ? 0.5 : 1;
  const min = u && u.allow_decimal ? 0.001 : 1;
  let next;
  if (delta === 0 && direct !== undefined) next = parseFloat(direct);
  else next = Number(it.quantity) + delta * step;
  if (!isFinite(next) || next <= 0) next = min;
  if (!(u && u.allow_decimal)) next = Math.max(1, Math.round(next));
  else next = Math.max(min, parseFloat(next.toFixed(3)));
  if (it.available != null && next > it.available) {
    toast(`حداکثر موجودی این بچ ${qty(it.available)} است`, "err");
    next = it.available;
  }
  it.quantity = next;
  renderPosCart();
  posRevalidateCoupon();
};
window.posRemove = (idx) => { posState.cart.splice(idx, 1); renderPosCart(); };
window.posClearCustomer = () => { posState.customer = null; renderPosCart(); };

/* The receipt clock must show STORE-local time (the configured timezone), not
 * the workstation's. A till whose Windows clock/timezone is wrong would
 * otherwise print a misleading time on every receipt. We anchor to the
 * server's time once and tick locally from that offset. */
let _posClockOffsetMs = null;

async function syncPosClock() {
  try {
    const t = await api("/settings/time");
    // offset between store-local wall clock and this machine's clock
    _posClockOffsetMs = new Date(t.local.slice(0, 19) + "Z") - new Date(
      new Date().toISOString().slice(0, 19) + "Z");
    state.serverTime = t;
  } catch (e) { _posClockOffsetMs = null; }
}

function posClock() {
  const el = $("#pos-clock");
  if (!el) return;
  const tick = () => {
    const node = $("#pos-clock");
    if (!node) { clearInterval(window._posClockTimer); return; }
    const base = new Date(Date.now() + (_posClockOffsetMs || 0));
    const hhmm = base.toISOString().slice(11, 19);
    node.textContent = _posClockOffsetMs === null
      ? new Date().toLocaleTimeString("fa-IR")
      : hhmm.replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  };
  syncPosClock().then(tick);
  clearInterval(window._posClockTimer);
  window._posClockTimer = setInterval(tick, 1000);
}

RENDER.pos = async () => {
  let cfg = { shortcut: "Ctrl+Shift+L", store_name: "فروشگاه" };
  try { cfg = await api("/pos/kiosk/config"); } catch (e) { /* defaults */ }
  state.kioskShortcut = cfg.shortcut;
  $("#view").innerHTML = `
    <div class="pos-screen" id="pos-screen">
      <div class="pos-header">
        <div class="pos-store">🏪 ${esc(cfg.store_name)}</div>
        <div class="pos-register">صندوق: ${esc(state.user ? state.user.full_name || state.user.username : "")}</div>
        <div class="pos-clock" id="pos-clock"></div>
        <button class="btn btn-sm" id="pos-kiosk-btn">${state.kiosk ? "🔓 خروج کیوسک" : "🔒 قفل (میان‌بر)"}</button>
      </div>
      <div class="pos-main">
        <div class="pos-cart"><table class="pos-cart-table" id="pos-cart-table"></table></div>
        <div class="pos-side">
          <input id="pos-scan" class="pos-scan" placeholder="＝ اسکن بارکد یا جستجوی نام کالا…" autocomplete="off" autofocus />
          <div id="pos-suggest" class="pos-suggest hidden"></div>
          <div class="pos-hint muted"><span class="kbd">Enter</span> افزودن · <span class="kbd">F2</span> پرداخت · <span class="kbd">F4</span> تخفیف · <span class="kbd">F8</span> مشتری · <span class="kbd">F9</span> کوپن · <span class="kbd">Del</span> حذف آخرین · <span class="kbd">Esc</span> خالی کردن</div>
          <div id="pos-customer" class="pos-customer"></div>
          <div id="pos-coupon-state" class="pos-customer"></div>
          <div id="pos-totals" class="pos-totals"></div>
          <div class="pos-actions">
            <button class="pos-btn pos-btn-pay" id="pos-pay">پرداخت (F2)</button>
            <button class="pos-btn" id="pos-discount-btn">تخفیف (F4)</button>
            <button class="pos-btn" id="pos-customer-btn">مشتری (F8)</button>
            <button class="pos-btn" id="pos-coupon-btn">کوپن (F9)</button>
            <button class="pos-btn pos-btn-danger" id="pos-clear-btn">خالی کردن (Esc)</button>
          </div>
        </div>
      </div>
      <div id="pos-receipt"></div>
    </div>`;
  $("#pos-scan").addEventListener("keydown", async (e) => {
    if (e.key === "ArrowDown") {
      const first = document.querySelector(".pos-suggest .sug");
      if (first) { e.preventDefault(); first.focus(); }
      return;
    }
    if (e.key !== "Enter") return;
    const term = e.target.value.trim();
    e.target.value = "";
    hideSuggest();
    if (term) await posAddByTerm(term);
  });
  /* Typed searches (name / SKU / code) show live suggestions; a hardware
     scanner types too fast for this to interfere — it ends with Enter. */
  $("#pos-scan").addEventListener("input", debounce(async (e) => {
    const term = e.target.value.trim();
    if (term.length < 2 || /^\d{8,}$/.test(term)) { hideSuggest(); return; }
    try {
      const r = await api(`/pos/search?q=${encodeURIComponent(term)}&limit=8`);
      showSuggest(r.items);
    } catch (err) { hideSuggest(); }
  }, 220));
  $("#pos-pay").addEventListener("click", () => posCheckoutModal());
  $("#pos-discount-btn").addEventListener("click", () => posDiscountModal());
  $("#pos-customer-btn").addEventListener("click", () => posCustomerModal());
  $("#pos-coupon-btn").addEventListener("click", () => posCouponModal());
  $("#pos-clear-btn").addEventListener("click", () => {
    posState.cart = []; posState.coupon = null; posState.couponInfo = null; renderPosCart();
  });
  $("#pos-kiosk-btn").addEventListener("click", () => (state.kiosk ? exitKioskPrompt() : enterKiosk()));
  posClock();
  renderPosCart();
  $("#pos-scan").focus();
};

function hideSuggest() {
  const box = $("#pos-suggest");
  if (box) { box.classList.add("hidden"); box.innerHTML = ""; }
}

function showSuggest(items) {
  const box = $("#pos-suggest");
  if (!box) return;
  if (!items || !items.length) {
    box.innerHTML = `<div class="sug-empty muted">کالایی یافت نشد</div>`;
    box.classList.remove("hidden");
    return;
  }
  box.innerHTML = items.map((i) => `
    <button class="sug" data-id="${i.product_id}" tabindex="0">
      <span class="sug-name">${esc(i.name)}</span>
      <span class="sug-meta">${esc(i.barcode)} · موجودی ${qty(i.available_qty)}${i.unit ? " " + esc(i.unit.symbol || "") : ""}
        ${i.price_count > 1 ? ` · <em>${i.price_count} قیمت</em>` : ""}</span>
    </button>`).join("");
  box.classList.remove("hidden");
  box.querySelectorAll(".sug").forEach((node) => node.addEventListener("click", async () => {
    const item = items.find((x) => String(x.product_id) === node.dataset.id);
    $("#pos-scan").value = ""; hideSuggest();
    await posAddResolved(item);
  }));
}

/* Accepts a barcode OR a typed term; a single exact match is added directly. */
async function posAddByTerm(term) {
  try {
    const r = await api(`/pos/search?q=${encodeURIComponent(term)}&limit=8`);
    if (!r.items.length) { await posAddByBarcode(term); return; }
    const exact = r.items.filter((i) => i.exact);
    if (exact.length === 1) { await posAddResolved(exact[0]); return; }
    if (r.items.length === 1) { await posAddResolved(r.items[0]); return; }
    showSuggest(r.items);
  } catch (e) { await posAddByBarcode(term); }
}

async function posAddResolved(item) {
  if (!item) return;
  const product = { id: item.product_id, name: item.name, unit_id: item.unit ? unitIdByName(item.unit.name) : null };
  const opts = item.batches || [];
  if (!opts.length) { toast("موجودی قابل فروش ندارد", "err"); return; }
  if (opts.length === 1) { posAskQuantity(product, opts[0]); return; }
  posBatchChooser(product, opts);
}

const unitIdByName = (name) => {
  const u = state.units.find((x) => x.name === name);
  return u ? u.id : null;
};

function posBatchChooser(product, opts) {
  const rows = opts.map((o) => `
    <div class="batch-option ${o.is_recommended ? "recommended" : ""}" data-batch="${o.batch_id}">
      <div class="b-title">${o.is_recommended ? "⭐ " : ""}${esc(o.batch_number)} — ${money(o.sell_price)}</div>
      <div class="b-meta">موجودی: ${qty(o.current_qty)}${o.expiry_date ? " · انقضا: " + esc(o.expiry_date) + " (" + (o.days_left ?? "—") + " روز)" : ""}</div>
    </div>`).join("");
  openModal(`<h3>${esc(product.name)} — انتخاب قیمت / بچ</h3>${rows}
    <p class="muted">پیشنهاد سیستم بر اساس سیاست موجودی است؛ بچ واقعی قفسه را شما انتخاب می‌کنید.</p>`);
  document.querySelectorAll(".batch-option").forEach((node) =>
    node.addEventListener("click", () => {
      const b = opts.find((o) => String(o.batch_id) === node.dataset.batch);
      closeModal(); posAskQuantity(product, b);
    }));
}

async function posAddByBarcode(barcode) {
  let p;
  try {
    p = await api(`/products/barcode/${encodeURIComponent(barcode)}`);
  } catch (err) {
    try {
      const r = await api(`/barcode/resolve/${encodeURIComponent(barcode)}`);
      if (r.origin === "local" && r.product) p = r.product;
      else toast(r.message || "بارکد ناشناخته — ثبت دستی لازم است", "err");
    } catch (e2) { toast("کالا یافت نشد", "err"); }
    $("#pos-scan").focus();
    if (!p) return;
  }
  let options;
  try { options = await api(`/pos/batch-options/${p.id}`); } catch (e) { toast(e.message, "err"); return; }
  const opts = options.options || [];
  if (!opts.length) { toast("موجودی قابل فروش ندارد", "err"); return; }
  if (opts.length === 1) { posAskQuantity(p, opts[0]); return; }
  // چند Batch / قیمت قدیم-جدید (§16): صندوق‌دار انتخاب می‌کند
  const rows = opts.map((o) => `
    <div class="batch-option ${o.is_recommended ? "recommended" : ""}" data-batch="${o.batch_id}">
      <div class="b-title">${o.is_recommended ? "⭐ " : ""}${esc(o.batch_number)} — ${money(o.sell_price)}</div>
      <div class="b-meta">موجودی: ${o.current_qty} ${o.expiry_date ? "· انقضا: " + esc(o.expiry_date) + " (" + (o.days_left ?? "—") + " روز)" : ""}</div>
    </div>`).join("");
  openModal(`<h3>${esc(p.name)} — انتخاب قیمت / Batch</h3>${rows}
    <p class="muted">پیشنهاد سیستم بر اساس سیاست موجودی است؛ Batch واقعی قفسه را شما انتخاب می‌کنید.</p>`);
  document.querySelectorAll(".batch-option").forEach((node) =>
    node.addEventListener("click", () => {
      const b = opts.find((o) => o.batch_id == node.dataset.batch);
      closeModal(); posAskQuantity(p, b);
    }));
}

function posPushCart(p, batch, amount) {
  const u = unitById(p.unit_id);
  const existing = posState.cart.find((i) => i.product_id === p.id && i.batch_id === batch.batch_id);
  if (existing) existing.quantity = parseFloat((Number(existing.quantity) + Number(amount)).toFixed(3));
  else posState.cart.push({ product_id: p.id, product_name: p.name, batch_id: batch.batch_id,
    batch_number: batch.batch_number, quantity: Number(amount),
    unit_id: p.unit_id, unit_symbol: u ? u.symbol : null,
    available: batch.current_qty,
    unit_sell_price: batch.sell_price,
    unit_buy_price: batch.buy_price, expiry_date: batch.expiry_date, discount: 0 });
  renderPosCart();
  posRevalidateCoupon();
  const scan = $("#pos-scan");
  if (scan) scan.focus();
}

/* Weighted goods: ask for the exact amount when the unit is divisible (§25) */
function posAskQuantity(p, batch) {
  const u = unitById(p.unit_id);
  if (!u || !u.allow_decimal) { posPushCart(p, batch, 1); return; }
  openModal(`<h3>${esc(p.name)}</h3>
    <p class="muted">واحد: ${esc(u.name)} — موجودی این بچ: ${qty(batch.current_qty)} ${esc(u.symbol || "")}</p>
    <label>مقدار (${esc(u.symbol || u.name)})</label>
    <input id="pq-val" inputmode="decimal" value="1" autofocus />
    <button id="pq-ok" class="btn btn-primary btn-block" style="margin-top:14px">افزودن به سبد</button>`);
  const submit = () => {
    const val = parseFloat($("#pq-val").value);
    if (!isFinite(val) || val <= 0) { toast("مقدار نامعتبر", "err"); return; }
    closeModal(); posPushCart(p, batch, parseFloat(val.toFixed(3)));
  };
  $("#pq-ok").addEventListener("click", submit);
  $("#pq-val").addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  $("#pq-val").focus(); $("#pq-val").select();
}

/* ---------- POS coupon (§31–38) ---------- */
window.posClearCoupon = () => { posState.coupon = null; posState.couponInfo = null; renderPosCart(); };

function posCouponModal() {
  openModal(`<h3>🎁 کد تخفیف</h3>
    <label>کد کوپن</label><input id="cp-input" autocomplete="off" autofocus
      value="${esc(posState.coupon || "")}" placeholder="مثال: NEXT-AB12CD34" />
    <p class="muted">کوپن هنگام ثبت نهایی فروش مصرف می‌شود؛ اگر فروش ثبت نشود کوپن سوخت نمی‌شود.</p>
    <button id="cp-apply" class="btn btn-primary btn-block" style="margin-top:14px">اعمال</button>`);
  const apply = async () => {
    const code = $("#cp-input").value.trim();
    if (!code) return;
    posState.coupon = code;
    closeModal();
    await posRevalidateCoupon(true);
  };
  $("#cp-apply").addEventListener("click", apply);
  $("#cp-input").addEventListener("keydown", (e) => { if (e.key === "Enter") apply(); });
}

async function posRevalidateCoupon(announce) {
  if (!posState.coupon) return;
  const gross = posState.cart.reduce((a, it) => a + posGross(it) - (it.discount || 0), 0);
  if (gross <= 0) { posState.couponInfo = null; renderPosCart(); return; }
  try {
    const r = await api("/marketing/coupons/validate", { method: "POST", body: JSON.stringify({
      code: posState.coupon, amount: gross,
      customer_id: posState.customer ? posState.customer.id : null }) });
    posState.couponInfo = { ok: true, discount: r.discount };
    if (announce) toast(`کوپن اعمال شد: ${money(r.discount)} تخفیف`);
  } catch (e) {
    posState.couponInfo = { ok: false, message: e.message };
    if (announce) toast(e.message, "err");
  }
  renderPosCart();
}

/* POS: discount (line or whole cart, split proportionally) */
function posDiscountModal() {
  if (!posState.cart.length) { toast("سبد خالی است", "err"); return; }
  const options = posState.cart.map((it, idx) =>
    `<option value="${idx}">${esc(it.product_name)} (${money(posGross(it))})</option>`).join("");
  openModal(`<h3>تخفیف</h3>
    <label>اعمال روی</label>
    <select id="disc-target"><option value="-1">کل سبد</option>${options}</select>
    <label>مبلغ تخفیف (ریال)</label>
    <input id="disc-amount" type="number" min="0" value="0" />
    <button id="disc-apply" class="btn btn-primary btn-block" style="margin-top:14px">اعمال</button>`);
  $("#disc-apply").addEventListener("click", () => {
    const target = parseInt($("#disc-target").value, 10);
    const amount = Number($("#disc-amount").value || 0);
    if (amount <= 0) { toast("مبلغ نامعتبر", "err"); return; }
    if (target >= 0) {
      const it = posState.cart[target];
      if (amount > posGross(it)) { toast("تخفیف از مبلغ خط بیشتر است", "err"); return; }
      it.discount = amount;
    } else {
      const gross = posState.cart.reduce((a, it) => a + posGross(it), 0);
      if (amount > gross) { toast("تخفیف از جمع سبد بیشتر است", "err"); return; }
      // تقسیم متناسب؛ باقی‌مانده گرد شدن روی آخرین خط
      let assigned = 0;
      posState.cart.forEach((it, i) => {
        if (i === posState.cart.length - 1) { it.discount = amount - assigned; return; }
        it.discount = Math.round((posGross(it) / gross) * amount);
        assigned += it.discount;
      });
    }
    closeModal(); renderPosCart();
  });
}

/* POS: customer */
function posCustomerModal() {
  openModal(`<h3>مشتری</h3>
    <label>شماره موبایل</label><input id="cust-phone" autocomplete="off" />
    <label>نام (برای مشتری جدید)</label><input id="cust-name" autocomplete="off" />
    <button id="cust-save" class="btn btn-primary btn-block" style="margin-top:14px">انتخاب / ایجاد</button>`);
  $("#cust-save").addEventListener("click", async () => {
    const phone = $("#cust-phone").value.trim();
    const name = $("#cust-name").value.trim();
    try {
      if (!phone && !name) { posState.customer = null; closeModal(); renderPosCart(); return; }
      let c = null;
      if (phone) {
        try { c = await api(`/customers/phone/${encodeURIComponent(phone)}`); } catch (e) { c = null; }
      }
      if (!c && name) c = await api("/customers", { method: "POST", body: JSON.stringify({ name: name || phone, phone: phone || null }) });
      if (!c && phone) { toast("مشتری یافت نشد؛ نام را هم وارد کنید", "err"); return; }
      posState.customer = c; closeModal(); renderPosCart();
    } catch (e) { toast(e.message, "err"); }
  });
}

/* POS: checkout */
function posCheckoutModal() {
  if (!posState.cart.length) { toast("سبد خالی است", "err"); return; }
  const gross = posState.cart.reduce((a, it) => a + posGross(it), 0);
  const disc = posState.cart.reduce((a, it) => a + (it.discount || 0), 0);
  const coupon = posState.couponInfo && posState.couponInfo.ok ? posState.couponInfo.discount : 0;
  const total = gross - disc - coupon;
  openModal(`<h3>پرداخت</h3>
    ${coupon ? `<div class="row" style="display:flex;justify-content:space-between"><span class="muted">کوپن ${esc(posState.coupon)}</span><span class="err">−${money(coupon)}</span></div>` : ""}
    <div class="row" style="display:flex;justify-content:space-between"><span>قابل پرداخت</span><strong style="font-size:20px">${money(total)}</strong></div>
    <label>روش پرداخت</label>
    <select id="pay-method"><option value="CASH">نقدی</option><option value="CARD">کارت</option><option value="MIXED">ترکیبی</option>${
      posState.customer ? `<option value="ACCOUNT">افزودن به حساب دفتری (نسیه)</option>` : ""}</select>
    ${posState.customer
      ? `<p class="muted">مشتری: ${esc(posState.customer.name)}${
          posState.customer.balance ? ` — مانده فعلی ${money(posState.customer.balance)}` : ""}</p>`
      : `<p class="muted">مشتری آزاد — برای فروش نسیه ابتدا مشتری را انتخاب کنید (F4).</p>`}
    <div id="pay-account" class="hidden" style="margin-top:8px">
      <p class="muted">این مبلغ به‌عنوان <strong>بدهی</strong> در حساب دفتری مشتری ثبت می‌شود
        و وجهی دریافت نمی‌گردد.</p>
    </div>
    <div id="pay-cash-area" style="margin-top:8px">
      <label>دریافتی نقدی</label><input id="pay-cash" type="number" value="${total}" />
      <div id="pay-change" class="muted"></div>
    </div>
    <div id="pay-split" class="hidden" style="margin-top:8px">
      <label>مبلغ نقدی</label><input id="pay-cash2" type="number" value="0" />
      <label>مبلغ کارت</label><input id="pay-card" type="number" value="${total}" />
    </div>
    <button id="btn-pay" class="btn btn-primary btn-block" style="margin-top:14px">ثبت فروش (Enter)</button>`);
  const updChange = () => {
    const cash = Number($("#pay-cash").value || 0);
    $("#pay-change").textContent = cash >= total ? `باقی‌مانده: ${money(cash - total)}` : "نقصانه!";
  };
  $("#pay-method").addEventListener("change", (e) => {
    const m = e.target.value;
    $("#pay-cash-area").classList.toggle("hidden", m !== "CASH");
    $("#pay-split").classList.toggle("hidden", m !== "MIXED");
    $("#pay-account").classList.toggle("hidden", m !== "ACCOUNT");
  });
  $("#pay-cash").addEventListener("input", updChange); updChange();
  $("#btn-pay").addEventListener("click", () => doCheckout(total));
  $("#pay-cash").focus();
  $("#pay-cash").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); doCheckout(total); } });
}

async function doCheckout(total) {
  const method = $("#pay-method").value;
  let payments;
  if (method === "MIXED") {
    const cash = Number($("#pay-cash2").value || 0), card = Number($("#pay-card").value || 0);
    payments = [{ method: "CASH", amount: cash }, { method: "CARD", amount: card }];
  } else payments = [{ method, amount: total }];

  if (method === "ACCOUNT" && !posState.customer) {
    toast("فروش نسیه فقط برای مشتری ثبت‌شده ممکن است", "err");
    return;
  }
  try {
    const inv = await api("/pos/checkout", {
      method: "POST",
      body: JSON.stringify({
        items: posState.cart.map((i) => ({ product_id: i.product_id, batch_id: i.batch_id,
                                           quantity: i.quantity, discount: i.discount || 0 })),
        payments,
        customer_id: posState.customer ? posState.customer.id : null,
        coupon_code: posState.couponInfo && posState.couponInfo.ok ? posState.coupon : null }),
    });
    posState.cart = []; posState.customer = null;
    posState.coupon = null; posState.couponInfo = null;
    closeModal(); renderPosCart();
    toast(inv.payment_status === "ON_ACCOUNT"
      ? `ثبت شد (نسیه): ${inv.invoice_number}`
      : `فروش ثبت شد: ${inv.invoice_number}`);
    if (inv.issued_coupon) {
      openModal(`<h3>🎁 کوپن خرید بعدی</h3>
        <p>برای این مشتری کوپن <code style="font-size:18px">${esc(inv.issued_coupon.code)}</code> صادر شد.</p>
        <p class="muted">${inv.issued_coupon.valid_until ? "اعتبار تا " + esc(inv.issued_coupon.valid_until.slice(0, 10)) : ""}
          — همراه پیامک فاکتور ارسال می‌شود.</p>
        <button class="btn btn-primary btn-block" onclick="closeModal()">باشه</button>`);
    }
    try {
      const pr = await api(`/invoices/${inv.invoice_id}/print`, { method: "POST" });
      if (pr.ok && typeof pr.message === "string" && pr.message.includes("\n"))
        $("#pos-receipt").innerHTML = `<pre class="receipt">${esc(pr.message)}</pre>`;
      else toast("چاپ: " + pr.message, pr.ok ? "ok" : "err");
    } catch (e) { /* printing never blocks the sale */ }
  } catch (err) { toast(err.message, "err"); }
}

/* ---------- Kiosk / Lock mode (§7) ---------- */
async function enterKiosk() {
  state.kiosk = true;
  localStorage.setItem("kiosk", "1");
  document.body.classList.add("kiosk");
  try { await document.documentElement.requestFullscreen(); } catch (e) { /* user gesture needed */ }
  go("pos");
}

function exitKioskPrompt() {
  openModal(`<h3>🔓 خروج از حالت کیوسک</h3>
    <p class="muted">خروج تنها با احراز هویت مدیر امکان‌پذیر است.</p>
    <label>نام کاربری مدیر</label><input id="kiosk-user" autocomplete="off" />
    <label>رمز عبور</label><input id="kiosk-pass" type="password" autocomplete="current-password" />
    <button id="kiosk-unlock" class="btn btn-primary btn-block" style="margin-top:14px">تأیید و خروج</button>`);
  $("#kiosk-user").focus();
  $("#kiosk-unlock").addEventListener("click", kioskUnlock);
  $("#kiosk-pass").addEventListener("keydown", (e) => { if (e.key === "Enter") kioskUnlock(); });
}

async function kioskUnlock() {
  try {
    await api("/pos/kiosk/unlock", { method: "POST",
      body: JSON.stringify({ username: $("#kiosk-user").value.trim(), password: $("#kiosk-pass").value }) });
    state.kiosk = false;
    localStorage.removeItem("kiosk");
    document.body.classList.remove("kiosk");
    try { if (document.fullscreenElement) await document.exitFullscreen(); } catch (e) {}
    closeModal(); toast("خروج از حالت کیوسک انجام شد");
    go("dashboard");
  } catch (e) { toast(e.message, "err"); }
}

/* single global keyboard dispatcher (no listener leaks) */
function matchesShortcut(e, combo) {
  if (!combo) return false;
  const parts = combo.toLowerCase().split("+").map((x) => x.trim());
  const key = parts[parts.length - 1];
  const needCtrl = parts.includes("ctrl"), needShift = parts.includes("shift"), needAlt = parts.includes("alt");
  return e.key.toLowerCase() === key && e.ctrlKey === needCtrl && e.shiftKey === needShift && e.altKey === needAlt;
}

document.addEventListener("keydown", (e) => {
  // kiosk lock shortcut works anywhere in the app
  if (matchesShortcut(e, state.kioskShortcut || "Ctrl+Shift+L")) {
    e.preventDefault();
    if (!state.kiosk) enterKiosk(); else if (state.view === "pos") exitKioskPrompt();
    return;
  }
  if (state.view !== "pos" || !$("#pos-screen")) return;
  const modalOpen = !$("#modal").classList.contains("hidden");
  if (e.key === "F2") { e.preventDefault(); if (!modalOpen) posCheckoutModal(); }
  else if (e.key === "F4") { e.preventDefault(); if (!modalOpen) posDiscountModal(); }
  else if (e.key === "F8") { e.preventDefault(); if (!modalOpen) posCustomerModal(); }
  else if (e.key === "F9") { e.preventDefault(); if (!modalOpen) posCouponModal(); }
  else if (e.key === "Delete" && !modalOpen) { posState.cart.pop(); renderPosCart(); }
  else if (e.key === "Escape" && !modalOpen) {
    posState.cart = []; posState.coupon = null; posState.couponInfo = null; renderPosCart();
  }
  const tag = ((document.activeElement && document.activeElement.tagName) || "").toLowerCase();
  if (!modalOpen && tag !== "input" && tag !== "textarea" && tag !== "select" && e.key.length === 1) {
    $("#pos-scan").focus();
  }
});

setInterval(() => { if (state.view === "pos") posClock(); }, 1000);

/* ---------- products ---------- */
RENDER.products = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="card" style="margin-bottom:14px">
    <h3>ثبت کالای جدید</h3>
    <p class="muted">بارکد را اسکن کنید تا نام، برند، دسته و تصویر به‌صورت
      خودکار از منابع مجاز بازیابی شود. داده‌های بیرونی همیشه پیش از ثبت
      نیازمند تأیید شما هستند.</p>
    <div class="form-row">
      <div><label>بارکد</label>
        <input id="p-barcode" placeholder="اسکن یا تایپ بارکد" autocomplete="off" /></div>
      <div style="align-self:end">
        <button id="p-lookup" class="btn btn-ghost">بازیابی خودکار اطلاعات</button></div>
    </div>
    <div id="p-resolve-status" class="muted" style="margin-top:8px"></div>
    <div class="form-row" style="margin-top:8px">
      <div><label>نام کالا</label><input id="p-name" /></div>
      <div><label>برند</label><input id="p-brand" /></div>
      <div><label>دسته</label><input id="p-category" /></div>
      <div><label>حداقل موجودی هشدار</label><input id="p-min" type="number" value="5" /></div>
    </div>
    <div id="p-image-box" class="hidden" style="margin-top:10px">
      <label>تصویر کالا</label>
      <div class="img-preview">
        <img id="p-image" alt="تصویر کالا" />
        <div class="img-meta"><span id="p-image-meta" class="muted"></span>
          <button id="p-image-clear" class="btn btn-ghost btn-sm">حذف تصویر</button></div>
      </div>
    </div>
    <input id="p-image-url" type="hidden" />
    <button id="p-add" class="btn btn-primary" style="margin-top:12px">ثبت کالا</button>
  </div>
  <div class="card"><h3>فهرست کالاها</h3><table id="p-table"></table></div>`;

  const setImage = (path) => {
    $("#p-image-url").value = path || "";
    const box = $("#p-image-box");
    if (path) {
      $("#p-image").src = path.startsWith("http") ? path : `/media/${path.replace(/^\/?media\//, "")}`;
      box.classList.remove("hidden");
    } else { box.classList.add("hidden"); $("#p-image").removeAttribute("src"); }
  };
  $("#p-image-clear").addEventListener("click", () => { setImage(null); $("#p-image-meta").textContent = ""; });

  /* Scan -> multi-source lookup -> fill the form. The operator still confirms. */
  const lookup = async () => {
    const code = $("#p-barcode").value.trim();
    if (!code) return;
    const status = $("#p-resolve-status");
    status.className = "muted";
    status.textContent = "در حال جست‌وجو در منابع…";
    try {
      const r = await api(`/barcode/scan?barcode=${encodeURIComponent(code)}`,
        { method: "POST", body: JSON.stringify({ with_image: true }) });

      if (r.origin === "invalid") {
        status.className = "err"; status.textContent = r.message; return;
      }
      if (r.origin === "local" || r.origin === "cache") {
        status.className = "err";
        status.textContent = `${r.message} — «${(r.product || {}).name || ""}»`;
        return;
      }
      const d = r.draft || {};
      if (d.name) $("#p-name").value = d.name;
      if (d.brand) $("#p-brand").value = d.brand;
      if (d.category) $("#p-category").value = d.category;
      setImage(d.image_url || null);
      if (r.image && r.image.stored) {
        // Credit the source whose bytes were actually kept, not merely the
        // first candidate tried — several sources may offer an image.
        const won = (r.image.candidates || []).find(
          (c) => c.local_path && c.local_path === r.image.best_local_path);
        const dim = won && won.validation && won.validation.width
          ? ` · ${won.validation.width}×${won.validation.height}` : "";
        $("#p-image-meta").textContent =
          `منبع: ${(won && won.source) || "—"}${dim} · ذخیره‌شدهٔ محلی`;
      }

      const tried = (r.sources || []).length;
      const failed = (r.sources || []).filter((x) => !x.ok);
      if (r.coverage && r.coverage.fields_found) {
        status.className = "ok";
        status.textContent =
          `${r.coverage.fields_found} فیلد از ${tried} منبع بازیابی شد` +
          (r.coverage.image_found ? " + تصویر" : " (بدون تصویر)") +
          " — لطفاً بررسی و تأیید کنید.";
      } else {
        status.className = "err";
        // Be explicit about WHY nothing came back; silence here was the old bug.
        status.textContent = failed.length
          ? `هیچ داده‌ای یافت نشد. خطای منابع: ${failed.map((f) => `${f.source}=${(f.error || {}).kind}`).join("، ")} — ثبت دستی لازم است.`
          : (tried ? "منابع پاسخ دادند اما داده‌ای برای این بارکد نداشتند — ثبت دستی لازم است."
                   : "هیچ منبعی فعال نیست — در تنظیمات یک منبع اضافه کنید یا دستی ثبت کنید.");
      }
    } catch (e) {
      status.className = "err"; status.textContent = `خطا در بازیابی: ${e.message}`;
    }
  };
  $("#p-lookup").addEventListener("click", lookup);
  // A hardware barcode gun ends its burst with Enter.
  $("#p-barcode").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); lookup(); }
  });

  $("#p-add").addEventListener("click", async () => {
    try {
      const barcode = $("#p-barcode").value.trim();
      const name = $("#p-name").value.trim();
      if (!name) { toast("نام کالا الزامی است", "err"); return; }

      // Brand/category were typed by the operator but never sent — resolve
      // the free-text names to real rows so the FKs stop being null.
      const brandName = $("#p-brand").value.trim();
      const catName = $("#p-category").value.trim();
      const brand = brandName
        ? await api("/products/brands", { method: "POST", body: JSON.stringify({ name: brandName }) })
        : null;
      const category = catName
        ? await api("/products/categories", { method: "POST", body: JSON.stringify({ name: catName }) })
        : null;

      // §33 — warn before creating a probable duplicate. Advisory: the
      // operator may confirm, because two real products can share a name.
      const dup = await api("/products/check-duplicate", { method: "POST",
        body: JSON.stringify({ name, barcode: barcode || null,
                               brand_id: brand ? brand.id : null }) });
      if (dup.has_warning) {
        const lines = dup.exact_barcode_match
          ? `کالایی با همین بارکد وجود دارد: ${dup.exact_barcode_match.name}`
          : "کالاهای مشابه: " + dup.possible_duplicates
              .map((c) => `${c.name} (${Math.round(c.confidence * 100)}٪)`).join("، ");
        if (!confirm(`${lines}\n\nآیا مطمئن هستید که این کالای جدیدی است؟`)) return;
      }

      const body = {
        name, min_stock_alert: Number($("#p-min").value || 5),
        // §16 — no barcode typed means a loose/bulk item; the server mints
        // an internal INT- code instead of rejecting the product.
        has_own_barcode: Boolean(barcode),
      };
      if (barcode) body.barcode = barcode;
      if (brand) body.brand_id = brand.id;
      if (category) body.category_id = category.id;
      const img = $("#p-image-url").value.trim();
      if (img) body.image_url = img;
      const created = await api("/products", { method: "POST", body: JSON.stringify(body) });
      if (!barcode) toast(`بارکد داخلی ساخته شد: ${created.barcode}`);
      toast("کالا ثبت شد");
      RENDER.products();
    } catch (e) { toast(e.message, "err"); }
  });

  const { items } = await api("/products?limit=200");
  const rows = items.map((p) => el("tr", {},
    el("td", {}, p.image_url
      ? el("img", { class: "thumb", src: p.image_url.startsWith("http") ? p.image_url
          : `/media/${p.image_url.replace(/^\/?media\//, "")}`, alt: "" })
      : el("span", { class: "thumb thumb-empty", text: "—" })),
    el("td", {}, el("span", {
      // §16 — an internal code is visibly distinct from a real GTIN so staff
      // know it means nothing to external catalogues.
      class: p.has_own_barcode === false ? "badge badge-gray" : "",
      text: p.barcode })),
    el("td", { text: p.name }),
    el("td", { text: p.min_stock_alert }),
    el("td", {}, el("span", { class: "badge " + (p.is_active ? "badge-green" : "badge-gray"), text: p.is_active ? "فعال" : "غیرفعال" })),
    el("td", {}, el("button", { class: "btn btn-ghost btn-sm",
      text: "بچ‌ها و قیمت‌ها", onclick: () => showProductDetail(p.id) }))));
  const tbl = $("#p-table");
  tbl.innerHTML = "";
  tbl.append(el("thead", {}, el("tr", {},
    el("th", { text: "تصویر" }), el("th", { text: "بارکد" }), el("th", { text: "نام" }),
    el("th", { text: "حداقل موجودی" }), el("th", { text: "وضعیت" }),
    el("th", { text: "" }))),
    el("tbody", {}, ...rows));
};

/* ---------- §5: product detail — one identity, all its batches ----------
 * The batch list is the product's price history. Depleted batches are shown
 * in a separate, dimmed section rather than hidden, because deleting them
 * would erase the record of what each purchase actually cost. */
window.showProductDetail = async function showProductDetail(productId) {
  try {
    const d = await api(`/products/${productId}/detail`);
    const p = d.product;

    const money = (n) => (n === null || n === undefined ? "—" : fmt(n));
    const batchTable = (list, dim) => {
      if (!list.length) return el("p", { class: "muted", text: "موردی نیست." });
      const rows = list.map((b) => el("tr", { style: dim ? "opacity:.62" : "" },
        el("td", { text: b.batch_number }),
        el("td", { text: b.current_qty + " / " + b.quantity_received }),
        el("td", { text: money(b.buy_price) }),
        el("td", { text: money(b.supplier_price) }),
        el("td", { text: money(b.sell_price) }),
        el("td", { text: money(b.consumer_price) }),
        el("td", { text: b.discount ? money(b.discount) : "—" }),
        el("td", { text: b.tax ? money(b.tax) : "—" }),
        el("td", { text: b.expiry_date || "—" }),
        el("td", { text: (b.received_at || "").slice(0, 10) })));
      const t = el("table", {});
      t.append(el("thead", {}, el("tr", {},
        el("th", { text: "شماره بچ" }), el("th", { text: "موجودی/دریافتی" }),
        el("th", { text: "خرید" }), el("th", { text: "تأمین‌کننده" }),
        el("th", { text: "فروش" }), el("th", { text: "مصرف‌کننده" }),
        el("th", { text: "تخفیف" }), el("th", { text: "مالیات" }),
        el("th", { text: "انقضا" }), el("th", { text: "تاریخ ورود" }))),
        el("tbody", {}, ...rows));
      return t;
    };

    const body = el("div", {});
    body.append(el("p", { class: "muted", text:
      `بارکد ${p.barcode}${p.has_own_barcode === false ? " (بارکد داخلی — کالای فله)" : ""}` +
      ` · موجودی کل: ${d.total_stock} · تعداد بچ: ${d.batch_count}` }));
    body.append(el("h4", { text: "بچ‌های فعال" }));
    body.append(batchTable(d.active_batches, false));
    body.append(el("h4", { text: "بچ‌های تمام‌شده (تاریخچهٔ قیمت — حذف نمی‌شوند)",
                           style: "margin-top:16px" }));
    body.append(batchTable(d.depleted_batches, true));

    // openModal takes an HTML string, so render a shell then mount the
    // built nodes into it (keeps names/notes escaped as text, not HTML).
    // Ten price/date columns need more room than the default modal width.
    openModal(`<div class="modal-wide"><h3 id="pd-title"></h3><div id="pd-body"></div>
      <div style="margin-top:14px;text-align:left">
        <button class="btn btn-ghost" onclick="closeModal()">بستن</button></div></div>`);
    $("#pd-title").textContent = p.name;
    $("#pd-body").append(body);
  } catch (e) { toast(e.message, "err"); }
};

/* ---------- batches (receiving) ---------- */
RENDER.batches = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="card" style="margin-bottom:14px">
    <h3>ورود کالا (ایجاد Batch جدید)</h3>
    <div class="form-row">
      <div><label>بارکد</label><input id="b-barcode" placeholder="اسکن بارکد" /></div>
      <div><label>تعداد</label><input id="b-qty" type="number" value="1" /></div>
      <div><label>قیمت خرید</label><input id="b-buy" type="number" /></div>
      <div><label>قیمت تأمین‌کننده</label><input id="b-supplier" type="number" /></div>
      <div><label>قیمت مصرف‌کننده</label><input id="b-consumer" type="number" /></div>
      <div><label>قیمت فروش</label><input id="b-sell" type="number" /></div>
      <div><label>تخفیف بچ</label><input id="b-discount" type="number" /></div>
      <div><label>مالیات بچ</label><input id="b-tax" type="number" /></div>
      <div><label>تاریخ انقضا</label><input id="b-expiry" type="date" /></div>
    </div>
    <button id="b-receive" class="btn btn-primary" style="margin-top:12px">ثبت ورود</button>
  </div>
  <div class="card"><h3>Batch های اخیر</h3><table id="b-table"></table></div>`;
  $("#b-receive").addEventListener("click", async () => {
    try {
      const body = { barcode: $("#b-barcode").value.trim(), quantity_received: Number($("#b-qty").value),
        buy_price: Number($("#b-buy").value), consumer_price: Number($("#b-consumer").value || 0) || null,
        sell_price: Number($("#b-sell").value || 0) || null, expiry_date: $("#b-expiry").value || null,
        supplier_price: Number($("#b-supplier").value || 0) || null,
        discount: Number($("#b-discount").value || 0) || null,
        tax: Number($("#b-tax").value || 0) || null };
      await api("/batches/receive", { method: "POST", body: JSON.stringify(body) });
      toast("ورود کالا ثبت شد");
      RENDER.batches();
    } catch (e) { toast(e.message, "err"); }
  });
  const batches = await api("/batches");
  const rows = batches.slice(0, 50).map((b) => el("tr", {},
    el("td", { text: b.batch_number }), el("td", { text: b.buy_price && fmt(b.buy_price) }),
    el("td", { text: fmt(b.sell_price) }), el("td", { text: b.current_qty }),
    el("td", { text: b.expiry_date || "—" }),
    el("td", {}, el("span", { class: "badge " + (b.status === "ACTIVE" ? "badge-green" : "badge-gray"), text: b.status }))));
  const tbl = $("#b-table");
  tbl.innerHTML = "";
  tbl.append(el("thead", {}, el("tr", {},
    el("th", { text: "شماره Batch" }), el("th", { text: "خرید" }), el("th", { text: "فروش" }),
    el("th", { text: "موجودی" }), el("th", { text: "انقضا" }), el("th", { text: "وضعیت" }))),
    el("tbody", {}, ...rows));
};

/* ---------- inventory + stocktaking ---------- */
RENDER.inventory = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="grid grid-2">
    <div class="card"><h3>موجودی کالاها</h3><table id="i-table"></table></div>
    <div class="card">
      <h3>انبارگردانی</h3>
      <div class="form-row"><div><label>نام</label><input id="st-name" value="انبارگردانی دوره‌ای" /></div></div>
      <button id="st-create" class="btn btn-primary" style="margin-top:12px">ایجاد انبارگردانی</button>
      <div id="st-list" style="margin-top:14px"></div>
    </div>
  </div>`;
  const stock = await api("/inventory/stock");
  const rows = stock.map((s) => el("tr", {},
    el("td", { text: s.name }), el("td", { text: s.barcode }), el("td", { text: s.total_stock }),
    el("td", {}, el("span", { class: "badge " + (s.total_stock <= s.min_stock_alert ? "badge-amber" : "badge-green"),
      text: s.total_stock <= s.min_stock_alert ? "کم‌موجود" : "عادی" }))));
  const t = $("#i-table");
  t.innerHTML = "";
  t.append(el("thead", {}, el("tr", {}, el("th", { text: "کالا" }), el("th", { text: "بارکد" }),
    el("th", { text: "موجودی کل" }), el("th", { text: "وضعیت" }))), el("tbody", {}, ...rows));

  $("#st-create").addEventListener("click", async () => {
    try {
      const st = await api("/inventory/stocktakes", { method: "POST", body: JSON.stringify({ name: $("#st-name").value }) });
      toast("انبارگردانی ایجاد شد");
      window._stDetail(st.id);
    } catch (e) { toast(e.message, "err"); }
  });
  const list = await api("/inventory/stocktakes");
  $("#st-list").innerHTML = list.map((s) =>
    `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)">
      <span>${s.name}</span><span class="badge badge-${s.status === "COMPLETED" ? "green" : "blue"}">${s.status}</span>
      <button class="btn btn-sm" onclick="window._stDetail(${s.id})">مشاهده</button></div>`).join("");
};

window._stDetail = async (id) => {
  const st = await api(`/inventory/stocktakes/${id}`);
  const prog = await api(`/inventory/stocktakes/${id}/progress`);
  const rows = st.items.map((i) => `
    <tr>
      <td>${i.product_id}</td><td>${i.batch_id || "—"}</td><td>${i.system_qty}</td>
      <td><input type="number" id="count-${i.id}" value="${i.physical_qty ?? i.system_qty}" /></td>
      <td>${i.difference ?? 0}</td>
      <td><button class="btn btn-sm" onclick="window._count(${i.id})">ثبت</button></td>
    </tr>`).join("");
  const pct = prog.total ? Math.round((prog.counted / prog.total) * 100) : 0;
  let actions = "";
  if (st.status === "PENDING_APPROVAL")
    actions = `<button class="btn btn-primary btn-block" style="margin-top:12px" onclick="window._approve(${id})">تأیید مدیر و اعمال تطبیق</button>`;
  else if (st.status !== "ADJUSTED" && st.status !== "CANCELLED")
    actions = `<button class="btn btn-primary btn-block" style="margin-top:12px" onclick="window._complete(${id})">پایان شمارش (ارسال برای تأیید)</button>`;
  openModal(`<h3>${esc(st.name)}</h3>
    <p class="muted">وضعیت: ${st.status} | پیشرفت: ${prog.counted}/${prog.total} (${pct}%) — با بستن پنجره، شمارش‌ها ذخیره می‌ماند و بعداً قابل ادامه است.</p>
    <table><thead><tr><th>کالا</th><th>Batch</th><th>سیستم</th><th>فیزیکی</th><th>اختلاف</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    ${actions}`);
};

window._approve = async (id) => {
  try {
    await api(`/inventory/stocktakes/${id}/approve`, { method: "POST" });
    closeModal(); toast("تأیید مدیر انجام و موجودی تطبیق شد");
    RENDER.inventory();
  } catch (e) { toast(e.message, "err"); }
};

window._count = async (itemId) => {
  try {
    await api("/inventory/stocktakes/count", { method: "POST", body: JSON.stringify({ item_id: itemId, physical_qty: Number(document.getElementById(`count-${itemId}`).value) }) });
    toast("شمارش ثبت شد");
  } catch (e) { toast(e.message, "err"); }
};

window._complete = async (id) => {
  try {
    await api(`/inventory/stocktakes/${id}/complete`, { method: "POST" });
    closeModal(); toast("شمارش پایان یافت؛ در انتظار تأیید مدیر");
    RENDER.inventory();
  } catch (e) { toast(e.message, "err"); }
};

/* ---------- invoices ---------- */
RENDER.invoices = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="card"><h3>فاکتورها</h3><table id="inv-table"></table></div>`;
  const { items } = await api("/invoices?limit=100");
  const rows = items.map((i) => el("tr", {},
    el("td", { text: i.invoice_number }), el("td", { text: money(i.total_amount) }),
    el("td", { text: i.payment_method }),
    el("td", {}, el("span", { class: "badge " + (i.status === "PAID" ? "badge-green" : i.status === "VOID" ? "badge-red" : "badge-gray"), text: i.status })),
    el("td", { text: i.created_at && i.created_at.slice(0, 16).replace("T", " ") }),
    el("td", {},
      el("button", { class: "btn btn-sm", text: "چاپ", onclick: async () => {
        const p = await api(`/invoices/${i.id}/print`, { method: "POST" });
        if (p.ok && typeof p.message === "string") openModal(`<pre class="receipt">${p.message}</pre>`);
        else toast(p.message, p.ok ? "ok" : "err");
      } }),
      el("button", { class: "btn btn-sm btn-danger", text: "ابطال", onclick: async () => {
        if (!confirm("فاکتور ابطال شود؟")) return;
        try { await api(`/invoices/${i.id}/void`, { method: "POST", body: JSON.stringify({}) }); RENDER.invoices(); } catch (e) { toast(e.message, "err"); }
      } }))));
  const t = $("#inv-table");
  t.innerHTML = "";
  t.append(el("thead", {}, el("tr", {}, el("th", { text: "شماره" }), el("th", { text: "مبلغ" }),
    el("th", { text: "پرداخت" }), el("th", { text: "وضعیت" }), el("th", { text: "تاریخ" }), el("th", {}))),
    el("tbody", {}, ...rows));
};

/* ---------- reports (§49) ---------- */
const REPORT_TABS = [
  ["daily", "فروش روزانه", "reports.view"],
  ["cashiers", "صندوق‌دارها", "reports.view"],
  ["profit", "سود به تفکیک Batch", "reports.view"],
  ["inventory", "ارزش موجودی", "reports.view"],
  ["purchase", "تاریخچه بهای خرید", "pricing.view_cost"],
  ["expiry", "انقضا", "reports.view"],
  ["adjustments", "اصلاحات و ضایعات", "reports.view"],
  ["movements", "گردش کالا", "reports.view"],
];

RENDER.reports = async () => {
  const v = $("#view");
  const today = new Date().toISOString().slice(0, 10);
  v.innerHTML = `
    <div class="card" style="margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <input type="date" id="rep-start" value="${today}" style="max-width:170px" />
      <span class="muted">تا</span>
      <input type="date" id="rep-end" value="${today}" style="max-width:170px" />
      <button id="rep-refresh" class="btn btn-primary" style="max-width:120px">بروزرسانی</button>
    </div>
    <div id="rep-tabs" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px"></div>
    <div id="rep-out"></div>`;
  $("#rep-refresh").addEventListener("click", () => runReport(state.repTab || "daily"));
  const tabs = $("#rep-tabs");
  REPORT_TABS.forEach(([key, label, perm]) => {
    if (!can(perm)) return;
    tabs.append(el("button", { class: "btn btn-sm" + ((state.repTab || "daily") === key ? " btn-primary" : ""),
      text: label, style: "max-width:220px", onclick: () => { state.repTab = key; RENDER.reports(); } }));
  });
  await runReport(state.repTab || "daily");
};

async function runReport(tab) {
  state.repTab = tab;
  const out = $("#rep-out");
  out.innerHTML = `<div class="muted">در حال بارگذاری…</div>`;
  const start = $("#rep-start") ? $("#rep-start").value : null;
  const end = $("#rep-end") ? $("#rep-end").value : null;
  try {
    if (tab === "daily") {
      const d = await api(`/reports/sales?start=${start}&end=${end}&group=daily`);
      const rows = (d.groups || []).map((g) => el("tr", {},
        el("td", { text: g.date }), el("td", { text: g.invoice_count }),
        el("td", { text: money(g.total) })));
      out.innerHTML = "";
      out.append(el("div", { class: "card" },
        el("h3", { text: `فروش روزانه (مجموع: ${money(d.total_sales)} در ${d.invoice_count} فاکتور)` }),
        el("table", {}, el("thead", {}, el("tr", {},
          el("th", { text: "تاریخ" }), el("th", { text: "فاکتور" }), el("th", { text: "فروش" }))),
          el("tbody", {}, ...rows))));
    } else if (tab === "cashiers") {
      const rows = await api(`/reports/cashiers?start=${start}&end=${end}`);
      out.innerHTML = "";
      out.append(el("div", { class: "card" }, el("h3", { text: "گزارش صندوق‌دارها" }),
        el("table", {}, el("thead", {}, el("tr", {},
          el("th", { text: "کاربر" }), el("th", { text: "فاکتور" }), el("th", { text: "فروش" }),
          el("th", { text: "تخفیف" }), el("th", { text: "سود" }))),
          el("tbody", {}, ...rows.map((r) => el("tr", {},
            el("td", { text: r.username }), el("td", { text: r.invoice_count }),
            el("td", { text: money(r.total_sales) }), el("td", { text: money(r.total_discount) }),
            el("td", { class: "ok", text: money(r.profit) })))))));
    } else if (tab === "profit") {
      const rows = await api(`/reports/profit?start=${start}&end=${end}`);
      out.innerHTML = "";
      out.append(el("div", { class: "card" }, el("h3", { text: "سود به تفکیک Batch" }),
        el("table", {}, el("thead", {}, el("tr", {},
          el("th", { text: "Batch" }), el("th", { text: "کالا" }), el("th", { text: "تعداد" }),
          el("th", { text: "درآمد" }), el("th", { text: "سود" }))),
          el("tbody", {}, ...rows.map((r) => el("tr", {},
            el("td", { text: r.batch_id || "—" }), el("td", { text: r.product_id }),
            el("td", { text: r.qty }), el("td", { text: money(r.revenue) }),
            el("td", { class: "ok", text: money(r.profit) })))))));
    } else if (tab === "inventory") {
      const rows = await api("/reports/inventory");
      out.innerHTML = "";
      out.append(el("div", { class: "card" },
        el("h3", { text: `ارزش موجودی به بهای تمام‌شده (مجموع: ${money(rows.reduce((a, r) => a + r.value_at_cost, 0))})` }),
        el("table", {}, el("thead", {}, el("tr", {},
          el("th", { text: "کالا" }), el("th", { text: "بارکد" }), el("th", { text: "تعداد" }),
          el("th", { text: "Batchها" }), el("th", { text: "ارزش بهای تمام‌شده" }))),
          el("tbody", {}, ...rows.slice(0, 100).map((r) => el("tr", {},
            el("td", { text: r.name }), el("td", { text: r.barcode }), el("td", { text: r.total_qty }),
            el("td", { text: r.batches }), el("td", { text: money(r.value_at_cost) })))))));
    } else if (tab === "purchase") {
      const rows = await api("/reports/purchase-cost?limit=100");
      out.innerHTML = "";
      out.append(el("div", { class: "card" }, el("h3", { text: "تاریخچه بهای خرید (نوسان قیمت بازار)" }),
        el("table", {}, el("thead", {}, el("tr", {},
          el("th", { text: "کالا" }), el("th", { text: "Batch" }), el("th", { text: "خرید" }),
          el("th", { text: "فروش" }), el("th", { text: "ورود" }), el("th", { text: "تاریخ" }))),
          el("tbody", {}, ...rows.map((r) => el("tr", {},
            el("td", { text: r.product_name }), el("td", { text: r.batch_number }),
            el("td", { text: money(r.buy_price) }), el("td", { text: money(r.sell_price) }),
            el("td", { text: r.qty_received }),
            el("td", { text: r.received_at.slice(0, 10) })))))));
    } else if (tab === "expiry") {
      const buckets = await api("/reports/expiry");
      const labels = { EXPIRED: ["منقضی", "badge-red"], EXPIRING_TODAY: ["امروز", "badge-red"],
        EXPIRING_3_DAYS: ["≤ ۳ روز", "badge-amber"], EXPIRING_7_DAYS: ["≤ ۷ روز", "badge-amber"],
        EXPIRING_30_DAYS: ["≤ ۳۰ روز", "badge-blue"], NORMAL: ["عادی", "badge-green"] };
      out.innerHTML = "";
      const cards = Object.entries(buckets).map(([k, items]) => {
        const [label, cls] = labels[k] || [k, "badge-gray"];
        return el("div", { class: "card" },
          el("h3", {}, el("span", { class: "badge " + cls, text: label }), ` ${items.length} مورد`),
          el("table", {}, el("tbody", {}, ...items.slice(0, 30).map((i) => el("tr", {},
            el("td", { text: i.product_name }), el("td", { text: i.qty + " عدد" }),
            el("td", { text: "انقضا: " + i.expiry }), el("td", { text: money(i.value) }))))));
      });
      out.append(...cards);
    } else if (tab === "adjustments") {
      const rows = await api("/reports/adjustments?limit=100");
      out.innerHTML = "";
      out.append(el("div", { class: "card" }, el("h3", { text: "اصلاحات / ضایعات / انبارگردانی" }),
        el("table", {}, el("thead", {}, el("tr", {},
          el("th", { text: "نوع" }), el("th", { text: "کالا" }), el("th", { text: "تعداد" }),
          el("th", { text: "توسط" }), el("th", { text: "علت" }), el("th", { text: "زمان" }))),
          el("tbody", {}, ...rows.map((r) => el("tr", {},
            el("td", {}, el("span", { class: "badge badge-blue", text: r.movement_type })),
            el("td", { text: r.product_name }), el("td", { text: r.quantity }),
            el("td", { text: r.by }), el("td", { text: r.note || "—" }),
            el("td", { text: r.created_at.slice(0, 16).replace("T", " ") })))))));
    } else if (tab === "movements") {
      const rows = await api("/reports/movements?limit=100");
      out.innerHTML = "";
      out.append(el("div", { class: "card" }, el("h3", { text: "گردش‌های اخیر موجودی" }),
        el("table", {}, el("thead", {}, el("tr", {},
          el("th", { text: "نوع" }), el("th", { text: "تعداد" }), el("th", { text: "Batch" }),
          el("th", { text: "زمان" }))),
          el("tbody", {}, ...rows.map((m) => el("tr", {},
            el("td", { text: m.movement_type }), el("td", { text: m.quantity }),
            el("td", { text: m.batch_id || "—" }),
            el("td", { text: m.created_at.slice(0, 16).replace("T", " ") })))))));
    }
  } catch (e) {
    out.innerHTML = `<div class="card"><p class="error">خطا: ${esc(e.message)}</p></div>`;
  }
};

/* ---------- hardware ---------- */
RENDER.hardware = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="grid grid-2">
    <div class="card"><h3>وضعیت سخت‌افزار</h3><div id="h-status"></div></div>
    <div class="card"><h3>ثبت دستگاه</h3>
      <div class="form-row">
        <div><label>نوع</label><select id="h-type"><option>PRINTER</option><option>BARCODE_SCANNER</option><option>CASH_DRAWER</option></select></div>
        <div><label>نام</label><input id="h-name" /></div>
        <div><label>اتصال (اختیاری)</label><input id="h-conn" placeholder="file:///receipt.txt یا پورت" /></div>
      </div>
      <button id="h-add" class="btn btn-primary" style="margin-top:12px">ثبت</button>
      <div style="margin-top:14px">
        <button id="h-test-print" class="btn">تست چاپ</button>
        <button id="h-test-drawer" class="btn">تست کشو</button>
      </div>
    </div>
  </div>`;
  const health = await api("/hardware/health");
  $("#h-status").innerHTML = `<p>پرینتر: <span class="badge badge-${health.printer === "CONNECTED" ? "green" : "red"}">${health.printer}</span></p>
    <p>اسکنر: <span class="badge badge-${health.scanner === "CONNECTED" ? "green" : "red"}">${health.scanner}</span></p>
    <p>کشوی پول: <span class="badge badge-${health.cash_drawer === "CONNECTED" ? "green" : "red"}">${health.cash_drawer}</span></p>`;
  $("#h-add").addEventListener("click", async () => {
    try { await api("/hardware", { method: "POST", body: JSON.stringify({ device_type: $("#h-type").value, name: $("#h-name").value, connection: $("#h-conn").value || null }) });
      toast("ثبت شد"); RENDER.hardware(); } catch (e) { toast(e.message, "err"); }
  });
  $("#h-test-print").addEventListener("click", async () => { const r = await api("/hardware/test/print", { method: "POST" }); toast(r.message, r.ok ? "ok" : "err"); });
  $("#h-test-drawer").addEventListener("click", async () => { const r = await api("/hardware/test/drawer", { method: "POST" }); toast(r.message, r.ok ? "ok" : "err"); });
};

/* ---------- users ---------- */
RENDER.users = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="grid grid-2">
    <div class="card"><h3>کاربران</h3><table id="u-table"></table></div>
    <div class="card"><h3>افزودن کاربر</h3>
      <label>نام کاربری</label><input id="u-username" />
      <label>رمز</label><input id="u-password" type="password" />
      <label>نام کامل</label><input id="u-fullname" />
      <label>نقش</label><select id="u-role"><option>Cashier</option><option>Manager</option><option>Inventory Operator</option><option>Viewer</option></select>
      <button id="u-add" class="btn btn-primary" style="margin-top:12px">ثبت</button>
    </div>
  </div>`;
  const users = await api("/users");
  const rows = users.map((u) => el("tr", {},
    el("td", { text: u.username }), el("td", { text: u.full_name }), el("td", { text: u.roles.join(", ") }),
    el("td", {}, el("span", { class: "badge " + (u.is_active ? "badge-green" : "badge-red"), text: u.is_active ? "فعال" : "غیرفعال" }))));
  const t = $("#u-table");
  t.append(el("thead", {}, el("tr", {}, el("th", { text: "کاربر" }), el("th", { text: "نام" }),
    el("th", { text: "نقش‌ها" }), el("th", { text: "وضعیت" }))), el("tbody", {}, ...rows));
  $("#u-add").addEventListener("click", async () => {
    try {
      await api("/users", { method: "POST", body: JSON.stringify({ username: $("#u-username").value.trim(),
        password: $("#u-password").value, full_name: $("#u-fullname").value, roles: [$("#u-role").value] }) });
      toast("کاربر ساخته شد"); RENDER.users();
    } catch (e) { toast(e.message, "err"); }
  });
};

/* ---------- settings ---------- */
/* §36 — the settings page used to be one undifferentiated key/value dump.
   It is now grouped into Persian categories with a tab bar, so an operator
   changing the receipt footer never has to scroll past SMS credentials. */
const SET_CATEGORIES = [
  { id: "store",  label: "فروشگاه",        icon: "box",  prefixes: ["store."], panel: "store" },
  { id: "pos",    label: "صندوق (POS)",    icon: "pos",  prefixes: ["pos."] },
  { id: "inv",    label: "انبار و انقضا",  icon: "warehouse", prefixes: ["stocktake.", "expiry."] },
  { id: "barcode",label: "بارکد و اسکنر",  icon: "inbox", prefixes: ["barcode."] },
  { id: "print",  label: "چاپگر",          icon: "printer", prefixes: ["printer."] },
  { id: "sms",    label: "پیامک",          icon: "user", prefixes: ["sms."] },
  { id: "general",label: "عمومی و زمان",   icon: "gear", prefixes: ["time.", "sync.", "backup."], panel: "general" },
  { id: "theme",  label: "ظاهر",           icon: "chart", prefixes: ["ui."], panel: "theme" },
  { id: "update", label: "به‌روزرسانی",    icon: "shield", prefixes: [], panel: "update" },
  { id: "about",  label: "درباره",         icon: "gear", prefixes: [], panel: "about" },
];

RENDER.settings = async () => {
  const v = $("#view");
  const allRows = await api("/settings");

  v.innerHTML = `<div class="set-tabs" id="set-tabs"></div><div id="set-body"></div>`;
  const tabsEl = $("#set-tabs");
  SET_CATEGORIES.forEach((cat, i) => {
    const b = el("button", { class: "set-tab" + (i === 0 ? " active" : ""), text: cat.label,
      onclick: () => {
        tabsEl.querySelectorAll(".set-tab").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        renderSettingsPanel(cat, allRows);
      } });
    tabsEl.append(b);
  });
  renderSettingsPanel(SET_CATEGORIES[0], allRows);
};

async function renderSettingsPanel(cat, allRows) {
  const body = $("#set-body");
  body.innerHTML = "";

  if (cat.panel === "store") {
    const card = el("div", { class: "card", id: "store-card" });
    card.innerHTML = `<h3>پروفایل فروشگاه</h3>
      <p class="muted">این اطلاعات روی فاکتور چاپی، نوار وضعیت و صفحهٔ ورود نمایش داده می‌شود.</p>
      <div class="form-grid" id="store-form"></div>
      <button class="btn btn-primary" id="store-save" style="margin-top:12px">ذخیره پروفایل</button>`;
    body.append(card);
    await renderStoreProfile();
    return;
  }
  if (cat.panel === "theme") {
    const card = el("div", { class: "card" });
    card.innerHTML = `<h3>ظاهر و پوسته</h3><div id="theme-box" class="muted">…</div>`;
    body.append(card);
    await renderThemeBox();
    return;
  }
  if (cat.panel === "general") {
    const grid = el("div", { class: "grid grid-2" });
    const timeCard = el("div", { class: "card" });
    timeCard.innerHTML = `<h3>تاریخ و ساعت</h3><div id="time-box" class="muted">…</div>
      <button class="btn btn-sm" id="time-verify" style="margin-top:10px">بررسی با سرور زمان (NTP)</button>
      <div id="time-result" style="margin-top:8px"></div>`;
    grid.append(timeCard);
    body.append(grid);
    await renderTimeBox();
  }
  if (cat.panel === "update") {
    const card = el("div", { class: "card" });
    card.innerHTML = `<h3>به‌روزرسانی سامانه</h3><div id="upd-box" class="muted">در حال بررسی…</div>
      <div id="upd-steps" style="margin-top:10px"></div>`;
    body.append(card);
    await renderUpdateBox();
    return;
  }
  if (cat.panel === "about") {
    const card = el("div", { class: "card" });
    card.innerHTML = `<h3>درباره سامانه</h3><div id="about-box" class="muted">…</div>`;
    body.append(card);
    await renderAbout();
    return;
  }

  // raw-key category: show the grouped key/value table for this prefix set.
  const rows = allRows.filter((r) => cat.prefixes.some((px) => r.key.startsWith(px)));
  const card = el("div", { class: "card" });
  card.append(el("h3", { text: cat.label }));
  if (!rows.length) { card.append(el("p", { class: "muted", text: "تنظیمی در این دسته نیست." })); body.append(card); return; }
  const trs = rows.map((r) => el("tr", { class: "kv-row" },
    el("td", { text: r.key }),
    el("td", {}, (() => {
      const input = el("input", { id: "set-" + r.key.replace(/\./g, "_") });
      if (r.is_secret) {
        input.setAttribute("type", "password");
        input.setAttribute("placeholder", r.has_value ? "(بدون تغییر)" : "خالی");
        input.setAttribute("autocomplete", "new-password");
      } else input.value = r.value;
      return input;
    })()),
    el("td", { text: r.description || "" }),
    el("td", {}, el("button", { class: "btn btn-sm btn-primary", text: "ذخیره", onclick: async () => {
      const input = document.getElementById("set-" + r.key.replace(/\./g, "_"));
      let value = input.value;
      if (r.is_secret && value === "") value = "__KEEP__";
      try { await api("/settings", { method: "PUT", body: JSON.stringify({ key: r.key, value, is_secret: !!r.is_secret }) });
        toast("ذخیره شد"); } catch (e) { toast(e.message, "err"); }
    } }))));
  const table = el("table", { class: "s-table set-panel" });
  table.append(el("thead", {}, el("tr", {}, el("th", { text: "کلید" }), el("th", { text: "مقدار" }),
    el("th", { text: "توضیح" }), el("th", {}))), el("tbody", {}, ...trs));
  card.append(table);
  body.append(card);
}

/* ---------- Settings sub-panels (§22, §23, §25, §27–29, §59) ---------- */
const STORE_FIELDS = [
  ["name", "نام فروشگاه"], ["legal_name", "نام حقوقی"],
  ["phone", "تلفن"], ["mobile", "همراه"],
  ["address", "آدرس", true], ["city", "شهر"],
  ["postal_code", "کد پستی"], ["tax_id", "شناسه مالیاتی"],
  ["receipt_note", "یادداشت پای فاکتور", true],
];

async function renderStoreProfile() {
  let p = {};
  try { p = await api("/settings/store-profile"); } catch (e) { /* empty form */ }
  $("#store-form").innerHTML = STORE_FIELDS.map(([key, label, full]) =>
    `<div class="${full ? "full" : ""}"><label>${label}</label>
       <input id="sp-${key}" value="${esc(p[key] || "")}" /></div>`).join("");
  $("#store-save").addEventListener("click", async () => {
    const body = {};
    STORE_FIELDS.forEach(([key]) => { body[key] = $("#sp-" + key).value.trim(); });
    try {
      state.store = await api("/settings/store-profile",
        { method: "PUT", body: JSON.stringify(body) });
      const sb = $("#sb-store"); if (sb) sb.textContent = state.store.name || "";
      const brand = document.querySelector(".brand span");
      if (brand && state.store.name) brand.textContent = state.store.name;
      toast("پروفایل فروشگاه ذخیره شد");
    } catch (e) { toast(e.message, "err"); }
  });
}

async function renderThemeBox() {
  const t = await api("/settings/theme").catch(() => null);
  if (!t) return;
  const box = $("#theme-box");
  box.innerHTML = `
    <label>حالت نمایش</label>
    <select id="th-mode">
      <option value="auto" ${t.theme === "auto" ? "selected" : ""}>خودکار (بر اساس ساعت)</option>
      <option value="light" ${t.theme === "light" ? "selected" : ""}>روشن</option>
      <option value="dark" ${t.theme === "dark" ? "selected" : ""}>تیره</option>
    </select>
    <div class="form-grid" style="margin-top:10px">
      <div><label>شروع پوستهٔ روشن</label><input id="th-light" value="${esc(t.light_at)}" /></div>
      <div><label>شروع پوستهٔ تیره</label><input id="th-dark" value="${esc(t.dark_at)}" /></div>
    </div>
    <p class="muted" style="margin-top:8px">اکنون: پوستهٔ
      <strong>${t.resolved === "dark" ? "تیره" : "روشن"}</strong> اعمال شده است.</p>
    <button class="btn btn-primary btn-sm" id="th-save">ذخیره</button>`;
  $("#th-save").addEventListener("click", async () => {
    try {
      await api("/settings/theme", { method: "PUT", body: JSON.stringify({
        theme: $("#th-mode").value,
        light_at: $("#th-light").value.trim(),
        dark_at: $("#th-dark").value.trim() })});
      await applyTheme();
      toast("پوسته ذخیره شد");
      renderThemeBox();
    } catch (e) { toast(e.message, "err"); }
  });
}

async function renderTimeBox() {
  const t = await api("/settings/time").catch(() => null);
  if (!t) return;
  $("#time-box").innerHTML = `
    <div><strong>${esc(t.weekday)} ${esc(t.jalali)}</strong></div>
    <div class="muted">میلادی: ${esc(t.gregorian)} · منطقهٔ زمانی: ${esc(t.timezone)}</div>
    <div class="muted">UTC ذخیره‌شده: ${esc(t.utc)}</div>`;
  $("#time-verify").addEventListener("click", async () => {
    $("#time-result").innerHTML = `<span class="muted">در حال تماس با سرور زمان…</span>`;
    try {
      const r = await api("/settings/time/verify", { method: "POST" });
      const cls = r.status === "PASS" ? "green" : r.status === "WARNING" ? "amber" : "blue";
      $("#time-result").innerHTML =
        `<span class="badge badge-${cls}">${esc(r.status)}</span> ${esc(r.message)}`;
    } catch (e) { $("#time-result").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  });
}

async function renderAbout() {
  const a = await api("/settings/about").catch(() => null);
  if (!a) return;
  $("#about-box").innerHTML = `
    <div class="about-head">
      <img class="about-logo" src="/icons/logo.svg" alt="لوگوی سامانه" />
      <div>
        <div style="font-size:15px;color:var(--text)"><strong>${esc(a.app_name)}</strong></div>
        <div class="muted">${esc(a.app_name_en)} — نسخهٔ ${esc(a.version)}</div>
      </div>
    </div>
    <p style="margin:10px 0">${esc(a.description)}</p>
    <div class="muted">طراحی و توسعه توسط <strong>${esc(a.developer)}</strong></div>`;
}

async function renderUpdateBox() {
  const box = $("#upd-box");
  try {
    const r = await api("/system/update/check");
    if (r.status === "UNAVAILABLE") {
      box.innerHTML = `<span class="badge badge-blue">بدون دسترسی</span>
        ${esc(r.message)} <span class="muted">(نسخهٔ فعلی ${esc(r.current_version)})</span>`;
      return;
    }
    if (!r.update_available) {
      box.innerHTML = `<span class="badge badge-green">به‌روز</span>
        نسخهٔ فعلی <strong>${esc(r.current_version)}</strong> آخرین نسخه است.`;
      return;
    }
    box.innerHTML = `<span class="badge badge-amber">نسخهٔ جدید</span>
      نسخهٔ <strong>${esc(r.latest.version)}</strong> منتشر شده است
      <span class="muted">(فعلی: ${esc(r.current_version)})</span>
      <p class="muted" style="margin:8px 0">${esc((r.latest.notes || "").slice(0, 400))}</p>
      ${r.installable ? `<button class="btn btn-primary" id="upd-go">دریافت و آماده‌سازی نصب</button>`
        : `<span class="muted">فایل نصب ویندوز برای این نسخه منتشر نشده است.</span>`}
      <p class="muted" style="margin-top:8px">پیش از هر به‌روزرسانی، به‌صورت خودکار از
        پایگاه‌داده پشتیبان گرفته می‌شود؛ در صورت شکست پشتیبان‌گیری، عملیات متوقف می‌شود.</p>`;
    const go = $("#upd-go");
    if (go) go.addEventListener("click", startUpdate);
  } catch (e) {
    box.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

function startUpdate() {
  openModal(`<h3>تأیید به‌روزرسانی</h3>
    <p class="muted">به دلیل حساسیت عملیات، رمز عبور خود را دوباره وارد کنید (§28).</p>
    <label>رمز عبور</label><input id="upd-pass" type="password" autocomplete="current-password" />
    <button class="btn btn-primary btn-block" id="upd-run" style="margin-top:12px">
      پشتیبان‌گیری و دریافت به‌روزرسانی</button>`);
  $("#upd-run").addEventListener("click", async () => {
    const pass = $("#upd-pass").value;
    $("#upd-run").disabled = true;
    $("#upd-run").textContent = "در حال اجرا…";
    try {
      const r = await api("/system/update/prepare", { method: "POST",
        body: JSON.stringify({ password: pass, download: true }) });
      closeModal();
      $("#upd-steps").innerHTML = r.steps.map((st) => `
        <div class="update-step"><span class="st ${esc(st.status)}">${esc(st.status)}</span>
          <span>${esc(st.name)}</span>
          <span class="muted" style="margin-inline-start:auto">${esc(st.detail || "")}</span>
        </div>`).join("") +
        `<p class="${r.status === "READY" ? "" : "err"}" style="margin-top:8px">${esc(r.message)}</p>`;
      toast(r.message, r.status === "READY" || r.status === "UP_TO_DATE" ? "ok" : "err");
    } catch (e) {
      toast(e.message, "err");
      $("#upd-run").disabled = false;
      $("#upd-run").textContent = "تلاش دوباره";
    }
  });
}

/* ---------- audit ---------- */
RENDER.audit = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="card"><h3>لاگ حسابرسی</h3><table id="a-table"></table></div>`;
  const logs = await api("/audit?limit=200");
  const rows = logs.map((a) => el("tr", {},
    el("td", {}, el("span", { class: "badge badge-blue", text: a.action })),
    el("td", { text: a.entity_type ? `${a.entity_type}#${a.entity_id ?? ""}` : "—" }),
    el("td", { text: a.user_id || "—" }),
    el("td", { text: a.reference || "—" }),
    el("td", { text: a.created_at.slice(0, 16).replace("T", " ") })));
  const t = $("#a-table");
  t.append(el("thead", {}, el("tr", {}, el("th", { text: "عملیات" }), el("th", { text: "موجودیت" }),
    el("th", { text: "کاربر" }), el("th", { text: "مرجع" }), el("th", { text: "زمان" }))),
    el("tbody", {}, ...rows));
};


/* ---------- Marketing: campaigns & coupons (§31–38) ---------- */
RENDER.marketing = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="grid grid-4" id="mk-stats"></div>
    <div class="grid grid-2" style="margin-top:14px">
      <div class="card">
        <div class="card-head"><h3>کوپن‌ها</h3>
          <button class="btn btn-primary btn-sm" id="mk-new-coupon">+ کوپن جدید</button></div>
        <div class="toolbar"><input id="mk-q" placeholder="جستجوی کد یا شماره موبایل…" />
          <select id="mk-status"><option value="">همه وضعیت‌ها</option>
            <option value="ACTIVE">فعال</option><option value="USED">مصرف‌شده</option>
            <option value="EXPIRED">منقضی</option><option value="BLOCKED">مسدود</option></select></div>
        <div class="table-wrap"><table id="mk-coupons"></table></div>
      </div>
      <div class="card">
        <div class="card-head"><h3>جشنواره‌ها (کمپین)</h3>
          <button class="btn btn-primary btn-sm" id="mk-new-camp">+ کمپین جدید</button></div>
        <div class="table-wrap"><table id="mk-camps"></table></div>
      </div>
    </div>`;
  $("#mk-new-coupon").addEventListener("click", couponModal);
  $("#mk-new-camp").addEventListener("click", campaignModal);
  $("#mk-q").addEventListener("input", debounce(loadCoupons, 300));
  $("#mk-status").addEventListener("change", loadCoupons);
  await Promise.all([loadMarketingStats(), loadCoupons(), loadCampaigns()]);
};

async function loadMarketingStats() {
  const s = await api("/marketing/stats");
  const by = s.by_status || {};
  $("#mk-stats").innerHTML = "";
  $("#mk-stats").append(
    statCard("کل کوپن‌ها", fmt(s.total_coupons), `${s.campaigns} کمپین`),
    statCard("فعال", fmt(by.ACTIVE || 0), ""),
    statCard("مصرف‌شده", fmt(by.USED || 0), ""),
    statCard("ارزش تخفیف داده‌شده", money(s.redeemed_value), ""),
  );
}

const COUPON_BADGE = { ACTIVE: "green", USED: "blue", EXPIRED: "amber", BLOCKED: "red" };

async function loadCoupons() {
  const params = new URLSearchParams();
  if ($("#mk-q").value.trim()) params.set("q", $("#mk-q").value.trim());
  if ($("#mk-status").value) params.set("status", $("#mk-status").value);
  const rows = await api("/marketing/coupons?" + params.toString());
  const body = rows.map((c) => `<tr>
      <td><code>${esc(c.code)}</code>${c.customer_phone ? `<div class="muted">${esc(c.customer_phone)}</div>` : ""}</td>
      <td>${c.discount_type === "PERCENT" ? fmt(c.discount_value) + "٪" : money(c.discount_value)}
        ${c.max_discount ? `<div class="muted">سقف ${money(c.max_discount)}</div>` : ""}</td>
      <td>${c.min_purchase ? money(c.min_purchase) : "—"}</td>
      <td>${c.used_count}/${c.usage_limit}</td>
      <td><span class="badge badge-${COUPON_BADGE[c.status] || "blue"}">${esc(c.status)}</span></td>
      <td>${c.valid_until ? esc(c.valid_until.slice(0, 10)) : "—"}</td>
      <td>${c.status === "ACTIVE" ? `<button class="btn btn-sm btn-danger" onclick="window._blockCoupon(${c.id})">مسدود</button>` : ""}</td>
    </tr>`).join("");
  $("#mk-coupons").innerHTML = `<thead><tr><th>کد</th><th>تخفیف</th><th>حداقل خرید</th>
      <th>مصرف</th><th>وضعیت</th><th>اعتبار تا</th><th></th></tr></thead>
    <tbody>${body || `<tr><td colspan="7" class="muted empty">کوپنی ثبت نشده است</td></tr>`}</tbody>`;
}

window._blockCoupon = async (id) => {
  try { await api(`/marketing/coupons/${id}/block`, { method: "POST" });
    toast("کوپن مسدود شد"); loadCoupons(); loadMarketingStats();
  } catch (e) { toast(e.message, "err"); }
};

async function loadCampaigns() {
  const rows = await api("/marketing/campaigns");
  const body = rows.map((c) => `<tr>
      <td>${esc(c.name)}${c.auto_issue_threshold ? `<div class="muted">صدور خودکار بالای ${money(c.auto_issue_threshold)}</div>` : ""}</td>
      <td>${c.discount_type === "PERCENT" ? fmt(c.discount_value) + "٪" : money(c.discount_value)}</td>
      <td>${c.min_purchase ? money(c.min_purchase) : "—"}</td>
      <td><span class="badge badge-${c.status === "ACTIVE" ? "green" : "amber"}">${esc(c.status)}</span></td>
    </tr>`).join("");
  $("#mk-camps").innerHTML = `<thead><tr><th>نام</th><th>تخفیف</th><th>حداقل خرید</th><th>وضعیت</th></tr></thead>
    <tbody>${body || `<tr><td colspan="4" class="muted empty">کمپینی ثبت نشده است</td></tr>`}</tbody>`;
}

function couponModal() {
  openModal(`<h3>کوپن جدید</h3>
    <div class="form-row">
      <div><label>کد (خالی = تولید خودکار)</label><input id="cp-code" placeholder="AUTO" /></div>
      <div><label>نوع تخفیف</label><select id="cp-type">
        <option value="PERCENT">درصدی</option><option value="FIXED">مبلغ ثابت</option></select></div>
    </div>
    <div class="form-row">
      <div><label>مقدار تخفیف</label><input id="cp-value" type="number" value="10" /></div>
      <div><label>سقف تخفیف (اختیاری)</label><input id="cp-max" type="number" placeholder="بدون سقف" /></div>
    </div>
    <div class="form-row">
      <div><label>حداقل مبلغ خرید</label><input id="cp-min" type="number" value="0" /></div>
      <div><label>تعداد دفعات مجاز</label><input id="cp-limit" type="number" value="1" min="1" /></div>
    </div>
    <div class="form-row">
      <div><label>موبایل مشتری (اختصاصی)</label><input id="cp-phone" placeholder="اختیاری — 0912…" /></div>
      <div><label>اعتبار تا</label><input id="cp-until" type="date" /></div>
    </div>
    <button id="cp-save" class="btn btn-primary btn-block" style="margin-top:14px">ثبت کوپن</button>`);
  $("#cp-save").addEventListener("click", async () => {
    const until = $("#cp-until").value;
    try {
      const c = await api("/marketing/coupons", { method: "POST", body: JSON.stringify({
        code: $("#cp-code").value.trim() || null,
        discount_type: $("#cp-type").value,
        discount_value: Number($("#cp-value").value || 0),
        max_discount: $("#cp-max").value ? Number($("#cp-max").value) : null,
        min_purchase: Number($("#cp-min").value || 0),
        usage_limit: Number($("#cp-limit").value || 1),
        customer_phone: $("#cp-phone").value.trim() || null,
        valid_until: until ? until + "T23:59:59" : null,
      }) });
      closeModal(); toast("کوپن ساخته شد: " + c.code);
      loadCoupons(); loadMarketingStats();
    } catch (e) { toast(e.message, "err"); }
  });
}

function campaignModal() {
  openModal(`<h3>کمپین / جشنواره جدید</h3>
    <label>نام</label><input id="cm-name" placeholder="جشنواره پاییز" />
    <div class="form-row">
      <div><label>نوع تخفیف</label><select id="cm-type">
        <option value="PERCENT">درصدی</option><option value="FIXED">مبلغ ثابت</option></select></div>
      <div><label>مقدار</label><input id="cm-value" type="number" value="10" /></div>
    </div>
    <div class="form-row">
      <div><label>حداقل خرید بعدی</label><input id="cm-min" type="number" value="400000" /></div>
      <div><label>سقف تخفیف</label><input id="cm-max" type="number" value="1000000" /></div>
    </div>
    <div class="form-row">
      <div><label>صدور خودکار برای خرید بالای</label><input id="cm-thr" type="number" value="1000000" /></div>
      <div><label>اعتبار کوپن (روز)</label><input id="cm-days" type="number" value="30" /></div>
    </div>
    <p class="muted">وقتی مبلغ فاکتور از آستانه عبور کند، یک کوپن خرید بعدی صادر و همراه پیامک فاکتور ارسال می‌شود.</p>
    <button id="cm-save" class="btn btn-primary btn-block" style="margin-top:14px">ثبت کمپین</button>`);
  $("#cm-save").addEventListener("click", async () => {
    try {
      await api("/marketing/campaigns", { method: "POST", body: JSON.stringify({
        name: $("#cm-name").value.trim() || "کمپین",
        discount_type: $("#cm-type").value,
        discount_value: Number($("#cm-value").value || 0),
        min_purchase: Number($("#cm-min").value || 0),
        max_discount: Number($("#cm-max").value || 0) || null,
        auto_issue_threshold: Number($("#cm-thr").value || 0) || null,
        auto_issue_validity_days: Number($("#cm-days").value || 30),
      }) });
      closeModal(); toast("کمپین ثبت شد"); loadCampaigns(); loadMarketingStats();
    } catch (e) { toast(e.message, "err"); }
  });
}

/* ---------- Customers phone book (§30) ---------- */
RENDER.customers = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="card">
      <div class="card-head"><h3>دفترچه مشتریان</h3>
        <button class="btn btn-primary btn-sm" id="cu-new">+ مشتری جدید</button></div>
      <div class="toolbar"><input id="cu-q" placeholder="جستجوی نام یا شماره تماس…" /></div>
      <div class="table-wrap"><table id="cu-table"></table></div>
    </div>`;
  $("#cu-q").addEventListener("input", debounce(loadCustomers, 300));
  $("#cu-new").addEventListener("click", () => {
    openModal(`<h3>مشتری جدید</h3>
      <div class="form-grid">
        <div><label>نام</label><input id="nc-name" /></div>
        <div><label>نام خانوادگی</label><input id="nc-last" /></div>
        <div><label>شماره تماس</label><input id="nc-phone" placeholder="0912…" /></div>
        <div><label>سقف اعتبار (۰ = بدون سقف)</label><input id="nc-limit" inputmode="numeric" value="0" /></div>
        <div class="full"><label>آدرس</label><input id="nc-address" /></div>
        <div class="full"><label>یادداشت</label><input id="nc-notes" /></div>
      </div>
      <p class="muted">ثبت فقط با شماره تماس هم مجاز است؛ نام را می‌توان بعداً تکمیل کرد.</p>
      <button id="nc-save" class="btn btn-primary btn-block" style="margin-top:14px">ثبت</button>`);
    $("#nc-save").addEventListener("click", async () => {
      try {
        await api("/customers", { method: "POST", body: JSON.stringify({
          name: $("#nc-name").value.trim() || $("#nc-phone").value.trim(),
          last_name: $("#nc-last").value.trim() || null,
          phone: $("#nc-phone").value.trim() || null,
          address: $("#nc-address").value.trim() || null,
          notes: $("#nc-notes").value.trim() || null,
          credit_limit: Number($("#nc-limit").value || 0) }) });
        closeModal(); toast("مشتری ثبت شد"); loadCustomers();
      } catch (e) { toast(e.message, "err"); }
    });
  });
  await loadCustomers();
};

async function loadCustomers() {
  const q = $("#cu-q") ? $("#cu-q").value.trim() : "";
  const params = new URLSearchParams({ with_debt: "true" });
  if (q) params.set("q", q);
  const rows = await api("/customers?" + params.toString());
  const body = rows.map((c) => {
    const bal = Number(c.balance || 0);
    return `<tr>
      <td>${esc(c.name)} ${esc(c.last_name || "")}</td>
      <td>${esc(c.phone || "—")}</td>
      <td class="${bal > 0 ? "ledger-amount debit" : "muted"}">
        ${bal > 0 ? money(bal) : "تسویه"}</td>
      <td>
        <button class="btn btn-sm" onclick="showCustomerLedger(${c.id})">حساب دفتری</button>
        <button class="btn btn-ghost btn-sm" onclick="window._custHistory(${c.id}, '${esc(c.name)}')">سوابق خرید</button>
      </td>
    </tr>`;
  }).join("");
  $("#cu-table").innerHTML = `<thead><tr><th>نام</th><th>تلفن</th><th>مانده حساب</th><th></th></tr></thead>
    <tbody>${body || `<tr><td colspan="4" class="muted empty">مشتری‌ای ثبت نشده است</td></tr>`}</tbody>`;
}

window._custHistory = async (id, name) => {
  const invoices = await api("/invoices?customer_id=" + id).catch(() => ({ items: [] }));
  const list = (invoices.items || invoices || []).filter((i) => i.customer_id === id);
  const coupons = await api("/marketing/coupons?customer_id=" + id).catch(() => []);
  openModal(`<h3>سوابق ${esc(name)}</h3>
    <h4>فاکتورها</h4>
    <table><thead><tr><th>شماره</th><th>مبلغ</th><th>وضعیت</th></tr></thead><tbody>
      ${list.map((i) => `<tr><td>${esc(i.invoice_number)}</td><td>${money(i.total_amount)}</td><td>${esc(i.status)}</td></tr>`).join("")
        || `<tr><td colspan="3" class="muted">فاکتوری ثبت نشده</td></tr>`}
    </tbody></table>
    <h4 style="margin-top:14px">کوپن‌ها</h4>
    <table><thead><tr><th>کد</th><th>وضعیت</th></tr></thead><tbody>
      ${coupons.map((c) => `<tr><td><code>${esc(c.code)}</code></td><td>${esc(c.status)}</td></tr>`).join("")
        || `<tr><td colspan="2" class="muted">کوپنی ندارد</td></tr>`}
    </tbody></table>`);
};

/* ---------- Connection diagnostics (§42–44) ---------- */
const DIAG_BADGE = { PASS: "green", FAIL: "red", WARN: "amber", SKIPPED: "blue" };

RENDER.diagnostics = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="card">
      <div class="card-head"><h3>تست اتصالات سیستم</h3>
        <div>
          <label class="inline"><input type="checkbox" id="dg-ext" checked /> شامل منابع خارجی</label>
          <button class="btn btn-primary" id="dg-run">▶ اجرای تست کامل</button>
        </div>
      </div>
      <p class="muted">هر تست یک عملیات واقعی انجام می‌دهد (نوشتن/خواندن دیتابیس، دسترسی شبکه،
        فراخوانی منبع، نوشتن روی پرینتر). سرویسی که سخت‌افزار یا تنظیمات آن موجود نیست،
        «رد شده» گزارش می‌شود و هرگز سبز نمایش داده نمی‌شود.</p>
      <div id="dg-summary"></div>
      <div id="dg-results"></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>صف همگام‌سازی آفلاین</h3><div id="dg-sync"></div></div>
    <div class="card" style="margin-top:14px"><h3>تاریخچه تست‌ها</h3><div id="dg-history"></div></div>`;
  $("#dg-run").addEventListener("click", runDiagnostics);
  await Promise.all([loadSyncPanel(), loadDiagHistory()]);
};

async function runDiagnostics() {
  const btn = $("#dg-run");
  btn.disabled = true; btn.textContent = "در حال اجرا…";
  $("#dg-results").innerHTML = `<p class="muted">در حال تست اتصال‌ها…</p>`;
  try {
    const ext = $("#dg-ext").checked;
    const r = await api(`/diagnostics/run?include_external=${ext}`, { method: "POST" });
    renderDiagnostics(r);
    await loadDiagHistory();
  } catch (e) { toast(e.message, "err"); $("#dg-results").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  btn.disabled = false; btn.textContent = "▶ اجرای تست کامل";
}

function renderDiagnostics(r) {
  $("#dg-summary").innerHTML = `<div class="diag-summary">
      <span class="badge badge-green">موفق ${r.passed}</span>
      <span class="badge badge-red">ناموفق ${r.failed}</span>
      <span class="badge badge-blue">رد/هشدار ${r.skipped}</span>
      <span class="muted">مجموع ${r.total} تست</span></div>`;
  $("#dg-results").innerHTML = r.checks.map((c) => `
    <div class="diag-row">
      <div class="diag-head">
        <span class="badge badge-${DIAG_BADGE[c.status] || "blue"}">${esc(c.status)}</span>
        <strong>${esc(c.name)}</strong>
        <span class="muted">${c.duration_ms} ms</span>
      </div>
      <div class="diag-detail">${esc(c.detail || "")}</div>
      ${(c.steps || []).length ? `<div class="diag-steps">${c.steps.map((s) =>
        `<span class="step ${s.ok ? "ok" : "bad"}">${s.ok ? "✓" : "✗"} ${esc(s.step)}${s.note ? " — " + esc(s.note) : ""}</span>`).join("")}</div>` : ""}
    </div>`).join("");
}

async function loadSyncPanel() {
  const s = await api("/diagnostics/sync/stats");
  const jobs = await api("/diagnostics/sync/jobs?limit=20");
  $("#dg-sync").innerHTML = `
    <div class="diag-summary">
      <span class="badge badge-amber">در انتظار ${s.pending}</span>
      <span class="badge badge-red">ناموفق ${s.failed}</span>
      <button class="btn btn-sm" onclick="window._runSync()">اجرای صف</button>
    </div>
    <div class="table-wrap"><table><thead><tr><th>نوع</th><th>وضعیت</th><th>تلاش</th><th>خطا</th><th></th></tr></thead>
      <tbody>${jobs.map((j) => `<tr><td>${esc(j.job_type)}</td>
        <td><span class="badge badge-${j.status === "COMPLETED" ? "green" : j.status === "FAILED" ? "red" : "amber"}">${esc(j.status)}</span></td>
        <td>${j.attempts}/${j.max_attempts}</td><td class="muted">${esc((j.last_error || "").slice(0, 60))}</td>
        <td>${j.status === "FAILED" ? `<button class="btn btn-sm" onclick="window._retryJob(${j.id})">تلاش مجدد</button>` : ""}</td></tr>`).join("")
        || `<tr><td colspan="5" class="muted empty">صف خالی است</td></tr>`}</tbody></table></div>`;
}

window._runSync = async () => {
  try { const r = await api("/diagnostics/sync/run", { method: "POST" });
    toast(`پردازش ${r.processed} کار — موفق ${r.succeeded}`); loadSyncPanel();
  } catch (e) { toast(e.message, "err"); }
};
window._retryJob = async (id) => {
  try { await api(`/diagnostics/sync/jobs/${id}/retry`, { method: "POST" });
    toast("در صف تلاش مجدد قرار گرفت"); loadSyncPanel();
  } catch (e) { toast(e.message, "err"); }
};

async function loadDiagHistory() {
  const h = await api("/diagnostics/history");
  $("#dg-history").innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>زمان</th><th>موفق</th><th>ناموفق</th><th>رد شده</th><th></th></tr></thead>
    <tbody>${h.map((r) => `<tr><td>${esc(r.started_at.slice(0, 16).replace("T", " "))}</td>
      <td class="ok">${r.passed}</td><td class="error">${r.failed}</td><td>${r.skipped}</td>
      <td><button class="btn btn-sm" onclick="window._showRun(${r.id})">مشاهده</button></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted empty">هنوز تستی اجرا نشده است</td></tr>`}</tbody></table></div>`;
}

window._showRun = async (id) => {
  const r = await api(`/diagnostics/runs/${id}`);
  renderDiagnostics({ ...r, checks: r.checks });
  window.scrollTo(0, 0);
};

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ---------- runtime config (currency + units) ---------- */
async function loadRuntimeConfig() {
  try { state.currency = await api("/settings/currency"); } catch (e) { /* defaults */ }
  try { state.units = await api("/units"); } catch (e) { state.units = []; }
  try {
    state.store = await api("/settings/store-profile");
    const el = $("#sb-store");
    if (el && state.store.name) el.textContent = state.store.name;
    if (state.store.name) {
      const brand = document.querySelector(".brand span");
      if (brand) brand.textContent = state.store.name;
    }
  } catch (e) { state.store = {}; }
}
const unitById = (id) => state.units.find((u) => u.id === id) || null;


/* ===========================================================================
 * Theme engine (§23) and status bar (§21).
 * The resolved theme comes from the server so the light/dark schedule lives in
 * one place (settings) instead of being reimplemented per client.
 * ========================================================================= */
async function applyTheme(pref) {
  try {
    if (pref) await api("/settings/theme", { method: "PUT", body: JSON.stringify({ theme: pref }) });
    const t = await api("/settings/theme");
    state.theme = t;
    document.documentElement.setAttribute("data-theme", t.resolved);
    const btn = $("#sb-theme");
    if (btn) {
      btn.textContent = t.theme === "auto" ? "◐" : (t.resolved === "dark" ? "☾" : "☀");
      btn.title = t.theme === "auto"
        ? `خودکار (روشن ${t.light_at} تا ${t.dark_at}) — اکنون ${t.resolved === "dark" ? "تیره" : "روشن"}`
        : `پوستهٔ ${t.resolved === "dark" ? "تیره" : "روشن"} (دستی)`;
    }
  } catch (e) { /* keep whatever theme is already applied */ }
}

/* auto mode must flip at the scheduled time without a reload */
function scheduleThemeRefresh() {
  clearInterval(window._themeTimer);
  window._themeTimer = setInterval(() => {
    if (state.theme && state.theme.theme === "auto") applyTheme();
  }, 60000);
}

window.cycleTheme = async () => {
  const order = ["auto", "light", "dark"];
  const next = order[(order.indexOf((state.theme || {}).theme || "auto") + 1) % 3];
  await applyTheme(next);
  toast(`پوسته: ${next === "auto" ? "خودکار" : next === "light" ? "روشن" : "تیره"}`);
};

async function refreshStatusBar() {
  const online = navigator.onLine;
  const dot = $("#sb-net-dot"), net = $("#sb-net");
  if (dot) dot.className = "sb-dot" + (online ? " on" : "");
  if (net) net.textContent = online ? "متصل" : "آفلاین";

  const user = $("#sb-user");
  if (user && state.user) user.textContent = state.user.full_name || state.user.username;

  try {
    const t = await api("/settings/time");
    state.serverTime = t;
    const d = $("#sb-date"), c = $("#sb-clock");
    if (d) d.textContent = `${t.weekday} ${t.jalali_date}`;
    // Use the store-local time the server already computed. Re-parsing it with
    // the browser's timezone showed a UTC client the wrong wall-clock time.
    if (c) {
      const hhmm = String(t.local).slice(11, 16);
      c.textContent = hhmm.replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
    }
    const db = $("#sb-db");
    if (db) { db.textContent = "پایگاه‌داده"; db.className = "sb-item ok"; }
  } catch (e) {
    const db = $("#sb-db");
    if (db) { db.textContent = "بدون اتصال به سرور"; db.className = "sb-item bad"; }
  }
}

function startStatusBar() {
  const btn = $("#sb-theme");
  if (btn && !btn._wired) { btn._wired = true; btn.addEventListener("click", cycleTheme); }
  window.addEventListener("online", refreshStatusBar);
  window.addEventListener("offline", refreshStatusBar);
  refreshStatusBar();
  clearInterval(window._sbTimer);
  window._sbTimer = setInterval(refreshStatusBar, 30000);
  scheduleThemeRefresh();
}

/* ===========================================================================
 * Customer ledger (§30–35)
 * ========================================================================= */
window.showCustomerLedger = async (id) => {
  let data;
  try { data = await api(`/customers/${id}/ledger`); }
  catch (e) { toast(e.message, "err"); return; }

  const c = data.customer;
  const bal = Number(data.balance || 0);
  const rows = data.entries.map((e) => {
    const amt = Number(e.amount);
    const label = {
      CREDIT_SALE: "فروش نسیه", PAYMENT: "پرداخت مشتری",
      RETURN_REFUND: "برگشت کالا", ADJUSTMENT_DEBIT: "اصلاح (بدهکار)",
      ADJUSTMENT_CREDIT: "اصلاح (بستانکار)", OPENING_BALANCE: "مانده ابتدای دوره",
    }[e.entry_type] || e.entry_type;
    return `<tr>
      <td>${esc(faDateTime(e.created_at))}</td>
      <td>${esc(label)}</td>
      <td class="ledger-amount ${amt > 0 ? "debit" : "credit"}">
        ${amt > 0 ? "+" : "−"}${money(Math.abs(amt))}</td>
      <td>${money(e.balance_after)}</td>
      <td class="muted">${esc(e.note || "")}${e.method ? ` (${esc(e.method)})` : ""}</td>
    </tr>`;
  }).join("");

  openModal(`<h3>حساب دفتری — ${esc(c.name)} ${esc(c.last_name || "")}</h3>
    <div class="balance-hero ${bal > 0 ? "debt" : "clear"}">
      <span class="muted">مانده حساب</span>
      <b>${money(bal)}</b>
      <span class="muted">${bal > 0 ? "بدهکار" : "تسویه"}</span>
      <span class="sb-grow"></span>
      <span class="muted">جمع خرید ${money(data.total_charged)} · جمع پرداخت ${money(data.total_paid)}</span>
    </div>
    ${bal > 0 ? `<div class="toolbar">
      <input id="lg-amt" inputmode="numeric" placeholder="مبلغ دریافتی…" />
      <select id="lg-method"><option value="CASH">نقدی</option><option value="CARD">کارت</option>
        <option value="TRANSFER">انتقال</option></select>
      <button class="btn btn-primary btn-sm" onclick="doSettle(${id}, false)">ثبت پرداخت</button>
      <button class="btn btn-sm" onclick="doSettle(${id}, true)">تسویه کامل (${money(bal)})</button>
      <button class="btn btn-ghost btn-sm" onclick="smsDebtReminder(${id})">پیامک یادآوری</button>
    </div>` : ""}
    <div class="table-wrap"><table>
      <thead><tr><th>تاریخ</th><th>نوع</th><th>مبلغ</th><th>مانده</th><th>توضیح</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="5" class="empty">تراکنشی ثبت نشده است</td></tr>`}</tbody>
    </table></div>
    <p class="muted" style="margin-top:8px">
      این دفتر فقط-افزودنی است: اصلاح‌ها به‌صورت سند معکوس ثبت می‌شوند و هیچ
      سطری حذف یا بازنویسی نمی‌شود.</p>
  `);
};

window.doSettle = async (id, full) => {
  const body = { method: ($("#lg-method") || {}).value || "CASH" };
  if (!full) {
    const v = parseFloat(($("#lg-amt") || {}).value);
    if (!isFinite(v) || v <= 0) { toast("مبلغ نامعتبر", "err"); return; }
    body.amount = v;
  }
  try {
    const r = await api(`/customers/${id}/settle`, { method: "POST", body: JSON.stringify(body) });
    toast(r.settled_in_full ? "حساب تسویه شد" : `ثبت شد — مانده ${money(r.balance)}`);
    closeModal();
    showCustomerLedger(id);
  } catch (e) { toast(e.message, "err"); }
};

window.smsDebtReminder = async (id) => {
  /* The server renders the configured template and enforces "no debt, no
     nag" — the client must not compose the message itself. */
  try {
    const r = await api(`/customers/${id}/debt-reminder`, { method: "POST",
      body: JSON.stringify({}) });
    toast(`پیامک یادآوری در صف ارسال قرار گرفت: ${r.phone}`);
  } catch (e) { toast(e.message, "err"); }
};

/* ---------- boot ---------- */
async function boot() {
  if (!state.token) { showLogin(); return; }
  try {
    state.user = await api("/auth/me");
    await loadRuntimeConfig();
    showApp();
    buildNav();
    await applyTheme();
    startStatusBar();
    go("dashboard");
  } catch (e) {
    localStorage.removeItem("token"); state.token = "";
    showLogin();
  }
}
boot();
