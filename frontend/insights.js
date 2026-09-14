/* v3.0 — «هوش فروشگاه» (Store Intelligence): insights view, dashboard impact
 * block, POS whisper-suggestions, Backup + AI settings panels.
 * Depends on app.js globals: api, $, el, esc, money, fmt, icon, toast, openModal,
 * closeModal, faDateTime, can, go, RENDER, NAV, NAV_GROUPS, posState. */
(function () {
  const fa = (n) => String(n).replace(/\d/g, (x) => "۰۱۲۳۴۵۶۷۸۹"[x]);
  const pct = (x) => fa(Math.round((Number(x) || 0) * 100)) + "٪";
  const KIND_ICON = { CROSS_SELL: "gift", EXPIRY_LADDER: "clock", DEAD_STOCK: "warehouse", VELOCITY: "trend", SUPPLIER: "inbox", CASHFLOW: "cash",
    VIP: "star", CHURN: "user", BASKET_NUDGE: "pos", PRICE_GAP: "tag", LOSS_PREV: "shield", SEASON: "chart" };
  const PRIO = { 1: ["فوری", "badge-red"], 2: ["مهم", "badge-amber"], 3: ["پیشنهاد", "badge-green"] };
  const STATUS = { NEW: "جدید", ACCEPTED: "در حال اندازه‌گیری", MEASURED: "اندازه‌گیری‌شده", DISMISSED: "ردشده", SNOOZED: "به تعویق", EXPIRED: "منقضی" };
  const ico = (k, s) => (typeof ICONS !== "undefined" && ICONS[k]) ? icon(k, s) : icon("chart", s);

  // ---------------------------------------------------------------- nav registration
  if (typeof NAV !== "undefined" && !NAV.some((n) => n[0] === "insights")) {
    NAV.splice(1, 0, ["insights", "هوش فروشگاه", "reports.view", "sparkle"]);
    const grp = NAV_GROUPS.find((g) => g[0] === "رشد و تحلیل");
    if (grp) grp[1].splice(1, 0, "insights");
  }
  if (typeof ICONS !== "undefined") {
    ICONS.sparkle = ICONS.sparkle || '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>';
    ICONS.star = ICONS.star || '<path d="M12 3l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 18l-5.9 3 1.2-6.5L2.5 9.9 9.1 9z"/>';
    ICONS.tag = ICONS.tag || '<path d="M20 12l-8 8-9-9V4h7z"/><circle cx="7.5" cy="7.5" r="1.5"/>';
    ICONS.clock = ICONS.clock || '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>';
  }

  // ---------------------------------------------------------------- shared card
  function gainLine(i) {
    if (i.status === "MEASURED" || (i.status === "ACCEPTED" && i.measured_gain != null)) {
      const g = Number(i.measured_gain || 0);
      return `<span class="ins-gain ${g >= 0 ? "ok" : "err"}">${g >= 0 ? "▲" : "▼"} اثر واقعی: ${money(Math.abs(g))}</span>`;
    }
    return Number(i.expected_gain) > 0 ? `<span class="ins-gain muted">برآورد اثر: ${money(i.expected_gain)} / ماه</span>` : "";
  }

  function card(i, compact) {
    const [pl, pc] = PRIO[i.priority] || PRIO[3];
    const c = el("article", { class: "ins-card ins-" + i.kind.toLowerCase() + (i.priority === 1 ? " ins-urgent" : "") });
    c.innerHTML = `
      <header><span class="ins-ic">${ico(KIND_ICON[i.kind] || "chart", 20)}</span>
        <div class="ins-head"><span class="ins-kind">${esc(i.label)}</span><h4>${esc(i.title)}</h4></div>
        <span class="badge ${pc}">${pl}</span></header>
      ${compact ? "" : `<p class="ins-body">${esc(i.body)}</p>`}
      <div class="ins-foot">${gainLine(i)}<span class="muted">${faDateTime(i.created_at, false)}</span></div>
      <div class="ins-actions"></div>`;
    const act = c.querySelector(".ins-actions");
    act.append(el("button", { class: "btn btn-sm btn-ghost", text: "جزئیات و شواهد", onclick: () => detail(i.id) }));
    if (i.status === "NEW" || i.status === "SNOOZED") {
      if (can("settings.manage")) {
        act.append(el("button", { class: "btn btn-sm btn-primary", text: "اجرا کن", onclick: () => acceptDialog(i) }));
        act.append(el("button", { class: "btn btn-sm", text: "بعداً", onclick: async () => { await api(`/insights/${i.id}/snooze`, { method: "POST", body: JSON.stringify({ days: 7 }) }); toast("یک هفته به تعویق افتاد"); refreshCurrent(); } }));
        act.append(el("button", { class: "btn btn-sm btn-ghost", text: "رد", onclick: async () => { await api(`/insights/${i.id}/dismiss`, { method: "POST" }); refreshCurrent(); } }));
      }
    } else if (i.status === "ACCEPTED" && can("reports.view")) {
      act.append(el("button", { class: "btn btn-sm", text: "اندازه‌گیری الان", onclick: async () => { try { await api(`/insights/${i.id}/measure`, { method: "POST" }); toast("اندازه‌گیری به‌روز شد"); } catch (e) { toast(e.message, "err"); } refreshCurrent(); } }));
    }
    return c;
  }

  function evidenceTable(ev) {
    const rows = ev.rows || ev.table || ev.pairs || ev.rules || ev.spikes || ev.timeline || null;
    if (Array.isArray(rows) && rows.length && typeof rows[0] === "object") {
      const cols = Object.keys(rows[0]).filter((k) => !/_id$/.test(k) && k !== "phone");
      const L = { name: "نام", invoices: "فاکتور", sales: "فروش", profit: "سود", score: "امتیاز", batches: "بچ", over_best_pct: "٪ بالاتر از بهترین قیمت", short_life_pct: "٪ تاریخ کوتاه", returns: "مرجوعی", value: "ارزش خرید", due: "سررسید", amount: "مبلغ", party: "طرف", day: "روز", balance: "مانده", index: "شاخص", qty_total: "تعداد", a: "کالا", b: "همراه", support: "تکرار", confidence: "اطمینان", lift: "قدرت رابطه", days_since: "روز غیبت", avg_gap: "فاصلهٔ معمول", last_seen: "آخرین خرید", if_name: "اگر", then_name: "پیشنهاد", void_rate: "نرخ ابطال", return_rate: "نرخ مرجوعی", drawer_rate: "بازکردن کشو", label: "برچسب", a_name: "کالا", b_name: "همراه" };
      const cell = (k, v) => (typeof v === "number" ? (/rate|confidence|share/.test(k) ? pct(v) : /pct|index|lift|score/.test(k) ? fa(v) : money(v).replace(/ .*$/, "")) : esc(String(v ?? "")));
      return `<div class="table-wrap"><table class="tbl"><thead><tr>${cols.map((k) => `<th>${esc(L[k] || k)}</th>`).join("")}</tr></thead><tbody>${rows.slice(0, 15).map((r) => `<tr>${cols.map((k) => `<td>${cell(k, r[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }
    const flat = Object.entries(ev).filter(([, v]) => typeof v !== "object");
    return `<div class="kv">${flat.map(([k, v]) => `<div><span class="muted">${esc(k)}</span><b>${typeof v === "number" ? fa(v.toLocaleString("en-US")) : esc(String(v))}</b></div>`).join("")}</div>`;
  }

  function abBlock(i) {
    if (!i.baseline) return "";
    const b = i.baseline, r = i.result || {};
    const L = { product_units: "تعداد فروش", product_profit: "سود کالا", customer_sales: "فروش این مشتریان", attach_rate: "نرخ همراهی", avg_basket_size: "میانگین اقلام سبد", receivables_collected: "وصولی", void_rate: "نرخ ابطال", weekday_sales: "فروش روز اوج", purchase_over_best: "اضافه‌پرداخت خرید" };
    const kind = (i.metric || {}).metric;
    const f = (v) => (v == null ? "—" : (/rate/.test(kind) ? pct(v) : /units|basket/.test(kind) ? fa(Number(v).toFixed(1)) : money(v)));
    return `<div class="ab">
      <div class="ab-col"><span class="muted">قبل (${fa(b.days || 30)} روز)</span><b>${f(b.value)}</b><span class="muted">${b.from ? faDateTime(b.from, false) : ""}</span></div>
      <div class="ab-arrow">${i.measured_gain == null ? "…" : (Number(i.measured_gain) >= 0 ? "▲" : "▼")}</div>
      <div class="ab-col"><span class="muted">بعد (${fa(r.days || 0)} روز)</span><b>${f(r.value)}</b><span class="muted">${r.to ? faDateTime(r.to, false) : "در جریان"}</span></div>
      <div class="ab-sum ${Number(i.measured_gain) >= 0 ? "ok" : "err"}">${i.measured_gain == null ? "اندازه‌گیری هنوز داده کافی ندارد" : `اثر بر سود: ${money(i.measured_gain)}`}${r.change_pct != null ? ` (${fa(r.change_pct)}٪ تغییر ${L[kind] || ""})` : ""}</div>
    </div>`;
  }

  async function detail(id) {
    const i = await api(`/insights/${id}?narrate=true`);
    openModal(`<div class="ins-detail">
      <header><span class="ins-ic">${ico(KIND_ICON[i.kind] || "chart", 26)}</span><div><span class="ins-kind">${esc(i.label)} · ${STATUS[i.status] || i.status}</span><h3>${esc(i.title)}</h3></div></header>
      ${i.narrative ? `<div class="ins-narr">${esc(i.narrative).replace(/\n/g, "<br/>")}</div>` : `<p>${esc(i.body)}</p>`}
      ${abBlock(i)}
      <h4>اقدام‌ها</h4><ul class="ins-list">${(i.actions || []).map((a) => `<li>${esc(a.label)}</li>`).join("") || "<li class='muted'>—</li>"}</ul>
      <h4>شواهد (از داده‌های خود فروشگاه)</h4>${evidenceTable(i.evidence || {})}
      <div class="row" style="justify-content:flex-end;gap:8px;margin-top:12px">
        ${(i.status === "NEW" || i.status === "SNOOZED") && can("settings.manage") ? `<button class="btn btn-primary" id="ins-acc">اجرا کن</button>` : ""}
        <button class="btn" onclick="closeModal()">بستن</button></div>
    </div>`);
    const b = $("#ins-acc"); if (b) b.onclick = () => { closeModal(); acceptDialog(i); };
  }

  function acceptDialog(i) {
    openModal(`<div class="ins-detail">
      <h3>اجرای پیشنهاد</h3><p class="muted">${esc(i.title)}</p>
      <p>کدام اقدام‌ها انجام شود؟ همهٔ اقدام‌ها از مسیر عادی سیستم (جشنواره، کوپن، صف پیامک، قیمت‌گذاری، اعلان) ثبت می‌شوند و در لاگ قابل پیگیری‌اند.</p>
      <div class="ins-list">${(i.actions || []).map((a) => `<label class="row" style="gap:8px"><input type="checkbox" class="ins-act" value="${esc(a.type)}" checked/> ${esc(a.label)}</label>`).join("")}</div>
      <p class="muted" style="margin-top:8px">از لحظهٔ اجرا، شاخص «${esc(({ product_units: "تعداد فروش", product_profit: "سود کالا", customer_sales: "فروش مشتریان هدف", attach_rate: "نرخ همراهی دو کالا", avg_basket_size: "میانگین اقلام سبد", receivables_collected: "وصولی مطالبات", void_rate: "نرخ ابطال", weekday_sales: "فروش روز اوج", purchase_over_best: "اضافه‌پرداخت خرید" })[(i.metric || {}).metric] || "مربوطه")}» با ${fa((i.metric || {}).window_days || 30)} روز قبل مقایسه و اثر آن روی داشبورد نشان داده می‌شود.</p>
      <div class="row" style="justify-content:flex-end;gap:8px;margin-top:12px"><button class="btn btn-primary" id="ins-go">اجرا و شروع اندازه‌گیری</button><button class="btn" onclick="closeModal()">انصراف</button></div>
    </div>`);
    $("#ins-go").onclick = async () => {
      const acts = [...document.querySelectorAll(".ins-act:checked")].map((x) => x.value);
      $("#ins-go").disabled = true;
      try {
        const r = await api(`/insights/${i.id}/accept`, { method: "POST", body: JSON.stringify({ actions: acts }) });
        const failed = (r.executed || []).filter((x) => !x.ok);
        toast(failed.length ? `اجرا شد؛ ${fa(failed.length)} اقدام ناموفق: ${failed.map((x) => x.error).join("، ")}` : "اجرا شد — اندازه‌گیری آغاز شد", failed.length ? "err" : "ok");
        if (window.Sfx) Sfx.play("success");
        closeModal(); refreshCurrent();
      } catch (e) { toast(e.message, "err"); $("#ins-go").disabled = false; }
    };
  }

  function refreshCurrent() { if (state.view === "insights") RENDER.insights(); else if (state.view === "dashboard") RENDER.dashboard(); }

  // ---------------------------------------------------------------- insights view
  let insTab = "NEW";
  RENDER.insights = async () => {
    const v = $("#view");
    v.innerHTML = `<div class="ins-wrap">
      <section class="ins-hero" id="ins-hero"><div class="muted">در حال تحلیل…</div></section>
      <div class="set-tabs" id="ins-tabs"></div>
      <div id="ins-list" class="ins-grid"></div></div>`;
    $("#topbar-actions").innerHTML = "";
    $("#topbar-actions").append(el("button", { class: "btn btn-sm", text: "تحلیل دوباره", onclick: async () => { toast("در حال تحلیل داده‌ها…"); const r = await api("/insights/run", { method: "POST" }); toast(`${fa(r.created)} پیشنهاد جدید، ${fa(r.refreshed)} به‌روزرسانی`); RENDER.insights(); } }));
    $("#topbar-actions").append(el("button", { class: "btn btn-sm btn-ghost", text: "گزارش هفتگی", onclick: weeklyReport }));
    const [s, list] = await Promise.all([api("/insights/summary"), api(`/insights?status=${insTab}&limit=80`)]);
    if (!list.length && insTab === "NEW" && !s.accepted && !s.open) {
      // first visit: run analyzers
      try { await api("/insights/run", { method: "POST" }); return RENDER.insights(); } catch (_) { /* fallthrough */ }
    }
    hero(s, $("#ins-hero"));
    const tabs = [["NEW", "پیشنهادهای باز", s.open], ["ACCEPTED,MEASURED", "اجراشده و اثر", s.accepted], ["SNOOZED", "به تعویق"], ["DISMISSED,EXPIRED", "بایگانی"]];
    const t = $("#ins-tabs"); t.innerHTML = "";
    tabs.forEach(([k, l, n]) => t.append(el("button", { class: "set-tab" + (k === insTab ? " active" : ""), text: l + (n != null ? ` (${fa(n)})` : ""), onclick: () => { insTab = k; RENDER.insights(); } })));
    const grid = $("#ins-list"); grid.innerHTML = "";
    if (!list.length) grid.innerHTML = `<div class="card muted">موردی نیست. ${insTab === "NEW" ? "همه چیز مرتب است — تحلیل بعدی به‌طور خودکار انجام می‌شود." : ""}</div>`;
    list.forEach((i) => grid.append(card(i)));
  };

  function hero(s, host) {
    const share = s.share_of_month_profit ? ` (${fa(Math.round(s.share_of_month_profit * 100))}٪ سود ۳۰ روز اخیر)` : "";
    host.innerHTML = `
      <div class="ins-kpis">
        <div class="ins-kpi"><span class="muted">اثر اندازه‌گیری‌شدهٔ کل</span><b class="${s.total_gain >= 0 ? "ok" : "err"}">${money(s.total_gain)}</b><span class="muted">${fa(s.measured)} اقدام اندازه‌گیری‌شده</span></div>
        <div class="ins-kpi"><span class="muted">اثر ۳۰ روز اخیر</span><b>${money(s.month_gain)}</b><span class="muted">${share || "—"}</span></div>
        <div class="ins-kpi"><span class="muted">پیشنهادهای باز</span><b>${fa(s.open)}</b><span class="muted">برآورد ${money(s.expected_open)} / ماه</span></div>
        <div class="ins-kpi"><span class="muted">موتور تحلیل</span><b>${s.ai && s.ai.online ? "محلی + روایت ابری" : "محلی (آفلاین)"}</b><span class="muted">${s.ai && s.ai.online ? esc(s.ai.model) : "روایت متنی داخلی"}</span></div>
      </div>
      ${s.by_kind && s.by_kind.length ? `<div class="ins-bars">${s.by_kind.map((k) => `<div class="ins-bar"><span>${esc(k.label)}</span><i style="width:${Math.min(100, Math.round(Math.abs(k.gain) / Math.max(1, Math.abs(s.by_kind[0].gain)) * 100))}%" class="${k.gain >= 0 ? "" : "neg"}"></i><b>${money(k.gain)}</b></div>`).join("")}</div>` : ""}`;
  }

  async function weeklyReport() {
    openModal(`<div class="ins-detail"><h3>گزارش هفتگی هوش فروشگاه</h3><div id="wr" class="muted">در حال نوشتن…</div><div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn" onclick="closeModal()">بستن</button></div></div>`);
    try {
      const r = await api("/insights/report");
      $("#wr").className = "ins-narr"; $("#wr").innerHTML = esc(r.narrative).replace(/\n/g, "<br/>");
    } catch (e) { $("#wr").textContent = e.message; }
  }

  // ---------------------------------------------------------------- dashboard block
  window.InsightsDash = {
    async mount(host) {
      try {
        const s = await api("/insights/summary");
        const top = (s.top || []).slice(0, 4);
        host.innerHTML = `<h3>${ico("sparkle", 18)} هوش فروشگاه <span class="muted">اثر اقدام‌های اجراشده</span></h3>
          <div class="ins-dash">
            <div class="ins-dash-big"><span class="muted">اثر کل بر سود</span><b class="${s.total_gain >= 0 ? "ok" : "err"}">${money(s.total_gain)}</b><span class="muted">۳۰ روز اخیر ${money(s.month_gain)}${s.share_of_month_profit ? ` · ${fa(Math.round(s.share_of_month_profit * 100))}٪ سود دوره` : ""}</span></div>
            <div class="ins-dash-list">${top.map((t) => `<div class="ins-dash-row" onclick="go('insights')"><span>${esc(t.title)}</span><b class="${t.gain >= 0 ? "ok" : "err"}">${t.gain >= 0 ? "+" : ""}${money(t.gain)}</b></div>`).join("") || `<div class="muted">هنوز اقدامی اجرا نشده است.</div>`}</div>
          </div>
          <div class="row" style="justify-content:space-between;align-items:center;margin-top:8px"><span class="muted">${fa(s.open)} پیشنهاد باز · برآورد ${money(s.expected_open)} / ماه</span><button class="btn btn-sm btn-primary" onclick="go('insights')">مشاهدهٔ پیشنهادها</button></div>`;
      } catch (e) { host.innerHTML = `<h3>هوش فروشگاه</h3><div class="muted">${esc(e.message)}</div>`; }
    },
  };

  // ---------------------------------------------------------------- POS whisper
  let nudgeTimer = null, lastKey = "";
  window.PosNudges = {
    refresh() {
      const host = $("#pos-nudge"); if (!host || !window.posState) return;
      const ids = [...new Set(posState.cart.map((it) => it.product_id))];
      const key = ids.join(",");
      if (key === lastKey) return; lastKey = key;
      clearTimeout(nudgeTimer);
      if (!ids.length) { host.innerHTML = ""; host.classList.add("hidden"); return; }
      nudgeTimer = setTimeout(async () => {
        try {
          const r = await api("/insights/nudges", { method: "POST", body: JSON.stringify({ product_ids: ids }) });
          if (!r.length) { host.innerHTML = ""; host.classList.add("hidden"); return; }
          host.classList.remove("hidden");
          host.innerHTML = `<span class="nudge-ic">${ico("sparkle", 16)}</span><span class="nudge-txt">پیشنهاد به مشتری:</span>` +
            r.map((n) => `<button class="nudge-chip" title="چون ${esc(n.because)} در سبد است" onclick="PosNudges.add(${n.product_id})">${esc(n.name)}</button>`).join("");
        } catch (_) { host.classList.add("hidden"); }
      }, 350);
    },
    async add(pid) {
      try { const p = await api(`/products/${pid}`); await posAddResolved({ product_id: p.id, name: p.name, image_url: p.image_url, unit: p.unit }); }
      catch (e) { toast(e.message, "err"); }
    },
  };

  // ---------------------------------------------------------------- settings panels
  window.InsightsSettings = {
    async backup(body) {
      const card = el("div", { class: "card" });
      card.innerHTML = `<h3>${ico("shield", 18)} پشتیبان‌گیری</h3>
        <p class="muted">نسخهٔ پشتیبان یک فایل کامل از همهٔ داده‌های فروشگاه است (کالا، فاکتور، مشتری، حسابداری، تنظیمات). آن را روی فلش/تلگرام/گوشی نگه دارید.</p>
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <button class="btn btn-primary" id="bk-make">تهیهٔ نسخهٔ پشتیبان و دانلود</button>
          <label class="btn"><input type="file" id="bk-file" accept=".db" hidden/> بازیابی از فایل…</label>
        </div>
        <h4 style="margin-top:14px">نسخه‌های ذخیره‌شده روی این دستگاه</h4><div id="bk-list" class="muted">…</div>
        <div id="bk-demo" style="margin-top:16px"></div>`;
      body.append(card);
      const list = async () => {
        const rows = await api("/system/backups");
        $("#bk-list").innerHTML = rows.length ? `<table class="tbl"><tbody>${rows.slice(0, 12).map((r) => `<tr><td class="ltr">${esc(r.name)}</td><td>${faDateTime(r.created_at)}</td><td>${fa((r.size / 1048576).toFixed(1))} MB</td><td><a class="btn btn-sm" href="${API}/system/backups/${encodeURIComponent(r.name)}/download" data-bk="${esc(r.name)}">دانلود</a></td></tr>`).join("")}</tbody></table>` : "هنوز نسخه‌ای ساخته نشده است.";
        $("#bk-list").querySelectorAll("a[data-bk]").forEach((a) => a.onclick = (ev) => { ev.preventDefault(); download(`/system/backups/${encodeURIComponent(a.dataset.bk)}/download`, a.dataset.bk); });
      };
      $("#bk-make").onclick = async () => { $("#bk-make").disabled = true; try { await download("/system/backup/download", `supermarket_${Date.now()}.db`, "POST"); toast("نسخهٔ پشتیبان آماده شد"); list(); } catch (e) { toast(e.message, "err"); } $("#bk-make").disabled = false; };
      $("#bk-file").onchange = async (ev) => {
        const f = ev.target.files[0]; if (!f) return;
        if (!confirm(`همهٔ داده‌های فعلی با محتوای «${f.name}» جایگزین می‌شود (یک نسخهٔ ایمنی از وضعیت فعلی هم ذخیره می‌شود). ادامه می‌دهید؟`)) return;
        const fd = new FormData(); fd.append("file", f);
        try { const r = await api("/system/restore", { method: "POST", body: fd }); toast(r.detail || "بازیابی شد"); setTimeout(() => location.reload(), 1200); } catch (e) { toast(e.message, "err"); }
      };
      list();
      try {
        const d = await api("/system/demo");
        if (d.available) $("#bk-demo").innerHTML = `<div class="demo-box"><b>فروشگاه نمونه (یک سال داده واقعی‌نما)</b><p class="muted">برای آموزش و نمایش: ~۴۰ هزار فاکتور، ۱۴۰ مشتری، ۷۵ کالا، حسابداری کامل. ${d.is_demo ? "<b>هم‌اکنون فعال است.</b>" : ""}</p><button class="btn btn-sm" id="bk-demo-load">بارگذاری فروشگاه نمونه</button></div>`;
        const b = $("#bk-demo-load"); if (b) b.onclick = async () => { if (!confirm("داده‌های فعلی با فروشگاه نمونه جایگزین می‌شود (نسخهٔ ایمنی ذخیره می‌شود). ادامه؟")) return; try { await api("/system/demo/load", { method: "POST" }); toast("فروشگاه نمونه بارگذاری شد"); setTimeout(() => location.reload(), 1200); } catch (e) { toast(e.message, "err"); } };
      } catch (_) {}
    },
    async ai(body, allRows) {
      const g = (k) => { const r = allRows.find((x) => x.key === k); return r ? (r.value || "") : ""; };
      const card = el("div", { class: "card" });
      card.innerHTML = `<h3>${ico("sparkle", 18)} هوش فروشگاه</h3>
        <p class="muted">تحلیل‌ها همیشه روی همین دستگاه و آفلاین انجام می‌شود. «روایت ابری» اختیاری است: فقط متن گزارش‌ها را زیباتر می‌نویسد و هیچ شمارهٔ تلفن یا نام مشتری ارسال نمی‌شود.</p>
        <div class="form-grid">
          <label>موتور تحلیل<select id="ai-en"><option value="true" ${g("insights.enabled") !== "false" ? "selected" : ""}>فعال</option><option value="false" ${g("insights.enabled") === "false" ? "selected" : ""}>غیرفعال</option></select></label>
          <label>فاصلهٔ تحلیل (ساعت)<input id="ai-int" type="number" min="1" max="48" value="${esc(g("insights.interval_hours") || "6")}"/></label>
          <label>پیشنهاد لحظه‌ای در صندوق<select id="ai-nd"><option value="true" ${g("insights.pos_nudges") === "true" ? "selected" : ""}>نمایش</option><option value="false" ${g("insights.pos_nudges") !== "true" ? "selected" : ""}>خاموش</option></select></label>
          <label>روایت ابری<select id="ai-pr"><option value="" ${!g("ai.provider") ? "selected" : ""}>خاموش (متن داخلی)</option><option value="openai_compatible" ${g("ai.provider") === "openai_compatible" ? "selected" : ""}>سرویس سازگار با OpenAI</option></select></label>
          <label>آدرس سرویس (Base URL)<input id="ai-url" class="ltr" placeholder="https://api.openai.com/v1" value="${esc(g("ai.base_url"))}"/></label>
          <label>کلید API<input id="ai-key" class="ltr" type="password" placeholder="${g("ai.api_key") ? "•••••• (ذخیره‌شده)" : "sk-…"}"/></label>
          <label>مدل<input id="ai-model" class="ltr" placeholder="gpt-4o-mini" value="${esc(g("ai.model"))}"/></label>
        </div>
        <p class="muted" style="margin-top:8px">هر سرویس با API سازگار با OpenAI کار می‌کند (OpenAI، OpenRouter، Groq، یا مدل محلی مثل Ollama روی همین شبکه). هزینهٔ آن بر عهدهٔ شماست و بدون آن هم همهٔ امکانات کار می‌کند.</p>
        <div class="row" style="gap:8px;margin-top:10px"><button class="btn btn-primary" id="ai-save">ذخیره</button><button class="btn" id="ai-test">تست روایت</button></div>`;
      body.append(card);
      $("#ai-save").onclick = async () => {
        const upd = { "insights.enabled": $("#ai-en").value, "insights.interval_hours": $("#ai-int").value, "insights.pos_nudges": $("#ai-nd").value, "ai.provider": $("#ai-pr").value, "ai.base_url": $("#ai-url").value.trim(), "ai.model": $("#ai-model").value.trim() };
        if ($("#ai-key").value) upd["ai.api_key"] = $("#ai-key").value.trim();
        try { for (const [k, v] of Object.entries(upd)) await api("/settings", { method: "PUT", body: JSON.stringify({ key: k, value: v, is_secret: k === "ai.api_key" }) }); toast("ذخیره شد"); } catch (e) { toast(e.message, "err"); }
      };
      $("#ai-test").onclick = async () => { try { const r = await api("/insights/report"); openModal(`<div class="ins-detail"><h3>نمونهٔ روایت</h3><div class="ins-narr">${esc(r.narrative).replace(/\n/g, "<br/>")}</div><div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn" onclick="closeModal()">بستن</button></div></div>`); } catch (e) { toast(e.message, "err"); } };
    },
  };

  async function download(path, name, method = "GET") {
    const res = await fetch(API + path, { method, headers: { Authorization: "Bearer " + state.token } });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    const blob = await res.blob();
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }
})();
