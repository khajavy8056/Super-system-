/* v1.4 smoke: neon dashboard, POS cart cards, accounting UI, scanner discovery, receiving supplier/paid_from. */
const { JSDOM } = require("jsdom");
const fs = require("fs"); const path = require("path");
const BASE = "http://127.0.0.1:8000"; const FE = path.join(__dirname, "..", "..", "frontend");
(async () => {
  const dom = new JSDOM(fs.readFileSync(FE + "/index.html", "utf8"), { url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom; const errors = [];
  window.addEventListener("error", (e) => errors.push("onerror: " + e.message));
  window.fetch = async (i, init) => fetch(typeof i === "string" && i.startsWith("http") ? i : BASE + i, init);
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener(){}, addListener(){} }));
  window.navigator.serviceWorker = { register: async () => {} };
  window.confirm = () => true; window.print = () => {};
  const tok = (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).json()).access_token;
  window.localStorage.setItem("token", tok);
  const H = { Authorization: "Bearer " + tok, "Content-Type": "application/json" };
  window.eval(fs.readFileSync(FE + "/jalali.js", "utf8"));
  window.eval(fs.readFileSync(FE + "/app.js", "utf8") + "\n;\n" + fs.readFileSync(FE + "/accounting.js", "utf8"));
  await new Promise((r) => setTimeout(r, 800));
  const $ = (s) => window.document.querySelector(s); const $$ = (s) => [...window.document.querySelectorAll(s)];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const check = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) errors.push(m); };
  const txt = (s) => ($(s) ? $(s).textContent : "");

  // seed
  await fetch(BASE + "/api/products/import/starter", { method: "POST", headers: H });
  const prods = (await (await fetch(BASE + "/api/products?limit=3", { headers: H })).json()).items;
  const p = prods[0];
  const sup = await (await fetch(BASE + "/api/accounting/suppliers", { method: "POST", headers: H, body: JSON.stringify({ name: "تأمین‌کنندهٔ اسموک" }) })).json();
  const b = await (await fetch(BASE + "/api/batches/receive", { method: "POST", headers: H, body: JSON.stringify({ product_id: p.id, quantity_received: 9, buy_price: 1000, sell_price: 1500, expiry_date: "2027-01-15", supplier_id: sup.id, paid_from: "PAYABLE" }) })).json();
  await fetch(BASE + "/api/pos/checkout", { method: "POST", headers: H, body: JSON.stringify({ items: [{ product_id: p.id, batch_id: b.id, quantity: 2 }], payments: [{ method: "CASH", amount: 3000 }] }) });

  // dashboard
  await window.go("dashboard"); await sleep(1200);
  check($$(".dash .dcard").length >= 8, "dashboard: >=8 neon cards rendered (" + $$(".dash .dcard").length + ")");
  check(!!$(".gauge"), "dashboard: today-sales gauge");
  check($$(".toplist .topitem").length >= 1, "dashboard: top products list");
  check(!!$("svg.trend, .trend svg"), "dashboard: SVG trend chart");
  check(!!$(".acc-mini"), "dashboard: accounting mini KPIs");
  check(!!$(".quick-grid"), "dashboard: quick actions");
  check(!/undefined|NaN|\[object/.test($("#view").textContent), "dashboard: no undefined/NaN leaks");

  // POS
  await window.go("pos"); await sleep(800);
  for (const id of ["#pos-pay", "#pos-customer-btn", "#pos-coupon-btn", "#pos-discount-btn", "#pos-clear-btn", "#pos-cart-table", "#pos-cart-count", "#pos-clock", "#pos-scan"]) check(!!$(id), "pos: element " + id);
  const s = await (await fetch(BASE + "/api/pos/search?q=" + encodeURIComponent(p.name.slice(0, 4)) + "&limit=1", { headers: H })).json();
  const it = s.items[0];
  window.posPushCart({ id: it.product_id, name: it.name, image_url: it.image_url }, it.batches[0], 1); await sleep(200);
  check($$("#pos-cart-table .citem").length === 1, "pos: cart item card rendered");
  check(txt("#pos-cart-count").length > 0, "pos: cart count updated");
  $("#pos-cart-table .cqty .plus, #pos-cart-table .citem button[data-d='1'], #pos-cart-table .citem .qplus") && ($("#pos-cart-table .cqty .plus, #pos-cart-table .citem button[data-d='1'], #pos-cart-table .citem .qplus").click(), await sleep(150));
  check(/۲|2/.test($("#pos-cart-table .citem").textContent), "pos: qty + works via card");
  $("#pos-clear-btn").click(); await sleep(200);
  check($$("#pos-cart-table .citem").length === 0, "pos: clear empties cart");
  check(!!$("#pos-scan").closest(".scan-field") || !!$(".scan-field"), "pos: scanner icon/wedge field present");

  // receiving: supplier + paid_from
  await window.go("batches"); await sleep(600);
  check($("#b-supplier") && $("#b-supplier").tagName === "SELECT" && $$("#b-supplier option").length >= 2, "receiving: supplier dropdown populated");
  check(!!$("#b-paid"), "receiving: paid_from selector");

  // accounting
  await window.go("accounting"); await sleep(1200);
  check($$(".acc-tab").length >= 9, "accounting: tabs (" + $$(".acc-tab").length + ")");
  check($$(".kpi").length >= 5, "accounting: overview KPIs");
  const tabs = $$(".acc-tab");
  const names = ["journal", "ledger", "trial", "pl", "bs", "expenses", "cheques", "suppliers", "shift", "accounts", "periods"];
  for (let i = 1; i < tabs.length; i++) {
    tabs[i].click(); await sleep(900);
    const body = $("#acc-body") || $("#view");
    check(body.textContent.trim().length > 20 && !/undefined|NaN/.test(body.textContent) && !body.querySelector(".error"), "accounting tab '" + tabs[i].textContent.trim() + "' renders");
  }
  tabs[4].click(); await sleep(900);
  check($("#pl-start") && $("#pl-start").value && $("#pl-start").jalaliInput.value.length >= 8, "accounting: P&L Jalali dates prefilled (" + ($("#pl-start") ? $("#pl-start").jalaliInput.value : "") + ")");
  check(!!$(".pl-line.grand"), "accounting: net profit line");
  // expense modal from dashboard quick action
  await window.go("dashboard"); await sleep(1000);
  window.AccountingUI.expenseModal(); await sleep(600);
  check(!!$("#ex-d") && !!$("#ex-d").value, "expense modal opens with today date");
  window.closeModal && window.closeModal();

  // hardware scanner discovery
  await window.go("hardware"); await sleep(1000);
  check(/بارکدخوان/.test($("#view").textContent) && !!$("#h-scanners"), "hardware: scanner section");

  // English leak scan across visited views
  const leak = $("#view").textContent.match(/\b(undefined|null|error|Error)\b/);
  check(!leak, "no English/undefined leaks in view (" + (leak ? leak[0] : "") + ")");

  if (errors.length) { console.log("ERRORS:"); errors.forEach((e) => console.log(" - " + e)); process.exit(1); }
  console.log("V1.4 SMOKE OK"); process.exit(0);
})().catch((e) => { console.error("CRASH", e); process.exit(2); });
