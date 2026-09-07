/* v1.3 smoke: Jalali date fields, receiving suggestions, stocktake wizard, alarms. */
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
  window.confirm = () => true;
  const tok = (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" })).json()).access_token;
  window.localStorage.setItem("token", tok);
  const H = { Authorization: "Bearer " + tok, "Content-Type": "application/json" };
  window.eval(fs.readFileSync(FE + "/jalali.js", "utf8"));
  window.eval(fs.readFileSync(FE + "/app.js", "utf8"));
  await new Promise((r) => setTimeout(r, 800));
  const $ = (s) => window.document.querySelector(s); const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const check = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) errors.push(m); };

  // Jalali lib
  check(window.Jalali.toIso("1403/06/15") === "2024-09-05", "Jalali.toIso 1403/06/15 -> 2024-09-05");
  check(window.Jalali.fromIso("2024-09-05") === "۱۴۰۳/۰۶/۱۵", "Jalali.fromIso -> ۱۴۰۳/۰۶/۱۵");
  check(window.Jalali.toIso("1403/12/31") === null, "1403 is not leap -> 12/31 invalid");

  // seed: product + batch via API
  await fetch(BASE + "/api/products/import/starter", { method: "POST", headers: H });
  const prods = (await (await fetch(BASE + "/api/products?limit=3", { headers: H })).json()).items;
  const p = prods[0];
  await fetch(BASE + "/api/batches/receive", { method: "POST", headers: H, body: JSON.stringify({ product_id: p.id, quantity_received: 5, buy_price: 1000, sell_price: 1500, expiry_date: "2027-01-15" }) });

  // receiving view
  await window.go("batches"); await sleep(500);
  check(!!$("#b-barcode") && !!$("#b-suggest"), "receiving: barcode box + suggestion host");
  check($("#b-supplier") && $("#b-supplier").tagName === "SELECT", "receiving: supplier is a dropdown (v1.4 accounting)");
  check($("#b-expiry") && $("#b-expiry").type === "hidden" && !!$(".jdate"), "receiving: expiry is Jalali field");
  check(($("#view").textContent || "").includes("۱۴۰۵/۱۰/۲۵"), "recent batches show Jalali expiry (2027-01-15 -> ۱۴۰۵/۱۰/۲۵)");
  const bi = $(".jdate"); bi.value = "1405/01/01"; bi.dispatchEvent(new window.Event("input", { bubbles: true }));
  check($("#b-expiry").value === "2026-03-21", "typing 1405/01/01 -> hidden ISO 2026-03-21");
  $("#b-barcode").value = p.name.slice(0, 3); $("#b-barcode").dispatchEvent(new window.Event("input", { bubbles: true })); await sleep(700);
  check($("#b-suggest").querySelectorAll(".sug").length > 0 && !$("#b-suggest").classList.contains("hidden"), "receiving: live suggestions appear for partial name");
  $("#b-suggest .sug").click(); await sleep(200);
  check(!$("#b-picked").classList.contains("hidden") && $("#b-picked").textContent.includes(p.name.slice(0, 3)), "receiving: clicking suggestion selects product");

  // inventory: plan a stocktake with Jalali date (today) -> wizard
  await window.go("inventory"); await sleep(700);
  check(!!$("#st-date") && $("#st-date").type === "hidden", "inventory: schedule date is Jalali field");
  $("#st-name").value = "تست v1.3"; $("#st-date").value = window.Jalali.todayIso(); $("#st-note").value = "یادآوری تست";
  $("#st-create").click(); await sleep(1200);
  check(!!$(".st-wiz"), "wizard opened after creating a stocktake for today");
  check(!!$(".st-card h2") && !!$(".st-input"), "wizard shows product name + count input");
  check(!!$(".st-progress .progress"), "wizard shows progress bar");
  const inp = $(".st-input"); inp.value = String(Number(inp.dataset.sys) + 1); inp.dispatchEvent(new window.Event("input", { bubbles: true }));
  check($(`[data-diff="${inp.dataset.item}"]`).textContent.includes("+1"), "live difference shows +1");
  $("#st-save").click(); await sleep(900);
  if (errors.length) console.log("JS ERRORS:", errors); check(!errors.length, "no JS errors after save & next");
  // alarms visible on dashboard + inventory
  await window.go("dashboard"); await sleep(900);
  check(!!$("#dash-alarms .alarm"), "dashboard shows stocktake alarm strip");
  await window.go("inventory"); await sleep(900);
  check(!!$("#st-alarms .alarm") && $("#st-alarms").textContent.includes("یادآوری تست"), "inventory shows alarm with reminder note");
  check(($("#st-list").textContent || "").includes("در حال شمارش"), "session list uses Persian status");

  if (errors.length) { console.log("ERRORS:"); errors.forEach((e) => console.log(" -", e)); process.exit(1); }
  console.log("V1.3 SMOKE OK"); process.exit(0);
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
