/* v3.1 smoke (server on :8000 with the demo store loaded, setup done):
   planning view (forecast charts, action plan table, calibration), what-if prediction block in the
   suggestion detail, POS pay modal phone field → customer auto-created & recognised, backup restore
   input accepts .gz. */
const { JSDOM } = require("jsdom"); const fs = require("fs"); const path = require("path");
const BASE = "http://127.0.0.1:8000"; const FE = path.join(__dirname, "..", "..", "frontend");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errors = []; const check = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) errors.push(m); };
  const tok = (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).json()).access_token;
  const H = { Authorization: "Bearer " + tok, "Content-Type": "application/json" };
  // API: plan
  await fetch(BASE + "/api/insights/plan/learn", { method: "POST", headers: H });
  const plan = await (await fetch(BASE + "/api/insights/plan?horizon=90", { headers: H })).json();
  check(plan.baseline && plan.baseline.profit_month > 0 && plan.forecast.length >= 12, `api: plan baseline ${plan.baseline && plan.baseline.profit_month}/month, ${plan.forecast.length} forecast points`);
  check(plan.model.calibration.length >= 3 && plan.model.measured_count >= 5, `api: calibration learned for ${plan.model.calibration.length} kinds from ${plan.model.measured_count} measured actions`);
  check(plan.items.every((i) => i.low_month <= i.gain_month && i.gain_month <= i.high_month), "api: every open suggestion has a consistent low ≤ gain ≤ high band");
  const dom = new JSDOM(fs.readFileSync(FE + "/index.html", "utf8"), { url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom; window.addEventListener("error", (e) => errors.push("onerror: " + e.message));
  window.fetch = async (i, init) => fetch(typeof i === "string" && i.startsWith("http") ? i : BASE + i, init);
  window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} }); window.navigator.serviceWorker = { register: async () => {} };
  window.requestAnimationFrame = (f) => setTimeout(f, 16); window.print = () => {}; window.confirm = () => true; window.URLSearchParams = URLSearchParams;
  window.HTMLElement.prototype.scrollIntoView = function () {}; window.URL.createObjectURL = () => "blob:x"; window.URL.revokeObjectURL = () => {};
  window.localStorage.setItem("token", tok); window.sessionStorage.setItem("sm.loading.fast", "3"); window.localStorage.setItem("tour.seen", JSON.stringify(["*"]));
  window.eval(["jalali.js", "vendor-qrcode.js", "sfx.js", "onboarding.js", "tour.js", "app.js", "insights.js", "accounting.js"].map((f) => fs.readFileSync(FE + "/" + f, "utf8")).join("\n;"));
  const $ = (s) => window.document.querySelector(s); const $$ = (s) => [...window.document.querySelectorAll(s)];
  let booted = false;
  for (let i = 0; i < 40 && !booted; i++) { await sleep(500); booted = !$("#app-view").classList.contains("hidden"); }
  check(booted, "app booted"); await sleep(3000); if (window.Tour) window.Tour.end();
  // insights → planning button
  await window.go("insights"); await sleep(2500); if (window.Tour) window.Tour.end();
  const pb = $$("#topbar-actions button").find((b) => /برنامه‌ریزی/.test(b.textContent)); check(!!pb, "insights: «برنامه‌ریزی و پیش‌بینی سود» button");
  const card0 = $("#ins-list .ins-card"); check(!!card0 && /پیش‌بینی سود ماهانه/.test(card0.textContent) && /اطمینان/.test(card0.textContent), "insights: card shows calibrated monthly forecast with band + confidence");
  // detail → what-if block
  [...card0.querySelectorAll("button")].find((b) => /جزئیات/.test(b.textContent)).click(); await sleep(1800);
  const det = $(".ins-detail"); check(!!det && /اگر این پیشنهاد اجرا شود/.test(det.textContent) && !!det.querySelector(".predict svg"), "detail: what-if prediction block with SVG chart");
  check(!!det && /رشد سود ماهانهٔ فروشگاه/.test(det.textContent) && /جمع ۹۰ روز/.test(det.textContent), "detail: growth % and 90-day cumulative shown");
  if (window.closeModal) window.closeModal(); await sleep(200);
  // planning view
  await window.go("insightsPlan"); await sleep(3000); if (window.Tour) window.Tour.end();
  check(/برنامه‌ریزی و پیش‌بینی سود/.test($("#view-title").textContent), "plan: view title");
  const hero = $("#pl-hero"); check(!!hero && /سود ماهانهٔ پایه/.test(hero.textContent) && /دقت مدل/.test(hero.textContent), "plan: hero KPIs (baseline, plan, band, model accuracy)");
  const svgs = $$("#pl-body svg"); check(svgs.length >= 4, `plan: ${svgs.length} SVG charts rendered (weekly, cumulative, by-kind, accuracy)`);
  check(!!$("#pl-body .tbl") && $$("#pl-body .tbl tbody tr").length >= 5, `plan: action-plan table with ${$$("#pl-body .tbl tbody tr").length} rows`);
  check(/ضریب یادگرفته‌شده/.test($("#pl-body").textContent), "plan: calibration (learning) section");
  const det2 = $$("#pl-body button[data-ins]")[0]; if (det2) { det2.click(); await sleep(1500); check(!!$(".ins-detail"), "plan: row detail opens the suggestion card"); if (window.closeModal) window.closeModal(); }
  // dashboard link
  await window.go("dashboard"); await sleep(2500); if (window.Tour) window.Tour.end();
  check(!!$("#dash-ins") && /پیش‌بینی سود/.test($("#dash-ins").textContent), "dashboard: intelligence card links to the profit forecast");
  // POS: phone field at payment → customer auto-created
  const phone = "0935" + String(Date.now()).slice(-7);
  const prods = await (await fetch(BASE + "/api/products?limit=40", { headers: H })).json();
  const prod = (Array.isArray(prods) ? prods : prods.items || []).find((p) => (p.available_qty || p.stock || 0) > 0) || (Array.isArray(prods) ? prods : prods.items)[0];
  await window.go("pos"); await sleep(1500); if (window.Tour) window.Tour.end();
  $("#pos-scan").value = prod.barcode; $("#pos-scan").dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true })); await sleep(2500);
  const opt = $(".batch-option.recommended") || $(".batch-option"); if (opt) { opt.click(); await sleep(800); }
  const pq = $("#pq-ok"); if (pq) { pq.click(); await sleep(800); }
  await sleep(500); window.document.dispatchEvent(new window.KeyboardEvent("keydown", { key: "F2", bubbles: true }));
  await sleep(800);
  if (!$("#pay-phone")) { const b = $$("button").find((x) => /پرداخت/.test(x.textContent) && !/روش/.test(x.textContent)); if (b) { b.click(); await sleep(800); } }
  check(!!$("#pay-phone"), "pos/pay: optional phone field for the invoice SMS");
  if ($("#pay-phone")) {
    $("#pay-phone").value = phone; $("#btn-pay").click(); await sleep(3500);
    const c = await fetch(BASE + "/api/customers/phone/" + phone, { headers: H });
    check(c.status === 200, "pos/pay: phone typed at checkout is now in the customer book");
    if (c.status === 200) { const cu = await c.json(); check(cu.last_name == null && !!cu.name, "customer: created without last name (optional)"); }
    // second purchase with the same phone → recognised via /customers/phone (POS F4 flow)
    const again = await (await fetch(BASE + "/api/customers?q=" + phone, { headers: H })).json();
    check((Array.isArray(again) ? again : []).filter((x) => x.phone === phone).length === 1, "customer: no duplicate for the same phone");
  }
  // settings/backup input accepts .gz
  await window.go("settings"); await sleep(2000); if (window.Tour) window.Tour.end();
  const bkTab = $$(".set-tab").find((b) => b.textContent.trim() === "پشتیبان‌گیری"); if (bkTab) { bkTab.click(); await sleep(1500); }
  check(!!$("#bk-file") && /\.gz/.test($("#bk-file").getAttribute("accept") || ""), "settings/backup: restore input accepts .gz demo file");
  console.log(errors.length ? `\n${errors.length} FAIL` : "\nALL PASS"); process.exit(errors.length ? 1 : 0);
})().catch((e) => { console.error("CRASH", e); process.exit(2); });
