/* v1.7 smoke (server on :8000, gate off): support view (types, form, geo, list), settings → موبایل shows a real
   SVG QR that decodes with jsQR to the pairing payload, settings → ابر panel renders. */
const { JSDOM } = require("jsdom"); const fs = require("fs"); const path = require("path"); const jsQR = require("jsqr");
const BASE = "http://127.0.0.1:8000"; const FE = path.join(__dirname, "..", "..", "frontend");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errors = []; const check = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) errors.push(m); };
  const tok = (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).json()).access_token;
  const dom = new JSDOM(fs.readFileSync(FE + "/index.html", "utf8"), { url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom; window.addEventListener("error", (e) => errors.push("onerror: " + e.message));
  window.fetch = async (i, init) => fetch(typeof i === "string" && i.startsWith("http") ? i : BASE + i, init);
  window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} }); window.navigator.serviceWorker = { register: async () => {} };
  window.requestAnimationFrame = (f) => setTimeout(f, 16); window.print = () => {}; window.confirm = () => true; window.URLSearchParams = URLSearchParams;
  window.navigator.geolocation = { getCurrentPosition: (ok) => ok({ coords: { latitude: 39.0997, longitude: -94.5786, accuracy: 20 } }) };
  window.localStorage.setItem("token", tok); window.sessionStorage.setItem("sm.loading.fast", "3");
  window.eval(["jalali.js", "vendor-qrcode.js", "sfx.js", "onboarding.js", "app.js"].map((f) => fs.readFileSync(FE + "/" + f, "utf8")).join("\n;"));
  const $ = (s) => window.document.querySelector(s); const $$ = (s) => [...window.document.querySelectorAll(s)];
  let booted = false;
  for (let i = 0; i < 40 && !booted; i++) { await sleep(500); booted = !$("#app-view").classList.contains("hidden"); }
  check(booted, "app booted to dashboard (setup done)");
  check(typeof window.qrcode === "function", "browser QR library loaded (vendor-qrcode.js)");
  // support view
  await window.go("support"); await sleep(900);
  check($$("#sup-type option").length >= 5, "support: request types populated (" + $$("#sup-type option").length + ")");
  $("#sup-subject").value = "چاپگر تست دسکتاپ"; $("#sup-desc").value = "smoke";
  $("#sup-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })); await sleep(1500);
  const list = await (await fetch(BASE + "/api/support/tickets?limit=1", { headers: { Authorization: "Bearer " + tok } })).json();
  check(list[0] && list[0].subject === "چاپگر تست دسکتاپ" && list[0].latitude === 39.0997, "support: ticket stored with exact geo from the form");
  check(/چاپگر تست دسکتاپ/.test($("#sup-list").textContent), "support: previous-tickets list refreshed");
  check(/در انتظار ارسال مجدد|ارسال‌شده|ثبت‌شده/.test($("#sup-list").textContent), "support: delivery status shown in Persian");
  // settings → mobile pairing QR
  await window.go("settings"); await sleep(600);
  const tab = $$(".set-tab").find((b) => /موبایل/.test(b.textContent)); check(!!tab, "settings has موبایل tab"); tab.click(); await sleep(1500);
  const svg = $("#mob-qr svg"); check(!!svg, "pairing QR rendered as SVG in the browser");
  if (svg) {
    // rasterise the SVG rects → decode with jsQR
    const vb = svg.getAttribute("viewBox").split(" ").map(Number); const W = vb[2]; // viewBox units = px (cellSize 4 → 4×4 units per module)
    const img = new Uint8ClampedArray(W * W * 4).fill(255);
    const d = svg.querySelector("path").getAttribute("d"); // qrcode-generator: "Mx,yl4,0 0,4 -4,0 0,-4z" per module
    for (const m of d.matchAll(/M(\d+),(\d+)l(\d+),0/g)) { const x = +m[1], y = +m[2], c = +m[3]; for (let dy = 0; dy < c; dy++) for (let dx = 0; dx < c; dx++) { const o = ((y + dy) * W + x + dx) * 4; img[o] = img[o + 1] = img[o + 2] = 0; } }
    const r = jsQR(img, W, W); check(!!r, "QR decodes with jsQR");
    if (r) { check(r.data.startsWith("SMKT:"), "decoded text has SMKT: prefix (same as the phone parser)"); const p = JSON.parse(Buffer.from(r.data.slice(5).replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8")); check(p.v === 2 && p.token && p.urls.length > 0, "decoded payload is pairing v2 with token + urls"); }
  }
  check(/ورود دستی/.test($("#mob-qr").textContent), "manual text code always offered");
  const ctab = $$(".set-tab").find((b) => /ابر|پشتیبان‌گیری ابری/.test(b.textContent)); check(!!ctab, "settings has cloud tab"); ctab.click(); await sleep(900);
  check(/Google|گوگل/.test($("#set-body").textContent) && ($("#cl-id") || $("#cl-sync")), "cloud panel renders with connect button");
  check(!/undefined|NaN/.test($("#set-body").textContent), "cloud panel has no undefined/NaN");
  // first-login pairing intro (shown once after the wizard): QR + continue closes it
  const pp = window.Onboarding.pairingIntro(); await sleep(1200);
  check(!!$("#ob-pair-qr svg"), "first-login pairing intro shows QR");
  check(!/دقیقه/.test($("#ob-overlay").textContent), "no 'دقیقه' wording on overlay");
  $("#ob-pair-done").click(); await pp; check($("#ob-overlay").classList.contains("hidden"), "pairing intro closes on continue");
  if (errors.length) { console.log("ERRORS:"); errors.forEach((e) => console.log(" - " + e)); process.exit(1); }
  console.log("V1.7 SMOKE OK"); process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
