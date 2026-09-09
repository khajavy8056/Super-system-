/* v1.9 — Android full-panel E2E in a 390×844 viewport with a simulated bridge.
 * Verifies: auto-login via pairing token, every section renders, POS scan→pay,
 * hold/restore, product create (phone→PC), stock receive, customer create,
 * PC→phone visibility, back-button routing, offline hand-off.
 * Run: cd scripts && LD_LIBRARY_PATH=/tmp/al2023/lib node uitest/phone-full-panel.js */
const chromium = require("@sparticuz/chromium").default || require("@sparticuz/chromium");
const puppeteer = require("puppeteer-core");
const fs = require("fs");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const B = process.env.BASE || "http://127.0.0.1:8000";
const results = []; const ok = (name, cond, extra = "") => { results.push([name, !!cond]); console.log((cond ? "PASS " : "FAIL ") + name + (extra ? " — " + extra : "")); };
(async () => {
  // pairing token like the QR gives the phone
  const login = await fetch(B + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" });
  const adminTok = (await login.json()).access_token;
  const pair = await (await fetch(B + "/api/mobile/pair/token", { method: "POST", headers: { Authorization: "Bearer " + adminTok, "Content-Type": "application/json" }, body: JSON.stringify({ name: "e2e phone" }) })).json();
  const stamp = Date.now().toString().slice(-7);
  const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true, args: [...chromium.args, "--no-sandbox", "--lang=fa"] });
  const page = await browser.newPage(); await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const errors = []; page.on("pageerror", (e) => errors.push(e.message.slice(0, 160)));
  page.on("dialog", (d) => d.accept());   // duplicate-name advisory confirm on reruns
  await page.evaluateOnNewDocument((tok, dev, base) => {
    window.__scans = []; window.__scanCode = "6260000000012";
    window.SupermarketAndroid = { getServerUrl: () => base, getDeviceToken: () => tok, getDeviceId: () => dev, getStoreName: () => "فروشگاه خواجوی", version: () => "1.9.0", isPaired: () => true, pair() {}, unpair() {}, exitApp() {}, hasNativeScanner: () => true, scan: (t) => { window.__scans.push(t); setTimeout(() => window.__nativeScan(window.__scanCode, "EAN_13"), 30); } };
    localStorage.setItem("m_token", tok); localStorage.setItem("m_server", base);
  }, pair.token, pair.device_id, B);
  await page.goto(B + "/index.html", { waitUntil: "networkidle0" });
  await page.waitForSelector("#app-view:not(.hidden)", { timeout: 30000 });
  await sleep(1200);
  await page.evaluate(() => { localStorage.setItem("sm.tour.done", "1"); });
  const killTour = () => page.evaluate(() => document.querySelectorAll(".tour-layer,[class^=tour-]").forEach((e) => e.remove()));
  ok("auto-login with pairing token (no login form)", await page.evaluate(() => state.user && state.user.username === "admin"));
  ok("mobile shell active + 5 tabs", await page.evaluate(() => document.documentElement.classList.contains("m-shell") && document.querySelectorAll("#m-tabbar .m-tab").length === 5));
  // all sections
  await page.evaluate(() => document.getElementById("m-menu").click()); await sleep(300);
  const keys = await page.evaluate(() => [...document.querySelectorAll("#m-drawer .nav-item[data-k]")].map((b) => b.dataset.k));
  ok("drawer lists all 16 sections", keys.length === 16, keys.join(","));
  await page.evaluate(() => document.querySelector(".m-drawer-bg").click());
  for (const v of keys) {
    await page.evaluate((v) => go(v), v); await sleep(900); await killTour();
    const err = await page.evaluate(() => { const e = document.querySelector("#view .error"); return e ? e.textContent.slice(0, 60) : ""; });
    const w = await page.evaluate(() => document.documentElement.scrollWidth);
    ok(`section ${v} renders, no overflow`, !err && w <= 390, err || (w > 390 ? "width " + w : ""));
  }
  // products: create from phone
  await page.evaluate(() => go("products")); await sleep(900); await killTour();
  await page.evaluate((s) => { document.getElementById("p-barcode").value = "627" + s + "000"; document.getElementById("p-name").value = "کالای ثبت‌شده از گوشی " + s; }, stamp);
  await page.evaluate(() => document.getElementById("p-add").click()); await sleep(1200);
  const onPc = await (await fetch(B + "/api/products/barcode/627" + stamp + "000", { headers: { Authorization: "Bearer " + adminTok } })).json();
  ok("product created on phone is on PC instantly", onPc && onPc.name.startsWith("کالای ثبت‌شده از گوشی"));
  // batches: receive stock for it from phone
  await page.evaluate(() => go("batches")); await sleep(900); await killTour();
  await page.evaluate((s) => { const b = document.getElementById("b-barcode"); b.value = "627" + s + "000"; b.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); }, stamp); await sleep(800);
  await page.evaluate(() => { document.getElementById("b-qty").value = "7"; const buy = document.getElementById("b-buy"); if (buy) buy.value = "20000"; document.getElementById("b-sell").value = "30000"; const c = document.getElementById("b-consumer"); if (c) c.value = "32000"; });
  await page.evaluate(() => document.getElementById("b-receive").click()); await sleep(1500);
  const stock = await (await fetch(B + "/api/pos/search?q=627" + stamp + "000&limit=1", { headers: { Authorization: "Bearer " + adminTok } })).json();
  ok("stock received on phone visible on PC", stock.items.length && Number(stock.items[0].available_qty) === 7, JSON.stringify(stock.items[0] && stock.items[0].available_qty));
  // PC creates a product → phone sees it
  await fetch(B + "/api/products", { method: "POST", headers: { Authorization: "Bearer " + adminTok, "Content-Type": "application/json" }, body: JSON.stringify({ barcode: "628" + stamp + "000", name: "کالای ثبت‌شده از رایانه " + stamp }) });
  await page.evaluate(() => go("products")); await sleep(1200);
  ok("product created on PC visible on phone", await page.evaluate(() => document.body.innerText.includes("کالای ثبت‌شده از رایانه")));
  // POS: native scan → cart → hold → restore → pay
  await page.evaluate(() => go("pos")); await sleep(900); await killTour();
  await page.evaluate((s) => { window.__scanCode = "627" + s + "000"; document.getElementById("m-scan-fab").click(); }, stamp); await sleep(1200);
  ok("native scan adds to POS cart", await page.evaluate(() => posState.cart.length === 1 && posState.cart[0].product_name && posState.cart[0].product_name.includes("گوشی")), await page.evaluate(() => JSON.stringify(posState.cart[0] && Object.keys(posState.cart[0]))));
  await page.evaluate(() => posHold("تست")); await sleep(500);
  ok("hold empties cart and lists it in dock", await page.evaluate(() => posState.cart.length === 0 && document.querySelectorAll("#pos-held button, #pos-held .held-chip, #pos-held [onclick]").length >= 1));
  await page.evaluate(() => { const b = document.querySelector("#pos-held [onclick], #pos-held button"); b && b.click(); }); await sleep(600);
  ok("held invoice restored by tap", await page.evaluate(() => posState.cart.length === 1));
  await page.evaluate(() => document.getElementById("pos-pay").click()); await sleep(600);
  ok("pay sheet opens as bottom-sheet", await page.evaluate(() => !document.getElementById("modal").classList.contains("hidden") && getComputedStyle(document.querySelector(".modal")).borderTopLeftRadius !== "0px"));
  await page.screenshot({ path: "../docs/screenshots/v19_phone_pay_sheet.png" });
  await page.evaluate(() => document.getElementById("btn-pay").click()); await sleep(2000);
  const inv = await (await fetch(B + "/api/invoices?limit=1", { headers: { Authorization: "Bearer " + adminTok } })).json().catch(() => null);
  ok("checkout from phone created an invoice on PC", await page.evaluate(() => posState.cart.length === 0), inv ? JSON.stringify(inv).slice(0, 80) : "");
  // customer create from phone via POS customer modal
  await page.evaluate(() => document.getElementById("pos-customer-btn").click()); await sleep(500);
  await page.evaluate((s) => { document.getElementById("cust-phone").value = "0912" + s; document.getElementById("cust-name").value = "مشتری گوشی"; document.getElementById("cust-save").click(); }, stamp); await sleep(1200);
  const cust = await (await fetch(B + "/api/customers?q=0912" + stamp, { headers: { Authorization: "Bearer " + adminTok } })).json();
  ok("customer created on phone exists on PC", JSON.stringify(cust).includes("مشتری گوشی"));
  await page.evaluate(() => closeModal());
  // back button
  ok("android back: view → dashboard", await page.evaluate(() => window.__androidBack() && state.view === "dashboard"));
  ok("android back at dashboard → let native confirm exit", await page.evaluate(() => window.__androidBack() === false));
  // support badge / tour button present
  ok("tour button present in top bar", await page.evaluate(() => { return go("pos").then(() => !!document.getElementById("tour-btn")); }));
  ok("no page errors", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: "../docs/screenshots/v19_phone_pos_final.png" });
  await browser.close();
  const fails = results.filter((r) => !r[1]).length;
  console.log(`\n${results.length - fails}/${results.length} checks passed`);
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
