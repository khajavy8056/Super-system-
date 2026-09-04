/* Supermarket System — Web Panel (vanilla JS SPA) */
const $ = (sel) => document.querySelector(sel);
const API = "/api";

const state = {
  token: localStorage.getItem("token") || "",
  user: null,
  view: "dashboard",
  cart: [], // {product_id, batch_id, quantity, ...}
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
    go("dashboard");
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

/* ---------- navigation ---------- */
const NAV = [
  ["dashboard", "📊 داشبورد"],
  ["pos", "🧾 صندوق (POS)"],
  ["products", "📦 کالاها"],
  ["batches", "📥 ورود کالا"],
  ["inventory", "🏬 انبار و انبارگردانی"],
  ["invoices", "🧮 فاکتورها"],
  ["reports", "📈 گزارش‌ها"],
  ["hardware", "🖨️ سخت‌افزار"],
  ["users", "👥 کاربران"],
  ["settings", "⚙️ تنظیمات"],
  ["audit", "🕵️ لاگ‌ها"],
];

function buildNav() {
  const nav = $("#nav");
  nav.innerHTML = "";
  NAV.forEach(([key, label]) => {
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

/* ---------- POS ---------- */
RENDER.pos = async () => {
  const v = $("#view");
  v.innerHTML = `
    <div class="pos-wrap">
      <div>
        <input id="pos-scan" class="scan-input" placeholder="اسکن بارکد… (تمرکز همیشه اینجاست)" autocomplete="off" />
        <div class="card" style="margin-top:12px">
          <h3>سبد خرید</h3>
          <div id="cart-table-wrap"></div>
          <div id="cart-totals" class="card" style="margin-top:8px"></div>
          <div style="display:flex;gap:8px;margin-top:10px">
            <button id="btn-checkout" class="btn btn-primary" style="flex:2">پرداخت / ثبت فروش</button>
            <button id="btn-void" class="btn btn-danger">خالی کردن سبد</button>
          </div>
        </div>
      </div>
      <div class="card">
        <h3>راهنمای سریع</h3>
        <p class="muted">بارکد را اسکن کنید. اگر کالا چند Batch (قیمت قدیم/جدید) داشته باشد، انتخابگر نمایش داده می‌شود. سیستم بر اساس سیاست FEFO/Hybrid بهترین Batch را پیشنهاد می‌دهد.</p>
        <p class="muted">کلید <span class="kbd">Enter</span> = افزودن | <span class="kbd">F12</span> = پرداخت</p>
        <div id="last-receipt"></div>
      </div>
    </div>`;
  const scan = $("#pos-scan");
  scan.focus();
  document.addEventListener("click", () => scan.focus());
  scan.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    const barcode = scan.value.trim();
    scan.value = "";
    if (!barcode) return;
    await addByBarcode(barcode);
  });
  $("#btn-void").addEventListener("click", () => { state.cart = []; renderCart(); });
  $("#btn-checkout").addEventListener("click", () => checkoutModal());
  document.addEventListener("keydown", (e) => { if (e.key === "F12") { e.preventDefault(); checkoutModal(); } });
  renderCart();
};

async function addByBarcode(barcode) {
  try {
    const p = await api(`/products/barcode/${barcode}`);
    await addToCart(p);
  } catch (err) {
    // Unknown product -> resolve
    try {
      const r = await api(`/barcode/resolve/${barcode}`);
      toast(`بارکد ناشناخته: ${r.message || "نیاز به ثبت دستی"}`, "err");
      $("#pos-scan").focus();
    } catch (e2) {
      toast("کالا یافت نشد", "err");
    }
  }
}

async function addToCart(p) {
  let options;
  try { options = await api(`/pos/batch-options/${p.id}`); } catch (e) { toast(e.message, "err"); return; }
  const opts = options.options || [];
  if (opts.length === 0) { toast("موجودی برای این کالا موجود نیست", "err"); return; }
  if (opts.length === 1) { pushCart(p, opts[0], 1); return; }
  // multiple batches -> selector
  const rows = opts.map((o) => `
    <div class="batch-option ${o.is_recommended ? "recommended" : ""}" data-batch="${o.batch_id}">
      <div class="b-title">${o.is_recommended ? "⭐ " : ""}${o.batch_number} — ${money(o.sell_price)}</div>
      <div class="b-meta">خرید: ${money(o.buy_price)} | موجودی: ${o.current_qty} |
        انقضا: ${o.expiry_date || "—"} (${o.days_left ?? "—"} روز)</div>
    </div>`).join("");
  openModal(`<h3>${p.name} — انتخاب Batch / قیمت</h3>${rows}
    <p class="muted">سیستم بر اساس سیاست موجودی پیشنهاد داده؛ می‌توانید Batch واقعی را انتخاب کنید.</p>`);
  document.querySelectorAll(".batch-option").forEach((node) =>
    node.addEventListener("click", () => {
      const b = opts.find((o) => o.batch_id == node.dataset.batch);
      closeModal(); pushCart(p, b, 1);
    }));
}

function pushCart(p, batch, qty) {
  const existing = state.cart.find((i) => i.product_id === p.id && i.batch_id === batch.batch_id);
  if (existing) existing.quantity += qty;
  else state.cart.push({ product_id: p.id, product_name: p.name, batch_id: batch.batch_id,
    batch_number: batch.batch_number, quantity: qty, unit_sell_price: batch.sell_price,
    unit_buy_price: batch.buy_price, expiry_date: batch.expiry_date });
  renderCart();
}

function renderCart() {
  const wrap = $("#cart-table-wrap");
  if (!state.cart.length) { wrap.innerHTML = `<p class="muted">سبد خالی است.</p>`; $("#cart-totals").innerHTML = ""; return; }
  let subtotal = 0, profit = 0;
  const rows = state.cart.map((it, idx) => {
    const st = it.unit_sell_price * it.quantity;
    const pr = (it.unit_sell_price - it.unit_buy_price) * it.quantity;
    subtotal += st; profit += pr;
    return el("tr", {},
      el("td", { text: it.product_name }),
      el("td", { text: it.batch_number || "—" }),
      el("td", {}, qtyCtrl(idx, it)),
      el("td", { text: money(st) }),
      el("td", {}, el("button", { class: "btn btn-sm btn-danger", text: "✕", onclick: () => { state.cart.splice(idx, 1); renderCart(); } })),
    );
  });
  wrap.innerHTML = "";
  wrap.append(el("table", { class: "cart-table" },
    el("thead", {}, el("tr", {},
      el("th", { text: "کالا" }), el("th", { text: "Batch" }), el("th", { text: "تعداد" }),
      el("th", { text: "جمع" }), el("th", {}))),
    el("tbody", {}, ...rows)));
  $("#cart-totals").innerHTML =
    `<div style="display:flex;justify-content:space-between"><span>جمع</span><strong>${money(subtotal)}</strong></div>
     <div style="display:flex;justify-content:space-between"><span class="muted">سود تخمینی</span><span class="ok">${money(profit)}</span></div>`;
}

function qtyCtrl(idx, it) {
  return el("span", {},
    el("button", { class: "btn btn-sm", text: "+", onclick: () => { it.quantity++; renderCart(); } }),
    el("span", { text: " " + it.quantity + " ", style: "min-width:24px;display:inline-block;text-align:center" }),
    el("button", { class: "btn btn-sm", text: "−", onclick: () => { it.quantity = Math.max(1, it.quantity - 1); renderCart(); } }),
  );
}

function checkoutModal() {
  if (!state.cart.length) { toast("سبد خالی است", "err"); return; }
  let subtotal = 0;
  state.cart.forEach((it) => subtotal += it.unit_sell_price * it.quantity);
  openModal(`
    <h3>پرداخت</h3>
    <p>جمع کل: <strong>${money(subtotal)}</strong></p>
    <label>روش پرداخت</label>
    <select id="pay-method">
      <option value="CASH">نقدی</option><option value="CARD">کارت</option><option value="MIXED">ترکیبی</option>
    </select>
    <div id="pay-split" class="hidden" style="margin-top:8px">
      <label>مبلغ نقدی</label><input id="pay-cash" type="number" value="0" />
      <label>مبلغ کارت</label><input id="pay-card" type="number" value="0" />
    </div>
    <div style="display:flex;gap:8px;margin-top:16px">
      <button id="btn-pay" class="btn btn-primary btn-block">ثبت و پرداخت</button>
      <button class="btn" onclick="closeModal()">انصراف</button>
    </div>`);
  $("#pay-method").addEventListener("change", (e) => {
    $("#pay-split").classList.toggle("hidden", e.target.value !== "MIXED");
  });
  $("#btn-pay").addEventListener("click", async () => {
    const method = $("#pay-method").value;
    let payments;
    if (method === "MIXED") {
      const cash = Number($("#pay-cash").value || 0), card = Number($("#pay-card").value || 0);
      payments = [{ method: "CASH", amount: cash }, { method: "CARD", amount: card }];
    } else payments = [{ method, amount: subtotal }];
    try {
      const inv = await api("/pos/checkout", {
        method: "POST",
        body: JSON.stringify({ items: state.cart.map((i) => ({ product_id: i.product_id, batch_id: i.batch_id, quantity: i.quantity })), payments }),
      });
      state.cart = [];
      closeModal();
      renderCart();
      toast(`فروش ثبت شد: ${inv.invoice_number}`);
      try {
        const print = await api(`/invoices/${inv.invoice_id}/print`, { method: "POST" });
        if (print.ok && typeof print.message === "string") showReceipt(print.message);
        else toast("چاپ: " + print.message, print.ok ? "ok" : "err");
      } catch (e) { /* print is non-blocking */ }
    } catch (err) { toast(err.message, "err"); }
  });
}

function showReceipt(text) {
  $("#last-receipt").innerHTML = `<h3>رسید</h3><pre class="receipt">${text}</pre>`;
}

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
  const rows = st.items.map((i) => `
    <tr>
      <td>${i.product_id}</td><td>${i.batch_id || "—"}</td><td>${i.system_qty}</td>
      <td><input type="number" id="count-${i.id}" value="${i.physical_qty ?? i.system_qty}" /></td>
      <td>${i.difference ?? 0}</td>
      <td><button class="btn btn-sm" onclick="window._count(${i.id})">ثبت</button></td>
    </tr>`).join("");
  openModal(`<h3>${st.name}</h3>
    <table><thead><tr><th>کالا</th><th>Batch</th><th>سیستم</th><th>فیزیکی</th><th>اختلاف</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    <button class="btn btn-primary btn-block" style="margin-top:12px" onclick="window._complete(${id})">تایید و اعمال تطبیق</button>`);
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
    closeModal(); toast("انبارگردانی تکمیل و موجودی تطبیق شد");
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

/* ---------- reports ---------- */
RENDER.reports = async () => {
  const v = $("#view");
  v.innerHTML = `<div class="grid grid-2">
    <div class="card"><h3>سود به تفکیک Batch</h3><table id="r-profit"></table></div>
    <div class="card"><h3>وضعیت Batch ها</h3><div id="r-batches"></div></div>
    <div class="card"><h3>آخرین گردش‌های موجودی</h3><table id="r-movements"></table></div>
  </div>`;
  const profit = await api("/reports/profit");
  const pRows = profit.map((p) => el("tr", {},
    el("td", { text: p.batch_id || "—" }), el("td", { text: p.product_id }),
    el("td", { text: p.qty }), el("td", { text: money(p.revenue) }), el("td", { text: money(p.profit) })));
  const pt = $("#r-profit");
  pt.append(el("thead", {}, el("tr", {}, el("th", { text: "Batch" }), el("th", { text: "کالا" }),
    el("th", { text: "تعداد" }), el("th", { text: "درآمد" }), el("th", { text: "سود" }))), el("tbody", {}, ...pRows));

  const b = await api("/reports/batches");
  $("#r-batches").innerHTML = `
    <p>فعال: ${b.active.length} | تمام‌شده: ${b.sold_out.length} | منقضی: ${b.expired.length}</p>`;

  const moves = await api("/reports/movements?limit=30");
  const mRows = moves.map((m) => el("tr", {},
    el("td", { text: m.movement_type }), el("td", { text: m.quantity }),
    el("td", { text: m.batch_id || "—" }), el("td", { text: m.created_at.slice(0, 16).replace("T", " ") })));
  const mt = $("#r-movements");
  mt.append(el("thead", {}, el("tr", {}, el("th", { text: "نوع" }), el("th", { text: "تعداد" }),
    el("th", { text: "Batch" }), el("th", { text: "زمان" }))), el("tbody", {}, ...mRows));
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
    el("td", {}, el("input", { value: s.value, id: "set-" + s.key.replace(/\./g, "_") })),
    el("td", { text: s.description || "" }),
    el("td", {}, el("button", { class: "btn btn-sm btn-primary", text: "ذخیره", onclick: async () => {
      try { await api("/settings", { method: "PUT", body: JSON.stringify({ key: s.key, value: document.getElementById("set-" + s.key.replace(/\./g, "_")).value }) });
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
