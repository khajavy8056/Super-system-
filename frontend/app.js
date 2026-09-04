/* Supermarket System — Web Panel (vanilla JS SPA) */
const $ = (sel) => document.querySelector(sel);
const API = "/api";

const state = {
  token: localStorage.getItem("token") || "",
  user: null,
  view: "dashboard",
  kiosk: localStorage.getItem("kiosk") === "1",
  kioskShortcut: "Ctrl+Shift+L",
};

/* ---------- helpers ---------- */
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const money = (n) => fmt(n) + " ریال";

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
    showApp();
    buildNav();
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
const NAV = [
  ["dashboard", "📊 داشبورد", "reports.view"],
  ["pos", "🧾 صندوق (POS)", "pos.sell"],
  ["products", "📦 کالاها", "products.view"],
  ["batches", "📥 ورود کالا", "batches.manage"],
  ["inventory", "🏬 انبار و انبارگردانی", "inventory.view"],
  ["invoices", "🧮 فاکتورها", "reports.view"],
  ["reports", "📈 گزارش‌ها", "reports.view"],
  ["hardware", "🖨️ سخت‌افزار", "settings.manage"],
  ["users", "👥 کاربران", "users.manage"],
  ["settings", "⚙️ تنظیمات", "settings.manage"],
  ["audit", "🕵️ لاگ‌ها", "audit.view"],
];

function can(perm) {
  if (!state.user) return false;
  return (state.user.permissions || []).includes(perm);
}

function buildNav() {
  const nav = $("#nav");
  nav.innerHTML = "";
  NAV.forEach(([key, label, perm]) => {
    if (!can(perm)) return;
    nav.append(el("button", { class: "nav-item" + (state.view === key ? " active" : ""),
      onclick: () => go(key), text: label }));
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
const posState = { cart: [], customer: null };

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
          <input value="${it.quantity}" onchange="posQty(${idx},0,this.value)" />
          <button class="btn btn-sm" onclick="posQty(${idx},-1)">−</button></td>
        <td>${money(it.unit_sell_price)}</td>
        <td>${it.discount ? "<div class=\"muted\" style=\"font-size:11px\">−" + money(it.discount) + "</div>" : ""}${money(posGross(it) - (it.discount || 0))}</td>
        <td><button class="btn btn-sm btn-danger" onclick="posRemove(${idx})">✕</button></td>
      </tr>`).join("");
    tbl.innerHTML = `<thead><tr><th>کالا</th><th>تعداد</th><th>فی</th><th>جمع</th><th></th></tr></thead><tbody>${rows}</tbody>`;
  }
  // totals
  const gross = posState.cart.reduce((a, it) => a + posGross(it), 0);
  const disc = posState.cart.reduce((a, it) => a + (it.discount || 0), 0);
  const count = posState.cart.reduce((a, it) => a + it.quantity, 0);
  const showCost = can("pricing.view_cost");
  const profit = posState.cart.reduce((a, it) => a + (posGross(it) - (it.discount || 0) - (it.unit_buy_price || 0) * it.quantity), 0);
  $("#pos-totals").innerHTML = `
    <div class="row"><span class="muted">تعداد کالا</span><strong>${count}</strong></div>
    <div class="row"><span class="muted">جمع</span><span>${money(gross)}</span></div>
    ${disc ? `<div class="row"><span class="muted">تخفیف</span><span class="err">−${money(disc)}</span></div>` : ""}
    <div class="row grand"><span>قابل پرداخت</span><span>${money(gross - disc)}</span></div>
    ${showCost ? `<div class="row"><span class="muted">سود تخمینی</span><span class="ok">${money(profit)}</span></div>` : ""}`;
  $("#pos-customer").innerHTML = posState.customer
    ? `👤 ${esc(posState.customer.name)} ${posState.customer.phone ? "· " + esc(posState.customer.phone) : ""} <button class="btn btn-sm" onclick="posClearCustomer()">✕</button>`
    : `<span class="muted">بدون مشتری (F8)</span>`;
}

window.posQty = (idx, delta, direct) => {
  const it = posState.cart[idx];
  if (!it) return;
  if (delta === 0 && direct !== undefined) it.quantity = Math.max(1, parseInt(direct || "1", 10) || 1);
  else it.quantity = Math.max(1, it.quantity + delta);
  renderPosCart();
};
window.posRemove = (idx) => { posState.cart.splice(idx, 1); renderPosCart(); };
window.posClearCustomer = () => { posState.customer = null; renderPosCart(); };

function posClock() {
  const el = $("#pos-clock");
  if (!el) return;
  el.textContent = new Date().toLocaleTimeString("fa-IR");
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
          <input id="pos-scan" class="pos-scan" placeholder="＝ اسکن بارکد…" autocomplete="off" autofocus />
          <div class="pos-hint muted"><span class="kbd">Enter</span> افزودن · <span class="kbd">F2</span> پرداخت · <span class="kbd">F4</span> تخفیف · <span class="kbd">F8</span> مشتری · <span class="kbd">Del</span> حذف آخرین · <span class="kbd">Esc</span> خالی کردن</div>
          <div id="pos-customer" class="pos-customer"></div>
          <div id="pos-totals" class="pos-totals"></div>
          <div class="pos-actions">
            <button class="pos-btn pos-btn-pay" id="pos-pay">پرداخت (F2)</button>
            <button class="pos-btn" id="pos-discount-btn">تخفیف (F4)</button>
            <button class="pos-btn" id="pos-customer-btn">مشتری (F8)</button>
            <button class="pos-btn pos-btn-danger" id="pos-clear-btn">خالی کردن (Esc)</button>
          </div>
        </div>
      </div>
      <div id="pos-receipt"></div>
    </div>`;
  $("#pos-scan").addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    const bc = e.target.value.trim();
    e.target.value = "";
    if (bc) await posAddByBarcode(bc);
  });
  $("#pos-pay").addEventListener("click", () => posCheckoutModal());
  $("#pos-discount-btn").addEventListener("click", () => posDiscountModal());
  $("#pos-customer-btn").addEventListener("click", () => posCustomerModal());
  $("#pos-clear-btn").addEventListener("click", () => { posState.cart = []; renderPosCart(); });
  $("#pos-kiosk-btn").addEventListener("click", () => (state.kiosk ? exitKioskPrompt() : enterKiosk()));
  posClock();
  renderPosCart();
  $("#pos-scan").focus();
};

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
  if (opts.length === 1) { posPushCart(p, opts[0], 1); return; }
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
      closeModal(); posPushCart(p, b, 1);
    }));
}

function posPushCart(p, batch, qty) {
  const existing = posState.cart.find((i) => i.product_id === p.id && i.batch_id === batch.batch_id);
  if (existing) existing.quantity += qty;
  else posState.cart.push({ product_id: p.id, product_name: p.name, batch_id: batch.batch_id,
    batch_number: batch.batch_number, quantity: qty, unit_sell_price: batch.sell_price,
    unit_buy_price: batch.buy_price, expiry_date: batch.expiry_date, discount: 0 });
  renderPosCart();
  $("#pos-scan").focus();
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
  const total = gross - disc;
  openModal(`<h3>پرداخت</h3>
    <div class="row" style="display:flex;justify-content:space-between"><span>قابل پرداخت</span><strong style="font-size:20px">${money(total)}</strong></div>
    <label>روش پرداخت</label>
    <select id="pay-method"><option value="CASH">نقدی</option><option value="CARD">کارت</option><option value="MIXED">ترکیبی</option></select>
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
  try {
    const inv = await api("/pos/checkout", {
      method: "POST",
      body: JSON.stringify({
        items: posState.cart.map((i) => ({ product_id: i.product_id, batch_id: i.batch_id,
                                           quantity: i.quantity, discount: i.discount || 0 })),
        payments, customer_id: posState.customer ? posState.customer.id : null }),
    });
    posState.cart = []; posState.customer = null;
    closeModal(); renderPosCart();
    toast(`فروش ثبت شد: ${inv.invoice_number}`);
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
  else if (e.key === "Delete" && !modalOpen) { posState.cart.pop(); renderPosCart(); }
  else if (e.key === "Escape" && !modalOpen) { posState.cart = []; renderPosCart(); }
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
    <div class="form-row">
      <div><label>بارکد</label><input id="p-barcode" placeholder="اسکن یا تایپ بارکد" /></div>
      <div><label>نام کالا</label><input id="p-name" /></div>
      <div><label>حداقل موجودی هشدار</label><input id="p-min" type="number" value="5" /></div>
    </div>
    <button id="p-add" class="btn btn-primary" style="margin-top:12px">ثبت کالا</button>
  </div>
  <div class="card"><h3>فهرست کالاها</h3><table id="p-table"></table></div>`;
  $("#p-add").addEventListener("click", async () => {
    try {
      await api("/products", { method: "POST", body: JSON.stringify({
        barcode: $("#p-barcode").value.trim(), name: $("#p-name").value.trim(),
        min_stock_alert: Number($("#p-min").value || 5) }) });
      toast("کالا ثبت شد");
      $("#p-barcode").value = ""; $("#p-name").value = "";
      RENDER.products();
    } catch (e) { toast(e.message, "err"); }
  });
  const { items } = await api("/products?limit=200");
  const rows = items.map((p) => el("tr", {},
    el("td", { text: p.barcode }), el("td", { text: p.name }), el("td", { text: p.min_stock_alert }),
    el("td", {}, el("span", { class: "badge " + (p.is_active ? "badge-green" : "badge-gray"), text: p.is_active ? "فعال" : "غیرفعال" }))));
  const tbl = $("#p-table");
  tbl.innerHTML = "";
  tbl.append(el("thead", {}, el("tr", {},
    el("th", { text: "بارکد" }), el("th", { text: "نام" }), el("th", { text: "حداقل موجودی" }), el("th", { text: "وضعیت" }))),
    el("tbody", {}, ...rows));
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
      <div><label>قیمت مصرف‌کننده</label><input id="b-consumer" type="number" /></div>
      <div><label>قیمت فروش</label><input id="b-sell" type="number" /></div>
      <div><label>تاریخ انقضا</label><input id="b-expiry" type="date" /></div>
    </div>
    <button id="b-receive" class="btn btn-primary" style="margin-top:12px">ثبت ورود</button>
  </div>
  <div class="card"><h3>Batch های اخیر</h3><table id="b-table"></table></div>`;
  $("#b-receive").addEventListener("click", async () => {
    try {
      const body = { barcode: $("#b-barcode").value.trim(), quantity_received: Number($("#b-qty").value),
        buy_price: Number($("#b-buy").value), consumer_price: Number($("#b-consumer").value || 0) || null,
        sell_price: Number($("#b-sell").value || 0) || null, expiry_date: $("#b-expiry").value || null };
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
RENDER.settings = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="card"><h3>تنظیمات سیستم</h3><table id="s-table"></table></div>`;
  const rows = await api("/settings");
  const t = $("#s-table");
  const trs = rows.map((s) => el("tr", {},
    el("td", { text: s.key }),
    el("td", {}, (() => {
      const input = el("input", { id: "set-" + s.key.replace(/\./g, "_") });
      if (s.is_secret) {
        input.setAttribute("type", "password");
        input.setAttribute("placeholder", s.has_value ? "(بدون تغییر)" : "خالی");
        input.setAttribute("autocomplete", "new-password");
      } else input.value = s.value;
      return input;
    })()),
    el("td", { text: s.description || "" }),
    el("td", {}, el("button", { class: "btn btn-sm btn-primary", text: "ذخیره", onclick: async () => {
      const input = document.getElementById("set-" + s.key.replace(/\./g, "_"));
      let value = input.value;
      if (s.is_secret && value === "") value = "__KEEP__"; // sentinel: keep stored secret
      try { await api("/settings", { method: "PUT", body: JSON.stringify({ key: s.key, value, is_secret: !!s.is_secret }) });
        toast("ذخیره شد"); } catch (e) { toast(e.message, "err"); }
    } }))));
  t.append(el("thead", {}, el("tr", {}, el("th", { text: "کلید" }), el("th", { text: "مقدار" }),
    el("th", { text: "توضیح" }), el("th", {}))), el("tbody", {}, ...trs));
};

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

/* ---------- boot ---------- */
async function boot() {
  if (!state.token) { showLogin(); return; }
  try {
    state.user = await api("/auth/me");
    showApp();
    buildNav();
    go("dashboard");
  } catch (e) {
    localStorage.removeItem("token"); state.token = "";
    showLogin();
  }
}
boot();
