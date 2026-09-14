/* v3.2 smoke (server on :8000 with the demo store loaded, setup done):
   measured effect shown as percent with a before/after chart, per-kind evidence charts (no raw JSON),
   VELOCITY measured via availability (non-zero), customer purchase-pattern view + API, VISIT_PATTERN insight. */
const { JSDOM } = require("jsdom"); const fs = require("fs"); const path = require("path");
const BASE = "http://127.0.0.1:8000"; const FE = path.join(__dirname, "..", "..", "frontend");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errors = []; const check = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) errors.push(m); };
  const tok = (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).json()).access_token;
  const H = { Authorization: "Bearer " + tok, "Content-Type": "application/json" };
  // API
  const done = await (await fetch(BASE + "/api/insights?status=ACCEPTED,MEASURED&limit=200", { headers: H })).json();
  const measured = done.filter((r) => r.measured_gain != null);
  check(measured.length >= 10, `api: ${measured.length} measured actions in the demo`);
  const zero = measured.filter((r) => Number(r.measured_gain) === 0);
  check(zero.length === 0, `api: no measured action with a zero effect (${zero.length} zero)`);
  const vel = measured.filter((r) => r.kind === "VELOCITY");
  check(vel.length >= 5 && vel.every((r) => r.metric.metric === "availability") && vel.filter((r) => Number(r.measured_gain) > 0).length >= vel.length * 0.6, `api: VELOCITY measured by availability, ${vel.filter((r) => Number(r.measured_gain) > 0).length}/${vel.length} positive`);
  check(measured.every((r) => (r.result.profit_pct != null || Number(r.result.base_profit_per_day) === 0) && r.result.daily && Array.isArray(r.result.daily.after)), "api: every measurement carries profit % (unless the baseline was zero) + daily before/after series");
  const kinds = new Set(measured.map((r) => r.kind)); check(kinds.size >= 5, `api: ${kinds.size} different kinds measured (${[...kinds].join(",")})`);
  const pat = await (await fetch(BASE + "/api/insights/customers/patterns?days=7", { headers: H })).json();
  check(pat.rows.length >= 5 && pat.rows[0].usual_items.length > 0 && pat.rows[0].predicted, `api: ${pat.rows.length} customers predicted due this week; top: ${pat.rows[0].name} every ${pat.rows[0].typical_gap}d`);
  const vp = await (await fetch(BASE + "/api/insights?status=NEW,ACCEPTED,MEASURED&kind=VISIT_PATTERN", { headers: H })).json();
  check(vp.length >= 1 && vp[0].actions[0].type === "visit_sms", "api: VISIT_PATTERN insight with visit_sms action");
  // UI
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
  for (let i = 0; i < 90 && !booted; i++) { await sleep(500); booted = !$("#app-view").classList.contains("hidden"); }
  check(booted, "app booted"); await sleep(3000); if (window.Tour) window.Tour.end();
  await window.go("insights"); await sleep(2500); if (window.Tour) window.Tour.end();
  check(!!$$("#topbar-actions button").find((b) => /پیش‌بینی خرید مشتریان/.test(b.textContent)), "insights: «پیش‌بینی خرید مشتریان» button");
  // executed tab → percent on card + detail chart
  $$("#ins-tabs .set-tab").find((b) => /اجراشده/.test(b.textContent)).click(); await sleep(2500);
  const cards = $$("#ins-list .ins-card"); check(cards.length >= 10, `executed tab: ${cards.length} cards`);
  const pc = cards.find((c) => /رشد سود [+−]/.test(c.textContent)); check(!!pc, "executed card shows «رشد سود ±٪» and real toman effect");
  const velCard = cards.find((c) => /هشدار اتمام موجودی/.test(c.textContent)); check(!!velCard && !/اثر واقعی: ۰ /.test(velCard.textContent), "VELOCITY card: non-zero effect");
  [...(velCard || pc).querySelectorAll("button")].find((b) => /جزئیات/.test(b.textContent)).click(); await sleep(2000);
  const det = $(".ins-detail"); check(!!det && !!det.querySelector(".ab2") && /رشد سود/.test(det.textContent), "detail: before/after block with growth %");
  check(!!det && det.querySelectorAll("svg").length >= 2, `detail: ${det && det.querySelectorAll("svg").length} charts (before/after + evidence)`);
  check(!!det && !/\{"/.test(det.textContent), "detail: no raw JSON dump");
  if (window.closeModal) window.closeModal(); await sleep(200);
  // open tab: evidence charts for a NEW card
  $$("#ins-tabs .set-tab").find((b) => /پیشنهادهای باز/.test(b.textContent)).click(); await sleep(2500);
  const c0 = $$("#ins-list .ins-card")[0]; [...c0.querySelectorAll("button")].find((b) => /جزئیات/.test(b.textContent)).click(); await sleep(2000);
  const d2 = $(".ins-detail"); check(!!d2 && (d2.querySelectorAll(".ev-kpis").length + d2.querySelectorAll("svg").length) >= 1, "open detail: evidence tiles / chart rendered");
  if (window.closeModal) window.closeModal(); await sleep(200);
  // customers view
  await window.go("insightsCustomers"); await sleep(3000); if (window.Tour) window.Tour.end();
  check(/پیش‌بینی خرید مشتریان/.test($("#view-title").textContent), "customers: view title");
  check(!!$("#vc-chart svg") && $$("#vc-table tbody tr").length >= 5, `customers: chart + ${$$("#vc-table tbody tr").length} predicted rows`);
  check(/نوبت بعدی/.test($("#vc-table").textContent) && /خرید همیشگی/.test($("#vc-table").textContent), "customers: next visit + usual basket columns");
  console.log(errors.length ? `\n${errors.length} FAILED:\n - ` + errors.join("\n - ") : "\nALL PASS");
  process.exit(errors.length ? 1 : 0);
})().catch((e) => { console.error("CRASH", e); process.exit(2); });
