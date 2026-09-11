/* Mobile app running inside a simulated Android shell (origin https://app.local,
 * bridge window.SupermarketAndroid) + offline sale queued → /api/mobile/sync. */
const { JSDOM } = require("jsdom");
const fs = require("fs"), path = require("path");
require("fake-indexeddb/auto");
const BASE = "http://127.0.0.1:8000";
const FE = path.join(__dirname, "..", "..", "frontend");
(async () => {
  const login = await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" });
  const token = (await login.json()).access_token;
  const html = fs.readFileSync(FE + "/mobile/index.html", "utf8");
  const dom = new JSDOM(html, { url: "https://app.local/mobile/index.html", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom; const errors = [];
  window.addEventListener("error", (e) => errors.push("onerror: " + e.message));
  window.indexedDB = indexedDB; window.IDBKeyRange = IDBKeyRange;
  let offline = false;
  window.fetch = async (input, init) => {
    if (offline && /\/api\/pos\/checkout/.test(input)) throw new TypeError("Failed to fetch");
    const r = await fetch(input, init);
    if (init && init.headers && r.headers.get("access-control-allow-origin") == null && input.startsWith(BASE + "/api/")) { /* CORS checked separately */ }
    return r;
  };
  window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
  window.navigator.serviceWorker = { register: async () => {} };
  window.SupermarketAndroid = { getServerUrl: () => BASE, getDeviceToken: () => "", getDeviceId: () => "dev-smoke-1", getStoreName: () => "", version: () => "2.5.2", isPaired: () => true, pair() {}, unpair() {}, exitApp() {} };
  window.localStorage.setItem("m_token", token);
  window.confirm = () => true;
  // both files are classic <script> tags in index.html → one shared global lexical scope; eval them together to mirror that
  window.HTMLElement.prototype.scrollIntoView = function () {};
  try { window.eval(fs.readFileSync(FE + "/mobile/vendor/zxing.min.js", "utf8") + "\n" + fs.readFileSync(FE + "/mobile/app.js", "utf8") + "\n" + fs.readFileSync(FE + "/mobile/app-more.js", "utf8") + "\n" + fs.readFileSync(FE + "/mobile/tour.js", "utf8") + "\nwindow.__st = state;"); } catch (e) { errors.push("eval: " + e.message); }
  window.document.dispatchEvent(new window.Event("DOMContentLoaded"));
  window.prompt = () => "مشتری تست"; window.navigator.geolocation = { getCurrentPosition: (ok) => ok({ coords: { latitude: 35.7, longitude: 51.4, accuracy: 9 } }) };
  await new Promise((r) => setTimeout(r, 1500));
  const app = window.document.getElementById("app");
  console.log("native mode API base:", window.SM_MOBILE.API);
  if (window.SM_MOBILE.API !== BASE + "/api") errors.push("API base not taken from bridge");
  console.log("populated:", app.innerHTML.length > 20);
  // CORS preflight from app.local
  const pre = await fetch(BASE + "/api/products", { method: "OPTIONS", headers: { Origin: "https://app.local", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization" } });
  console.log("CORS app.local:", pre.headers.get("access-control-allow-origin"));
  if (pre.headers.get("access-control-allow-origin") !== "https://app.local") errors.push("CORS missing");
  // offline sale
  const prods = await (await fetch(BASE + "/api/products?limit=5", { headers: { Authorization: "Bearer " + token } })).json();
  const list = Array.isArray(prods) ? prods : prods.items || [];
  console.log("products:", list.length);
  offline = true;
  await window.eval(`opQueueAdd("POS_CHECKOUT", {items:[], payments:[{method:"CASH",amount:0}]}, "تست")`);
  await window.eval(`opQueueAdd("CUSTOMER_CREATE", {name:"مشتری اندروید", phone:"0912${Date.now()%10000000}"}, "مشتری")`);
  let ops = await window.eval("opsAll()"); console.log("queued ops:", ops.length);
  offline = false;
  await window.eval("mobileSync(true)");
  ops = await window.eval("opsAll()"); const conf = await window.eval("conflictAll()");
  console.log("after sync queued:", ops.length, "conflicts:", conf.length, conf.map((c) => c.server_message));
  if (ops.length) errors.push("ops not drained");
    await window.eval("showSync()"); await new Promise((r) => setTimeout(r, 300));
  console.log("sync screen mentions PC sync:", app.textContent.includes("همگام‌سازی با رایانه"));
  await window.eval("showSettingsM()"); await new Promise((r) => setTimeout(r, 300));
  console.log("settings shows unpair:", app.textContent.includes("قطع اتصال"));
  // v1.7 — every "More" screen must render without runtime errors (feature parity on the phone)
  const screens = ["showMore","showHeldM","showProducts","showStockOpsM","showWarehousesM","showMovementsM","showCustomersM","showDebtorsM","showInvoicesM","showCampaignsM","showCouponsM","showReportsM","showAccountingM","showUsersM","showStoreM","showSmsM","showHardwareM","showLicenseM","showAuditM","showAboutM","showSupportM","showCloudM","showSync","showSettingsM"];
  let rendered = 0;
  for (const fn of screens) {
    try { await window.eval(`${fn}()`); await new Promise((r) => setTimeout(r, 350)); if (app.textContent.trim().length > 10 && !/undefined/.test(app.textContent)) rendered++; else errors.push("screen empty/undefined: " + fn); }
    catch (e) { errors.push("screen " + fn + ": " + e.message); }
  }
  console.log("mobile screens rendered:", rendered + "/" + screens.length);
  for (const k of ["mReport('sales')","mReport('low-stock')","mReport('expiry')","mExpenses()","mCheques()","mSuppliers()"]) { try { await window.eval(k); await new Promise((r) => setTimeout(r, 300)); } catch (e) { errors.push(k + ": " + e.message); } }
  // held invoices: hold 1 cart, list, resume
  window.eval(`__st.cart = [{product_id: ${list[0] ? list[0].id : 1}, batch_id: 1, name: "x", sell: 1000, qty: 2}]`); window.eval("mHold()");
  await window.eval("showHeldM()"); await new Promise((r) => setTimeout(r, 200));
  console.log("held listed:", app.textContent.includes("مشتری تست"));
  if (!app.textContent.includes("مشتری تست")) errors.push("held invoice not listed");
  // support ticket from the phone (relay unreachable → stored locally as FAILED, retried later)
  await window.eval("showSupportM()"); await new Promise((r) => setTimeout(r, 400));
  window.document.getElementById("tk-subj").value = "تست از گوشی"; window.document.getElementById("tk-send").click();
  await new Promise((r) => setTimeout(r, 1200));
  const tk = await (await fetch(BASE + "/api/support/tickets?limit=1", { headers: { Authorization: "Bearer " + token } })).json();
  console.log("ticket from phone:", tk[0] && tk[0].subject, tk[0] && tk[0].status, "geo:", tk[0] && tk[0].latitude, "device:", tk[0] && tk[0].device);
  if (!tk[0] || tk[0].subject !== "تست از گوشی" || tk[0].latitude !== 35.7 || tk[0].device !== "Android") errors.push("ticket not stored with geo/device");
  // v1.8: ticket conversation screen, ZXing loaded for the camera scanner, tour auto + «?» button
  await window.eval(`showTicketM(${tk[0].id})`); await new Promise((r) => setTimeout(r, 800));
  const conv = app.textContent;
  console.log("ticket conversation screen:", /پیام به پشتیبانی/.test(conv) && !!window.document.getElementById("tk-file") && !!window.document.getElementById("tk-poll"));
  if (!/پیام به پشتیبانی/.test(conv) || !window.document.getElementById("tk-file")) errors.push("ticket conversation screen missing reply/attachment");
  window.document.getElementById("tk-reply").value = "پیگیری از گوشی"; window.document.getElementById("tk-sendr").click(); await new Promise((r) => setTimeout(r, 1200));
  const msgs = await (await fetch(BASE + `/api/support/tickets/${tk[0].id}/messages`, { headers: { Authorization: "Bearer " + token } })).json();
  console.log("follow-up from phone stored:", msgs.messages.some((m) => m.text === "پیگیری از گوشی"));
  if (!msgs.messages.some((m) => m.text === "پیگیری از گوشی")) errors.push("phone follow-up not stored");
  console.log("ZXing engine available to scanner:", typeof window.ZXing === "object" && typeof window.ZXing.MultiFormatReader === "function", "| zxReader():", !!window.eval("zxReader()"));
  if (!window.eval("zxReader()")) errors.push("zxReader() returned null");
  window.localStorage.removeItem("m_tour_seen_admin"); await window.eval("goTab('pos')"); await new Promise((r) => setTimeout(r, 1000));
  const tourAuto = window.document.getElementById("mt-layer") && !window.document.getElementById("mt-layer").classList.contains("hidden");
  const tourBtn = !!window.document.querySelector(".topbar .mt-btn");
  console.log("mobile tour auto on first visit:", tourAuto, "| ? button:", tourBtn, "| step:", tourAuto && window.document.querySelector("#mt-card b").textContent);
  if (!tourAuto || !tourBtn) errors.push("mobile tour not shown");
  window.MTour.end(); await window.eval("goTab('pos')"); await new Promise((r) => setTimeout(r, 900));
  const again = !window.document.getElementById("mt-layer").classList.contains("hidden");
  console.log("mobile tour suppressed on second visit:", !again); if (again) errors.push("tour re-ran");
  window.document.querySelector(".topbar .mt-btn").click(); await new Promise((r) => setTimeout(r, 100));
  console.log("mobile tour replay via ?:", !window.document.getElementById("mt-layer").classList.contains("hidden")); window.MTour.end();
  if (errors.length) { console.log("ERRORS:"); errors.forEach((e) => console.log(" -", e)); process.exit(1); }
  console.log("ANDROID SMOKE OK"); process.exit(0);
})();
