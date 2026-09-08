/* v1.7 — Mobile parity module.
 * Every desktop capability reachable from the phone, redesigned for a thumb:
 * bottom sheets instead of modals, one-column forms, big tap targets.
 * Loaded after app.js; uses its helpers ($, api, esc, money, qtyFmt, toast,
 * chrome, tabbar, closeSheet, icon, state, opQueueAdd). */
(function () {
  "use strict";
  // dates: plain YYYY-MM-DD (expiry etc.) → Jalali date; timestamps → store timezone (Tehran) via faDT
  const J = (iso, t = true) => {
    if (!iso) return "—";
    const str = String(iso);
    if (/^\d{4}-\d{2}-\d{2}$/.test(str)) { try { return window.Jalali ? Jalali.fromIso(str) : str; } catch (_) { return str; } }
    return window.faDT ? faDT(str, t) : str.slice(0, 16).replace("T", " ");
  };
  const perm = (p) => !p || ((state.user && state.user.permissions) || []).includes(p);
  const num = (v) => Number(String(v || "0").replace(/[^\d.-]/g, "")) || 0;
  const screen = (title, back, html) => { $("#app").innerHTML = chrome(title, back || "goTab('more')") + `<div class="screen">${html}</div>` + tabbar(); updateSyncPill(); };
  const sheet = (html) => { closeSheet(); $("#app").insertAdjacentHTML("beforeend", `<div class="sheet" id="m-sheet"><div class="sheet-body">${html}</div></div>`); };
  const field = (id, label, attrs = "", type = "input") => `<label>${label}</label>${type === "textarea" ? `<textarea id="${id}" rows="3" ${attrs}></textarea>` : `<input id="${id}" ${attrs} />`}`;
  const sel = (id, label, opts, cur) => `<label>${label}</label><select id="${id}">${opts.map((o) => `<option value="${esc(o[0])}" ${String(o[0]) === String(cur) ? "selected" : ""}>${esc(o[1])}</option>`).join("")}</select>`;
  const v = (id) => ($("#" + id) ? $("#" + id).value.trim() : "");
  const run = async (fn, ok) => { try { await fn(); if (ok) toast(ok); return true; } catch (e) { toast(e.message, "err"); return false; } };
  const empty = (msg = "موردی یافت نشد") => `<p class="muted">${msg}</p>`;
  const row = (main, sub, right, onclick) => `<div class="stock-row" ${onclick ? `onclick="${onclick}"` : ""}><div><b>${main}</b>${sub ? `<div class="muted">${sub}</div>` : ""}</div>${right ? `<div>${right}</div>` : ""}</div>`;
  const list = async (id, loader, rowFn, emptyMsg) => { try { const rows = await loader(); $(id).innerHTML = rows.length ? rows.map(rowFn).join("") : empty(emptyMsg); } catch (e) { $(id).innerHTML = `<p class="err">${esc(e.message)}</p>`; } };

  /* ------------------------------------------------------------------ MORE menu */
  const MENU = [
    ["فروش و مشتری", [
      ["showHeldM", "clipboard", "فاکتورهای معلق", "pos.sell"],
      ["showInvoicesM", "invoice", "فاکتورها / ابطال / مرجوعی", "reports.view"],
      ["showCustomersM", "user", "مشتریان و دفتر حساب", "pos.sell"],
      ["showCampaignsM", "gift", "جشنواره‌ها", "reports.view"],
      ["showCouponsM", "gift", "کوپن‌ها", "reports.view"],
    ]],
    ["کالا و انبار", [
      ["showProducts", "box", "کالاها (افزودن / ویرایش / قیمت)", "products.view"],
      ["showStockOpsM", "warehouse", "ضایعات / اصلاح / انتقال", "inventory.view"],
      ["showWarehousesM", "warehouse", "انبارها و محل نگهداری", "inventory.view"],
      ["showMovementsM", "sync", "گردش موجودی", "inventory.view"],
    ]],
    ["گزارش و مالی", [
      ["showReportsM", "chart", "داشبورد و گزارش‌ها", "reports.view"],
      ["showAccountingM", "chart", "حسابداری (صندوق، هزینه، چک)", "accounting.view"],
    ]],
    ["مدیریت", [
      ["showUsersM", "user", "کاربران و نقش‌ها", "users.manage"],
      ["showStoreM", "gear", "مشخصات فروشگاه و پوسته", "settings.manage"],
      ["showSmsM", "invoice", "پیامک", "settings.manage"],
      ["showHardwareM", "gear", "سخت‌افزار و تست اتصالات", "settings.manage"],
      ["showLicenseM", "gear", "لایسنس", "settings.manage"],
      ["showAuditM", "clipboard", "لاگ حسابرسی", "audit.view"],
      ["showSupportM", "more", "درخواست پشتیبانی", null],
      ["showCloudM", "sync", "همگام‌سازی ابری (اینترنت)", "settings.manage"],
      ["showSync", "sync", "همگام‌سازی با رایانه", null],
      ["showSettingsM", "gear", "تنظیمات دستگاه", null],
      ["showAboutM", "more", "دربارهٔ برنامه", null],
    ]],
  ];
  window.showMore = () => {
    state.view = "more";
    $("#app").innerHTML = chrome("بیشتر") + `<div class="screen">${MENU.map(([title, items]) => {
      const vis = items.filter((i) => perm(i[3]));
      return vis.length ? `<div class="card"><h2>${title}</h2><div class="menu-list">${vis.map((i) => `<button class="menu-item" onclick="${i[0]}()">${icon(i[1])} ${i[2]}</button>`).join("")}</div></div>` : "";
    }).join("")}<button class="menu-item danger" onclick="logout()">${icon("exit")} خروج از حساب</button></div>` + tabbar();
    updateSyncPill();
  };

  /* ------------------------------------------------------------------ Held invoices (≤10) */
  const HELD_KEY = "m_held";
  const held = () => { try { return JSON.parse(localStorage.getItem(HELD_KEY) || "[]"); } catch (_) { return []; } };
  const saveHeld = (h) => localStorage.setItem(HELD_KEY, JSON.stringify(h));
  window.mHold = () => {
    if (!state.cart.length) { toast("سبد خالی است", "err"); return; }
    const h = held();
    if (h.length >= 10) { toast("حداکثر ۱۰ فاکتور معلق مجاز است", "err"); return; }
    const label = prompt("نام مشتری / برچسب فاکتور (اختیاری)") || `فاکتور ${h.length + 1}`;
    h.push({ id: Date.now(), label, cart: state.cart, at: new Date().toISOString() });
    saveHeld(h); state.cart = []; toast("فاکتور معلق شد"); showPos();
  };
  window.mResume = (id) => {
    const h = held(); const it = h.find((x) => x.id === id); if (!it) return;
    if (state.cart.length) { if (!confirm("سبد فعلی معلق شود و این فاکتور باز شود؟")) return; h.push({ id: Date.now(), label: `فاکتور ${h.length + 1}`, cart: state.cart, at: new Date().toISOString() }); }
    state.cart = it.cart; saveHeld(h.filter((x) => x.id !== id)); goTab("pos");
  };
  window.mDropHeld = (id) => { if (!confirm("این فاکتور معلق حذف شود؟")) return; saveHeld(held().filter((x) => x.id !== id)); showHeldM(); };
  window.showHeldM = () => {
    const h = held();
    screen("فاکتورهای معلق", null, `<p class="muted">تا ۱۰ فاکتور می‌تواند هم‌زمان معلق بماند؛ با لمس هر کدام دوباره در صندوق باز می‌شود.</p>
      ${h.length ? h.map((x) => `<div class="stock-row"><div onclick="mResume(${x.id})" style="flex:1"><b>${esc(x.label)}</b><div class="muted">${x.cart.length} قلم · ${money(x.cart.reduce((a, i) => a + i.sell * i.qty, 0))} · ${J(x.at)}</div></div><button class="qbtn del" onclick="mDropHeld(${x.id})">${icon("close", 15)}</button></div>`).join("") : empty("فاکتور معلقی نیست")}`);
  };
  window.mHeldBar = () => { const h = held(); return h.length ? `<div class="held-bar">${h.map((x) => `<button class="held-chip" onclick="mResume(${x.id})">${esc(x.label)} · ${x.cart.length}</button>`).join("")}</div>` : ""; };

  /* ------------------------------------------------------------------ Products */
  window.showProducts = async () => {
    screen("کالاها", null, `<div class="search-bar"><input id="p-q" placeholder="نام / بارکد / SKU…" /><button class="icon-btn big" onclick="openScanForLookup()">${icon("camera", 22)}</button></div>
      ${perm("products.manage") ? `<button class="btn btn-primary" onclick="mProductForm()">${icon("plus", 18)} کالای جدید</button>` : ""}<div id="p-list">${empty("در حال بارگذاری…")}</div>`);
    const render = (q) => list("#p-list", async () => (await api(`/products?limit=80${q ? "&q=" + encodeURIComponent(q) : ""}`)).items || [],
      (p) => row(esc(p.name), `${esc(p.barcode)}${p.has_own_barcode === false ? " (داخلی)" : ""}${p.sku ? " · " + esc(p.sku) : ""}`, icon("back", 16), `mProductMenu(${p.id})`));
    $("#p-q").addEventListener("input", debounceM(() => render(v("p-q")), 250)); render("");
  };
  window.mProductMenu = async (id) => {
    let d; try { d = await api(`/products/${id}/detail`); } catch (e) { toast(e.message, "err"); return; }
    const p = d.product;
    sheet(`<h2>${esc(p.name)}</h2><p class="muted">${esc(p.barcode)} · موجودی ${qtyFmt(d.total_stock)} · ${d.batch_count} بچ</p>
      ${(d.active_batches || []).map((b) => row(esc(b.batch_number), `خرید ${money(b.buy_price)} · فروش ${money(b.sell_price)}${b.expiry_date ? " · انقضا " + J(b.expiry_date, false) : ""}`, `<b>${qtyFmt(b.current_qty)}</b>`)).join("") || empty("موجودی فعالی نیست")}
      <div class="btn-row" style="margin-top:10px">
        ${perm("products.manage") ? `<button class="btn" onclick="mProductForm(${p.id})">ویرایش</button><button class="btn" onclick="mQuickPrice(${p.id})">تغییر قیمت</button>` : ""}
        <button class="btn" onclick="closeSheet();showPriceHistory(${p.id})">تاریخچهٔ قیمت</button>
        <button class="btn" onclick="closeSheet();showStockIn()">ورود کالا</button>
      </div><button class="btn" onclick="closeSheet()">بستن</button>`);
  };
  window.showPriceHistory = async (id) => {
    screen("تاریخچهٔ قیمت", "showProducts()", `<div id="ph"></div>`);
    list("#ph", () => api(`/prices/history/${id}`), (h) => row(money(h.price), `${esc(h.price_type || "")} · ${esc(h.source || "")} · ${J(h.created_at || h.effective_from)}`), "سابقه‌ای ثبت نشده");
  };
  window.mProductForm = async (id) => {
    let p = {}; if (id) { try { p = (await api(`/products/${id}`)) || {}; } catch (e) { toast(e.message, "err"); return; } }
    const units = (state.units || []).map((u) => [u.id, u.name]);
    sheet(`<h2>${id ? "ویرایش کالا" : "کالای جدید"}</h2>
      ${field("pf-name", "نام *", `value="${esc(p.name || "")}"`)}
      ${id ? "" : `<label>بارکد (خالی = بارکد داخلی INT-)</label><div class="search-bar"><input id="pf-barcode" class="ltr" inputmode="numeric" /><button class="icon-btn big" onclick="scanInto('pf-barcode')">${icon("camera", 20)}</button></div>`}
      ${field("pf-sku", "SKU", `value="${esc(p.sku || "")}"`)}
      ${units.length ? sel("pf-unit", "واحد", units, p.unit_id) : ""}
      ${field("pf-min", "حداقل موجودی هشدار", `type="number" inputmode="numeric" value="${p.min_stock_alert ?? 0}"`)}
      ${field("pf-desc", "توضیح", "", "textarea")}
      <button class="btn btn-primary" id="pf-save">ذخیره</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    if (p.description) $("#pf-desc").value = p.description;
    $("#pf-save").onclick = async () => {
      const body = { name: v("pf-name"), sku: v("pf-sku") || null, unit_id: $("#pf-unit") ? Number(v("pf-unit")) : undefined, min_stock_alert: num(v("pf-min")), description: v("pf-desc") || null };
      if (!body.name) { toast("نام لازم است", "err"); return; }
      if (!id) { body.barcode = v("pf-barcode") || null; body.has_own_barcode = !!body.barcode; }
      if (await run(() => api(id ? `/products/${id}` : "/products", { method: id ? "PATCH" : "POST", body: JSON.stringify(body) }), id ? "ویرایش شد" : "کالا ثبت شد")) { closeSheet(); showProducts(); }
    };
  };
  window.mQuickPrice = (id) => {
    sheet(`<h2>تغییر قیمت</h2><p class="muted">قیمت روی بچ‌های فعال اعمال و در تاریخچه ثبت می‌شود.</p>
      ${field("qp-sell", "قیمت فروش *", `type="number" inputmode="numeric"`)}${field("qp-cons", "قیمت مصرف‌کننده", `type="number" inputmode="numeric"`)}
      <label class="check"><input type="checkbox" id="qp-all" checked /> اعمال روی همهٔ بچ‌های فعال</label>
      <button class="btn btn-primary" id="qp-save">ثبت</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#qp-save").onclick = async () => {
      if (await run(() => api(`/products/${id}/quick-price`, { method: "POST", body: JSON.stringify({ sell_price: num(v("qp-sell")), consumer_price: v("qp-cons") ? num(v("qp-cons")) : null, apply_to_all_batches: $("#qp-all").checked }) }), "قیمت به‌روز شد")) { closeSheet(); }
    };
  };

  /* ------------------------------------------------------------------ Stock ops: waste / adjust / transfer */
  window.showStockOpsM = () => {
    screen("عملیات انبار", null, `<div class="menu-list">
      <button class="menu-item" onclick="mStockOp('waste')">${icon("close")} ثبت ضایعات</button>
      <button class="menu-item" onclick="mStockOp('adjust')">${icon("clipboard")} اصلاح موجودی</button>
      <button class="menu-item" onclick="mStockOp('transfer')">${icon("sync")} انتقال بین انبارها</button>
      <button class="menu-item" onclick="showMovementsM()">${icon("chart")} گردش موجودی</button></div>`);
  };
  window.mStockOp = async (kind) => {
    const titles = { waste: "ثبت ضایعات", adjust: "اصلاح موجودی", transfer: "انتقال بین انبارها" };
    let whs = []; if (kind === "transfer") whs = await api("/warehouses").catch(() => []);
    sheet(`<h2>${titles[kind]}</h2>
      <label>بارکد کالا</label><div class="search-bar"><input id="so-bc" class="ltr" inputmode="numeric" /><button class="icon-btn big" onclick="scanInto('so-bc')">${icon("camera", 20)}</button></div>
      <button class="btn" id="so-find">یافتن بچ‌ها</button><div id="so-batches"></div>
      ${kind === "transfer" ? sel("so-wh", "انبار مقصد", whs.map((w) => [w.id, w.name]), "") : ""}
      ${field("so-qty", kind === "transfer" ? "مقدار انتقال" : "موجودی واقعی جدید", `type="number" inputmode="decimal"`)}
      ${field("so-reason", "دلیل", "", "textarea")}
      <button class="btn btn-primary" id="so-save" disabled>ثبت</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    let batchId = null;
    $("#so-find").onclick = async () => {
      const bc = v("so-bc"); if (!bc) return;
      try {
        const p = await api(`/products/barcode/${encodeURIComponent(bc)}`);
        const d = await api(`/products/${p.id}/detail`);
        $("#so-batches").innerHTML = (d.active_batches || []).map((b) => `<button class="batch-pick" onclick="window._soPick(${b.id},this)"><b>${esc(b.batch_number)}</b><span class="muted">موجودی ${qtyFmt(b.current_qty)} · فروش ${money(b.sell_price)}</span></button>`).join("") || empty("بچ فعالی ندارد");
      } catch (e) { toast(e.message, "err"); }
    };
    window._soPick = (id, el) => { batchId = id; document.querySelectorAll(".batch-pick").forEach((b) => b.classList.remove("on")); el.classList.add("on"); $("#so-save").disabled = false; };
    $("#so-save").onclick = async () => {
      const body = kind === "transfer" ? { batch_id: batchId, quantity: num(v("so-qty")), to_warehouse_id: Number(v("so-wh")), reason: v("so-reason") || null }
        : { batch_id: batchId, new_current_qty: num(v("so-qty")), reason: v("so-reason") || null };
      const url = { waste: "/inventory/waste", adjust: "/inventory/adjust", transfer: "/warehouses/transfer" }[kind];
      if (await run(() => api(url, { method: "POST", body: JSON.stringify(body) }), "ثبت شد")) closeSheet();
    };
  };
  window.showMovementsM = () => { screen("گردش موجودی", "showStockOpsM()", `<div id="mv"></div>`); list("#mv", () => api("/inventory/movements?limit=100"), (m) => row(esc(m.product_name || m.product_id), `${esc(m.movement_type)} · ${J(m.created_at)}${m.reason ? " · " + esc(m.reason) : ""}`, `<b>${qtyFmt(m.quantity)}</b>`)); };
  window.showWarehousesM = () => {
    screen("انبارها", null, `${perm("settings.manage") ? `<button class="btn btn-primary" onclick="mWarehouseForm()">${icon("plus", 18)} انبار جدید</button>` : ""}<div id="wh"></div>`);
    list("#wh", () => api("/warehouses"), (w) => row(esc(w.name) + (w.is_default ? ' <span class="badge badge-green">پیش‌فرض</span>' : ""), `${esc(w.code || "")} ${esc(w.address || "")} · ${(w.locations || []).length} محل`, `<button class="qbtn" onclick="mLocationForm(${w.id})">${icon("plus", 15)}</button>`));
  };
  window.mWarehouseForm = () => { sheet(`<h2>انبار جدید</h2>${field("wf-name", "نام *")}${field("wf-code", "کد")}${field("wf-addr", "نشانی")}<button class="btn btn-primary" id="wf-save">ذخیره</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#wf-save").onclick = async () => { if (await run(() => api("/warehouses", { method: "POST", body: JSON.stringify({ name: v("wf-name"), code: v("wf-code") || null, address: v("wf-addr") || null }) }), "انبار ثبت شد")) { closeSheet(); showWarehousesM(); } }; };
  window.mLocationForm = (wid) => { sheet(`<h2>محل نگهداری جدید</h2>${field("lf-name", "نام (مثلاً قفسه A3) *")}<button class="btn btn-primary" id="lf-save">ذخیره</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#lf-save").onclick = async () => { if (await run(() => api(`/warehouses/${wid}/locations`, { method: "POST", body: JSON.stringify({ name: v("lf-name") }) }), "ثبت شد")) { closeSheet(); showWarehousesM(); } }; };

  /* ------------------------------------------------------------------ Customers + ledger */
  window.showCustomersM = () => {
    screen("مشتریان", null, `<div class="search-bar"><input id="c-q" placeholder="نام یا شماره…" /></div><div class="btn-row"><button class="btn btn-primary" onclick="mCustomerForm()">${icon("plus", 18)} مشتری جدید</button><button class="btn" onclick="showDebtorsM()">بدهکاران</button></div><div id="c-list"></div>`);
    const render = (q) => list("#c-list", async () => { const rows = await api("/customers"); return q ? rows.filter((c) => (c.name + " " + (c.phone || "")).includes(q)) : rows; },
      (c) => row(esc(c.name + " " + (c.last_name || "")), `${esc(c.phone || "—")}${c.credit_enabled ? " · اعتباری" : ""}`, icon("back", 16), `mCustomerMenu(${c.id})`));
    $("#c-q").addEventListener("input", debounceM(() => render(v("c-q")), 250)); render("");
  };
  window.showDebtorsM = () => { screen("بدهکاران", "showCustomersM()", `<div id="dl"></div>`); list("#dl", () => api("/customers/debtors"), (c) => row(esc(c.name), esc(c.phone || ""), `<b class="err">${money(c.balance || c.debt)}</b>`, `mCustomerMenu(${c.id})`), "بدهکاری وجود ندارد"); };
  window.mCustomerMenu = async (id) => {
    let c, led = []; try { c = await api(`/customers/${id}`); led = await api(`/customers/${id}/ledger?limit=20`); } catch (e) { toast(e.message, "err"); return; }
    const entries = led.entries || led.items || led || [];
    sheet(`<h2>${esc(c.name)} ${esc(c.last_name || "")}</h2><p class="muted">${esc(c.phone || "—")} · ماندهٔ حساب: <b>${money(led.balance ?? c.balance ?? 0)}</b></p>
      ${entries.slice(0, 10).map((e) => row(esc(e.entry_type || e.type), `${J(e.created_at)}${e.note ? " · " + esc(e.note) : ""}`, `<b>${money(e.amount)}</b>`)).join("") || empty("تراکنشی نیست")}
      <div class="btn-row" style="margin-top:10px">
        <button class="btn" onclick="mSettle(${id})">تسویه / دریافت</button><button class="btn" onclick="mCustomerForm(${id})">ویرایش</button>
        <button class="btn" onclick="mLedgerAdjust(${id})">ثبت بدهی / بستانکاری</button><button class="btn" onclick="mDebtReminder(${id})">پیامک یادآوری</button>
      </div><button class="btn" onclick="closeSheet()">بستن</button>`);
  };
  window.mSettle = (id) => { sheet(`<h2>تسویه حساب</h2>${field("st-amt", "مبلغ (خالی = تسویهٔ کامل)", `type="number" inputmode="numeric"`)}${sel("st-m", "روش", [["CASH", "نقدی"], ["CARD", "کارت"]], "CASH")}${field("st-note", "یادداشت")}<button class="btn btn-primary" id="st-save">ثبت</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#st-save").onclick = async () => { if (await run(() => api(`/customers/${id}/settle`, { method: "POST", body: JSON.stringify({ amount: v("st-amt") ? num(v("st-amt")) : null, method: v("st-m"), note: v("st-note") || null }) }), "تسویه ثبت شد")) closeSheet(); }; };
  window.mLedgerAdjust = (id) => { sheet(`<h2>ثبت دستی در دفتر حساب</h2>${sel("la-t", "نوع", [["DEBIT", "بدهکار (طلب ما)"], ["CREDIT", "بستانکار (طلب مشتری)"]], "DEBIT")}${field("la-amt", "مبلغ *", `type="number" inputmode="numeric"`)}${field("la-note", "توضیح *")}<button class="btn btn-primary" id="la-save">ثبت</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#la-save").onclick = async () => { if (await run(() => api(`/customers/${id}/ledger/adjust`, { method: "POST", body: JSON.stringify({ entry_type: v("la-t"), amount: num(v("la-amt")), note: v("la-note") }) }), "ثبت شد")) closeSheet(); }; };
  window.mDebtReminder = (id) => run(() => api(`/customers/${id}/debt-reminder`, { method: "POST" }), "پیامک یادآوری در صف ارسال قرار گرفت");
  window.mCustomerForm = async (id) => {
    let c = {}; if (id) c = await api(`/customers/${id}`).catch(() => ({}));
    sheet(`<h2>${id ? "ویرایش مشتری" : "مشتری جدید"}</h2>${field("cf-name", "نام *", `value="${esc(c.name || "")}"`)}${field("cf-last", "نام خانوادگی", `value="${esc(c.last_name || "")}"`)}${field("cf-phone", "موبایل", `class="ltr" inputmode="tel" value="${esc(c.phone || "")}"`)}${field("cf-addr", "نشانی", `value="${esc(c.address || "")}"`)}
      <label class="check"><input type="checkbox" id="cf-credit" ${c.credit_enabled ? "checked" : ""}/> خرید اعتباری (نسیه) مجاز</label>${field("cf-limit", "سقف اعتبار", `type="number" inputmode="numeric" value="${c.credit_limit || 0}"`)}
      <button class="btn btn-primary" id="cf-save">ذخیره</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#cf-save").onclick = async () => {
      const body = { name: v("cf-name"), last_name: v("cf-last") || null, phone: v("cf-phone") || null, address: v("cf-addr") || null, credit_enabled: $("#cf-credit").checked, credit_limit: num(v("cf-limit")) };
      if (!body.name) { toast("نام لازم است", "err"); return; }
      const call = () => api(id ? `/customers/${id}` : "/customers", { method: id ? "PATCH" : "POST", body: JSON.stringify(body) });
      try { await call(); toast("ذخیره شد"); closeSheet(); showCustomersM(); }
      catch (e) { if (!id && (!e.status || e.status >= 500)) { await opQueueAdd("CUSTOMER_CREATE", body, `مشتری ${body.name}`); toast("آفلاین: مشتری ذخیره شد و بعداً همگام می‌شود"); closeSheet(); } else toast(e.message, "err"); }
    };
  };

  /* ------------------------------------------------------------------ Invoices: detail / void / return / print */
  window.showInvoicesM = () => { screen("فاکتورها", null, `<div id="inv"></div>`); list("#inv", async () => (await api("/invoices")).items || [], (i) => row(esc(i.invoice_number), `${J(i.created_at)} · ${esc(i.status || "")}`, `<b>${money(i.total_amount)}</b>`, `mInvoice(${i.id})`)); };
  window.mInvoice = async (id) => {
    let i; try { i = await api(`/invoices/${id}`); } catch (e) { toast(e.message, "err"); return; }
    const items = i.items || [];
    sheet(`<h2>${esc(i.invoice_number)}</h2><p class="muted">${J(i.created_at)} · ${esc(i.status || "")} · ${esc(i.customer_name || "مشتری آزاد")}</p>
      ${items.map((it) => row(esc(it.product_name), `${qtyFmt(it.quantity)} × ${money(it.unit_price)}`, `<b>${money(it.total_price ?? it.line_total ?? it.quantity * it.unit_price)}</b>${i.status !== "VOID" ? `<button class="qbtn" style="margin-right:6px" onclick="mReturn(${i.id},${it.id},${it.quantity})">مرجوع</button>` : ""}`)).join("")}
      <div class="pay-total">${money(i.total_amount)}</div>
      <div class="btn-row"><button class="btn" onclick="run_(()=>api('/invoices/${id}/print',{method:'POST'}),'به چاپگر فروشگاه ارسال شد')">چاپ رسید</button>${i.status !== "VOID" && perm("pos.void") ? `<button class="btn btn-danger" onclick="mVoid(${id})">ابطال فاکتور</button>` : ""}</div>
      <button class="btn" onclick="closeSheet()">بستن</button>`);
  };
  window.run_ = run;
  window.mVoid = (id) => { sheet(`<h2>ابطال فاکتور</h2><p class="muted">ابطال، موجودی را برمی‌گرداند و در لاگ ثبت می‌شود. رمز مدیر لازم است.</p>${field("vd-reason", "دلیل *")}${field("vd-pass", "رمز مدیر *", `type="password"`)}<button class="btn btn-danger" id="vd-go">ابطال</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#vd-go").onclick = async () => { if (await run(() => api(`/invoices/${id}/void`, { method: "POST", body: JSON.stringify({ reason: v("vd-reason"), admin_password: v("vd-pass") }) }), "فاکتور ابطال شد")) { closeSheet(); showInvoicesM(); } }; };
  window.mReturn = (inv, item, max) => { sheet(`<h2>مرجوعی کالا</h2>${field("rt-qty", `تعداد (حداکثر ${qtyFmt(max)})`, `type="number" inputmode="numeric" value="1"`)}${field("rt-reason", "دلیل")}<button class="btn btn-primary" id="rt-go">ثبت مرجوعی</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#rt-go").onclick = async () => { if (await run(() => api("/returns", { method: "POST", body: JSON.stringify({ invoice_id: inv, invoice_item_id: item, qty: num(v("rt-qty")), reason: v("rt-reason") || null }) }), "مرجوعی ثبت شد")) closeSheet(); }; };

  /* ------------------------------------------------------------------ Marketing */
  window.showCampaignsM = () => { screen("جشنواره‌ها", null, `${perm("settings.manage") ? `<button class="btn btn-primary" onclick="mCampaignForm()">${icon("plus", 18)} جشنوارهٔ جدید</button>` : ""}<div id="cp"></div>`);
    list("#cp", () => api("/marketing/campaigns"), (c) => row(esc(c.name), `${c.discount_type === "PERCENT" ? c.discount_value + "٪" : money(c.discount_value)} · حداقل خرید ${money(c.min_purchase)} · ${J(c.valid_from, false)} تا ${J(c.valid_until, false)}`, `<span class="badge ${c.status === "ACTIVE" ? "badge-green" : "badge-gray"}">${esc(c.status)}</span>`)); };
  window.mCampaignForm = () => { sheet(`<h2>جشنوارهٔ جدید</h2>${field("cm-name", "نام *")}${sel("cm-type", "نوع تخفیف", [["PERCENT", "درصدی"], ["FIXED", "مبلغ ثابت"]], "PERCENT")}${field("cm-val", "مقدار *", `type="number" inputmode="decimal"`)}${field("cm-min", "حداقل خرید", `type="number" inputmode="numeric" value="0"`)}${field("cm-from", "از تاریخ (YYYY-MM-DD)", `class="ltr" placeholder="2026-01-01"`)}${field("cm-to", "تا تاریخ", `class="ltr"`)}<button class="btn btn-primary" id="cm-save">ذخیره</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#cm-save").onclick = async () => { if (await run(() => api("/marketing/campaigns", { method: "POST", body: JSON.stringify({ name: v("cm-name"), discount_type: v("cm-type"), discount_value: num(v("cm-val")), min_purchase: num(v("cm-min")), valid_from: v("cm-from") || null, valid_until: v("cm-to") || null, status: "ACTIVE" }) }), "جشنواره ثبت شد")) { closeSheet(); showCampaignsM(); } }; };
  window.showCouponsM = () => { screen("کوپن‌ها", null, `${perm("settings.manage") ? `<button class="btn btn-primary" onclick="mCouponForm()">${icon("plus", 18)} کوپن جدید</button>` : ""}<div id="cu"></div>`);
    list("#cu", () => api("/marketing/coupons?limit=50"), (c) => row(`<span class="ltr">${esc(c.code)}</span>`, `${c.discount_type === "PERCENT" ? c.discount_value + "٪" : money(c.discount_value)} · ${c.used_count}/${c.usage_limit}${c.customer_phone ? " · " + esc(c.customer_phone) : ""}`, `<span class="badge ${c.status === "ACTIVE" ? "badge-green" : "badge-gray"}">${esc(c.status)}</span>${c.status === "ACTIVE" ? `<button class="qbtn del" onclick="run_(()=>api('/marketing/coupons/${c.id}/block',{method:'POST'}),'مسدود شد').then(showCouponsM)">${icon("close", 14)}</button>` : ""}`)); };
  window.mCouponForm = () => { sheet(`<h2>کوپن جدید</h2>${field("co-code", "کد (خالی = خودکار)", `class="ltr"`)}${sel("co-type", "نوع", [["PERCENT", "درصدی"], ["FIXED", "مبلغ ثابت"]], "PERCENT")}${field("co-val", "مقدار *", `type="number" inputmode="decimal"`)}${field("co-min", "حداقل خرید", `type="number" inputmode="numeric" value="0"`)}${field("co-phone", "فقط برای این مشتری (موبایل)", `class="ltr" inputmode="tel"`)}${field("co-limit", "تعداد دفعات استفاده", `type="number" value="1"`)}${field("co-to", "تا تاریخ (YYYY-MM-DD)", `class="ltr"`)}<button class="btn btn-primary" id="co-save">ذخیره</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#co-save").onclick = async () => { if (await run(() => api("/marketing/coupons", { method: "POST", body: JSON.stringify({ code: v("co-code") || null, discount_type: v("co-type"), discount_value: num(v("co-val")), min_purchase: num(v("co-min")), customer_phone: v("co-phone") || null, usage_limit: num(v("co-limit")) || 1, valid_until: v("co-to") || null }) }), "کوپن ساخته شد")) { closeSheet(); showCouponsM(); } }; };

  /* ------------------------------------------------------------------ Reports */
  const today = () => new Date().toISOString().slice(0, 10);
  const daysAgo = (n) => new Date(Date.now() - n * 864e5).toISOString().slice(0, 10);
  window.showReportsM = async () => {
    screen("گزارش‌ها", null, `<div id="rp">${empty("در حال بارگذاری…")}</div><div class="menu-list">
      <button class="menu-item" onclick="mReport('sales')">${icon("chart")} فروش ۳۰ روز اخیر</button>
      <button class="menu-item" onclick="mReport('profit')">${icon("chart")} سود</button>
      <button class="menu-item" onclick="mReport('low-stock')">${icon("box")} کالاهای رو به اتمام</button>
      <button class="menu-item" onclick="mReport('expiry')">${icon("clipboard")} انقضا</button>
      <button class="menu-item" onclick="mReport('cashiers')">${icon("user")} عملکرد صندوق‌داران</button>
      <button class="menu-item" onclick="mReport('inventory')">${icon("warehouse")} ارزش موجودی</button>
      <button class="menu-item" onclick="mReport('stocktakes')">${icon("clipboard")} انبارگردانی‌ها</button></div>`);
    try {
      const d = await api("/reports/dashboard");
      const k = (l, val, warn) => `<div class="kpi ${warn ? "warn" : ""}"><span class="k">${l}</span><b>${val}</b></div>`;
      $("#rp").innerHTML = `<div class="kpi-grid">${k("فروش امروز", money(d.sales.today))}${k("فروش ماه", money(d.sales.month))}${k("سود امروز", money(d.profit.today))}${k("سود ماه", money(d.profit.month))}${k("فاکتور امروز", d.sales.count_today ?? d.sales.invoices_today ?? "—")}${k("میانگین فاکتور", money(d.sales.avg_invoice_today))}${k("ارزش موجودی", money(d.inventory.value))}${k("کالای کم‌موجود", d.inventory.low_stock ?? (d.low_stock || []).length, true)}${k("در آستانهٔ انقضا", (d.expiry && (d.expiry.soon_count ?? d.expiry.count)) ?? "—", true)}${k("بدهی مشتریان", money(d.customers ? d.customers.debt_total : 0))}${k("ضایعات ماه", money(d.waste ? d.waste.month : 0))}${k("مرجوعی ماه", money(d.returns ? d.returns.month : 0))}</div>`;
    } catch (e) { $("#rp").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  };
  window.mReport = async (kind) => {
    const qs = { sales: `?start=${daysAgo(30)}&end=${today()}&group=day`, profit: `?start=${daysAgo(30)}&end=${today()}`, cashiers: `?start=${daysAgo(30)}&end=${today()}` }[kind] || "";
    const titles = { sales: "فروش", profit: "سود", "low-stock": "کم‌موجود", expiry: "انقضا", cashiers: "صندوق‌داران", inventory: "ارزش موجودی", stocktakes: "انبارگردانی‌ها" };
    screen(titles[kind], "showReportsM()", `<div id="rd"></div>`);
    try {
      const d = await api(`/reports/${kind}${qs}`);
      const rows = Array.isArray(d) ? d : (d.rows || d.items || d.groups || d.expiring || d.products || d.cashiers || []);
      const summary = !Array.isArray(d) ? Object.entries(d).filter(([, val]) => typeof val === "number").map(([key, val]) => `<div class="kpi"><span class="k">${esc(key)}</span><b>${/amount|total|value|profit|revenue|cost/.test(key) ? money(val) : qtyFmt(val)}</b></div>`).join("") : "";
      $("#rd").innerHTML = (summary ? `<div class="kpi-grid">${summary}</div>` : "") + (rows.length ? rows.slice(0, 200).map((r) => row(esc(r.name || r.product_name || r.label || r.period || r.day || r.date || r.cashier || r.username || r.batch_number || ""), esc([r.barcode, r.expiry_date && J(r.expiry_date, false), r.days_left != null && r.days_left + " روز", r.count != null && r.count + " فاکتور", r.status].filter(Boolean).join(" · ")), `<b>${r.total != null ? money(r.total) : r.total_amount != null ? money(r.total_amount) : r.profit != null ? money(r.profit) : r.value != null ? money(r.value) : r.total_stock != null ? qtyFmt(r.total_stock) : r.current_qty != null ? qtyFmt(r.current_qty) : ""}</b>`)).join("") : empty());
    } catch (e) { $("#rd").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  };

  /* ------------------------------------------------------------------ Accounting */
  window.showAccountingM = async () => {
    screen("حسابداری", null, `<div id="ac-ov"></div><div class="menu-list">
      <button class="menu-item" onclick="mCashSession()">${icon("pos")} صندوق روزانه (باز/بستن)</button>
      <button class="menu-item" onclick="mExpenses()">${icon("invoice")} هزینه‌ها</button>
      <button class="menu-item" onclick="mSuppliers()">${icon("user")} تأمین‌کنندگان</button>
      <button class="menu-item" onclick="mCheques()">${icon("clipboard")} چک‌ها</button>
      <button class="menu-item" onclick="mStatement()">${icon("chart")} سود و زیان / تراز</button></div>`);
    try { const o = await api("/accounting/overview"); $("#ac-ov").innerHTML = `<div class="kpi-grid">${Object.entries(o).filter(([, x]) => typeof x === "number").slice(0, 8).map(([k, x]) => `<div class="kpi"><span class="k">${esc(k)}</span><b>${money(x)}</b></div>`).join("")}</div>`; } catch (e) { $("#ac-ov").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  };
  window.mCashSession = async () => {
    const cur = await api("/accounting/cash-sessions/current").catch(() => null);
    sheet(cur && cur.id ? `<h2>صندوق باز است</h2><p class="muted">شروع ${J(cur.opened_at)} · موجودی اولیه ${money(cur.opening_float)} · فروش نقدی ${money(cur.cash_sales ?? cur.expected_cash ?? 0)}</p>${field("cs-cnt", "وجه شمارش‌شده *", `type="number" inputmode="numeric"`)}${field("cs-note", "یادداشت")}<button class="btn btn-danger" id="cs-close">بستن صندوق</button><button class="btn" onclick="closeSheet()">انصراف</button>`
      : `<h2>باز کردن صندوق</h2>${field("cs-open", "موجودی اولیه", `type="number" inputmode="numeric" value="0"`)}<button class="btn btn-primary" id="cs-openb">باز کردن</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    if ($("#cs-close")) $("#cs-close").onclick = async () => { if (await run(() => api(`/accounting/cash-sessions/${cur.id}/close`, { method: "POST", body: JSON.stringify({ counted_cash: num(v("cs-cnt")), note: v("cs-note") || null }) }), "صندوق بسته شد")) closeSheet(); };
    if ($("#cs-openb")) $("#cs-openb").onclick = async () => { if (await run(() => api("/accounting/cash-sessions/open", { method: "POST", body: JSON.stringify({ opening_float: num(v("cs-open")) }) }), "صندوق باز شد")) closeSheet(); };
  };
  window.mExpenses = async () => {
    screen("هزینه‌ها", "showAccountingM()", `<button class="btn btn-primary" onclick="mExpenseForm()">${icon("plus", 18)} هزینهٔ جدید</button><div id="ex"></div>`);
    list("#ex", () => api("/accounting/expenses?limit=100"), (e) => row(esc(e.category_name || e.category || ""), `${J(e.expense_date, false)}${e.description ? " · " + esc(e.description) : ""}`, `<b>${money(e.amount)}</b>`));
  };
  window.mExpenseForm = async () => {
    const cats = await api("/accounting/expense-categories").catch(() => []);
    sheet(`<h2>هزینهٔ جدید</h2>${sel("ef-cat", "دسته *", cats.map((c) => [c.id, c.name]), "")}${field("ef-amt", "مبلغ *", `type="number" inputmode="numeric"`)}${sel("ef-from", "پرداخت از", [["CASH", "صندوق نقدی"], ["BANK", "بانک"]], "CASH")}${field("ef-desc", "شرح")}<button class="btn btn-primary" id="ef-save">ثبت</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#ef-save").onclick = async () => { if (await run(() => api("/accounting/expenses", { method: "POST", body: JSON.stringify({ category_id: Number(v("ef-cat")), amount: num(v("ef-amt")), paid_from: v("ef-from"), description: v("ef-desc") || null }) }), "هزینه ثبت شد")) { closeSheet(); mExpenses(); } };
  };
  window.mSuppliers = () => { screen("تأمین‌کنندگان", "showAccountingM()", `<button class="btn btn-primary" onclick="mSupplierForm()">${icon("plus", 18)} تأمین‌کنندهٔ جدید</button><div id="sp"></div>`);
    list("#sp", () => api("/accounting/suppliers"), (s) => row(esc(s.name), esc(s.phone || ""), `<b>${money(s.balance || 0)}</b><button class="qbtn" style="margin-right:6px" onclick="mSupplierPay(${s.id})">پرداخت</button>`)); };
  window.mSupplierForm = () => { sheet(`<h2>تأمین‌کنندهٔ جدید</h2>${field("sf-name", "نام *")}${field("sf-phone", "تلفن", `class="ltr"`)}${field("sf-addr", "نشانی")}<button class="btn btn-primary" id="sf-save">ذخیره</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#sf-save").onclick = async () => { if (await run(() => api("/accounting/suppliers", { method: "POST", body: JSON.stringify({ name: v("sf-name"), phone: v("sf-phone") || null, address: v("sf-addr") || null }) }), "ثبت شد")) { closeSheet(); mSuppliers(); } }; };
  window.mSupplierPay = (id) => { sheet(`<h2>پرداخت به تأمین‌کننده</h2>${field("pp-amt", "مبلغ *", `type="number" inputmode="numeric"`)}${sel("pp-from", "از", [["CASH", "صندوق"], ["BANK", "بانک"]], "CASH")}${field("pp-desc", "شرح")}<button class="btn btn-primary" id="pp-save">ثبت</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#pp-save").onclick = async () => { if (await run(() => api(`/accounting/suppliers/${id}/pay`, { method: "POST", body: JSON.stringify({ amount: num(v("pp-amt")), paid_from: v("pp-from"), description: v("pp-desc") || null }) }), "پرداخت ثبت شد")) { closeSheet(); mSuppliers(); } }; };
  window.mCheques = () => { screen("چک‌ها", "showAccountingM()", `<button class="btn btn-primary" onclick="mChequeForm()">${icon("plus", 18)} چک جدید</button><div id="ch"></div>`);
    list("#ch", () => api("/accounting/cheques"), (c) => row(`${c.direction === "IN" ? "دریافتی" : "پرداختی"} · <span class="ltr">${esc(c.number)}</span>`, `${esc(c.bank_name || "")} · سررسید ${J(c.due_date, false)} · ${esc(c.party_name || "")}`, `<b>${money(c.amount)}</b><span class="badge badge-gray">${esc(c.status)}</span>${c.status === "PENDING" ? `<div class="btn-row" style="margin-top:6px"><button class="qbtn" onclick="run_(()=>api('/accounting/cheques/${c.id}/clear',{method:'POST'}),'وصول شد').then(mCheques)">وصول</button><button class="qbtn del" onclick="run_(()=>api('/accounting/cheques/${c.id}/bounce',{method:'POST'}),'برگشت ثبت شد').then(mCheques)">برگشت</button></div>` : ""}`)); };
  window.mChequeForm = () => { sheet(`<h2>چک جدید</h2>${sel("cq-dir", "نوع", [["IN", "دریافتی"], ["OUT", "پرداختی"]], "IN")}${field("cq-num", "شمارهٔ چک *", `class="ltr"`)}${field("cq-amt", "مبلغ *", `type="number" inputmode="numeric"`)}${field("cq-due", "سررسید (YYYY-MM-DD) *", `class="ltr"`)}${field("cq-bank", "بانک")}${field("cq-party", "طرف حساب")}<button class="btn btn-primary" id="cq-save">ثبت</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#cq-save").onclick = async () => { if (await run(() => api("/accounting/cheques", { method: "POST", body: JSON.stringify({ direction: v("cq-dir"), number: v("cq-num"), amount: num(v("cq-amt")), due_date: v("cq-due"), bank_name: v("cq-bank") || null, party_name: v("cq-party") || null }) }), "چک ثبت شد")) { closeSheet(); mCheques(); } }; };
  window.mStatement = async () => {
    screen("سود و زیان / تراز", "showAccountingM()", `<div id="stm"></div>`);
    try {
      const [is, tb] = await Promise.all([api(`/accounting/income-statement?start=${daysAgo(30)}&end=${today()}`), api("/accounting/trial-balance")]);
      const kv = (o) => Object.entries(o).filter(([, x]) => typeof x === "number").map(([k, x]) => row(esc(k), "", `<b>${money(x)}</b>`)).join("");
      $("#stm").innerHTML = `<div class="card"><h2>سود و زیان ۳۰ روز</h2>${kv(is)}</div><div class="card"><h2>تراز آزمایشی</h2>${(tb.rows || tb.accounts || []).slice(0, 40).map((a) => row(esc(a.name || a.account_name), esc(a.code || ""), `<b>${money(a.balance ?? (a.debit - a.credit))}</b>`)).join("") || kv(tb)}</div>`;
    } catch (e) { $("#stm").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  };

  /* ------------------------------------------------------------------ Users */
  window.showUsersM = () => { screen("کاربران", null, `<button class="btn btn-primary" onclick="mUserForm()">${icon("plus", 18)} کاربر جدید</button><div id="us"></div>`);
    list("#us", () => api("/users"), (u) => row(esc(u.full_name || u.username), `${esc(u.username)} · ${(u.roles || []).join("، ")}${u.is_active === false ? " · غیرفعال" : ""}`, icon("back", 16), `mUserForm(${u.id})`)); };
  window.mUserForm = async (id) => {
    const roles = await api("/users/roles").catch(() => []);
    let u = {}; if (id) u = ((await api("/users").catch(() => [])).find((x) => x.id === id)) || {};
    sheet(`<h2>${id ? "ویرایش کاربر" : "کاربر جدید"}</h2>${id ? "" : field("uf-user", "نام کاربری *", `class="ltr"`)}${field("uf-name", "نام کامل", `value="${esc(u.full_name || "")}"`)}${field("uf-pass", id ? "رمز جدید (خالی = بدون تغییر)" : "رمز عبور *", `type="password"`)}
      <label>نقش‌ها</label>${roles.map((r) => `<label class="check"><input type="checkbox" class="uf-role" value="${esc(r.name || r)}" ${(u.roles || []).includes(r.name || r) ? "checked" : ""}/> ${esc(r.label || r.name || r)}</label>`).join("")}
      ${id ? `<label class="check"><input type="checkbox" id="uf-active" ${u.is_active !== false ? "checked" : ""}/> فعال</label>` : ""}
      <button class="btn btn-primary" id="uf-save">ذخیره</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#uf-save").onclick = async () => {
      const rs = [...document.querySelectorAll(".uf-role:checked")].map((c) => c.value);
      const body = id ? { full_name: v("uf-name"), roles: rs, is_active: $("#uf-active").checked, ...(v("uf-pass") ? { password: v("uf-pass") } : {}) } : { username: v("uf-user"), password: v("uf-pass"), full_name: v("uf-name"), roles: rs };
      if (await run(() => api(id ? `/users/${id}` : "/users", { method: id ? "PATCH" : "POST", body: JSON.stringify(body) }), "ذخیره شد")) { closeSheet(); showUsersM(); }
    };
  };

  /* ------------------------------------------------------------------ Store profile / theme / settings */
  window.showStoreM = async () => {
    const p = await api("/settings/store-profile").catch(() => ({}));
    const th = await api("/settings/theme").catch(() => ({ theme: "auto" }));
    screen("مشخصات فروشگاه", null, `<div class="card"><h2>فروشگاه</h2>${["name", "نام"].length ? "" : ""}
      ${[["name", "نام فروشگاه"], ["legal_name", "نام قانونی"], ["phone", "تلفن"], ["mobile", "همراه"], ["city", "شهر"], ["address", "نشانی"], ["postal_code", "کد پستی"], ["tax_id", "شناسهٔ مالیاتی"], ["receipt_note", "پیام پایین رسید"]].map(([k, l]) => field("sp-" + k, l, `value="${esc(p[k] || "")}"`)).join("")}
      <button class="btn btn-primary" id="sp-save">ذخیره</button></div>
      <div class="card"><h2>پوسته</h2>${sel("th-mode", "حالت", [["auto", "خودکار (روز/شب)"], ["light", "روشن"], ["dark", "تیره"]], th.theme)}<button class="btn" id="th-save">اعمال</button></div>
      <div class="card"><h2>تنظیمات سیستم</h2><p class="muted">مقادیر کلید/مقدار سیستم (برای کاربران پیشرفته).</p><div id="sysset"></div></div>`);
    $("#sp-save").onclick = async () => { const body = {}; ["name", "legal_name", "phone", "mobile", "city", "address", "postal_code", "tax_id", "receipt_note"].forEach((k) => body[k] = v("sp-" + k)); await run(() => api("/settings/store-profile", { method: "PUT", body: JSON.stringify(body) }), "ذخیره شد"); };
    $("#th-save").onclick = async () => { await run(() => api("/settings/theme", { method: "PUT", body: JSON.stringify({ theme: v("th-mode") }) }), "پوسته ذخیره شد"); if (window.applyThemeM) applyThemeM(v("th-mode")); };
    list("#sysset", async () => (await api("/settings")).filter((s) => !s.is_secret).slice(0, 60), (s) => row(`<span class="ltr">${esc(s.key)}</span>`, esc(s.description || ""), `<button class="qbtn" onclick="mSetEdit('${esc(s.key)}','${esc(String(s.value || "")).replace(/'/g, "&#39;")}')">ویرایش</button>`));
  };
  window.mSetEdit = (key, cur) => { sheet(`<h2 class="ltr">${esc(key)}</h2>${field("se-val", "مقدار", `value="${esc(cur)}"`)}<button class="btn btn-primary" id="se-save">ذخیره</button><button class="btn" onclick="closeSheet()">انصراف</button>`);
    $("#se-save").onclick = async () => { if (await run(() => api("/settings", { method: "PUT", body: JSON.stringify({ key, value: v("se-val") }) }), "ذخیره شد")) closeSheet(); }; };

  /* ------------------------------------------------------------------ SMS */
  window.showSmsM = async () => {
    screen("پیامک", null, `<div class="card"><h2>ارسال پیامک</h2>${field("sm-phone", "شماره", `class="ltr" inputmode="tel"`)}${field("sm-text", "متن", "", "textarea")}<button class="btn btn-primary" id="sm-send">ارسال</button><button class="btn" id="sm-test">تست اتصال سامانه</button><button class="btn" id="sm-daily">ارسال گزارش مدیریتی امروز</button></div><div class="card"><h2>آخرین پیامک‌ها</h2><div id="sm-list"></div></div>`);
    $("#sm-send").onclick = () => run(() => api("/sms/send", { method: "POST", body: JSON.stringify({ phone: v("sm-phone"), text: v("sm-text") }) }), "در صف ارسال قرار گرفت").then(loadSms);
    $("#sm-test").onclick = async () => { try { const r = await api("/sms/test-connection", { method: "POST" }); toast(r.ok || r.success ? "اتصال برقرار است" : (r.message || "ناموفق"), r.ok || r.success ? "ok" : "err"); } catch (e) { toast(e.message, "err"); } };
    $("#sm-daily").onclick = () => run(() => api("/sms/daily-report", { method: "POST" }), "گزارش ارسال شد");
    const loadSms = () => list("#sm-list", async () => (await api("/sms")).slice ? (await api("/sms")).slice(0, 30) : [], (s) => row(`<span class="ltr">${esc(s.phone)}</span>`, `${esc(s.text).slice(0, 60)} · ${J(s.created_at)}`, `<span class="badge ${s.status === "SENT" ? "badge-green" : s.status === "FAILED" ? "badge-red" : "badge-gray"}">${esc(s.status)}</span>`));
    loadSms();
  };

  /* ------------------------------------------------------------------ Hardware & diagnostics */
  window.showHardwareM = async () => {
    screen("سخت‌افزار و اتصالات", null, `<div id="hw"></div><div class="btn-row"><button class="btn" onclick="run_(()=>api('/hardware/test/print',{method:'POST'}),'صفحهٔ تست به چاپگر فروشگاه رفت')">تست چاپ</button><button class="btn" onclick="run_(()=>api('/hardware/test/drawer',{method:'POST'}),'فرمان باز شدن کشو ارسال شد')">باز کردن کشو</button></div>
      <button class="btn btn-primary" id="dg-run">اجرای تست کامل اتصالات</button><div id="dg"></div>`);
    try { const h = await api("/hardware/health"); const devs = h.devices || h.items || (Array.isArray(h) ? h : []); $("#hw").innerHTML = devs.length ? devs.map((d) => row(esc(d.name || d.device_type), esc(d.connection || d.detail || ""), `<span class="badge ${d.status === "OK" || d.status === "ONLINE" ? "badge-green" : "badge-gray"}">${esc(d.status || "")}</span>`)).join("") : `<p class="muted">چاپگر/اسکنر/کشو به رایانهٔ فروشگاه وصل می‌شوند؛ وضعیت آن‌ها اینجا دیده می‌شود.</p>`; } catch (e) { $("#hw").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
    $("#dg-run").onclick = async () => { $("#dg").innerHTML = empty("در حال اجرا…"); try { const r = await api("/diagnostics/run?include_external=false", { method: "POST" }); const checks = r.checks || r.results || []; $("#dg").innerHTML = checks.map((c) => row(esc(c.name || c.check), esc(c.message || c.detail || ""), `<span class="badge ${c.status === "OK" || c.ok ? "badge-green" : "badge-red"}">${esc(c.status || (c.ok ? "OK" : "FAIL"))}</span>`)).join("") || `<pre class="ltr">${esc(JSON.stringify(r, null, 1)).slice(0, 2000)}</pre>`; } catch (e) { $("#dg").innerHTML = `<p class="err">${esc(e.message)}</p>`; } };
  };

  /* ------------------------------------------------------------------ Licence / audit / about */
  window.showLicenseM = async () => {
    screen("لایسنس", null, `<div id="lic"></div>`);
    try { const l = await api("/setup/license"); $("#lic").innerHTML = `<div class="card">${[["وضعیت", l.allowed ? "فعال ✓" : (l.reason || l.status)], ["نوع", l.type], ["مالک", l.owner], ["کلید", l.key_masked], ["انقضا", l.expires ? J(l.expires, false) : "—"], ["روز باقی‌مانده", l.days_left], ["آخرین بررسی", J(l.checked_at)], ["شناسهٔ دستگاه رایانه", l.hwid]].map(([k, x]) => row(k, "", `<b>${esc(x ?? "—")}</b>`)).join("")}</div><button class="btn" onclick="run_(()=>api('/setup/license/recheck',{method:'POST'}),'بررسی شد').then(showLicenseM)">بررسی اکنون</button>`; } catch (e) { $("#lic").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  };
  window.showAuditM = () => { screen("لاگ حسابرسی", null, `<div id="au"></div>`); list("#au", () => api("/audit?limit=100"), (a) => row(`<span class="badge badge-blue">${esc(a.action)}</span>`, `${a.entity_type ? esc(a.entity_type) + "#" + (a.entity_id ?? "") : ""} · ${J(a.created_at)}${a.reference ? " · " + esc(a.reference) : ""}`)); };
  window.showAboutM = async () => {
    const a = await api("/settings/about").catch(() => ({}));
    screen("درباره", null, `<div class="card" style="text-align:center"><img src="/icons/logo.svg" style="width:72px;height:72px" alt="" /><h2 style="margin-top:8px">${esc(a.app_name || "سامانهٔ سوپرمارکت")}</h2><p class="muted">نسخهٔ سرور ${esc(a.version || "")}${window.SupermarketAndroid ? " · نسخهٔ اپ اندروید " + esc(SupermarketAndroid.version()) : ""}</p><p>${esc(a.store_name || "")}</p><p class="muted">طراحی و توسعه توسط خواجوی</p></div>`);
  };

  /* ------------------------------------------------------------------ Support tickets */
  const geo = () => new Promise((res) => { if (!navigator.geolocation) return res(null); navigator.geolocation.getCurrentPosition((p) => res({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy_m: p.coords.accuracy }), () => res(null), { enableHighAccuracy: true, timeout: 8000 }); });
  window.showSupportM = async () => {
    const meta = await api("/support/types").catch(() => ({ types: [], priorities: [] }));
    screen("درخواست پشتیبانی", null, `<div class="card"><h2>ثبت درخواست</h2><p class="muted">خرابی، پیشنهاد امکان جدید یا سؤال را ثبت کنید؛ همراه با مشخصات فروشگاه برای پشتیبانی ارسال می‌شود. بدون اینترنت هم ذخیره و بعداً ارسال می‌شود.</p>
      ${sel("tk-type", "نوع درخواست", meta.types.map((t) => [t.id, t.label]), "BUG")}${sel("tk-prio", "اولویت", meta.priorities.map((t) => [t.id, t.label]), "NORMAL")}${field("tk-subj", "موضوع *")}${field("tk-desc", "شرح", "", "textarea")}${field("tk-contact", "راه تماس", `class="ltr" inputmode="tel"`)}
      <label class="check"><input type="checkbox" id="tk-geo" checked /> ارسال موقعیت مکانی دقیق گوشی</label><button class="btn btn-primary" id="tk-send">ثبت و ارسال</button></div>
      <div class="card"><h2>درخواست‌های قبلی</h2><div id="tk-list"></div></div>`);
    const load = () => list("#tk-list", () => api("/support/tickets?limit=30"), (t) => row(`<span class="ltr">${esc(t.number)}</span> · ${esc(t.subject)}${t.unread ? ` <span class="badge badge-red">${t.unread} پاسخ جدید</span>` : ""}`, `${esc(t.type_label)} · ${J(t.created_at)}`, `<span class="badge ${t.status === "SENT" ? "badge-green" : t.status === "CLOSED" ? "badge-blue" : "badge-amber"}">${esc(t.status_label)}</span><button class="qbtn" onclick="showTicketM(${t.id})">💬</button>${t.status === "FAILED" || t.status === "NEW" ? `<button class="qbtn" onclick="run_(()=>api('/support/tickets/${t.id}/resend',{method:'POST'}),'تلاش شد').then(showSupportM)">↻</button>` : ""}`), "درخواستی ثبت نشده");
    $("#tk-send").onclick = async () => {
      if (v("tk-subj").length < 3) { toast("موضوع را بنویسید", "err"); return; }
      $("#tk-send").disabled = true;
      const g = $("#tk-geo").checked ? await geo() : null;
      const body = { type: v("tk-type"), priority: v("tk-prio"), subject: v("tk-subj"), description: v("tk-desc") || null, contact: v("tk-contact") || null, device: window.SupermarketAndroid ? "Android" : "Mobile Web", ...(g || {}) };
      try { const t = await api("/support/tickets", { method: "POST", body: JSON.stringify(body) }); toast(t.status === "SENT" ? `درخواست ${t.number} ارسال شد` : `درخواست ${t.number} ذخیره شد و به‌محض اتصال ارسال می‌شود`); showSupportM(); }
      catch (e) { if (!e.status || e.status >= 500) { await opQueueAdd("SUPPORT_TICKET", body, `درخواست پشتیبانی: ${body.subject}`); toast("آفلاین: درخواست ذخیره شد و با اتصال به رایانه ارسال می‌شود"); showSupportM(); } else { toast(e.message, "err"); $("#tk-send").disabled = false; } }
    };
    load();
  };

  /* v1.7.1 — conversation with support (replies from the vendor bot + store follow-ups with attachment) */
  window.showTicketM = async (id) => {
    let conv; try { conv = await api(`/support/tickets/${id}/messages`); } catch (e) { toast(e.message, "err"); return; }
    const t = conv.ticket;
    const sz = (n) => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : n > 1024 ? Math.round(n / 1024) + " KB" : (n || 0) + " B";
    const bub = (m) => `<div class="tk-msg ${m.direction === "IN" ? "in" : "out"}"><div class="muted" style="font-size:11px">${m.direction === "IN" ? "پشتیبانی" : "شما"} · ${J(m.created_at)}${m.direction === "OUT" ? " · " + esc(m.status_label) : ""}</div>${m.text ? `<div>${esc(m.text).replace(/\n/g, "<br/>")}</div>` : ""}${m.attachment_url ? `<a href="${(typeof SERVER !== "undefined" ? SERVER : "") + m.attachment_url}" target="_blank">📎 ${esc(m.attachment_name || "پیوست")} (${sz(m.attachment_size)})</a>` : ""}</div>`;
    screen(t.number, "showSupportM()", `<div class="card"><b>${esc(t.subject)}</b><div class="muted">${esc(t.type_label)} · ${esc(t.status_label)}</div></div>
      <div class="card tk-thread" id="tk-thread"><div class="tk-msg out"><div class="muted" style="font-size:11px">شما · ${J(t.created_at)}</div><div>${esc(t.description || t.subject)}</div></div>${conv.messages.map(bub).join("")}${conv.messages.some((m) => m.direction === "IN") ? "" : `<div class="muted" style="text-align:center">هنوز پاسخی نرسیده؛ پاسخ پشتیبانی همین‌جا نمایش داده می‌شود.</div>`}</div>
      <div class="card">${field("tk-reply", "پیام به پشتیبانی", "", "textarea")}<label class="btn" style="display:block;text-align:center">📎 پیوست (عکس/فایل)<input type="file" id="tk-file" style="display:none" accept="*/*" /></label><div class="muted" id="tk-fname" style="text-align:center"></div>
      <div class="row" style="gap:8px"><button class="btn" id="tk-poll" style="flex:1">بررسی پاسخ جدید</button><button class="btn btn-primary" id="tk-sendr" style="flex:1">ارسال</button></div></div>`);
    const th = $("#tk-thread"); if (th) th.scrollTop = th.scrollHeight;
    $("#tk-file").onchange = (e) => { const f = e.target.files[0]; $("#tk-fname").textContent = f ? `${f.name} (${sz(f.size)})` : ""; };
    $("#tk-poll").onclick = async () => { try { const r = await api("/support/poll", { method: "POST" }); toast(r.received ? `${r.received} پاسخ جدید` : "پاسخ جدیدی نیست"); if (r.received) showTicketM(id); } catch (e) { toast(e.message, "err"); } };
    $("#tk-sendr").onclick = async () => {
      const text = v("tk-reply"), f = $("#tk-file").files[0];
      if (!text && !f) { toast("متن یا پیوست لازم است", "err"); return; }
      if (f && f.size > 50 * 1024 * 1024) { toast("حجم پیوست حداکثر ۵۰ مگابایت است", "err"); return; }
      const fd = new FormData(); if (text) fd.append("text", text); if (f) fd.append("file", f, f.name);
      $("#tk-sendr").disabled = true;
      try { const m = await api(`/support/tickets/${id}/messages`, { method: "POST", body: fd }); toast(m.status === "SENT" ? "ارسال شد" : "ذخیره شد؛ به‌محض اتصال ارسال می‌شود"); showTicketM(id); }
      catch (e) { toast(e.message, "err"); $("#tk-sendr").disabled = false; }
    };
  };

  /* ------------------------------------------------------------------ Cloud sync (internet) */
  window.showCloudM = async () => {
    const st = await api("/cloud/status").catch((e) => ({ error: e.message }));
    screen("همگام‌سازی ابری", null, `<div class="card"><h2>وضعیت</h2>${st.error ? `<p class="err">${esc(st.error)}</p>` : `${row("سرویس", "", `<b>${st.provider_label || (st.connected ? "متصل" : "غیرفعال")}</b>`)}${row("حساب", "", `<b>${esc(st.account || "—")}</b>`)}${row("آخرین ارسال", "", `<b>${J(st.last_push_at)}</b>`)}${row("آخرین دریافت", "", `<b>${J(st.last_pull_at)}</b>`)}${row("وضعیت", "", `<span class="badge ${st.connected ? "badge-green" : "badge-gray"}">${st.connected ? "متصل" : "غیرفعال"}</span>`)}`}
      <p class="muted" style="margin-top:8px">با اتصال هر دو دستگاه (رایانه و گوشی) به یک حساب Google Drive، تغییرات از طریق اینترنت هم منتقل می‌شوند — حتی وقتی در یک شبکه نیستید. اتصال از تنظیمات ویندوز → «همگام‌سازی ابری» انجام می‌شود و در گوشی فقط کد اتصال وارد می‌شود.</p>
      <button class="btn btn-primary" onclick="run_(()=>api('/cloud/sync-now',{method:'POST'}),'همگام‌سازی ابری انجام شد').then(showCloudM)">همگام‌سازی اکنون</button></div>`);
  };

  /* ------------------------------------------------------------------ Theme on phone */
  window.applyThemeM = (mode) => { const h = new Date().getHours(); const dark = mode === "dark" || (mode === "auto" && (h < 7 || h >= 19)); document.documentElement.setAttribute("data-theme", dark ? "dark" : "light"); localStorage.setItem("m_theme", mode); };
  applyThemeM(localStorage.getItem("m_theme") || "auto");
})();
