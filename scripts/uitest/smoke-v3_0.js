/* v3.0 smoke (server on :8000 with the demo store loaded, setup done):
   dashboard impact card, «هوش فروشگاه» view (hero KPIs, tabs, cards, accept → measured list),
   weekly report modal, Settings → پشتیبان‌گیری (list / demo / restore form) + هوش فروشگاه panel,
   POS whisper suggestion after adding a product that has a nudge rule. */
const { JSDOM } = require("jsdom"); const fs = require("fs"); const path = require("path");
const BASE = "http://127.0.0.1:8000"; const FE = path.join(__dirname, "..", "..", "frontend");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errors = []; const check = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) errors.push(m); };
  const tok = (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).json()).access_token;
  const H = { Authorization: "Bearer " + tok, "Content-Type": "application/json" };
  const sum = await (await fetch(BASE + "/api/insights/summary", { headers: H })).json();
  check(sum.accepted >= 10 && sum.total_gain > 0, `api: demo store has ${sum.accepted} executed suggestions, measured gain ${sum.total_gain}`);
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
  check(booted, "app booted");
  if (window.Tour) window.Tour.end();
  // nav entry
  check($$("nav a, nav button, .nav-item, [data-view]").some((a) => /هوش فروشگاه/.test(a.textContent)), "nav: «هوش فروشگاه» entry present");
  // dashboard card
  await window.go("dashboard"); await sleep(2500); if (window.Tour) window.Tour.end();
  const di = $("#dash-ins");
  check(!!di && /اثر/.test(di.textContent) && /تومان|ریال/.test(di.textContent), "dashboard: intelligence impact card rendered with a money figure");
  check(!!di && !/…$/.test(di.textContent.trim()), "dashboard: card finished loading (no placeholder)");
  // insights view
  await window.go("insights"); await sleep(2500); if (window.Tour) window.Tour.end();
  const hero = $("#ins-hero");
  check(!!hero && /اثر اندازه‌گیری‌شدهٔ کل/.test(hero.textContent) && /۳۰ روز اخیر/.test(hero.textContent), "insights: hero KPIs (total + last-30-days)");
  check($$("#ins-tabs .set-tab").length >= 3, "insights: status tabs");
  let cards = $$("#ins-list .ins-card"); check(cards.length > 0, `insights: ${cards.length} open suggestion cards`);
  const first = cards[0]; check(!!first && /اجرا کن/.test(first.textContent) && /جزئیات و شواهد/.test(first.textContent), "insights: card has accept + evidence buttons");
  // detail modal
  [...first.querySelectorAll("button")].find((b) => /جزئیات/.test(b.textContent)).click(); await sleep(1500);
  check(!!$(".ins-detail") && /اقدام‌ها/.test($(".ins-detail").textContent), "insights: detail modal with actions + evidence");
  if (window.closeModal) window.closeModal(); await sleep(200);
  // accept the first NEW card (dialog → confirm)
  const newId = (await (await fetch(BASE + "/api/insights?status=NEW&limit=1", { headers: H })).json())[0].id;
  [...first.querySelectorAll("button")].find((b) => /اجرا کن/.test(b.textContent)).click(); await sleep(800);
  const dlg = $(".ins-detail, .modal"); check(!!dlg && /اجرا/.test(dlg.textContent), "insights: accept dialog opened");
  const go = $("#ins-go"); check(!!go, "insights: accept dialog has confirm button");
  if (go) { go.click(); await sleep(2500); }
  const after = await (await fetch(BASE + "/api/insights/" + newId, { headers: H })).json();
  check(after.status === "ACCEPTED" && after.baseline && after.baseline.window_days > 0, `insights: accepted via UI → status ${after.status}, baseline frozen (${after.baseline && after.baseline.window_days} days)`);
  // executed tab shows measured cards with before/after
  const tab = $$("#ins-tabs .set-tab").find((b) => /اجراشده/.test(b.textContent)); tab.click(); await sleep(2000);
  cards = $$("#ins-list .ins-card"); check(cards.length >= 10, `insights: executed tab lists ${cards.length} cards`);
  check(cards.some((c) => /اثر واقعی/.test(c.textContent)), "insights: measured cards show real (measured) effect");
  // weekly report
  const wr = $$("#topbar-actions button").find((b) => /گزارش هفتگی/.test(b.textContent)); check(!!wr, "insights: weekly report button"); if (wr) { wr.click(); await sleep(2000); check(!!$("#wr") && $("#wr").textContent.length > 80, "insights: weekly narrative rendered (" + ($("#wr") ? $("#wr").textContent.length : 0) + " chars)"); if (window.closeModal) window.closeModal(); }
  // settings → backup + ai panels
  await window.go("settings"); await sleep(2000); if (window.Tour) window.Tour.end();
  const bkTab = $$("#set-tabs .set-tab, .set-tabs .set-tab").find((b) => b.textContent.trim() === "پشتیبان‌گیری"); check(!!bkTab, "settings: «پشتیبان‌گیری» tab"); if (bkTab) { bkTab.click(); await sleep(3500); }
  check(!!$("#bk-make") && !!$("#bk-list"), "settings/backup: create-backup button + backup list");
  check(!!$("input[type=file]"), "settings/backup: restore-from-file input");
  check(/نمونه|دمو|یک سال/.test($("#app-view").textContent) && !!$("#bk-demo-load"), "settings/backup: bundled demo-store section with load button");
  const aiTab = $$(".set-tab").find((b) => /هوش فروشگاه/.test(b.textContent)); check(!!aiTab, "settings: «هوش فروشگاه» tab"); if (aiTab) { aiTab.click(); await sleep(1500); }
  check(/کلید|API|ارائه‌دهنده|روایت/.test($("#app-view").textContent), "settings/ai: LLM provider settings rendered");
  // POS whisper: find an accepted BASKET_NUDGE rule and add its "if" product
  const acc = await (await fetch(BASE + "/api/insights?status=ACCEPTED,MEASURED&limit=80", { headers: H })).json();
  const bn = acc.find((i) => i.kind === "BASKET_NUDGE" && i.evidence && i.evidence.rules && i.evidence.rules.length);
  if (bn) {
    const rule = bn.evidence.rules[0]; const nud = await (await fetch(BASE + "/api/insights/nudges", { method: "POST", headers: H, body: JSON.stringify({ product_ids: [rule.if] }) })).json();
    check(Array.isArray(nud) && nud.length > 0 && nud[0].product_id === rule.then, `api: nudge for «${rule.if_name}» → «${nud[0] && nud[0].name}»`);
    const prod = await (await fetch(BASE + "/api/products/" + rule.if, { headers: H })).json();
    await fetch(BASE + "/api/settings", { method: "PUT", headers: H, body: JSON.stringify({ key: "insights.pos_nudges", value: "true" }) });
    await window.go("pos"); await sleep(1200); if (window.Tour) window.Tour.end();
    $("#pos-scan").value = prod.barcode; $("#pos-scan").dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true })); await sleep(2500);
    const opt = $(".batch-option.recommended") || $(".batch-option"); if (opt) { opt.click(); await sleep(800); }
    const pq = $("#pq-ok"); if (pq) { pq.click(); await sleep(800); }
    await sleep(1500); const posTxt = ($("#pos-nudge") || {}).textContent || "";
    check(new RegExp(rule.then_name.slice(0, 6)).test(posTxt) && /پیشنهاد/.test(posTxt), "pos: whisper suggestion shown to the cashier for the paired product");
    check(!/سود/.test(($("#pos-cart-table") || {}).textContent || ""), "pos: still no profit shown");
  } else check(false, "demo store has an accepted BASKET_NUDGE with rules");
  console.log(errors.length ? `\n${errors.length} FAILED` : "\nALL PASS"); process.exit(errors.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
