/* v1.5 smoke (needs server on :8000 with SUPERMARKET_LICENSE_SERVER=http://127.0.0.1:8099/ and license_stub.py):
   setup wizard, licence gate, loading, alerts, settings licence tab. */
const { JSDOM } = require("jsdom"); const fs = require("fs"); const path = require("path");
const BASE = "http://127.0.0.1:8000"; const FE = path.join(__dirname, "..", "..", "frontend");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errors = []; const check = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) errors.push(m); };
  const H = { "Content-Type": "application/json" };
  // reset licence/setup through API (admin)
  // make sure we can log in (activate with the good key first), then clear the licence to test the gate
  await fetch(BASE + "/api/setup/license/activate", { method: "POST", headers: H, body: JSON.stringify({ key: "KEY-TEST-GOOD-0001" }) });
  const tok = (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).json()).access_token;
  const A = { ...H, Authorization: "Bearer " + tok };
  // gate
  let r = await fetch(BASE + "/api/setup/license", { method: "DELETE", headers: A }); check(r.status === 200, "licence cleared by admin");
  r = await fetch(BASE + "/api/products", { headers: A });
  check((await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).status === 402, "login itself blocked without licence");
  check(r.status === 402, "API blocked with 402 without licence");
  r = await fetch(BASE + "/api/setup/license/activate", { method: "POST", headers: H, body: JSON.stringify({ key: "KEY-TEST-MAXD-0001" }) });
  check(r.status === 422 && (await r.json()).detail.code === "MAX_DEVICES_REACHED", "server rejection surfaced (MAX_DEVICES_REACHED)");
  r = await fetch(BASE + "/api/setup/license/activate", { method: "POST", headers: H, body: JSON.stringify({ key: "KEY-TEST-GOOD-0001" }) });
  const st = await r.json(); check(r.status === 200 && st.allowed && st.type === "FULL", "activation succeeds and caches (type FULL)");
  check((await fetch(BASE + "/api/products", { headers: A })).status === 200, "API open after activation");

  // UI: wizard when setup not done (simulate by DOM boot with status override)
  const dom = new JSDOM(fs.readFileSync(FE + "/index.html", "utf8"), { url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom; window.addEventListener("error", (e) => errors.push("onerror: " + e.message));
  window.fetch = async (i, init) => fetch(typeof i === "string" && i.startsWith("http") ? i : BASE + i, init);
  window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} }); window.navigator.serviceWorker = { register: async () => {} };
  window.requestAnimationFrame = (f) => setTimeout(f, 16); window.__NO_AUTOBOOT = true; window.print = () => {};
  window.sessionStorage.setItem("sm.loading.fast", "3");
  window.eval(fs.readFileSync(FE + "/jalali.js", "utf8") + "\n;" + fs.readFileSync(FE + "/onboarding.js", "utf8") + "\n;" + fs.readFileSync(FE + "/app.js", "utf8"));
  const $ = (s) => window.document.querySelector(s); const $$ = (s) => [...window.document.querySelectorAll(s)];
  await window.Onboarding.wizard(() => {}); await sleep(200);
  check(!!$(".ob-wiz") && $$("#ob-steplist li").length === 10, "wizard renders with 10 steps");
  check($("#ob-skip").style.display === "none", "welcome step has no skip");
  $("#ob-next").click(); await sleep(200);
  check(/لایسنس فعال است/.test($("#ob-pane-body").textContent), "licence step shows active licence");
  $("#ob-next").click(); await sleep(200); check(!!$("#w-store"), "store step"); $("#w-store").value = "فروشگاه اسموک";
  check($("#ob-skip").style.display !== "none", "store step is skippable");
  $("#ob-next").click(); await sleep(200); check(!!$("#w-logo-drop"), "logo step"); $("#ob-skip").click(); await sleep(150);
  check(!!$("#w-phone"), "contact step"); $("#ob-skip").click(); await sleep(150);
  check($$('input[name="w-cur"]').length === 2, "currency step"); $("#ob-next").click(); await sleep(150);
  check($$('input[name="w-theme"]').length === 3 && $$('input[name="w-paper"]').length === 3, "theme+paper step"); $("#ob-next").click(); await sleep(150);
  check(!!$("#w-starter"), "catalog step"); $("#ob-next").click(); await sleep(150);
  check(!!$("#w-admin-user") && $("#ob-skip").style.display === "none", "admin step (not skippable)");
  $("#w-admin-user").value = "a"; $("#w-admin-pass").value = "123"; $("#w-admin-pass2").value = "123"; $("#ob-next").click(); await sleep(150);
  check(!!$("#w-admin-user"), "weak admin creds rejected client-side");
  $("#w-admin-user").value = "admin"; $("#w-admin-pass").value = "admin123"; $("#w-admin-pass2").value = "admin123"; $("#ob-next").click(); await sleep(200);
  check(/همه‌چیز آماده است/.test($("#ob-pane-body").textContent) && /فروشگاه اسموک/.test($("#ob-pane-body").textContent), "finish summary shows entered data");
  // loading screen
  await new Promise((res) => window.Onboarding.__test_loading ? res() : (window.Onboarding.closeOverlay(), res()));
  let done = false; window.eval("Onboarding._ls = null");
  // exercise loadingScreen via afterLogin with a valid token
  window.localStorage.setItem("token", tok); window.sessionStorage.removeItem("sm.loading.session");
  const p = window.Onboarding.afterLogin(); await sleep(400);
  check(!!$(".ob-load") && !!$("#ob-phases") && $$("#ob-phases li").length >= 5, "loading screen with phases visible after login");
  await p; check(!$(".ob-load") || $("#ob-overlay").classList.contains("hidden"), "loading finishes and closes");
  // alerts stack
  window.Onboarding.alertsStack(); await sleep(800);
  check($$("#ob-alerts .ob-alert").length >= 1, "bottom alert stack rendered (" + $$("#ob-alerts .ob-alert").length + ")");
  check($$("#ob-alerts .ob-alert").some((a) => /لایسنس/.test(a.textContent)), "licence countdown alert present");
  const x = $("#ob-alerts .ob-alert-x"); const n = $$("#ob-alerts .ob-alert").length; x.click(); await sleep(50);
  check($$("#ob-alerts .ob-alert").length === n - 1, "alert dismiss works");
  // settings licence tab
  const card = window.document.createElement("div"); window.document.body.append(card);
  await window.Onboarding.licensePanel(card);
  check(/فعال/.test(card.textContent) && /FULL/.test(card.textContent) && !!card.querySelector("#lic-recheck"), "settings licence panel renders");
  if (errors.length) { console.log("ERRORS:"); errors.forEach((e) => console.log(" - " + e)); process.exit(1); }
  console.log("V1.5 SMOKE OK"); process.exit(0);
})().catch((e) => { console.error("CRASH", e); process.exit(2); });
