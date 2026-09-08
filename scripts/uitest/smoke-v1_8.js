/* v1.8 smoke (server on :8000, setup done): guided tour on every desktop view (auto first visit + «راهنما» button,
   replay, keyboard), POS shows no profit + held dock restores, support conversation modal (thread, reply form, file input). */
const { JSDOM } = require("jsdom"); const fs = require("fs"); const path = require("path");
const BASE = "http://127.0.0.1:8000"; const FE = path.join(__dirname, "..", "..", "frontend");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errors = []; const check = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) errors.push(m); };
  const tok = (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).json()).access_token;
  const H = { Authorization: "Bearer " + tok, "Content-Type": "application/json" };
  // seed one product+batch so POS has something to sell
  let p = await (await fetch(BASE + "/api/products?q=smoke18", { headers: H })).json(); p = (p.items || p)[0];
  if (!p) p = await (await fetch(BASE + "/api/products", { method: "POST", headers: H, body: JSON.stringify({ name: "کالای smoke18", barcode: "6260000000018", unit_id: 1 }) })).json();
  const inv = await (await fetch(BASE + "/api/batches?product_id=" + p.id, { headers: H })).json();
  if (!(inv.items || inv).length) { const r = await fetch(BASE + "/api/batches/receive", { method: "POST", headers: H, body: JSON.stringify({ product_id: p.id, quantity_received: 50, buy_price: 10000, sell_price: 15000, consumer_price: 16000 }) }); if (!r.ok) console.log("seed batch:", await r.text()); }
  const dom = new JSDOM(fs.readFileSync(FE + "/index.html", "utf8"), { url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom; window.addEventListener("error", (e) => errors.push("onerror: " + e.message));
  window.fetch = async (i, init) => fetch(typeof i === "string" && i.startsWith("http") ? i : BASE + i, init);
  window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} }); window.navigator.serviceWorker = { register: async () => {} };
  window.requestAnimationFrame = (f) => setTimeout(f, 16); window.print = () => {}; window.confirm = () => true; window.URLSearchParams = URLSearchParams;
  window.HTMLElement.prototype.scrollIntoView = function () {};
  window.localStorage.setItem("token", tok); window.sessionStorage.setItem("sm.loading.fast", "3");
  window.eval(["jalali.js", "vendor-qrcode.js", "sfx.js", "onboarding.js", "tour.js", "app.js", "accounting.js"].map((f) => fs.readFileSync(FE + "/" + f, "utf8")).join("\n;"));
  const $ = (s) => window.document.querySelector(s); const $$ = (s) => [...window.document.querySelectorAll(s)];
  let booted = false;
  for (let i = 0; i < 40 && !booted; i++) { await sleep(500); booted = !$("#app-view").classList.contains("hidden"); }
  check(booted, "app booted (setup done)");
  check(window.Tour && window.Tour.sections.length >= 16, "tour: definitions for " + (window.Tour ? window.Tour.sections.length : 0) + " sections");
  // every nav view: auto tour on first visit, button present, replay works, Esc closes
  const views = window.Tour.sections;
  for (const v of views) {
    await window.go(v); await sleep(1300);
    const btn = $("#tour-btn"); const layer = $("#tour-layer");
    const auto = layer && !layer.classList.contains("hidden") && /۱ از/.test($("#tour-card").textContent);
    check(!!btn && auto, `tour[${v}]: «راهنما» button + auto-started on first visit (${$("#tour-card") ? $("#tour-card").querySelector("b").textContent : "-"})`);
    window.Tour.next(); await sleep(50);
    const twoOrDone = layer.classList.contains("hidden") || /۲ از/.test($("#tour-card").textContent);
    check(twoOrDone, `tour[${v}]: next step advances`);
    window.Tour.end();
    check(layer.classList.contains("hidden"), `tour[${v}]: closed`);
    await window.go(v); await sleep(1300);
    check($("#tour-layer").classList.contains("hidden"), `tour[${v}]: does NOT auto-run on second visit`);
    $("#tour-btn").click(); await sleep(50);
    check(!$("#tour-layer").classList.contains("hidden"), `tour[${v}]: replay via button`);
    window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape" })); await sleep(20);
    check($("#tour-layer").classList.contains("hidden"), `tour[${v}]: Esc closes`);
  }
  // POS: no profit, held dock
  await window.go("pos"); await sleep(800);
  $("#pos-scan").value = "6260000000018"; $("#pos-scan").dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true })); await sleep(800);
  check(/کالای smoke18/.test($("#pos-cart-table").textContent), "pos: item added by barcode");
  check(!/سود/.test($("#pos-cart-table").textContent + $("#pos-totals").textContent), "pos: no profit shown in cart/totals");
  $("#pos-hold-btn").click(); await sleep(600);
  const held = $("#pos-held");
  check(held && /smoke18|۱ قلم|قلم/.test(held.textContent) && held.querySelector("button, .held-card, [onclick]"), "pos: held invoice listed in dock with restore control");
  check(/\d{1,2}:\d{2}|[۰-۹]{1,2}:[۰-۹]{2}/.test(held.textContent), "pos: held card shows time");
  check(!/کالای smoke18/.test($("#pos-cart-table").textContent), "pos: cart empty after hold");
  const restore = held.querySelector(".held-main"); const oc = restore.getAttribute("onclick"); check(/posResume\('h/.test(oc), "pos: held card click bound to posResume (" + oc + ")");
  window.eval(oc); await sleep(500);  // jsdom outside-only mode does not run inline handlers
  console.log("   dock after restore:", held.textContent.replace(/\s+/g, " ").slice(0, 120));
  check(/کالای smoke18/.test($("#pos-cart-table").textContent), "pos: held invoice restored to cart by click");
  check(window.getComputedStyle ? true : true, "pos: view has view-pos class → " + $("#view").className);
  check($("#view").classList.contains("view-pos"), "pos: #view carries view-pos (fixed viewport css hook)");
  // support conversation modal
  await window.go("support"); await sleep(900); window.Tour.end();
  $("#sup-subject").value = "smoke18 گفتگو"; $("#sup-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })); await sleep(1500);
  const t = (await (await fetch(BASE + "/api/support/tickets?limit=1", { headers: H })).json())[0];
  check(t && /smoke18/.test(t.subject), "support: ticket created");
  check(/مشاهده \/ پاسخ/.test($("#sup-list").textContent), "support: list has «مشاهده / پاسخ» per ticket");
  await window.supOpen(t.id); await sleep(800);
  check(!!$("#sup-thread") && !!$("#sup-reply-text") && !!$("#sup-reply-file") && !!$("#sup-poll"), "support: conversation modal with thread, reply box, attachment input, poll button");
  $("#sup-reply-text").value = "پیگیری از دسکتاپ"; $("#sup-reply").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })); await sleep(1500);
  const conv = await (await fetch(BASE + `/api/support/tickets/${t.id}/messages`, { headers: H })).json();
  check(conv.messages.some((m) => m.direction === "OUT" && m.text === "پیگیری از دسکتاپ"), "support: follow-up stored (status " + (conv.messages[0] || {}).status + ")");
  check(/پیگیری از دسکتاپ/.test(($("#sup-thread") || {}).textContent || ""), "support: thread re-rendered with the follow-up");
  check(!!$("#nav-sup-badge"), "support: nav badge element exists");
  console.log(errors.length ? `\n${errors.length} FAILED` : "\nALL PASS"); process.exit(errors.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
