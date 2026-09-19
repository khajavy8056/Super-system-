/* =====================================================================
 * v1.4 — Accounting module (double-entry): overview, journal, ledgers,
 * trial balance, P&L, balance sheet, expenses, cheques, suppliers,
 * cash sessions (Z-report), fiscal periods. Loaded after app.js.
 * ===================================================================== */
(function () {
  const KIND_FA = { SALE: "فروش", SALE_RETURN: "برگشت از فروش", PURCHASE: "خرید", WASTE: "ضایعات", ADJUSTMENT: "اصلاح",
    SETTLEMENT: "تسویه", EXPENSE: "هزینه", CHEQUE: "چک", MANUAL: "دستی", OPENING: "افتتاحیه", CLOSING: "اختتامیه", REVERSAL: "برگشت سند" };
  const CLASS_FA = { ASSET: "دارایی", LIABILITY: "بدهی", EQUITY: "سرمایه", REVENUE: "درآمد", COGS: "بهای تمام‌شده", EXPENSE: "هزینه" };
  const PAY_FA = { CASH: "نقد (صندوق)", BANK: "بانک", CARD: "کارت‌خوان", PAYABLE: "نسیه (تأمین‌کننده)" };
  const STATUS_FA = { POSTED: "ثبت‌شده", REVERSED: "برگشت‌خورده", DRAFT: "پیش‌نویس", PENDING: "در جریان", CLEARED: "وصول‌شده", BOUNCED: "برگشتی", CANCELLED: "باطل", OPEN: "باز", CLOSED: "بسته" };
  const fa = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  const jd = (iso) => (iso ? Jalali.fromIso(String(iso).slice(0, 10)) : "—");
  const signed = (n) => `<span class="${n < 0 ? "err" : ""}">${money(n)}</span>`;

  const TABS = [
    ["overview", "نمای کلی", "trend"], ["journal", "دفتر روزنامه", "ledger"], ["ledger", "دفتر کل", "ledger"],
    ["trial", "تراز آزمایشی", "chart"], ["pl", "سود و زیان", "trend"], ["bs", "ترازنامه", "chart"],
    ["expenses", "هزینه‌ها", "cash"], ["cheques", "چک‌ها", "cheque"], ["suppliers", "تأمین‌کنندگان", "users"],
    ["sessions", "شیفت صندوق", "cash"], ["accounts", "کدینگ حساب‌ها", "gear"], ["periods", "دورهٔ مالی", "ledger"],
  ];
  let tab = "overview";

  RENDER.accounting = async () => {
    const v = $("#view");
    v.innerHTML = `<div class="acc-tabs" id="acc-tabs"></div><div id="acc-body"></div>`;
    drawTabs();
    await show(tab);
  };
  function drawTabs() {
    $("#acc-tabs").innerHTML = TABS.map(([k, l, ic]) => `<button class="acc-tab ${tab === k ? "active" : ""}" data-k="${k}">${icon(ic, 16)}<span>${l}</span></button>`).join("");
    $("#acc-tabs").querySelectorAll(".acc-tab").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.k; drawTabs(); show(tab); }));
  }
  async function show(k) {
    const body = $("#acc-body");
    body.innerHTML = `<div class="muted">در حال بارگذاری…</div>`;
    try { await VIEWS[k](body); Jalali.attachAll(body); } catch (e) { body.innerHTML = `<div class="card"><p class="error">${esc(e.message)}</p></div>`; }
  }

  const VIEWS = {};

  /* ---------- overview ---------- */
  VIEWS.overview = async (body) => {
    const o = await api("/accounting/overview");
    const kp = (label, val, ic, cls = "") => `<div class="kpi ${cls}"><span class="kpi-ic">${icon(ic, 22)}</span><div><span class="kpi-label">${label}</span><b class="kpi-val">${money(val)}</b></div></div>`;
    const due = o.cheques.overdue.map((c) => `<li><span>${c.direction === "RECEIVED" ? "دریافتی" : "پرداختی"} ${esc(c.number)} · ${esc(c.party_name || "")}</span><b>${money(c.amount)}</b><span class="muted">${jd(c.due_date)}</span></li>`).join("");
    body.innerHTML = `
      <div class="kpi-grid">
        ${kp("موجودی صندوق", o.cash, "cash", "kpi-green")}
        ${kp("موجودی بانک", o.bank, "cash", "kpi-blue")}
        ${kp("کارت‌خوان", o.card, "cash", "kpi-violet")}
        ${kp("طلب از مشتریان", o.receivables, "user", "kpi-amber")}
        ${kp("بدهی به تأمین‌کنندگان", o.payables, "users", "kpi-red")}
        ${kp("ارزش دفتری موجودی", o.inventory_value, "box", "kpi-blue")}
      </div>
      <div class="grid grid-3" style="margin-top:14px">
        <div class="card"><h3>${icon("trend", 18)} این ماه</h3>
          <div class="pl-rows">
            <div><span>درآمد فروش</span><b>${money(o.month.revenue)}</b></div>
            <div><span>بهای تمام‌شده</span><b class="err">−${money(o.month.cogs)}</b></div>
            <div><span>هزینه‌ها</span><b class="err">−${money(o.month.expenses)}</b></div>
            <div class="grand"><span>سود خالص</span><b class="${o.month.net_profit >= 0 ? "ok" : "err"}">${money(o.month.net_profit)}</b></div>
            <div><span>حاشیهٔ سود ناخالص</span><b>${fa(o.month.gross_margin_pct)}٪</b></div>
          </div>
          <div class="ring-wrap"><div class="ring" style="--p:${Math.max(0, Math.min(100, o.month.gross_margin_pct))}"><span>${fa(Math.round(o.month.gross_margin_pct))}٪</span></div><span class="muted">حاشیهٔ سود</span></div>
        </div>
        <div class="card"><h3>${icon("cheque", 18)} چک‌ها</h3>
          <div class="grid grid-2">
            <div class="mini-stat"><b>${money(o.cheques.received_pending)}</b><span>دریافتی در جریان · ${fa(o.cheques.received_count)}</span></div>
            <div class="mini-stat"><b>${money(o.cheques.issued_pending)}</b><span>پرداختی در جریان · ${fa(o.cheques.issued_count)}</span></div>
          </div>
          ${due ? `<h4 class="muted" style="margin:12px 0 6px">سررسید امروز / گذشته</h4><ul class="compact-list due-list">${due}</ul>` : `<div class="muted" style="margin-top:10px">چک سررسیدشده‌ای ندارید</div>`}
        </div>
        <div class="card"><h3>${icon("ledger", 18)} اقدام سریع</h3>
          <div class="quick-grid">
            <button class="qa qa-green" id="qa-expense">${icon("cash", 20)}<span>ثبت هزینه</span></button>
            <button class="qa qa-blue" id="qa-cheque">${icon("cheque", 20)}<span>ثبت چک</span></button>
            <button class="qa qa-violet" id="qa-entry">${icon("ledger", 20)}<span>سند دستی</span></button>
            <button class="qa qa-amber" id="qa-session">${icon("cash", 20)}<span>شیفت صندوق</span></button>
          </div>
          <div class="muted" style="margin-top:10px">${fa(o.entry_count)} سند ثبت‌شده در دفتر روزنامه</div>
        </div>
      </div>`;
    $("#qa-expense").onclick = () => expenseModal();
    $("#qa-cheque").onclick = () => chequeModal();
    $("#qa-entry").onclick = () => manualEntryModal();
    $("#qa-session").onclick = () => { tab = "sessions"; drawTabs(); show(tab); };
  };

  /* ---------- journal ---------- */
  VIEWS.journal = async (body) => {
    body.innerHTML = `<div class="card">
      <div class="card-head"><h3>دفتر روزنامه</h3>
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <input id="j-start" type="date" style="width:140px" placeholder="از تاریخ" />
          <input id="j-end" type="date" style="width:140px" placeholder="تا تاریخ" />
          <select id="j-kind" style="width:150px"><option value="">همهٔ انواع</option>${Object.entries(KIND_FA).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
          <input id="j-q" placeholder="جستجو در شرح…" style="width:180px" />
          <button id="j-go" class="btn">نمایش</button>
          <button id="j-new" class="btn btn-primary">+ سند دستی</button>
        </div></div>
      <div class="table-wrap"><table id="j-table"></table></div><div id="j-more" class="muted" style="margin-top:8px"></div></div>`;
    Jalali.attachAll(body);
    const load = async () => {
      const q = new URLSearchParams();
      const st = $("#j-start").value, en = $("#j-end").value;
      if (st) q.set("start", st); if (en) q.set("end", en);
      if ($("#j-kind").value) q.set("kind", $("#j-kind").value);
      if ($("#j-q").value.trim()) q.set("q", $("#j-q").value.trim());
      q.set("limit", "150");
      const r = await api(`/accounting/journal?${q}`);
      $("#j-table").innerHTML = `<thead><tr><th>شماره</th><th>تاریخ</th><th>نوع</th><th>شرح</th><th>مبلغ</th><th>وضعیت</th><th></th></tr></thead><tbody>${
        r.items.map((e) => `<tr class="j-row" data-id="${e.id}">
          <td class="ltr">${fa(e.number)}</td><td>${jd(e.date)}</td><td><span class="badge badge-blue">${KIND_FA[e.kind] || e.kind}</span></td>
          <td>${esc(e.description || "")}</td><td>${money(e.total)}</td>
          <td><span class="badge ${e.status === "REVERSED" ? "badge-red" : "badge-green"}">${STATUS_FA[e.status] || e.status}</span></td>
          <td><button class="btn btn-sm j-open">مشاهده</button></td></tr>`).join("") || `<tr><td colspan="7" class="muted">سندی یافت نشد</td></tr>`}</tbody>`;
      $("#j-more").textContent = `${fa(r.items.length)} از ${fa(r.total)} سند`;
      body.querySelectorAll(".j-open").forEach((b) => b.addEventListener("click", () => entryModal(Number(b.closest("tr").dataset.id))));
    };
    $("#j-go").onclick = load; $("#j-new").onclick = () => manualEntryModal(load);
    await load();
  };

  async function entryModal(id) {
    const e = await api(`/accounting/journal/${id}`);
    openModal(`<div class="modal-head"><h3>سند شمارهٔ ${fa(e.number)} <span class="badge badge-blue">${KIND_FA[e.kind] || e.kind}</span></h3>
        <span class="muted">${jd(e.date)}${e.source_type ? ` · مرجع: ${esc(e.source_type)} #${fa(e.source_id)}` : ""}</span></div>
      <p>${esc(e.description || "")}</p>
      <table class="je-table"><thead><tr><th>کد</th><th>حساب</th><th>شرح</th><th>بدهکار</th><th>بستانکار</th></tr></thead><tbody>
        ${e.lines.map((l) => `<tr><td class="ltr">${l.code}</td><td>${esc(l.name)}</td><td class="muted">${esc(l.description || "")}</td><td>${l.debit ? money(l.debit) : ""}</td><td>${l.credit ? money(l.credit) : ""}</td></tr>`).join("")}
        <tr class="je-total"><td colspan="3">جمع</td><td>${money(e.total)}</td><td>${money(e.total)}</td></tr></tbody></table>
      <div class="row" style="justify-content:space-between;margin-top:14px">
        <span class="badge ${e.status === "REVERSED" ? "badge-red" : "badge-green"}">${STATUS_FA[e.status] || e.status}</span>
        <div>${e.status !== "REVERSED" && can("accounting.post") ? `<button class="btn btn-danger" id="je-rev">برگشت سند</button>` : ""} <button class="btn" onclick="closeModal()">بستن</button></div></div>`);
    const rb = $("#je-rev");
    if (rb) rb.onclick = async () => {
      const reason = prompt("دلیل برگشت سند:"); if (reason === null) return;
      try { await api(`/accounting/journal/${id}/reverse`, { method: "POST", body: JSON.stringify({ reason }) }); toast("سند برگشت خورد"); closeModal(); show(tab); } catch (err) { toast(err.message, "err"); }
    };
  }

  let ACCOUNTS = null;
  async function accounts() { if (!ACCOUNTS) ACCOUNTS = await api("/accounting/accounts"); return ACCOUNTS; }
  const accOptions = (list, postableOnly = true) => list.filter((a) => !postableOnly || a.is_postable).filter((a) => a.is_active)
    .map((a) => `<option value="${a.code}">${a.code} — ${esc(a.name)}</option>`).join("");

  function manualEntryModal(after) {
    accounts().then((list) => {
      const opts = accOptions(list);
      const line = () => `<div class="je-line"><select class="je-acc">${opts}</select><input class="je-d" type="number" min="0" placeholder="بدهکار" /><input class="je-c" type="number" min="0" placeholder="بستانکار" /><input class="je-desc" placeholder="شرح ردیف" /><button class="btn btn-sm btn-danger je-del">✕</button></div>`;
      openModal(`<h3>سند حسابداری دستی</h3>
        <div class="form-row"><div><label>تاریخ (شمسی)</label><input id="je-date" type="date" /></div><div><label>شرح سند</label><input id="je-descr" placeholder="مثلاً: واریز سرمایهٔ اولیه" /></div></div>
        <div id="je-lines" class="je-lines">${line()}${line()}</div>
        <div class="row" style="justify-content:space-between;margin-top:8px"><button class="btn btn-sm" id="je-add">+ ردیف</button><span id="je-sum" class="muted"></span></div>
        <div class="row" style="justify-content:flex-end;gap:8px;margin-top:14px"><button class="btn" onclick="closeModal()">انصراف</button><button class="btn btn-primary" id="je-save">ثبت سند</button></div>`);
      Jalali.attachAll($("#modal"));
      Jalali.setValue($("#je-date"), Jalali.todayIso());
      const recalc = () => {
        let d = 0, c = 0;
        $("#modal").querySelectorAll(".je-line").forEach((l) => { d += Number(l.querySelector(".je-d").value || 0); c += Number(l.querySelector(".je-c").value || 0); });
        $("#je-sum").innerHTML = `بدهکار ${money(d)} · بستانکار ${money(c)} · ${d === c ? `<span class="ok">تراز</span>` : `<span class="err">اختلاف ${money(Math.abs(d - c))}</span>`}`;
      };
      const wire = () => { $("#modal").querySelectorAll(".je-line").forEach((l) => { l.oninput = recalc; l.querySelector(".je-del").onclick = () => { if ($("#modal").querySelectorAll(".je-line").length > 2) { l.remove(); recalc(); } }; }); };
      wire(); recalc();
      $("#je-add").onclick = () => { $("#je-lines").insertAdjacentHTML("beforeend", line()); wire(); };
      $("#je-save").onclick = async () => {
        const lines = [...$("#modal").querySelectorAll(".je-line")].map((l) => ({ account_code: l.querySelector(".je-acc").value, debit: Number(l.querySelector(".je-d").value || 0), credit: Number(l.querySelector(".je-c").value || 0), description: l.querySelector(".je-desc").value || null }));
        try { await api("/accounting/journal", { method: "POST", body: JSON.stringify({ entry_date: $("#je-date").value || null, description: $("#je-descr").value, lines }) }); toast("سند ثبت شد"); closeModal(); (after || (() => show(tab)))(); } catch (e) { toast(e.message, "err"); }
      };
    });
  }

  /* ---------- general ledger ---------- */
  VIEWS.ledger = async (body) => {
    const list = await accounts();
    body.innerHTML = `<div class="card"><div class="card-head"><h3>دفتر کل (گردش حساب)</h3>
      <div class="row" style="gap:8px;flex-wrap:wrap"><select id="gl-acc" style="width:280px">${accOptions(list).replace(/value="(\d+)"/g, (m, c) => `value="${list.find((a) => a.code === c).id}"`)}</select>
      <input id="gl-start" type="date" style="width:140px" /><input id="gl-end" type="date" style="width:140px" /><button id="gl-go" class="btn btn-primary">نمایش</button></div></div>
      <div id="gl-out"></div></div>`;
    Jalali.attachAll(body);
    const load = async () => {
      const q = new URLSearchParams(); if ($("#gl-start").value) q.set("start", $("#gl-start").value); if ($("#gl-end").value) q.set("end", $("#gl-end").value);
      const r = await api(`/accounting/ledger/${$("#gl-acc").value}?${q}`);
      $("#gl-out").innerHTML = `<div class="row" style="gap:16px;margin:8px 0"><span class="muted">مانده اول دوره: <b>${money(r.opening)}</b></span><span class="muted">مانده پایان: <b>${money(r.closing)}</b></span></div>
        <div class="table-wrap"><table><thead><tr><th>سند</th><th>تاریخ</th><th>نوع</th><th>شرح</th><th>بدهکار</th><th>بستانکار</th><th>مانده</th></tr></thead><tbody>
        ${r.rows.map((x) => `<tr><td class="ltr">${fa(x.number)}</td><td>${jd(x.date)}</td><td>${KIND_FA[x.kind] || x.kind}</td><td>${esc(x.description || "")}</td><td>${x.debit ? money(x.debit) : ""}</td><td>${x.credit ? money(x.credit) : ""}</td><td>${signed(x.balance)}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">گردشی ندارد</td></tr>`}</tbody></table></div>`;
    };
    $("#gl-go").onclick = load; await load();
  };

  /* ---------- trial balance ---------- */
  VIEWS.trial = async (body) => {
    body.innerHTML = `<div class="card"><div class="card-head"><h3>تراز آزمایشی</h3><div class="row" style="gap:8px"><input id="tb-start" type="date" style="width:140px" /><input id="tb-end" type="date" style="width:140px" /><button id="tb-go" class="btn btn-primary">نمایش</button><button class="btn" onclick="window.print()">چاپ</button></div></div><div id="tb-out"></div></div>`;
    Jalali.attachAll(body);
    const load = async () => {
      const q = new URLSearchParams(); if ($("#tb-start").value) q.set("start", $("#tb-start").value); if ($("#tb-end").value) q.set("end", $("#tb-end").value);
      const r = await api(`/accounting/trial-balance?${q}`);
      $("#tb-out").innerHTML = `<div class="table-wrap"><table class="tb-table"><thead><tr><th>کد</th><th>حساب</th><th>طبقه</th><th>گردش بدهکار</th><th>گردش بستانکار</th><th>مانده</th></tr></thead><tbody>
        ${r.rows.map((x) => `<tr class="${x.is_group ? "tb-group" : ""}"><td class="ltr">${x.code}</td><td style="padding-inline-start:${(x.code.length - 1) * 8 + 10}px">${esc(x.name)}</td><td><span class="badge badge-gray">${CLASS_FA[x.class]}</span></td><td>${money(x.debit)}</td><td>${money(x.credit)}</td><td>${signed(x.balance)}</td></tr>`).join("")}
        <tr class="je-total"><td colspan="3">جمع</td><td>${money(r.total_debit)}</td><td>${money(r.total_credit)}</td><td>${r.balanced ? `<span class="ok">تراز ✓</span>` : `<span class="err">ناتراز!</span>`}</td></tr></tbody></table></div>`;
    };
    $("#tb-go").onclick = load; await load();
  };

  /* ---------- P&L ---------- */
  VIEWS.pl = async (body) => {
    const today = Jalali.todayIso();
    body.innerHTML = `<div class="card"><div class="card-head"><h3>صورت سود و زیان</h3><div class="row" style="gap:8px"><input id="pl-start" type="date" style="width:140px" /><input id="pl-end" type="date" style="width:140px" /><button id="pl-go" class="btn btn-primary">نمایش</button><button class="btn" onclick="window.print()">چاپ</button></div></div><div id="pl-out"></div></div>`;
    Jalali.attachAll(body);
    const jt = Jalali.fromIso(today).split("/"); // yyyy/mm/dd
    Jalali.setValue($("#pl-start"), Jalali.toIso(`${jt[0]}/${jt[1]}/01`)); Jalali.setValue($("#pl-end"), today);
    const sec = (title, g, neg) => `<div class="pl-sec"><div class="pl-sec-head"><span>${title}</span><b>${neg ? "−" : ""}${money(g.total)}</b></div>${g.items.map((i) => `<div class="pl-item"><span class="ltr muted">${i.code}</span><span>${esc(i.name)}</span><b>${money(i.amount)}</b></div>`).join("")}</div>`;
    const load = async () => {
      const r = await api(`/accounting/income-statement?start=${$("#pl-start").value}&end=${$("#pl-end").value}`);
      $("#pl-out").innerHTML = `<div class="pl-wrap">${sec("درآمدها", r.revenue)}${sec("بهای تمام‌شدهٔ کالای فروش‌رفته", r.cogs, true)}
        <div class="pl-line"><span>سود ناخالص</span><b class="${r.gross_profit >= 0 ? "ok" : "err"}">${money(r.gross_profit)}</b><span class="muted">${fa(r.gross_margin_pct)}٪</span></div>
        ${sec("هزینه‌های عملیاتی", r.expenses, true)}
        <div class="pl-line grand"><span>سود (زیان) خالص</span><b class="${r.net_profit >= 0 ? "ok" : "err"}">${money(r.net_profit)}</b></div></div>
        <div class="bars"><div class="bar"><span>درآمد</span><div><i style="width:100%;background:var(--green)"></i></div><b>${money(r.revenue.total)}</b></div>
          <div class="bar"><span>بهای تمام‌شده</span><div><i style="width:${r.revenue.total ? Math.min(100, r.cogs.total / r.revenue.total * 100) : 0}%;background:var(--amber)"></i></div><b>${money(r.cogs.total)}</b></div>
          <div class="bar"><span>هزینه‌ها</span><div><i style="width:${r.revenue.total ? Math.min(100, r.expenses.total / r.revenue.total * 100) : 0}%;background:var(--red)"></i></div><b>${money(r.expenses.total)}</b></div>
          <div class="bar"><span>سود خالص</span><div><i style="width:${r.revenue.total ? Math.max(0, Math.min(100, r.net_profit / r.revenue.total * 100)) : 0}%;background:var(--primary)"></i></div><b>${money(r.net_profit)}</b></div></div>`;
    };
    $("#pl-go").onclick = load; await load();
  };

  /* ---------- balance sheet ---------- */
  VIEWS.bs = async (body) => {
    body.innerHTML = `<div class="card"><div class="card-head"><h3>ترازنامه</h3><div class="row" style="gap:8px"><input id="bs-date" type="date" style="width:140px" /><button id="bs-go" class="btn btn-primary">نمایش</button><button class="btn" onclick="window.print()">چاپ</button></div></div><div id="bs-out"></div></div>`;
    Jalali.attachAll(body); Jalali.setValue($("#bs-date"), Jalali.todayIso());
    const col = (title, g) => `<div class="bs-col"><h4>${title}</h4>${g.items.map((i) => `<div class="pl-item"><span class="ltr muted">${i.code}</span><span>${esc(i.name)}</span><b>${money(i.amount)}</b></div>`).join("") || `<div class="muted">—</div>`}<div class="pl-line"><span>جمع ${title}</span><b>${money(g.total)}</b></div></div>`;
    const load = async () => {
      const r = await api(`/accounting/balance-sheet?as_of=${$("#bs-date").value}`);
      $("#bs-out").innerHTML = `<div class="muted" style="margin-bottom:8px">به تاریخ ${jd(r.as_of)}</div><div class="bs-grid">${col("دارایی‌ها", r.assets)}<div>${col("بدهی‌ها", r.liabilities)}${col("حقوق صاحبان سرمایه", r.equity)}</div></div>
        <div class="pl-line grand" style="margin-top:12px"><span>دارایی = بدهی + سرمایه</span><b>${money(r.assets.total)} = ${money(r.liabilities.total + r.equity.total)}</b><span class="${r.balanced ? "ok" : "err"}">${r.balanced ? "تراز ✓" : "ناتراز!"}</span></div>`;
    };
    $("#bs-go").onclick = load; await load();
  };

  /* ---------- expenses ---------- */
  VIEWS.expenses = async (body) => {
    body.innerHTML = `<div class="card"><div class="card-head"><h3>هزینه‌ها</h3><div class="row" style="gap:8px"><input id="ex-start" type="date" style="width:140px" /><input id="ex-end" type="date" style="width:140px" /><button id="ex-go" class="btn">نمایش</button><button id="ex-new" class="btn btn-primary">+ ثبت هزینه</button><button id="ex-cat" class="btn">+ دستهٔ جدید</button></div></div><div id="ex-out"></div></div>`;
    Jalali.attachAll(body);
    const load = async () => {
      const q = new URLSearchParams(); if ($("#ex-start").value) q.set("start", $("#ex-start").value); if ($("#ex-end").value) q.set("end", $("#ex-end").value);
      const r = await api(`/accounting/expenses?${q}`);
      const byCat = {}; r.items.forEach((i) => { byCat[i.category] = (byCat[i.category] || 0) + i.amount; });
      const max = Math.max(1, ...Object.values(byCat));
      $("#ex-out").innerHTML = `<div class="row" style="gap:16px;align-items:flex-start;flex-wrap:wrap"><div style="flex:1;min-width:280px"><div class="muted" style="margin:6px 0">جمع: <b>${money(r.total)}</b></div>
        <div class="table-wrap"><table><thead><tr><th>تاریخ</th><th>دسته</th><th>شرح</th><th>پرداخت از</th><th>مبلغ</th><th></th></tr></thead><tbody>
        ${r.items.map((i) => `<tr><td>${jd(i.expense_date)}</td><td>${esc(i.category)}</td><td>${esc(i.description || "")}</td><td>${PAY_FA[i.paid_from] || i.paid_from}</td><td>${money(i.amount)}</td><td>${i.journal_entry_id ? `<button class="btn btn-sm" data-je="${i.journal_entry_id}">سند</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">هزینه‌ای ثبت نشده</td></tr>`}</tbody></table></div></div>
        <div class="card" style="width:300px"><h3>سهم دسته‌ها</h3><div class="bars">${Object.entries(byCat).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<div class="bar"><span>${esc(k)}</span><div><i style="width:${v / max * 100}%"></i></div><b>${money(v)}</b></div>`).join("") || `<span class="muted">—</span>`}</div></div></div>`;
      body.querySelectorAll("[data-je]").forEach((b) => b.onclick = () => entryModal(Number(b.dataset.je)));
    };
    $("#ex-go").onclick = load; $("#ex-new").onclick = () => expenseModal(load);
    $("#ex-cat").onclick = async () => {
      const list = await accounts();
      openModal(`<h3>دستهٔ هزینهٔ جدید</h3><label>نام دسته</label><input id="ec-name" /><label>حساب هزینه</label><select id="ec-acc">${accOptions(list.filter((a) => a.class === "EXPENSE"))}</select>
        <div class="row" style="justify-content:flex-end;gap:8px;margin-top:14px"><button class="btn" onclick="closeModal()">انصراف</button><button class="btn btn-primary" id="ec-save">ثبت</button></div>`);
      $("#ec-save").onclick = async () => { try { await api("/accounting/expense-categories", { method: "POST", body: JSON.stringify({ name: $("#ec-name").value, account_code: $("#ec-acc").value }) }); toast("دسته ثبت شد"); closeModal(); } catch (e) { toast(e.message, "err"); } };
    };
    await load();
  };

  async function expenseModal(after) {
    const cats = await api("/accounting/expense-categories");
    let sups = []; try { sups = await api("/accounting/suppliers"); } catch (e) { /* optional */ }
    openModal(`<h3>ثبت هزینه</h3>
      <div class="form-row"><div><label>دستهٔ هزینه</label><select id="ex-c">${cats.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></div>
      <div><label>مبلغ (${state.currency.label})</label><input id="ex-a" type="number" min="0" autofocus /></div>
      <div><label>تاریخ (شمسی)</label><input id="ex-d" type="date" /></div>
      <div><label>پرداخت از</label><select id="ex-p">${Object.entries(PAY_FA).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></div>
      <div><label>تأمین‌کننده (اختیاری)</label><select id="ex-s"><option value="">—</option>${sups.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></div>
      <div><label>شرح</label><input id="ex-desc" /></div></div>
      <div class="row" style="justify-content:flex-end;gap:8px;margin-top:14px"><button class="btn" onclick="closeModal()">انصراف</button><button class="btn btn-primary" id="ex-save">ثبت هزینه</button></div>`);
    Jalali.attachAll($("#modal")); Jalali.setValue($("#ex-d"), Jalali.todayIso());
    $("#ex-save").onclick = async () => {
      try { await api("/accounting/expenses", { method: "POST", body: JSON.stringify({ category_id: Number($("#ex-c").value), amount: Number($("#ex-a").value), expense_date: $("#ex-d").value || null, paid_from: $("#ex-p").value, description: $("#ex-desc").value || null, supplier_id: $("#ex-s").value ? Number($("#ex-s").value) : null }) }); toast("هزینه ثبت شد"); closeModal(); (after || (() => show(tab)))(); } catch (e) { toast(e.message, "err"); }
    };
  }

  /* ---------- cheques ---------- */
  VIEWS.cheques = async (body) => {
    body.innerHTML = `<div class="card"><div class="card-head"><h3>چک‌ها</h3><div class="row" style="gap:8px"><select id="ch-st" style="width:140px"><option value="">همه</option><option value="PENDING">در جریان</option><option value="CLEARED">وصول‌شده</option><option value="BOUNCED">برگشتی</option></select><select id="ch-dir" style="width:140px"><option value="">دریافتی و پرداختی</option><option value="RECEIVED">دریافتی</option><option value="ISSUED">پرداختی</option></select><button id="ch-go" class="btn">نمایش</button><button id="ch-new" class="btn btn-primary">+ ثبت چک</button></div></div><div id="ch-out"></div></div>`;
    const load = async () => {
      const q = new URLSearchParams(); if ($("#ch-st").value) q.set("status", $("#ch-st").value); if ($("#ch-dir").value) q.set("direction", $("#ch-dir").value);
      const rows = await api(`/accounting/cheques?${q}`);
      $("#ch-out").innerHTML = `<div class="table-wrap"><table><thead><tr><th>نوع</th><th>شماره</th><th>بانک</th><th>طرف حساب</th><th>مبلغ</th><th>سررسید</th><th>وضعیت</th><th></th></tr></thead><tbody>
        ${rows.map((c) => `<tr class="${c.status === "PENDING" && c.days_left < 0 ? "row-bad" : c.status === "PENDING" && c.days_left <= 3 ? "row-warn" : ""}">
          <td><span class="badge ${c.direction === "RECEIVED" ? "badge-green" : "badge-amber"}">${c.direction === "RECEIVED" ? "دریافتی" : "پرداختی"}</span></td>
          <td class="ltr">${esc(c.number)}</td><td>${esc(c.bank_name || "")}</td><td>${esc(c.party_name || "")}</td><td>${money(c.amount)}</td>
          <td>${jd(c.due_date)} ${c.status === "PENDING" ? `<span class="muted">(${c.days_left < 0 ? fa(-c.days_left) + " روز گذشته" : fa(c.days_left) + " روز مانده"})</span>` : ""}</td>
          <td><span class="badge ${c.status === "CLEARED" ? "badge-green" : c.status === "BOUNCED" ? "badge-red" : "badge-blue"}">${STATUS_FA[c.status]}</span></td>
          <td>${c.status === "PENDING" && can("accounting.post") ? `<button class="btn btn-sm" data-clear="${c.id}">وصول</button> <button class="btn btn-sm btn-danger" data-bounce="${c.id}">برگشت</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="8" class="muted">چکی ثبت نشده</td></tr>`}</tbody></table></div>`;
      body.querySelectorAll("[data-clear]").forEach((b) => b.onclick = async () => { try { await api(`/accounting/cheques/${b.dataset.clear}/clear`, { method: "POST" }); toast("چک وصول شد"); load(); } catch (e) { toast(e.message, "err"); } });
      body.querySelectorAll("[data-bounce]").forEach((b) => b.onclick = async () => { if (!confirm("چک برگشت خورده است؟")) return; try { await api(`/accounting/cheques/${b.dataset.bounce}/bounce`, { method: "POST" }); toast("برگشت چک ثبت شد"); load(); } catch (e) { toast(e.message, "err"); } });
    };
    $("#ch-go").onclick = load; $("#ch-new").onclick = () => chequeModal(load);
    await load();
  };

  async function chequeModal(after) {
    let custs = [], sups = [];
    try { custs = (await api("/customers?limit=200")).items || []; } catch (e) { /* optional */ }
    try { sups = await api("/accounting/suppliers"); } catch (e) { /* optional */ }
    openModal(`<h3>ثبت چک</h3>
      <div class="form-row">
        <div><label>نوع</label><select id="cq-dir"><option value="RECEIVED">دریافتی (از مشتری)</option><option value="ISSUED">پرداختی (به تأمین‌کننده)</option></select></div>
        <div><label>شماره چک</label><input id="cq-num" class="ltr" /></div>
        <div><label>مبلغ</label><input id="cq-amt" type="number" min="0" /></div>
        <div><label>بانک</label><input id="cq-bank" /></div>
        <div><label>تاریخ سررسید (شمسی)</label><input id="cq-due" type="date" /></div>
        <div><label>تاریخ صدور (شمسی)</label><input id="cq-iss" type="date" /></div>
        <div><label>مشتری</label><select id="cq-cust"><option value="">—</option>${custs.map((c) => `<option value="${c.id}">${esc(c.name)} ${esc(c.last_name || "")}</option>`).join("")}</select></div>
        <div><label>تأمین‌کننده</label><select id="cq-sup"><option value="">—</option>${sups.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></div>
        <div><label>نام طرف حساب (اگر ثبت‌نشده)</label><input id="cq-party" /></div>
        <div><label>شرح</label><input id="cq-desc" /></div></div>
      <div class="row" style="justify-content:flex-end;gap:8px;margin-top:14px"><button class="btn" onclick="closeModal()">انصراف</button><button class="btn btn-primary" id="cq-save">ثبت چک</button></div>`);
    Jalali.attachAll($("#modal"));
    $("#cq-save").onclick = async () => {
      const cust = $("#cq-cust").value, sup = $("#cq-sup").value;
      const body = { direction: $("#cq-dir").value, number: $("#cq-num").value, amount: Number($("#cq-amt").value), due_date: $("#cq-due").value, issue_date: $("#cq-iss").value || null, bank_name: $("#cq-bank").value || null, description: $("#cq-desc").value || null, party_name: $("#cq-party").value || null,
        party_type: cust ? "CUSTOMER" : sup ? "SUPPLIER" : null, party_id: cust ? Number(cust) : sup ? Number(sup) : null };
      try { await api("/accounting/cheques", { method: "POST", body: JSON.stringify(body) }); toast("چک ثبت شد"); closeModal(); (after || (() => show(tab)))(); } catch (e) { toast(e.message, "err"); }
    };
  }

  /* ---------- suppliers ---------- */
  VIEWS.suppliers = async (body) => {
    body.innerHTML = `<div class="grid grid-2"><div class="card"><div class="card-head"><h3>تأمین‌کنندگان و بدهی</h3></div><table id="sp-table"></table></div>
      <div class="card"><h3>تأمین‌کنندهٔ جدید</h3><label>نام</label><input id="sp-name" /><label>تلفن</label><input id="sp-phone" /><label>آدرس</label><input id="sp-addr" /><button id="sp-add" class="btn btn-primary" style="margin-top:12px">ثبت</button>
      <p class="muted" style="margin-top:12px">هنگام «ورود کالا» می‌توانید تأمین‌کننده و نحوهٔ پرداخت (نسیه/نقد/بانک) را انتخاب کنید؛ خرید نسیه به‌طور خودکار در بدهی تأمین‌کننده می‌نشیند.</p></div></div>`;
    const load = async () => {
      const rows = await api("/accounting/suppliers");
      $("#sp-table").innerHTML = `<thead><tr><th>نام</th><th>تلفن</th><th>بدهی ما</th><th></th></tr></thead><tbody>${rows.map((s) => `<tr><td>${esc(s.name)}</td><td class="ltr">${esc(s.phone || "")}</td><td>${signed(s.balance)}</td><td>${can("accounting.post") ? `<button class="btn btn-sm" data-pay="${s.id}" data-name="${esc(s.name)}">پرداخت</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">تأمین‌کننده‌ای ثبت نشده</td></tr>`}</tbody>`;
      body.querySelectorAll("[data-pay]").forEach((b) => b.onclick = () => {
        openModal(`<h3>پرداخت به ${b.dataset.name}</h3><label>مبلغ</label><input id="sp-amt" type="number" min="0" autofocus /><label>روش</label><select id="sp-m"><option value="CASH">نقد</option><option value="BANK">بانک</option><option value="CARD">کارت</option></select><label>توضیح</label><input id="sp-note" />
          <div class="row" style="justify-content:flex-end;gap:8px;margin-top:14px"><button class="btn" onclick="closeModal()">انصراف</button><button class="btn btn-primary" id="sp-ok">ثبت پرداخت</button></div>`);
        $("#sp-ok").onclick = async () => { try { await api(`/accounting/suppliers/${b.dataset.pay}/pay`, { method: "POST", body: JSON.stringify({ amount: Number($("#sp-amt").value), method: $("#sp-m").value, note: $("#sp-note").value || null }) }); toast("پرداخت ثبت شد"); closeModal(); load(); } catch (e) { toast(e.message, "err"); } };
      });
    };
    $("#sp-add").onclick = async () => { try { await api("/accounting/suppliers", { method: "POST", body: JSON.stringify({ name: $("#sp-name").value, phone: $("#sp-phone").value || null, address: $("#sp-addr").value || null }) }); toast("ثبت شد"); load(); } catch (e) { toast(e.message, "err"); } };
    await load();
  };

  /* ---------- cash sessions ---------- */
  VIEWS.sessions = async (body) => {
    const cur = await api("/accounting/cash-sessions/current");
    const hist = can("accounting.view") ? await api("/accounting/cash-sessions?limit=30") : [];
    const methods = (m) => Object.entries(m || {}).map(([k, v]) => `<div class="mini-stat"><b>${money(v)}</b><span>${PAY_FA[k] || (k === "ACCOUNT" ? "نسیه" : k)}</span></div>`).join("");
    body.innerHTML = `<div class="grid grid-2">
      <div class="card session-card">${cur ? `<div class="card-head"><h3>شیفت باز</h3><span class="badge badge-green">از ${faDateTime(cur.opened_at)}</span></div>
        <div class="grid grid-3" style="margin:10px 0">${methods(cur.by_method)}<div class="mini-stat"><b>${fa(cur.invoice_count)}</b><span>فاکتور</span></div></div>
        <div class="pl-rows"><div><span>وجه شروع</span><b>${money(cur.opening_float)}</b></div><div><span>فروش نقدی</span><b>${money(cur.cash_sales)}</b></div><div><span>استرداد</span><b class="err">−${money(cur.refunds)}</b></div><div class="grand"><span>نقد مورد انتظار در صندوق</span><b>${money(cur.expected_cash)}</b></div></div>
        <label>نقد شمارش‌شده</label><input id="cs-count" type="number" min="0" /><label>توضیح</label><input id="cs-note" />
        <button id="cs-close" class="btn btn-danger btn-block" style="margin-top:12px">بستن شیفت و گزارش Z</button>`
        : `<h3>شروع شیفت صندوق</h3><p class="muted">با وجه اولیهٔ داخل کشو شیفت را باز کنید؛ در پایان، شمارش نقد با فروش نقدی مقایسه و کسری/اضافه به‌طور خودکار در حسابداری ثبت می‌شود.</p><label>وجه اولیه (${state.currency.label})</label><input id="cs-float" type="number" min="0" value="0" /><button id="cs-open" class="btn btn-primary btn-block" style="margin-top:12px">باز کردن شیفت</button>`}</div>
      <div class="card"><h3>شیفت‌های اخیر</h3><div class="table-wrap"><table><thead><tr><th>#</th><th>صندوق‌دار</th><th>باز شدن</th><th>فروش</th><th>مورد انتظار</th><th>شمارش</th><th>اختلاف</th></tr></thead><tbody>
        ${hist.map((s) => `<tr><td>${fa(s.id)}</td><td>${esc(s.user || "")}</td><td>${faDateTime(s.opened_at)}</td><td>${money(s.total_sales)}</td><td>${money(s.expected_cash)}</td><td>${s.counted_cash == null ? "—" : money(s.counted_cash)}</td><td>${s.difference == null ? `<span class="badge badge-blue">باز</span>` : signed(s.difference)}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">—</td></tr>`}</tbody></table></div></div></div>`;
    const ob = $("#cs-open"); if (ob) ob.onclick = async () => { try { await api("/accounting/cash-sessions/open", { method: "POST", body: JSON.stringify({ opening_float: Number($("#cs-float").value || 0) }) }); toast("شیفت باز شد"); show(tab); } catch (e) { toast(e.message, "err"); } };
    const cb = $("#cs-close"); if (cb) cb.onclick = async () => {
      if ($("#cs-count").value === "") { toast("نقد شمارش‌شده را وارد کنید", "err"); return; }
      try { const r = await api(`/accounting/cash-sessions/${cur.id}/close`, { method: "POST", body: JSON.stringify({ counted_cash: Number($("#cs-count").value), note: $("#cs-note").value || null }) }); zReport(r); show(tab); } catch (e) { toast(e.message, "err"); }
    };
  };
  function zReport(s) {
    openModal(`<div class="zrep"><h3>گزارش Z — شیفت #${fa(s.id)}</h3><div class="muted">${faDateTime(s.opened_at)} تا ${faDateTime(s.closed_at)}</div>
      <table class="je-table" style="margin-top:10px"><tbody><tr><td>تعداد فاکتور</td><td>${fa(s.invoice_count)}</td></tr><tr><td>جمع فروش</td><td>${money(s.total_sales)}</td></tr>
      ${Object.entries(s.by_method || {}).map(([k, v]) => `<tr><td>— ${PAY_FA[k] || (k === "ACCOUNT" ? "نسیه" : k)}</td><td>${money(v)}</td></tr>`).join("")}
      <tr><td>استرداد</td><td>${money(s.refunds)}</td></tr><tr><td>وجه شروع</td><td>${money(s.opening_float)}</td></tr><tr><td>نقد مورد انتظار</td><td>${money(s.expected_cash)}</td></tr><tr><td>نقد شمارش‌شده</td><td>${money(s.counted_cash)}</td></tr>
      <tr class="je-total"><td>اختلاف</td><td class="${s.difference < 0 ? "err" : "ok"}">${money(s.difference)}</td></tr></tbody></table>
      <div class="row" style="justify-content:flex-end;gap:8px;margin-top:14px"><button class="btn" onclick="window.print()">چاپ</button><button class="btn btn-primary" onclick="closeModal()">بستن</button></div></div>`);
  }

  /* ---------- chart of accounts ---------- */
  VIEWS.accounts = async (body) => {
    ACCOUNTS = null; const list = await accounts();
    body.innerHTML = `<div class="grid grid-2" style="grid-template-columns:2fr 1fr"><div class="card"><div class="card-head"><h3>کدینگ حساب‌ها</h3><input id="ac-q" placeholder="جستجو…" style="width:200px" /></div><div class="table-wrap"><table id="ac-table"></table></div></div>
      <div class="card"><h3>حساب جدید (تفصیلی)</h3><label>کد</label><input id="ac-code" class="ltr" placeholder="مثلاً 6111" /><label>نام</label><input id="ac-name" /><label>طبقه</label><select id="ac-class">${Object.entries(CLASS_FA).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select><label>زیرمجموعهٔ</label><select id="ac-parent"><option value="">— (سطح اول)</option>${list.map((a) => `<option value="${a.id}">${a.code} — ${esc(a.name)}</option>`).join("")}</select>
      <button id="ac-add" class="btn btn-primary" style="margin-top:12px">ایجاد حساب</button><p class="muted" style="margin-top:10px">حساب‌های سیستمی (مقصد اسناد خودکار) قابل حذف نیستند؛ می‌توانید نام آن‌ها را ویرایش کنید.</p></div></div>`;
    const draw = () => {
      const q = $("#ac-q").value.trim();
      $("#ac-table").innerHTML = `<thead><tr><th>کد</th><th>نام</th><th>طبقه</th><th>مانده</th><th></th></tr></thead><tbody>${list.filter((a) => !q || a.code.includes(q) || a.name.includes(q)).map((a) => `<tr class="${a.is_postable ? "" : "tb-group"}"><td class="ltr">${a.code}</td><td style="padding-inline-start:${(a.code.replace(/0+$/, "").length - 1) * 10 + 10}px">${esc(a.name)} ${a.is_system ? `<span class="badge badge-gray">سیستمی</span>` : ""}${!a.is_active ? ` <span class="badge badge-red">غیرفعال</span>` : ""}</td><td>${CLASS_FA[a.class]}</td><td>${a.is_postable ? signed(a.balance) : ""}</td><td>${can("accounting.post") ? `<button class="btn btn-sm" data-edit="${a.id}">ویرایش</button>` : ""}</td></tr>`).join("")}</tbody>`;
      body.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => {
        const a = list.find((x) => x.id === Number(b.dataset.edit));
        openModal(`<h3>ویرایش ${a.code}</h3><label>نام</label><input id="ae-name" value="${esc(a.name)}" />${a.is_system ? "" : `<label><input type="checkbox" id="ae-active" ${a.is_active ? "checked" : ""} style="width:auto"/> فعال</label>`}
          <div class="row" style="justify-content:flex-end;gap:8px;margin-top:14px"><button class="btn" onclick="closeModal()">انصراف</button><button class="btn btn-primary" id="ae-save">ذخیره</button></div>`);
        $("#ae-save").onclick = async () => { const bodyP = { name: $("#ae-name").value }; if ($("#ae-active")) bodyP.is_active = $("#ae-active").checked; try { await api(`/accounting/accounts/${a.id}`, { method: "PATCH", body: JSON.stringify(bodyP) }); toast("ذخیره شد"); closeModal(); show(tab); } catch (e) { toast(e.message, "err"); } };
      });
    };
    $("#ac-q").oninput = draw; draw();
    $("#ac-add").onclick = async () => { try { await api("/accounting/accounts", { method: "POST", body: JSON.stringify({ code: $("#ac-code").value.trim(), name: $("#ac-name").value.trim(), account_class: $("#ac-class").value, parent_id: $("#ac-parent").value ? Number($("#ac-parent").value) : null }) }); toast("حساب ایجاد شد"); show(tab); } catch (e) { toast(e.message, "err"); } };
  };

  /* ---------- fiscal periods ---------- */
  VIEWS.periods = async (body) => {
    const rows = await api("/accounting/periods");
    body.innerHTML = `<div class="card"><h3>دوره‌های مالی (سال شمسی)</h3><p class="muted">با بستن دوره، حساب‌های موقت (درآمد، بهای تمام‌شده، هزینه) به «سود انباشته» منتقل و دوره قفل می‌شود؛ پس از آن هیچ سندی در آن دوره ثبت نمی‌شود.</p>
      <table><thead><tr><th>سال</th><th>از</th><th>تا</th><th>وضعیت</th><th></th></tr></thead><tbody>${rows.map((p) => `<tr><td><b>${fa(p.name)}</b></td><td>${jd(p.start_date)}</td><td>${jd(p.end_date)}</td><td><span class="badge ${p.is_closed ? "badge-red" : "badge-green"}">${p.is_closed ? "بسته" : "باز"}</span></td><td>${!p.is_closed && can("accounting.close") ? `<button class="btn btn-sm btn-danger" data-close="${p.id}" data-name="${p.name}">بستن دوره</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
    body.querySelectorAll("[data-close]").forEach((b) => b.onclick = async () => {
      if (!confirm(`دورهٔ مالی ${b.dataset.name} بسته شود؟ این عمل قابل بازگشت نیست.`)) return;
      try { await api(`/accounting/periods/${b.dataset.close}/close`, { method: "POST" }); toast("دوره بسته شد"); show(tab); } catch (e) { toast(e.message, "err"); }
    });
  };

  // expose for dashboard quick actions
  window.AccountingUI = { expenseModal, chequeModal, manualEntryModal, open(k) { tab = k || "overview"; go("accounting"); } };
})();
