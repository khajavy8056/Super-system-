/* v3.0 — «هوش فروشگاه» (Store Intelligence): insights view, dashboard impact
 * block, POS whisper-suggestions, Backup + AI settings panels.
 * Depends on app.js globals: api, $, el, esc, money, fmt, icon, toast, openModal,
 * closeModal, faDateTime, can, go, RENDER, NAV, NAV_GROUPS, posState. */
(function () {
  const fa = (n) => String(n).replace(/\d/g, (x) => "۰۱۲۳۴۵۶۷۸۹"[x]);
  const pct = (x) => fa(Math.round((Number(x) || 0) * 100)) + "٪";
  const KIND_ICON = { CROSS_SELL: "gift", EXPIRY_LADDER: "clock", DEAD_STOCK: "warehouse", VELOCITY: "trend", SUPPLIER: "inbox", CASHFLOW: "cash",
    VIP: "star", CHURN: "user", BASKET_NUDGE: "pos", PRICE_GAP: "tag", LOSS_PREV: "shield", SEASON: "chart", VISIT_PATTERN: "user" };
  // v3.5 — group → icon fallback for the 46 PRO kinds
  const GROUP_ICON = { customer: "user", stock: "warehouse", price: "tag", ops: "shield", growth: "trend", daily: "sparkle" };
  const iconOf = (i) => KIND_ICON[i.kind] || GROUP_ICON[i.group] || "chart";
  const CONF = { high: "بالا", medium: "متوسط", low: "پایین (اولین تجربه)", "n/a": "—" };
  const PRIO = { 1: ["فوری", "badge-red"], 2: ["مهم", "badge-amber"], 3: ["پیشنهاد", "badge-green"], 4: ["نکته", "badge-gray"] };
  const STATUS = { NEW: "جدید", ACCEPTED: "در حال اندازه‌گیری", MEASURED: "اندازه‌گیری‌شده", DISMISSED: "ردشده", SNOOZED: "به تعویق", EXPIRED: "منقضی" };
  const ico = (k, s) => (typeof ICONS !== "undefined" && ICONS[k]) ? icon(k, s) : icon("chart", s);

  // ---------------------------------------------------------------- nav registration
  if (typeof NAV !== "undefined" && !NAV.some((n) => n[0] === "insights")) {
    NAV.splice(1, 0, ["insights", "هوش فروشگاه", "reports.view", "sparkle"]);
    const grp = NAV_GROUPS.find((g) => g[0] === "رشد و تحلیل");
    if (grp) grp[1].splice(1, 0, "insights");
  }
  // v3.1: the planning view is reached from the insights page / dashboard (title only, not a separate nav entry)
  if (typeof NAV !== "undefined" && !NAV.some((n) => n[0] === "insightsPlan")) NAV.push(["insightsPlan", "برنامه‌ریزی و پیش‌بینی سود", "reports.view", "chart"]);
  if (typeof ICONS !== "undefined") {
    ICONS.sparkle = ICONS.sparkle || '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>';
    ICONS.star = ICONS.star || '<path d="M12 3l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 18l-5.9 3 1.2-6.5L2.5 9.9 9.1 9z"/>';
    ICONS.tag = ICONS.tag || '<path d="M20 12l-8 8-9-9V4h7z"/><circle cx="7.5" cy="7.5" r="1.5"/>';
    ICONS.clock = ICONS.clock || '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>';
  }

  // ---------------------------------------------------------------- shared card
  function gainLine(i) {
    if (i.status === "MEASURED" || (i.status === "ACCEPTED" && i.measured_gain != null)) {
      const g = Number(i.measured_gain || 0), r = i.result || {}, gr = r.profit_pct_adj != null ? r.profit_pct_adj : r.profit_pct;
      return `<span class="ins-gain ${g >= 0 ? "ok" : "err"}">${g >= 0 ? "▲" : "▼"} ${gr != null ? `رشد سود ${pctTxt(gr)} · ` : ""}اثر واقعی: ${money(Math.abs(g))}</span>`;
    }
    const fc = (i.evidence || {}).forecast;
    if (fc && Number(fc.gain_month) > 0) return `<span class="ins-gain muted">پیش‌بینی سود ماهانه: <b>${money(fc.gain_month)}</b> <span class="ins-band">(${money(fc.low_month)} تا ${money(fc.high_month)}) · اطمینان ${CONF[fc.confidence] || "—"}</span>`;
    return Number(i.expected_gain) > 0 ? `<span class="ins-gain muted">برآورد اثر: ${money(i.expected_gain)} / ماه</span>` : "";
  }

  function card(i, compact) {
    const [pl, pc] = PRIO[i.priority] || PRIO[3];
    const c = el("article", { class: "ins-card ins-" + i.kind.toLowerCase() + (i.priority === 1 ? " ins-urgent" : "") });
    c.innerHTML = `
      <header><span class="ins-ic">${ico(iconOf(i), 20)}</span>
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

  const METRIC_L = { product_units: "تعداد فروش", product_profit: "سود کالا", customer_sales: "فروش این مشتریان", attach_rate: "نرخ هم‌خرید", avg_basket_size: "میانگین فاکتور", receivables_collected: "وصولی", void_rate: "نرخ ابطال", weekday_sales: "فروش روز اوج", purchase_over_best: "اضافه‌پرداخت خرید", availability: "روزهای موجود بودن", stockout_days: "روزهای بدون موجودی" };
  const PALETTE = ["#3dd6c4", "#7c5cff", "#f5a524", "#e5484d", "#2f9e6b", "#3b82f6", "#d946ef", "#0ea5e9"];
  const pctTxt = (v, d = 1) => (v == null ? "—" : (v >= 0 ? "+" : "−") + fa(Math.abs(Number(v)).toFixed(d)) + "٪");

  /** v3.2 — measured effect: percent growth first, then toman, then the daily before/after chart. */
  function abBlock(i) {
    if (!i.baseline) return "";
    const b = i.baseline, r = i.result || {};
    const kind = (i.metric || {}).metric;
    const f = (v) => (v == null ? "—" : (/rate/.test(kind) ? pct(v) : /availability/.test(kind) ? fa(v) + "٪" : /units|basket|stockout/.test(kind) ? fa(Number(v).toFixed(1)) : money(v)));
    const g = Number(i.measured_gain || 0), growth = r.profit_pct_adj != null ? r.profit_pct_adj : r.profit_pct;
    const pending = i.measured_gain == null;
    const daily = r.daily || {}, bef = daily.before || [], aft = daily.after || [];
    const chart = (bef.length + aft.length) >= 4 ? svgLine([
      { name: "سود روزانه — قبل", color: "#8a94a6", points: [...bef, ...aft.map(() => null)], area: true },
      { name: "سود روزانه — بعد از اجرا", color: g >= 0 ? "#2f9e6b" : "#e5484d", points: [...bef.map(() => null), ...aft], area: true, width: 2.6 },
    ], { labels: [...bef.map((_, k) => (k === 0 ? "قبل" : null)), ...aft.map((_, k) => (k === 0 ? "اجرا ▶" : k === aft.length - 1 ? "امروز" : null))], height: 150 }) : "";
    return `<div class="ab2 ${pending ? "" : g >= 0 ? "ok" : "err"}">
      <div class="ab2-kpis">
        <div><span class="muted">رشد سود</span><b class="${growth == null ? "" : growth >= 0 ? "ok" : "err"}">${pending ? "…" : pctTxt(growth)}</b><span class="muted">${r.control_ratio && r.control_ratio !== 1 ? `پس از حذف روند فروشگاه (${fa(Math.round((r.control_ratio - 1) * 100))}٪)` : "نسبت به قبل از اجرا"}</span></div>
        <div><span class="muted">اثر بر سود</span><b class="${pending ? "" : g >= 0 ? "ok" : "err"}">${pending ? "در حال سنجش" : (g >= 0 ? "+" : "−") + money(Math.abs(g))}</b><span class="muted">${r.projected_month != null ? "برآورد ماهانه " + money(r.projected_month) : ""}</span></div>
        <div><span class="muted">${METRIC_L[kind] || "شاخص"} — قبل</span><b>${f(b.value)}</b><span class="muted">${fa(b.window_days || b.days || 28)} روز · ${money(Math.round(r.base_profit_per_day || 0))}/روز</span></div>
        <div><span class="muted">${METRIC_L[kind] || "شاخص"} — بعد</span><b>${f(r.value)}</b><span class="muted">${fa(r.elapsed_days || 0)} روز · ${money(Math.round(r.post_profit_per_day || 0))}/روز${r.change_pct != null ? ` · ${pctTxt(r.change_pct)}` : ""}</span></div>
      </div>
      ${chart}
      ${pending ? `<p class="muted">برای سنجش دقیق حداقل یک روز فروش پس از اجرا لازم است.</p>` : ""}
    </div>`;
  }

  /** v3.2 — evidence rendered per kind with charts instead of raw JSON. */
  function evidenceBlock(i) {
    const ev = i.evidence || {}, k = i.kind;
    const parts = [];
    if (k === "VELOCITY") {
      const cover = Number(ev.days_cover || 0);
      parts.push(`<div class="ev-kpis"><div><span class="muted">سرعت فروش</span><b>${fa((ev.velocity_per_day * 7).toFixed(1))}</b><span class="muted">عدد در هفته</span></div><div><span class="muted">موجودی</span><b>${fa(ev.stock)}</b><span class="muted">${fa(ev.sale_days)} روز فروش از ۲۸</span></div><div><span class="muted">پوشش</span><b class="${cover <= 2 ? "err" : "warn"}">${fa(cover)} روز</b></div><div><span class="muted">سفارش پیشنهادی</span><b class="ok">${fa(ev.reorder_qty)}</b><span class="muted">عدد (۲ هفته)</span></div></div>`);
      parts.push(svgBars([{ label: "موجودی فعلی", value: Number(ev.stock), color: "#e5484d" }, { label: "فروش ۲ هفته", value: Number(ev.velocity_per_day) * 14, color: "#8a94a6" }, { label: "بعد از سفارش", value: Number(ev.stock) + Number(ev.reorder_qty), color: "#2f9e6b" }], { unit: "عدد" }));
    } else if (k === "DEAD_STOCK") {
      parts.push(`<div class="ev-kpis"><div><span class="muted">تعداد راکد</span><b>${fa(ev.qty)}</b></div><div><span class="muted">سرمایهٔ قفل‌شده</span><b class="err">${money(ev.locked_value)}</b></div><div><span class="muted">عمر در انبار</span><b>${fa(ev.age_days)} روز</b></div><div><span class="muted">فروش ۶۰ روز</span><b>${fa(ev.sold_60d)}</b></div></div>`);
      parts.push(svgBars([{ label: "قفل در این کالا", value: Number(ev.locked_value), color: "#e5484d" }, { label: "کل کالاهای راکد", value: Number(ev.total_locked), color: "#f5a524" }]));
    } else if (k === "EXPIRY_LADDER") {
      parts.push(`<div class="ev-kpis"><div><span class="muted">تا انقضا</span><b class="err">${fa(ev.days_left)} روز</b></div><div><span class="muted">موجودی</span><b>${fa(ev.qty)}</b></div><div><span class="muted">مازاد (ضایعات)</span><b class="err">${fa(ev.surplus)}</b></div><div><span class="muted">در خطر</span><b class="err">${money(ev.at_risk)}</b></div></div>`);
      if (Array.isArray(ev.ladder)) parts.push(svgBars(ev.ladder.map((l, n) => ({ label: `از روز ${fa(l.from_day)} — ${fa(l.percent)}٪ تخفیف`, value: Number(l.price), color: PALETTE[n % PALETTE.length] }))));
    } else if (k === "CROSS_SELL") {
      parts.push(`<div class="ev-kpis"><div><span class="muted">هم‌خرید</span><b>${fa(ev.pair_count)}</b><span class="muted">از ${fa(ev.invoices)} فاکتور</span></div><div><span class="muted">اطمینان</span><b>${pct(ev.confidence)}</b></div><div><span class="muted">ضریب هم‌خرید</span><b class="ok">${fa(ev.lift)}×</b></div><div><span class="muted">پشتیبانی</span><b>${pct(ev.support)}</b></div></div>`);
      parts.push(donut([{ label: "با هم", value: Number(ev.pair_count), color: "#3dd6c4" }, { label: "جدا", value: Math.max(0, Number(ev.invoices) - Number(ev.pair_count)), color: "#2a3140" }], `${pct(Number(ev.pair_count) / Math.max(1, Number(ev.invoices)))} فاکتورها`));
    } else if (k === "CASHFLOW" && Array.isArray(ev.timeline)) {
      parts.push(`<div class="ev-kpis"><div><span class="muted">فروش روزانه</span><b>${money(ev.avg_daily_sales)}</b></div><div><span class="muted">هزینه + خرید روزانه</span><b>${money(Number(ev.expense_daily) + Number(ev.purchase_daily))}</b></div><div><span class="muted">کمترین مانده</span><b class="err">${money(ev.lowest)}</b><span class="muted">${esc(ev.lowest_day || "")}</span></div><div><span class="muted">چک‌های صادره</span><b>${fa(Array.isArray(ev.cheques_out) ? ev.cheques_out.length : ev.cheques_out)}</b></div></div>`);
      parts.push(svgLine([{ name: "ماندهٔ نقد پیش‌بینی‌شده", color: "#f5a524", points: ev.timeline.map((t) => Number(t.balance)), area: true }], { labels: ev.timeline.map((t, n) => (n % 6 === 0 ? faMonthDay(t.day) : null)), height: 160 }));
    } else if (k === "VIP" && Array.isArray(ev.rows)) {
      parts.push(donut([{ label: `${fa(ev.rows.length)} مشتری برتر`, value: Number(ev.profit_share), color: "#f5a524" }, { label: "بقیهٔ مشتریان", value: 1 - Number(ev.profit_share), color: "#2a3140" }], `${pct(ev.profit_share)} سود`));
      parts.push(svgBars(ev.rows.slice(0, 8).map((r, n) => ({ label: r.name, value: Number(r.profit), color: PALETTE[n % PALETTE.length] }))));
    } else if (k === "CHURN" && Array.isArray(ev.rows)) {
      parts.push(svgBars(ev.rows.slice(0, 8).map((r) => ({ label: `${r.name} — ${fa(r.silent_days)} روز غایب (معمولاً هر ${fa(r.typical_gap)})`, value: Number(r.monthly_profit), color: "#e5484d" }))));
    } else if (k === "VISIT_PATTERN" && Array.isArray(ev.rows)) {
      parts.push(`<div class="ev-kpis"><div><span class="muted">در نوبت خرید</span><b>${fa(ev.rows.length)}</b><span class="muted">مشتری</span></div><div><span class="muted">شماره دارند</span><b>${fa(ev.with_phone)}</b></div><div><span class="muted">سود ماهانهٔ گروه</span><b class="ok">${money(ev.monthly_profit)}</b></div></div>`);
      parts.push(visitTable(ev.rows.slice(0, 12)));
    } else if (k === "BASKET_NUDGE" && Array.isArray(ev.rules)) {
      parts.push(svgBars(ev.rules.slice(0, 8).map((r, n) => ({ label: `${r.if_name} ← ${r.then_name}`, value: Number(r.confidence) * 100, color: PALETTE[n % PALETTE.length] })), { unit: "٪" }));
    } else if (k === "SEASON" && ev.weekday_avg) {
      parts.push(svgBars(Object.entries(ev.weekday_avg).map(([d, v], n) => ({ label: d, value: Number(v), color: d === ev.peak ? "#f5a524" : "#3b82f6" }))));
    } else if (k === "SUPPLIER" && Array.isArray(ev.table)) {
      parts.push(svgBars(ev.table.map((r) => ({ label: r.name, value: Number(r.score), color: r.score >= 70 ? "#2f9e6b" : r.score >= 50 ? "#f5a524" : "#e5484d" })), { unit: "امتیاز" }));
    } else if (k === "PRICE_GAP") {
      parts.push(`<div class="ev-kpis"><div><span class="muted">قیمت خرید</span><b>${money(ev.buy)}</b></div><div><span class="muted">قیمت فروش فعلی</span><b class="err">${money(ev.sell || ev.sell_price)}</b></div>${ev.margin != null ? `<div><span class="muted">حاشیه</span><b class="err">${pct(ev.margin)}</b></div>` : ""}${ev.consumer ? `<div><span class="muted">قیمت مصرف‌کننده</span><b>${money(ev.consumer)}</b></div>` : ""}</div>`);
    } else if (k === "LOSS_PREV" && Array.isArray(ev.peers)) {
      parts.push(svgBars(ev.peers.map((r) => ({ label: r.name, value: Number(r.void_rate) * 100, color: r.user_id === (ev.row || {}).user_id ? "#e5484d" : "#8a94a6" })), { unit: "٪ ابطال" }));
    }
    parts.push(evidenceTable(ev));
    return parts.join("");
  }

  function donut(slices, centerText) {
    const total = slices.reduce((a, s) => a + Math.max(0, s.value), 0) || 1; let acc = 0; const R = 44, C = 2 * Math.PI * R;
    const segs = slices.map((s) => { const frac = Math.max(0, s.value) / total, off = acc; acc += frac; return `<circle r="${R}" cx="60" cy="60" fill="none" stroke="${s.color}" stroke-width="16" stroke-dasharray="${(frac * C).toFixed(2)} ${C.toFixed(2)}" stroke-dashoffset="${(-off * C).toFixed(2)}" transform="rotate(-90 60 60)"/>`; }).join("");
    return `<div class="donut"><svg viewBox="0 0 120 120">${segs}<text x="60" y="64" text-anchor="middle" class="t big">${esc(centerText || "")}</text></svg><div class="legend">${slices.map((s) => `<span class="lg"><i style="background:${s.color}"></i>${esc(s.label)}</span>`).join("")}</div></div>`;
  }

  function visitTable(rows) {
    return `<div class="table-wrap"><table class="tbl"><thead><tr><th>مشتری</th><th>نوبت بعدی</th><th>معمولاً</th><th>خرید همیشگی</th><th>سود ماهانه</th></tr></thead><tbody>${rows.map((r) => `<tr><td><b>${esc(r.name)}</b><div class="muted">${fa(r.visits)} خرید · هر ${fa(r.typical_gap)} روز · نظم ${pct(r.regularity)}</div></td><td>${r.due_in <= 0 ? `<span class="badge ok">امروز</span>` : `<span class="badge">${fa(r.due_in)} روز دیگر</span>`}<div class="muted">${faMonthDay(r.predicted)}</div></td><td>${esc(r.usual_weekday)}‌ها ساعت ${fa(r.usual_hour)}</td><td>${(r.usual_items || []).slice(0, 3).map((x) => esc(x.name)).join("، ")}</td><td>${money(r.monthly_profit)}</td></tr>`).join("")}</tbody></table></div>`;
  }

  // ---------------------------------------------------------------- v3.2 customer purchase-pattern view
  RENDER.insightsCustomers = async () => {
    const v = $("#view");
    v.innerHTML = `<div class="ins-wrap"><section class="ins-hero"><h2 style="margin:0">پیش‌بینی خرید مشتریان</h2><p class="muted">از فاصلهٔ خریدهای هر مشتری ثابت، نوبت بعدی‌اش پیش‌بینی می‌شود؛ درست قبل از نوبت، با یک پیامک شخصی («کالای همیشگی‌تان رسیده») صدایش کنید.</p><div id="vc-kpis" class="ins-kpis"></div></section><div class="card" id="vc-chart"></div><div class="card" id="vc-table">در حال تحلیل…</div></div>`;
    $("#topbar-actions").innerHTML = "";
    $("#topbar-actions").append(el("button", { class: "btn btn-sm", text: "هوش فروشگاه", onclick: () => go("insights") }));
    const d = await api("/insights/customers/patterns?days=7");
    const rows = d.rows || [];
    const today = rows.filter((r) => r.due_in <= 0).length, wk = rows.length, withPhone = rows.filter((r) => r.phone).length;
    $("#vc-kpis").innerHTML = `<div class="ins-kpi"><span class="muted">در نوبت امروز</span><b class="ok">${fa(today)}</b><span class="muted">مشتری</span></div><div class="ins-kpi"><span class="muted">۷ روز آینده</span><b>${fa(wk)}</b><span class="muted">مشتری ثابت</span></div><div class="ins-kpi"><span class="muted">قابل پیامک</span><b>${fa(withPhone)}</b><span class="muted">شماره دارند</span></div><div class="ins-kpi"><span class="muted">سود ماهانهٔ این گروه</span><b>${money(rows.reduce((a, r) => a + Number(r.monthly_profit || 0), 0))}</b></div>`;
    const byDay = {}; rows.forEach((r) => { const k = Math.max(0, r.due_in); byDay[k] = (byDay[k] || 0) + 1; });
    $("#vc-chart").innerHTML = `<h3>چند مشتری در هر روز نوبتشان است؟</h3>` + svgBars([0, 1, 2, 3, 4, 5, 6, 7].map((k) => ({ label: k === 0 ? "امروز" : `${fa(k)} روز دیگر`, value: byDay[k] || 0, color: PALETTE[k % PALETTE.length] })), { unit: "نفر" });
    $("#vc-table").innerHTML = rows.length ? visitTable(rows) : `<div class="muted">هنوز الگوی منظمی پیدا نشده — با ثبت مشتری روی فاکتورها، این صفحه پر می‌شود.</div>`;
  };
  if (typeof NAV !== "undefined" && !NAV.some((n) => n[0] === "insightsCustomers")) NAV.push(["insightsCustomers", "پیش‌بینی خرید مشتریان", "reports.view", "user"]);

  // ---------------------------------------------------------------- v3.1 forecast / planning
  function svgLine(series, opts) {
    // series: [{name, color, points:[y...], dash?}], x labels = opts.labels; returns an SVG string (responsive)
    const W = 640, H = opts.height || 200, P = { l: 8, r: 8, t: 14, b: 26 };
    const all = series.flatMap((s) => s.points).filter((v) => v != null);
    const max = Math.max(1, ...all), min = Math.min(0, ...all);
    const n = Math.max(2, ...series.map((s) => s.points.length));
    const x = (i) => P.l + (W - P.l - P.r) * i / (n - 1);
    const y = (v) => P.t + (H - P.t - P.b) * (1 - (v - min) / (max - min || 1));
    const grid = [0, .25, .5, .75, 1].map((g) => { const v = min + (max - min) * g; return `<line x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}" class="g"/><text x="${W - P.r}" y="${y(v) - 3}" class="t" text-anchor="end">${moneyShort(v)}</text>`; }).join("");
    const paths = series.map((s) => {
      const d = s.points.map((v, i) => (v == null ? "" : `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join(" ");
      const area = s.area ? `<path d="${d} L${x(s.points.length - 1).toFixed(1)},${y(min)} L${x(0)},${y(min)} Z" fill="${s.color}" opacity=".08"/>` : "";
      return `${area}<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2.2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
    }).join("");
    const band = opts.band ? (() => { const [lo, hi] = opts.band; const up = hi.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" "); const dn = lo.map((v, i) => `L${x(lo.length - 1 - i).toFixed(1)},${y(lo[lo.length - 1 - i]).toFixed(1)}`).join(" "); return `<path d="${up} ${dn} Z" fill="${opts.bandColor || "#7c5cff"}" opacity=".12"/>`; })() : "";
    const labels = (opts.labels || []).map((l, i) => (l ? `<text x="${x(i)}" y="${H - 8}" class="t" text-anchor="middle">${esc(l)}</text>` : "")).join("");
    const legend = series.map((s) => `<span class="lg"><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("");
    return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}${band}${paths}${labels}</svg><div class="legend">${legend}</div></div>`;
  }
  function svgBars(rows, opts) {
    const W = 640, H = (opts && opts.height) || Math.max(90, rows.length * 30 + 10);
    const max = Math.max(1, ...rows.map((r) => Math.abs(r.value)));
    const lw = 220;
    return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${rows.map((r, i) => {
      const w = (W - lw - 110) * Math.abs(r.value) / max, yy = 8 + i * 30;
      return `<text x="${W - 4}" y="${yy + 15}" class="t" text-anchor="end">${esc(r.label)}</text><rect x="${W - lw - 8 - w}" y="${yy}" width="${w}" height="20" rx="6" fill="${r.value >= 0 ? (r.color || "#3dd6c4") : "#e5484d"}"/><text x="${W - lw - 14 - w}" y="${yy + 15}" class="t" text-anchor="end">${opts && opts.unit ? fa(Math.round(r.value * 10) / 10) + " " + opts.unit : moneyShort(r.value)}</text>`;
    }).join("")}</svg></div>`;
  }
  function moneyShort(v) { v = Number(v) || 0; const a = Math.abs(v); const s = a >= 1e9 ? fa((v / 1e9).toFixed(1)) + " میلیارد" : a >= 1e6 ? fa((v / 1e6).toFixed(1)) + " میلیون" : a >= 1e3 ? fa(Math.round(v / 1e3)) + " هزار" : fa(Math.round(v)); return s; }
  const faMonthDay = (iso) => { try { return faDateTime(iso + "T00:00:00", false).replace(/^\S+\s/, "").slice(0, 8); } catch (_) { return iso.slice(5); } };

  function predictBlock(i) {
    const p = i.prediction; if (!p || !(p.gain_month > 0)) return "";
    const pts = [0, ...p.path.map((x) => x.cum_gain)], lo = [0, ...p.path.map((x) => x.cum_low)], hi = [0, ...p.path.map((x) => x.cum_high)];
    return `<div class="predict"><h4>اگر این پیشنهاد اجرا شود…</h4>
      <div class="predict-kpis">
        <div><span class="muted">سود اضافه در ماه</span><b class="ok">+${money(p.gain_month)}</b><span class="muted">بازهٔ ${money(p.low_month)} تا ${money(p.high_month)}</span></div>
        <div><span class="muted">رشد سود ماهانهٔ فروشگاه</span><b>${p.growth_pct != null ? fa(p.growth_pct) + "٪" : "—"}</b><span class="muted">پایهٔ ماهانه ${money(p.store_profit_month)}</span></div>
        <div><span class="muted">جمع ۹۰ روز</span><b>+${money(p.gain_90d)}</b><span class="muted">با شروع تدریجی در هفتهٔ اول</span></div>
        <div><span class="muted">اطمینان پیش‌بینی</span><b>${CONF[p.confidence] || "—"}</b><span class="muted">${p.history_n ? `از ${fa(p.history_n)} اقدام مشابه اندازه‌گیری‌شده (ضریب ${fa(p.ratio)})` : "هنوز اقدام مشابهی سنجیده نشده"}</span></div>
      </div>
      ${svgLine([{ name: "سود تجمعی اضافه", color: "#7c5cff", points: pts, area: true }], { labels: ["امروز", ...p.path.map((x) => `روز ${fa(x.day)}`)], band: [lo, hi], height: 170 })}
      <p class="muted">این پیش‌بینی با هر اقدام اجراشده دقیق‌تر می‌شود: اثر واقعی اندازه‌گیری و ضریب همین نوع پیشنهاد اصلاح می‌گردد.</p></div>`;
  }

  RENDER.insightsPlan = async () => {
    const v = $("#view");
    v.innerHTML = `<div class="ins-wrap"><section class="ins-hero" id="pl-hero"><div class="muted">در حال محاسبهٔ پیش‌بینی…</div></section><div id="pl-body"></div></div>`;
    $("#topbar-actions").innerHTML = "";
    $("#topbar-actions").append(el("button", { class: "btn btn-sm", text: "پیشنهادها", onclick: () => go("insights") }));
    $("#topbar-actions").append(el("button", { class: "btn btn-sm btn-ghost", text: "بازآموزی مدل", onclick: async () => { await api("/insights/plan/learn", { method: "POST" }); toast("ضرایب از اندازه‌گیری‌های واقعی به‌روز شد"); RENDER.insightsPlan(); } }));
    let p; try { p = await api("/insights/plan?horizon=90"); } catch (e) { $("#pl-hero").innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    const m = p.model, b = p.baseline, pl = p.plan;
    $("#pl-hero").innerHTML = `<div class="ins-kpis">
      <div class="ins-kpi"><span class="muted">سود ماهانهٔ پایه (روند فعلی)</span><b>${money(b.profit_month)}</b><span class="muted">روند ${m.trend_pct_per_week >= 0 ? "+" : ""}${fa(m.trend_pct_per_week)}٪ در هفته · ${fa(m.weeks_of_history)} هفته سابقه</span></div>
      <div class="ins-kpi"><span class="muted">با اجرای ${fa(pl.open)} پیشنهاد باز</span><b class="ok">${money(pl.profit_month)}</b><span class="muted">+${money(pl.gain_month)} (${pl.growth_pct != null ? fa(pl.growth_pct) + "٪" : "—"}) در ماه</span></div>
      <div class="ins-kpi"><span class="muted">بازهٔ اطمینان ماهانه</span><b>${money(pl.low_month)} – ${money(pl.high_month)}</b><span class="muted">۹۰ روز: +${money(pl.gain_horizon)}</span></div>
      <div class="ins-kpi"><span class="muted">دقت مدل تا امروز</span><b>${m.direction_accuracy != null ? fa(Math.round(m.direction_accuracy * 100)) + "٪ جهت درست" : "—"}</b><span class="muted">${m.measured_count ? `${fa(m.measured_count)} اقدام سنجیده · خطای میانگین ${m.mean_abs_pct_error != null ? fa(m.mean_abs_pct_error) + "٪" : "—"}` : "هنوز اقدامی سنجیده نشده"}</span></div></div>`;
    const wk = p.history_weeks.slice(-14), fc = p.forecast;
    const labels = [...wk.map((w, i) => (i % 2 ? "" : faMonthDay(w.week_start))), ...fc.map((f, i) => (i % 2 ? "" : faMonthDay(f.day)))];
    const hist = [...wk.map((w) => w.profit), ...fc.map(() => null)], base = [...wk.map((w, i) => (i === wk.length - 1 ? w.profit : null)), ...fc.map((f) => f.week_baseline)], plan = [...wk.map((w, i) => (i === wk.length - 1 ? w.profit : null)), ...fc.map((f) => f.week_plan)];
    const cumL = [...wk.map(() => null), ...fc.map((f) => f.cum_low)], cumH = [...wk.map(() => null), ...fc.map((f) => f.cum_high)];
    const body = $("#pl-body");
    body.innerHTML = `
      <div class="card"><h3>سود هفتگی: گذشته، روند پایه و برنامه</h3>
        ${svgLine([{ name: "سود واقعی هر هفته", color: "#3dd6c4", points: hist, area: true }, { name: "ادامهٔ روند فعلی", color: "#8a94a6", points: base, dash: "6 5" }, { name: "با اجرای پیشنهادها", color: "#7c5cff", points: plan, width: 2.8 }], { labels, height: 230 })}
        <p class="muted">مدل: روند خطی هفتگی × الگوی روزهای هفته (شاخص روزها: ${m.weekday_index.map((x, i) => `${["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"][i]} ${fa(x)}`).join("، ")}).</p></div>
      <div class="card"><h3>سود تجمعی ۹۰ روز آینده — پایه در برابر برنامه (با بازهٔ اطمینان)</h3>
        ${svgLine([{ name: "پایه (روند فعلی)", color: "#8a94a6", points: fc.map((f) => f.cum_baseline), dash: "6 5" }, { name: "برنامه (پیشنهادها اجرا شود)", color: "#7c5cff", points: fc.map((f) => f.cum_plan), area: true }], { labels: fc.map((f, i) => (i % 2 ? "" : faMonthDay(f.day))), band: [fc.map((f) => f.cum_low), fc.map((f) => f.cum_high)], height: 220 })}</div>
      <div class="card"><h3>سهم هر نوع پیشنهاد در سود ماهانهٔ برنامه</h3>${p.by_kind.length ? svgBars(p.by_kind.map((k) => ({ label: `${k.label} (${fa(k.count)})`, value: k.gain_month }))) : `<div class="muted">پیشنهاد بازی نیست.</div>`}</div>
      <div class="card"><h3>برنامهٔ اقدام — پیشنهادهای باز به ترتیب اثر</h3>
        <table class="tbl"><thead><tr><th>پیشنهاد</th><th>نوع</th><th>سود اضافه / ماه</th><th>بازه</th><th>۹۰ روز</th><th>اطمینان</th><th></th></tr></thead><tbody>
        ${p.items.sort((a, c) => c.gain_month - a.gain_month).map((it) => `<tr><td>${esc(it.title)}</td><td class="muted">${esc(it.label)}</td><td class="ok"><b>+${money(it.gain_month)}</b></td><td class="muted">${money(it.low_month)} – ${money(it.high_month)}</td><td>+${money(it.gain_horizon)}</td><td>${CONF[it.confidence] || "—"}${it.history_n ? ` <span class="muted">(${fa(it.history_n)})</span>` : ""}</td><td><button class="btn btn-sm btn-ghost" data-ins="${it.id}">جزئیات</button></td></tr>`).join("") || `<tr><td colspan="7" class="muted">—</td></tr>`}</tbody></table></div>
      <div class="card"><h3>یادگیری مدل — پیش‌بینی در برابر اثر واقعی</h3>
        ${m.calibration.length ? `<div class="cal-grid">${m.calibration.map((c) => `<div class="cal"><b>${esc(c.label)}</b><span>ضریب یادگرفته‌شده <b>${fa(c.ratio)}</b> از ${fa(c.n)} اقدام</span><span class="muted">جهت درست ${c.direction_accuracy != null ? fa(Math.round(c.direction_accuracy * 100)) + "٪" : "—"} · پراکندگی ${fa(c.sd)}</span></div>`).join("")}</div>` : `<p class="muted">هنوز اقدامی به پایان اندازه‌گیری نرسیده؛ پس از اولین اقدام سنجیده‌شده، ضرایب هر نوع پیشنهاد به‌طور خودکار یاد گرفته می‌شود.</p>`}
        ${p.accuracy.length ? svgBars(p.accuracy.slice(0, 10).flatMap((a) => [{ label: `${a.title.slice(0, 34)} — پیش‌بینی`, value: a.calibrated, color: "#8a94a6" }, { label: "اثر واقعی", value: a.measured, color: "#7c5cff" }]), { height: Math.min(620, p.accuracy.slice(0, 10).length * 60 + 10) }) : ""}</div>`;
    body.querySelectorAll("button[data-ins]").forEach((b) => b.onclick = () => detail(Number(b.dataset.ins)));
  };

  async function detail(id) {
    const i = await api(`/insights/${id}?narrate=true`);
    openModal(`<div class="ins-detail">
      <header><span class="ins-ic">${ico(iconOf(i), 26)}</span><div><span class="ins-kind">${esc(i.label)} · ${STATUS[i.status] || i.status}</span><h3>${esc(i.title)}</h3></div></header>
      ${i.narrative ? `<div class="ins-narr">${esc(i.narrative).replace(/\n/g, "<br/>")}</div>` : `<p>${esc(i.body)}</p>`}
      ${abBlock(i)}
      ${predictBlock(i)}
      <h4>اقدام‌ها</h4><ul class="ins-list">${(i.actions || []).map((a) => `<li>${esc(a.label)}</li>`).join("") || "<li class='muted'>—</li>"}</ul>
      <h4>شواهد (از داده‌های خود فروشگاه)</h4>${evidenceBlock(i)}
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
  let insTab = "NEW", insGroup = "", insRequest = 0;
  RENDER.insights = async () => {
    const request = ++insRequest;
    const v = $("#view");
    v.innerHTML = `<div class="ins-wrap">
      <div class="page-intro"><div><span class="eyebrow">تصمیم بهتر، بر پایهٔ داده</span><h2>هوش فروشگاه</h2><p>پیشنهادها را بررسی کنید، آگاهانه تصمیم بگیرید و نتیجهٔ اجرا را بسنجید.</p></div><span class="intro-badge">تحلیل داده‌های فروشگاه</span></div>
      <section class="ins-hero" id="ins-hero"><div class="muted">در حال تحلیل…</div></section>
      <div class="set-tabs" id="ins-tabs"></div>
      <div id="ins-list" class="ins-grid"></div></div>`;
    $("#topbar-actions").innerHTML = "";
    $("#topbar-actions").append(el("button", { class: "btn btn-sm btn-primary", text: "تحلیل دوباره", onclick: async (event) => {
      const button = event.currentTarget; button.disabled = true;
      try { const r = await api("/insights/run", { method: "POST" }); toast(`${fa(r.created || 0)} پیشنهاد جدید، ${fa(r.refreshed || 0)} به‌روزرسانی`); if (state.view === "insights") await RENDER.insights(); }
      catch (e) { toast(e.message, "err"); } finally { button.disabled = false; }
    } }));
    $("#topbar-actions").append(el("button", { class: "btn btn-sm btn-primary", text: "برنامه‌ریزی و پیش‌بینی سود", onclick: () => go("insightsPlan") }));
    $("#topbar-actions").append(el("button", { class: "btn btn-sm", text: "پیش‌بینی خرید مشتریان", onclick: () => go("insightsCustomers") }));
    $("#topbar-actions").append(el("button", { class: "btn btn-sm btn-ghost", text: "گزارش هفتگی", onclick: weeklyReport }));
    $("#topbar-actions").append(el("button", { class: "btn btn-sm btn-ghost", text: "مشاور هوش مصنوعی", onclick: aiAdvisor }));
    let s, list, gr;
    try {
      [s, list, gr] = await Promise.all([api("/insights/summary"), api(`/insights?status=${insTab}&limit=300${insGroup ? "&group=" + insGroup : ""}`), api("/insights/groups").catch(() => null)]);
      if (!Array.isArray(list)) throw new Error("پاسخ فهرست تحلیل‌ها معتبر نیست؛ دوباره تلاش کنید.");
    } catch (error) {
      if (request !== insRequest || !v.querySelector("#ins-hero")) return;
      const host = v.querySelector("#ins-hero");
      host.innerHTML = `<div class="view-feedback" role="alert"><h3>دریافت تحلیل‌ها انجام نشد</h3><p>${esc(error.message)}</p><button class="btn" id="ins-retry">تلاش دوباره</button></div>`;
      host.querySelector("#ins-retry").onclick = () => RENDER.insights();
      return;
    }
    if (request !== insRequest || !v.querySelector("#ins-hero")) return;
    // Reading a page must not recursively POST /run when there is no data.
    hero(s, $("#ins-hero"));
    const tabs = [["NEW", "پیشنهادهای باز", s.open], ["ACCEPTED,MEASURED", "اجراشده و اثر", s.accepted], ["SNOOZED", "به تعویق"], ["DISMISSED,EXPIRED", "بایگانی"]];
    const t = $("#ins-tabs"); t.innerHTML = "";
    tabs.forEach(([k, l, n]) => t.append(el("button", { class: "set-tab" + (k === insTab ? " active" : ""), text: l + (n != null ? ` (${fa(n)})` : ""), onclick: () => { insTab = k; RENDER.insights(); } })));
    if (gr && gr.groups) {   // v3.5 — group strip (customer / stock / price / ops / growth / daily)
      const gs = el("div", { class: "set-tabs ins-groups" });
      gs.append(el("button", { class: "set-tab" + (!insGroup ? " active" : ""), text: `همه (${fa(gr.analyzers)} تحلیل)`, onclick: () => { insGroup = ""; RENDER.insights(); } }));
      gr.groups.forEach((g) => gs.append(el("button", { class: "set-tab" + (g.id === insGroup ? " active" : ""), text: g.label + (g.open ? ` (${fa(g.open)})` : ""), onclick: () => { insGroup = g.id; RENDER.insights(); } })));
      t.after(gs);
    }
    const grid = $("#ins-list"); grid.innerHTML = "";
    if (!list.length) grid.innerHTML = `<div class="card muted">موردی نیست. ${insTab === "NEW" ? "هنوز پیشنهادی برای این فیلتر موجود نیست. نبود پیشنهاد به معنی بی‌نقص بودن فروشگاه نیست؛ می‌توانید «تحلیل دوباره» را اجرا کنید." : ""}</div>`;
    pagedAppend(grid, list, 12, (item) => card(item, false));   // v3.5 staged — long lists no longer freeze the page
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

  // v3.5 — AI advisor: show the (anonymised) report, send it to the configured free model, get suggestions as cards
  async function aiAdvisor() {
    const s = await api("/insights/summary");
    if (!s.ai || !s.ai.online) {
      openModal(`<div class="ins-detail"><h3>مشاور هوش مصنوعی</h3><p class="muted">هنوز سرویسی انتخاب نشده. از تنظیمات ← هوش فروشگاه یکی از سرویس‌های رایگان (OpenRouter، Groq، Gemini یا Ollama محلی) را انتخاب کنید و کلید رایگان را وارد کنید.</p>
        <div class="row" style="justify-content:flex-end;gap:8px"><button class="btn btn-primary" id="aa-go">رفتن به تنظیمات</button><button class="btn" onclick="closeModal()">بستن</button></div></div>`);
      $("#aa-go").onclick = () => { closeModal(); go("settings"); setTimeout(() => { const b = document.querySelector('[data-cat="ai"]'); if (b) b.click(); }, 200); };
      return;
    }
    openModal(`<div class="ins-detail"><h3>مشاور هوش مصنوعی <span class="muted" style="font-size:12px">(${esc(s.ai.model)})</span></h3>
      <p class="muted">این گزارش بدون نام و شمارهٔ مشتری به مدل فرستاده می‌شود و پیشنهادهایش به‌صورت کارت‌های قابل اجرا برمی‌گردد.</p>
      <pre id="aa-rep" class="receipt" style="max-height:220px;overflow:auto;direction:ltr;text-align:left;font-size:11px">در حال ساخت گزارش…</pre>
      <div id="aa-out" class="muted"></div>
      <div class="row" style="justify-content:flex-end;gap:8px;margin-top:8px"><button class="btn btn-primary" id="aa-send">ارسال و دریافت راهکارها</button><button class="btn" onclick="closeModal()">بستن</button></div></div>`);
    try { const rep = await api("/insights/ai/report"); $("#aa-rep").textContent = JSON.stringify(rep, null, 1).slice(0, 6000); } catch (e) { $("#aa-rep").textContent = e.message; }
    $("#aa-send").onclick = async () => {
      $("#aa-send").disabled = true; $("#aa-out").textContent = "در انتظار پاسخ مدل… (تا ۳۰ ثانیه)";
      try {
        const r = await api("/insights/ai/advise", { method: "POST" });
        $("#aa-out").className = "ins-narr"; $("#aa-out").innerHTML = `<b>${esc(r.summary || "")}</b><br/>${fa(r.created)} پیشنهاد به فهرست «روزانه ← مشاور هوش مصنوعی» اضافه شد؛ هر کدام را با یک لمس اجرا کنید.`;
        setTimeout(() => { closeModal(); insTab = "NEW"; insGroup = "daily"; RENDER.insights(); }, 1800);
      } catch (e) { $("#aa-out").textContent = e.message; $("#aa-send").disabled = false; }
    };
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
          <div class="row" style="justify-content:space-between;align-items:center;margin-top:8px"><span class="muted">${fa(s.open)} پیشنهاد باز · برآورد ${money(s.expected_open)} / ماه</span><span><button class="btn btn-sm btn-ghost" onclick="go('insightsPlan')">پیش‌بینی سود</button> <button class="btn btn-sm btn-primary" onclick="go('insights')">مشاهدهٔ پیشنهادها</button></span></div>`;
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
          if (!host.isConnected || key !== lastKey) return;
          if (!r.length) { host.innerHTML = ""; host.classList.add("hidden"); return; }
          host.classList.remove("hidden");
          host.innerHTML = `<span class="nudge-ic">${ico("sparkle", 16)}</span><span class="nudge-txt">پیشنهاد به مشتری:</span>` +
            r.map((n) => `<button class="nudge-chip" title="چون ${esc(n.because)} در سبد است" onclick="PosNudges.add(${n.product_id})">${esc(n.name)}</button>`).join("");
        } catch (_) { host.classList.add("hidden"); }
      }, 350);
    },
    async add(pid) {
      try { const p = await api(`/products/${pid}`); const result = await api(`/pos/batch-options/${pid}`);
        if (!(result.options || []).length) { toast("این کالا اکنون موجودی قابل فروش ندارد؛ برای شارژ موجودی از ورود کالا استفاده کنید.", "err"); return; }
        await posAddResolved({ product_id: p.id, name: p.name, image_url: p.image_url, unit: p.unit, batches: result.options }); }
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
          <label class="btn"><input type="file" id="bk-file" accept=".db,.gz,.sqlite,.bak,.zip" hidden/> بازیابی از فایل…</label>
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
        <div id="ai-presets" class="ins-presets" style="margin-top:10px"></div>
        <p class="muted" style="margin-top:8px">هر سرویس با API سازگار با OpenAI کار می‌کند (OpenAI، OpenRouter، Groq، یا مدل محلی مثل Ollama روی همین شبکه). هزینهٔ آن بر عهدهٔ شماست و بدون آن هم همهٔ امکانات کار می‌کند.</p>
        <div class="row" style="gap:8px;margin-top:10px"><button class="btn btn-primary" id="ai-save">ذخیره</button><button class="btn" id="ai-test">تست روایت</button></div>`;
      body.append(card);
      api("/insights/ai/presets").then((p) => {   // v3.5 — one-tap free providers
        const box = $("#ai-presets"); if (!box) return;
        box.append(el("div", { class: "muted", text: "سرویس‌های رایگان — یکی را انتخاب کنید، کلید رایگان را از سایتش بگیرید و همین‌جا وارد کنید:" }));
        const wrap = el("div", { class: "row", style: "flex-wrap:wrap;gap:6px;margin-top:6px" });
        p.presets.forEach((pr) => wrap.append(el("button", { class: "btn btn-sm" + (p.current.preset === pr.id ? " btn-primary" : ""), text: pr.label + (pr.free ? "" : " (پولی)"), title: pr.note, onclick: async () => {
          const key = $("#ai-key").value.trim();
          try { const r = await api("/insights/ai/preset", { method: "POST", body: JSON.stringify({ preset: pr.id, api_key: key || null }) });
            $("#ai-pr").value = "openai_compatible"; $("#ai-url").value = r.base_url; $("#ai-model").value = r.model; toast(`${pr.label} انتخاب شد`);
            if (!r.has_key && pr.id !== "ollama") { window.open(pr.keys_url, "_blank"); toast("کلید رایگان را از صفحهٔ بازشده بگیرید و در «کلید API» وارد و ذخیره کنید", "ok"); }
          } catch (e) { toast(e.message, "err"); }
        } })));
        box.append(wrap);
        const tb = el("button", { class: "btn btn-sm btn-ghost", text: "تست اتصال", style: "margin-top:6px", onclick: async () => {
          try { const r = await api("/insights/ai/test", { method: "POST" }); toast(r.ok ? `متصل شد (${fa(r.ms)} ms): ${r.reply}` : r.error, r.ok ? "ok" : "err"); } catch (e) { toast(e.message, "err"); }
        } });
        box.append(tb);
      }).catch(() => {});
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
