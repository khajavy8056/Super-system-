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
  window.SupermarketAndroid = { getServerUrl: () => BASE, getDeviceToken: () => "", getDeviceId: () => "dev-smoke-1", getStoreName: () => "", version: () => "1.6.0", isPaired: () => true, pair() {}, unpair() {}, exitApp() {} };
  window.localStorage.setItem("m_token", token);
  window.confirm = () => true;
  try { window.eval(fs.readFileSync(FE + "/mobile/app.js", "utf8")); } catch (e) { errors.push("eval: " + e.message); }
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
  if (errors.length) { console.log("ERRORS:"); errors.forEach((e) => console.log(" -", e)); process.exit(1); }
  console.log("ANDROID SMOKE OK"); process.exit(0);
})();
