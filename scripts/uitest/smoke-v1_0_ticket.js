/**
 * v1.0.0 (RASA) — بازبینی باگ «ثبت تیکت پشتیبانی از ویندوز» در رابط واقعی.
 *
 * شکایت مالک: «در بخش پشتیبانی ویندوز، ارسال تیکت خطا می‌دهد و ثبت نمی‌شود»
 * (روی اندروید سالم بود — چون حالت مستقل گوشی تیکت را مستقیم به رله می‌فرستد و
 * از بک‌اند عبور نمی‌کند).
 *
 * این تست سه چیز را می‌سنجد:
 *   ۱) مسیر سالم: فرم → ثبت → تیکت واقعاً در سرور ساخته می‌شود.
 *   ۲) *همان* حالت خرابی ویندوز: متد Geolocation هرگز پاسخ نمی‌دهد (در پوستهٔ
 *      دسکتاپ WebView2 پنجرهٔ اجازهٔ دسترسی مدیریت نمی‌شود). پیش از اصلاح،
 *      پرامیس هرگز settle نمی‌شد و دکمه تا ابد «در حال آماده‌سازی…» می‌ماند.
 *      حالا باید تیکت *بدون* موقعیت مکانی ثبت شود.
 *   ۳) فهرست انواع درخواست نباید به پاسخ سرور گره بخورد (اگر `types` نیامد،
 *      فرم با فهرست داخلی کار می‌کند).
 *
 * پیش‌نیاز: سرور زنده روی :8000 با `SUPERMARKET_LICENSE_GATE=0`.
 * اجرا:     cd scripts && npm run smoke-v100-ticket
 */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const BASE = process.env.BASE || "http://127.0.0.1:8000";
const FE = path.join(__dirname, "..", "..", "frontend");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
const ok = (label, cond, extra = "") => {
  console.log(`${cond ? "✅" : "❌"} ${label}${extra ? " — " + extra : ""}`);
  if (!cond) problems.push(label);
};

async function boot({ geolocation }) {
  const token = (await (await fetch(BASE + "/api/auth/login", {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "username=admin&password=admin123",
  })).json()).access_token;
  const dom = new JSDOM(fs.readFileSync(FE + "/index.html", "utf8"),
    { url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  window.addEventListener("error", (e) => problems.push("onerror: " + e.message));
  window.fetch = async (i, init) => fetch(typeof i === "string" && i.startsWith("http") ? i : BASE + i, init);
  window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
  window.navigator.serviceWorker = { register: async () => {} };
  window.requestAnimationFrame = (f) => setTimeout(f, 16);
  window.localStorage.setItem("token", token);
  window.sessionStorage.setItem("sm.loading.fast", "3");
  if (geolocation) window.navigator.geolocation = geolocation;
  window.eval(["jalali.js", "sfx.js", "onboarding.js", "app.js"].map((f) => fs.readFileSync(FE + "/" + f, "utf8")).join("\n;"));
  for (let i = 0; i < 40; i++) { await sleep(250); if (!window.document.querySelector("#app-view").classList.contains("hidden")) break; }
  return { window, token };
}

async function submit(window, { subject, withGeo }) {
  await window.go("support");
  await sleep(800);
  const d = window.document;
  d.querySelector("#sup-subject").value = subject;
  d.querySelector("#sup-desc").value = "بررسی خودکار مسیر ثبت درخواست پشتیبانی (RASA v1.0.0).";
  const geo = d.querySelector("#sup-geo");
  if (withGeo) geo.checked = true;
  d.querySelector("#sup-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  // ثبت درخواست نباید گروگانِ موقعیت مکانی باشد: حداکثر ۶ ثانیه صبر می‌کنیم و
  // همان‌طور که کاربر می‌بیند، «فعال‌شدن دکمه» را نشانهٔ پایان کار می‌گیریم.
  for (let i = 0; i < 30; i++) { await sleep(200); if (!d.querySelector("#sup-send").disabled) break; }
  await sleep(300);
  return {
    button: d.querySelector("#sup-send"),
    toast: (d.querySelector("#toast") || {}).textContent || "",
    status: (d.querySelector("#sup-status") || {}).textContent || "",
    list: (d.querySelector("#sup-list") || {}).textContent || "",
  };
}

(async () => {
  // ---------- ۱) مسیر سالم با موقعیت مکانی ----------
  {
    const { window, token } = await boot({
      geolocation: { getCurrentPosition: (ok) => ok({ coords: { latitude: 35.7, longitude: 51.4, accuracy: 25 } }) },
    });
    const r = await submit(window, { subject: "خرابی تست دسکتاپ", withGeo: true });
    const tickets = await (await fetch(BASE + "/api/support/tickets?limit=5", { headers: { Authorization: "Bearer " + token } })).json();
    const mine = tickets.find((t) => t.subject === "خرابی تست دسکتاپ");
    ok("تیکت از فرم ویندوز ثبت شد", !!mine, mine ? mine.number : "پیدا نشد");
    ok("موقعیت مکانی در تیکت ذخیره شد", !!mine && mine.latitude !== null, mine ? String(mine.latitude) : "—");
    ok("دکمهٔ ارسال پس از ثبت دوباره فعال است", r.button && r.button.disabled === false);
    ok("فهرست درخواست‌های قبلی تازه شد", /خرابی تست دسکتاپ/.test(r.list));
  }

  // ---------- ۲) همان سناریوی خرابی ویندوز: موقعیت مکانی هرگز پاسخ نمی‌دهد ----------
  {
    const { window, token } = await boot({
      // دقیقاً همان چیزی که در WebView2 دیده می‌شد: هیچ callbackی صدا زده نمی‌شود.
      geolocation: { getCurrentPosition: () => {} },
    });
    const started = Date.now();
    const r = await submit(window, { subject: "خرابی تست بدون پاسخ موقعیت مکانی", withGeo: true });
    const elapsed = Date.now() - started;
    const tickets = await (await fetch(BASE + "/api/support/tickets?limit=5", { headers: { Authorization: "Bearer " + token } })).json();
    const mine = tickets.find((t) => t.subject === "خرابی تست بدون پاسخ موقعیت مکانی");
    ok("تیکت حتی وقتی موقعیت مکانی پاسخ نمی‌دهد ثبت می‌شود", !!mine, mine ? mine.number : "پیدا نشد");
    ok("ثبت در مهلت معقول تمام شد (پرامیس معلق نماند)", elapsed < 12000, `${(elapsed / 1000).toFixed(1)} ثانیه`);
    ok("دکمه در حالت «در حال آماده‌سازی…» گیر نکرد", !/آماده‌سازی/.test(r.status), r.status || "—");
    ok("دکمه پس از ثبت فعال شد", r.button && r.button.disabled === false);
    ok("موقعیت مکانی ذخیره نشد ولی تیکت کامل است", !!mine && mine.latitude === null);
  }

  // ---------- ۳) فهرست انواع باید مستقل از سرور کار کند ----------
  {
    const { window } = await boot({});
    const realFetch = window.fetch;
    window.fetch = async (i, init) => {
      const u = typeof i === "string" ? i : (i && i.url) || "";
      if (/\/api\/support\/types/.test(u)) return new Response("{}", { status: 500, headers: { "Content-Type": "application/json" } });
      return realFetch(i, init);
    };
    const meta = await window.supMeta(true);
    ok("اگر سرور فهرست انواع را ندهد، فهرست داخلی جایگزین می‌شود", meta.degraded === true && meta.types.length >= 5,
       `${meta.types.length} نوع`);
  }

  console.log(problems.length ? `\n❌ ${problems.length} مشکل` : "\n✅ مسیر ثبت درخواست پشتیبانی در ویندوز سالم است");
  process.exit(problems.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
