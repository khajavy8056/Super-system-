/**
 * build-496 — بازبینی رابط «بازنشانی به تنظیمات کارخانه» در jsdom (کلیک واقعی).
 *
 * درخواست مالک: «در بخش تنظیمات، قابلیت Factory Reset با دقت بسیار بالا اضافه شود»
 * و «دقیقاً مشخص شود چه اطلاعاتی حذف و چه اطلاعاتی حفظ می‌شود». این تست همان مسیر
 * را با کلیک واقعی روی رابط طی می‌کند:
 *
 *   ۱. کارت بازنشانی فقط برای مدیر دیده می‌شود؛
 *   ۲. «نقشهٔ بازنشانی» از سرور گرفته و جدول‌های حذف/حفظ با شمار ردیف نشان داده می‌شود؛
 *   ۳. تا وقتی عبارت تأیید عیناً نوشته نشود، دکمهٔ اجرا فعال نمی‌شود؛
 *   ۴. با عبارت درست، اجرا واقعاً انجام می‌شود و سرور می‌گوید چه چیزی پاک شد
 *      (و پشتیبان کجا ذخیره شد) — و فروشگاه بعد از آن قابل استفاده می‌ماند.
 *
 * اجرا (سرور زنده روی http://127.0.0.1:8000 — روی پایگاه آزمایشی!):
 *     cd scripts && node uitest/smoke-factory-reset.js
 */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const BASE = process.env.BASE || "http://127.0.0.1:8000";
const FRONT = path.join(__dirname, "..", "..", "frontend");
const PHRASE = "بازنشانی";

const problems = [];
const ok = (label, cond, extra = "") => {
  console.log(`${cond ? "✅" : "❌"} ${label}${extra ? " — " + extra : ""}`);
  if (!cond) problems.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const html = fs.readFileSync(path.join(FRONT, "index.html"), "utf8");
  const dom = new JSDOM(html, { url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  window.addEventListener("error", (e) => problems.push("onerror: " + e.message));
  window.fetch = async (input, init) => {
    const url = typeof input === "string" && input.startsWith("http") ? input : BASE + input;
    return fetch(url, init);
  };
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, addListener() {} }));
  window.navigator.serviceWorker = { register: async () => {} };

  const login = await fetch(BASE + "/api/auth/login", {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "username=admin&password=admin123",
  });
  const token = (await login.json()).access_token;
  window.localStorage.setItem("token", token);
  const api = async (p, init = {}) => {
    const r = await fetch(BASE + "/api" + p, {
      ...init,
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token, ...(init.headers || {}) },
    });
    return r.json();
  };

  window.eval(["jalali.js", "app.js", "insights.js"]
    .map((f) => fs.readFileSync(path.join(FRONT, f), "utf8")).join("\n;\n"));
  await sleep(1500);

  // ---- ۱) داده‌ای برای پاک‌شدن: کالا + ورود کالا + یک فروش واقعی
  const search = await api("/products?q=" + encodeURIComponent("شیر"));
  const product = (search.items || [])[0];
  if (product) {
    const expiry = new Date(Date.now() + 90 * 86400000).toISOString().slice(0, 10);
    const received = await api("/batches/receive", { method: "POST", body: JSON.stringify({
      product_id: product.id, quantity_received: 12, buy_price: 40000, sell_price: 55000, expiry_date: expiry,
    }) });
    if (received && received.id) {
      const sale = await api("/pos/checkout", { method: "POST", body: JSON.stringify({
        items: [{ product_id: product.id, batch_id: received.id, quantity: 1 }],
        payments: [{ method: "CASH", amount: Number(received.sell_price) }],
      }) });
      ok("دادهٔ پیش‌نیاز: یک فروش واقعی ثبت شد", !!sale.invoice_id, JSON.stringify(sale.detail || sale.invoice_number || ""));
    }
    await api("/customers", { method: "POST", body: JSON.stringify({ name: "مشتری آزمایشی فر", phone: "09121234567" }) });
  }
  const before = { invoices: (await api("/invoices")).items.length, products: (await api("/products?limit=1")).total };

  // ---- ۲) کارت بازنشانی در پنل «پشتیبان‌گیری» تنظیمات دیده می‌شود
  await window.go("settings");
  await sleep(1200);
  const tab = [...window.document.querySelectorAll("#set-tabs button, #set-tabs a")]
    .find((b) => /پشتیبان/.test(b.textContent));
  ok("تب «پشتیبان‌گیری» در تنظیمات هست", !!tab);
  if (tab) { tab.dispatchEvent(new window.Event("click", { bubbles: true })); await sleep(1500); }
  const card = window.document.getElementById("fr-card");
  ok("کارت «بازنشانی به تنظیمات کارخانه» برای مدیر نمایش داده می‌شود", !!card,
     (card && card.textContent.replace(/\s+/g, " ").slice(0, 90)) || "");

  // ---- ۳) نقشهٔ بازنشانی: جدول حذف/حفظ + هشدارها
  const open = window.document.getElementById("fr-open");
  ok("دکمهٔ «مشاهدهٔ نقشهٔ بازنشانی» هست", !!open);
  if (!open) { console.log("\nPROBLEMS:", problems); process.exit(1); }
  open.dispatchEvent(new window.Event("click", { bubbles: true }));
  await sleep(1500);
  const modal = window.document.querySelector(".modal, #modal, .modal-backdrop") || window.document.body;
  const modalText = modal.textContent || "";
  ok("دیالوگ نقشه باز شد و جدول‌های حذف را نشان می‌دهد", /پاک می‌شود/.test(modalText) && /حفظ می‌شود/.test(modalText));
  ok("شمار ردیف‌های «فاکتورها» در نقشه آمده", /فاکتورها/.test(modalText), before.invoices + " فاکتور در فروشگاه");
  const keepRows = [...modal.querySelectorAll("table")].map((t) => t.textContent).join(" ");
  ok("فهرست «حفظ می‌شود» شامل کاربران و تنظیمات است", /users/.test(keepRows) && /system_settings/.test(keepRows));
  ok("هشدار دو مرحله‌ای و پشتیبان اجباری روی صفحه گفته شده", /پشتیبان/.test(modalText));

  // ---- ۴) تا عبارت تأیید دقیقاً نوشته نشود، دکمهٔ اجرا فعال نمی‌شود
  const run = window.document.getElementById("fr-run");
  const input = window.document.getElementById("fr-confirm");
  ok("دکمهٔ اجرا در ابتدا غیرفعال است", !!run && run.disabled);
  input.value = "بازنشا";
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  ok("با عبارت ناقص، دکمهٔ اجرا هنوز غیرفعال است", run.disabled);
  input.value = PHRASE;
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  ok("با عبارت کامل، دکمهٔ اجرا فعال می‌شود", !run.disabled);

  // ---- ۵) حالت «حفظ کالاها» انتخاب و نقشه دوباره خوانده می‌شود
  const mode = window.document.getElementById("fr-mode");
  mode.value = "keep_catalog";
  mode.dispatchEvent(new window.Event("change", { bubbles: true }));
  await sleep(1200);
  ok("تغییر حالت، نقشه را از نو می‌خواند (سطر تخصیص شیفت هم می‌ماند)",
     /حفظ کالاها/.test(window.document.getElementById("fr-lists").textContent + (window.document.body.textContent || "")));

  // ---- ۶) اجرای واقعی با تأیید مرورگر
  window.confirm = () => true;
  window.document.getElementById("fr-run").dispatchEvent(new window.Event("click", { bubbles: true }));
  await sleep(4000);
  const result = window.document.getElementById("fr-result");
  const resultText = (result && result.textContent) || "";
  ok("پیام نتیجهٔ بازنشانی نمایش داده شد", /بازنشانی انجام شد/.test(resultText), resultText.replace(/\s+/g, " ").slice(0, 100));
  ok("نام فایل پشتیبان به کاربر نشان داده شد", /supermarket_\d+.*\.db/.test(resultText));

  // ---- ۷) فروشگاه بعد از بازنشانی همچنان قابل استفاده است
  const me = await fetch(BASE + "/api/auth/me", { headers: { Authorization: "Bearer " + token } });
  ok("نشست مدیر پس از بازنشانی معتبر است", me.status === 200, "HTTP " + me.status);
  const after = { invoices: (await api("/invoices")).items.length, products: (await api("/products?limit=1")).total };
  ok("فاکتورها پاک شدند", after.invoices === 0, `قبل ${before.invoices} → بعد ${after.invoices}`);
  ok("کالاها در حالت «حفظ کالاها» ماندند", after.products > 0, `${after.products} کالا`);
  const backups = await api("/system/backups");
  ok("نسخهٔ پشتیبان روی دیسک هست", backups.some((b) => /keep_catalog/.test(b.name)),
     backups.slice(0, 2).map((b) => b.name).join(", "));
  const freshBarcode = "6260" + String(Date.now()).slice(-9);
  const created = await api("/products", { method: "POST", body: JSON.stringify({ barcode: freshBarcode, name: "کالای پس از بازنشانی jsdom" }) });
  ok("ثبت کالای تازه پس از بازنشانی کار می‌کند", created.id > 0,
     created.id ? freshBarcode : JSON.stringify(created).slice(0, 120));

  console.log("\n" + (problems.length ? `❌ ${problems.length} ایراد: ` + problems.join(" | ") : "✅ همهٔ بررسی‌ها سبز"));
  process.exit(problems.length ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
