/* v1.6 smoke (server on :8000 with licence active + setup done): held invoices (F6 dock),
   exit-with-backup, fullscreen/exit buttons, settings → موبایل pairing tab, new sounds. */
const { JSDOM } = require("jsdom"); const fs = require("fs"); const path = require("path");
const BASE = "http://127.0.0.1:8000"; const FE = path.join(__dirname, "..", "..", "frontend");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errors = []; const check = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) errors.push(m); };
  const H = { "Content-Type": "application/json" };
  const tok = (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).json()).access_token;
  const A = { ...H, Authorization: "Bearer " + tok };
  const dom = new JSDOM(fs.readFileSync(FE + "/index.html", "utf8"), { url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom; window.addEventListener("error", (e) => errors.push("onerror: " + e.message));
  window.fetch = async (i, init) => fetch(typeof i === "string" && i.startsWith("http") ? i : BASE + i, init);
  window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} }); window.navigator.serviceWorker = { register: async () => {} };
  window.requestAnimationFrame = (f) => setTimeout(f, 16); window.print = () => {}; window.confirm = () => true; window.URLSearchParams = URLSearchParams; /* jsdom→node fetch interop */
  window.localStorage.setItem("token", tok); window.sessionStorage.setItem("sm.loading.fast", "3"); window.localStorage.removeItem("sm.held");
  window.eval(fs.readFileSync(FE + "/jalali.js", "utf8") + "\n;" + fs.readFileSync(FE + "/sfx.js", "utf8") + "\n;" + fs.readFileSync(FE + "/onboarding.js", "utf8") + "\n;" + fs.readFileSync(FE + "/app.js", "utf8"));
  const $ = (s) => window.document.querySelector(s); const $$ = (s) => [...window.document.querySelectorAll(s)];
  await sleep(5500); // fast loading (3s) + boot
  check(!$("#app-view").classList.contains("hidden"), "app booted to dashboard");
  check(["welcome", "void", "hold", "resume", "exit", "note"].every((n) => window.Sfx.names.includes(n)), "v1.6 sounds registered (welcome/void/hold/resume/exit/note)");
  await window.go("pos"); await sleep(700);
  check(!!$("#pos-hold-btn") && !!$("#pos-held"), "POS has hold button + held dock");
  const sr = await (await fetch(BASE + "/api/pos/search?q=%D8%A2%D8%A8&limit=5", { headers: A })).json();
  const found = (sr.items || []).find((i) => i.batches && i.batches.length);
  check(!!found, "search returns a product with a batch for the hold test");
  if (found) {
    const item = { id: found.product_id, name: found.name, image_url: found.image_url, unit_id: null }; const b0 = found.batches[0];
    const push = (n) => window.eval(`posPushCart(${JSON.stringify(item)}, ${JSON.stringify(b0)}, ${n})`);
    push(1); await sleep(50);
    window.posHold("مشتری آزمون"); await sleep(50);
    check($$("#pos-held .held-chip").length === 1 && $("#pos-cart-table").textContent.includes("سبد خالی"), "hold parks the cart into a dock chip and empties the cart");
    push(2); await sleep(50);
    $("#pos-held .held-main").click(); await sleep(80);
    check($$("#pos-held .held-chip").length === 1 && /مشتری آزمون/.test($("#pos-cart-title").textContent + $("#pos-held").textContent) , "resume swaps: restored invoice back, current one auto-parked");
    check(JSON.parse(window.localStorage.getItem("sm.held") || "[]").length === 1, "held invoices persisted in localStorage");
    for (let i = 0; i < 12; i++) { push(1); window.posHold(); }
    check(JSON.parse(window.localStorage.getItem("sm.held")).length === 10, "hold cap = 10 invoices");
    const firstId = JSON.parse(window.localStorage.getItem("sm.held"))[0].id;
    window.posDropHeld(firstId); await sleep(30);
    check(JSON.parse(window.localStorage.getItem("sm.held")).length === 9, "drop a held invoice from the dock");
    window.localStorage.removeItem("sm.held");
  }
  check(!!$("#sb-full") && !!$("#sb-exit") && typeof window.toggleFullscreen === "function" && typeof window.exitPrompt === "function", "status bar has fullscreen + exit buttons");
  window.exitPrompt(); await sleep(50); check(!!$("#exit-app") && !!$("#exit-logout"), "exit prompt offers logout / close-with-backup");
  $("#exit-app").click(); await sleep(300);
  check(!!$("#exit-overlay") && /در حال بستن برنامه/.test($("#exit-overlay").textContent) && !/دقیقه/.test($("#exit-overlay").textContent), "exit loading overlay shown (no minutes text)");
  await sleep(3800);
  check(!$("#exit-overlay") && !$("#login-view").classList.contains("hidden"), "browser mode: after backup the app returns to login");
  const bks = await (await fetch(BASE + "/backups", { headers: A })).json(); check(bks.length >= 1, "backup file exists after exit (" + bks.length + ")");
  // settings → mobile
  $("#login-username").value = "admin"; $("#login-password").value = "admin123"; window.sessionStorage.removeItem("sm.loading.session");
  $("#login-form").dispatchEvent(new window.Event("submit", { cancelable: true })); await sleep(5500);
  check(!$("#app-view").classList.contains("hidden"), "re-login works after exit");
  await window.go("settings"); await sleep(800);
  const mobTab = $$(".set-tab").find((b) => /موبایل/.test(b.textContent)); check(!!mobTab, "settings has a موبایل tab");
  if (mobTab) { mobTab.click(); await sleep(1200); check(!!$("#mob-qr img") || !!$("#mob-qr textarea"), "pairing QR rendered"); check(/http:\/\//.test($("#mob-info").textContent), "LAN address shown"); check(!!$("#mob-devs table"), "paired device listed"); }
  // sounds card has new tests
  const themeTab = $$(".set-tab").find((b) => /ظاهر/.test(b.textContent)); if (themeTab) { themeTab.click(); await sleep(400); check(!!$("#sfx-test-welcome") && !!$("#sfx-test-void"), "sounds card offers welcome/void tests"); }
  if (errors.length) { console.log("ERRORS:"); errors.forEach((e) => console.log(" - " + e)); process.exit(1); }
  console.log("V1.6 SMOKE OK"); process.exit(0);
})().catch((e) => { console.error("CRASH", e); process.exit(2); });
