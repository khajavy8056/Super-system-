/**
 * v4.8.0 — بازبینی رابط ویندوز/وب در jsdom (مسیر «پیشنهاد → اجرا»).
 *
 * درخواست مالک: «وقتی روی اجرا می‌زنیم واقعاً کارها انجام شود.» این تست همان کلیک
 * واقعی را انجام می‌دهد: کارت انقضا در صفحهٔ هوش فروشگاه را پیدا می‌کند، دکمهٔ
 * «اجرا کن» را می‌زند، در دیالوگ «اجرا و شروع اندازه‌گیری» را تأیید می‌کند و بعد
 * از سرور می‌پرسد که آیا قیمت بچ واقعاً کم شده و گزارش بازبینی «برقرار» است.
 *
 * اجرا (سرور زنده روی http://127.0.0.1:8000):
 *     cd scripts && node uitest/smoke-v4_8.js
 */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const BASE = process.env.BASE || "http://127.0.0.1:8000";
const FRONT = path.join(__dirname, "..", "..", "frontend");

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

  // همه در یک eval: app.js چیزهایی را با const می‌سازد (مثل RENDER) که فقط در
  // همان دامنه دیده می‌شوند؛ جدا-جدا eval کردن، insights.js را به ReferenceError می‌برد.
  window.eval(["jalali.js", "app.js", "insights.js"]
    .map((f) => fs.readFileSync(path.join(FRONT, f), "utf8")).join("\n;\n"));
  await sleep(1200);

  // ---- ۱) لایهٔ ظاهر جدید واقعاً سرو می‌شود و جای درست بار می‌شود
  const css = await (await fetch(BASE + "/ui-refresh.css")).text();
  ok("ui-refresh.css سرو می‌شود", css.includes(".exp-chip"), `${css.length} بایت`);
  ok("index.html لایهٔ ظاهر را بعد از desktop.css می‌خواند",
     window.document.documentElement.innerHTML.indexOf("desktop.css") <
     window.document.documentElement.innerHTML.indexOf("ui-refresh.css"));

  // ---- ۲) نشان انقضا در انتخاب بچ صندوق: رنگ + ارقام فارسی
  const chip = window.batchExpiryChip({ expiry_date: "2026-10-20", days_left: 3 });
  ok("نشان انقضای فوری کلاس soon و ارقام فارسی دارد",
     chip.includes("exp-chip soon") && chip.includes("۳ روز"), chip.replace(/<[^>]+>/g, "").trim());
  const chipFar = window.batchExpiryChip({ expiry_date: "2026-11-20", days_left: 25 });
  ok("بچ ۲۵ روزه «نزدیک» است نه «فوری»", chipFar.includes("exp-chip near") && chipFar.includes("۲۵"), chipFar.replace(/<[^>]+>/g, "").trim());
  const chipBad = window.batchExpiryChip({ expiry_date: "2026-01-01", days_left: -4 });
  ok("بچ منقضی صریح علامت می‌خورد", chipBad.includes("expired") && chipBad.includes("منقضی"), chipBad.replace(/<[^>]+>/g, "").trim());

  // ---- ۳) صفحهٔ هوش فروشگاه: کارت انقضا با تایم‌لاین
  await window.go("insights");
  await sleep(1500);
  const cards = await api("/insights?status=NEW&limit=100");
  const exp = cards.find((c) => c.kind === "EXPIRY_LADDER" && (c.evidence || {}).mode === "ladder");
  ok("کارت تخفیف پله‌ای انقضا روی صفحه هست", !!exp,
     exp ? `«${exp.title}» — ${(exp.evidence || {}).days_left} روز` : "پیدا نشد");
  ok("تایم‌لاین پله‌ها در شواهد کارت آمده", !!(exp && (exp.evidence || {}).timeline || []).length,
     exp ? JSON.stringify((exp.evidence.timeline || []).map((t) => `${t.jdate}:${t.percent}٪`)) : "");
  const view = window.document.getElementById("view").textContent || "";
  ok("کارت روی صحنه دیده می‌شود (دسکتاپ)", view.includes("روز فرصت دارید") || view.includes("نمی‌فروشد"),
     view.replace(/\s+/g, " ").slice(0, 80));

  // ---- ۴) کلیک واقعی روی «اجرا کن» → تأیید دیالوگ → بررسی نتیجه روی سرور
  const before = (await api(`/batches/${exp.evidence.batch_id}`)).sell_price;
  const buttons = [...window.document.querySelectorAll("#view .ins-card button")]
    .filter((b) => b.textContent.trim() === "اجرا کن");
  ok("دکمهٔ «اجرا کن» روی کارت هست", buttons.length > 0, `${buttons.length} دکمه`);
  if (exp && buttons.length) {
    const cardEl = buttons[0].closest(".ins-card");
    const title = cardEl.querySelector("h4").textContent.trim();
    ok("اولین کارت همان کارت انتخاب‌شده است", title === exp.title, title.slice(0, 50));
    buttons[0].dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(300);
    const go = window.document.getElementById("ins-go");
    ok("دیالوگ اجرا با فهرست اقدام‌ها باز شد", !!go && /اجرا و شروع/.test(go.textContent),
       window.document.querySelectorAll(".ins-act").length + " اقدام");
    go.dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(2500);

    const after = (await api(`/batches/${exp.evidence.batch_id}`)).sell_price;
    ok("قیمت بچ واقعاً کم شد (اجرا کار کرد)", Number(after) < Number(before),
       `${Number(before).toLocaleString("en-US")} → ${Number(after).toLocaleString("en-US")}`);
    const fresh = await api(`/insights/${exp.id}`);
    ok("وضعیت پیشنهاد ACCEPTED شد", fresh.status === "ACCEPTED", fresh.status);
    const rep = await api("/insights/actions/report");
    const row = (rep.rows || []).find((r) => String(r.insight_id) === String(exp.id));
    const health = row && (row.actions || [])[0] && row.actions[0].health;
    ok("سیستم بررسی اجرا «برقرار» می‌گوید", health === "OK",
       row && JSON.stringify(row.actions[0]).slice(0, 140));
    const toast = [...window.document.querySelectorAll(".toast, #toast")]
      .map((t) => t.textContent).join(" ");
    ok("به کاربر پیام موفقیت نشان داده شد", /اجرا شد/.test(toast), toast.slice(0, 80));
  }

  // ---- ۵) نشان «⏰ N روز» در پیشنهاد پای صندوق (نوار نجوا)
  const search = await api("/products?q=" + encodeURIComponent("بیسکویت"));
  const basket = (search.items || []).slice(0, 1).map((p) => p.id);
  const bag = await api("/insights/nudges", {
    method: "POST", body: JSON.stringify({ product_ids: basket }),
  });
  const near = Array.isArray(bag) ? bag.find((n) => n.near_expiry) : null;
  ok("پیشنهاد پای صندوق کالای نزدیک انقضا را با روز باقی‌مانده می‌دهد", !!near,
     near ? `${near.name} — ${near.days_left} روز` : JSON.stringify(bag).slice(0, 120));
  if (near) {
    ok("متن پیشنهاد صندوق ارقام فارسی دارد", /[۰-۹]/.test(near.reason || ""),
       (near.reason || "").slice(0, 70));
    ok("پیشنهاد صندوق بچ و هدف را می‌گوید",
       !!near.batch_id && near.purpose === "sell_before_expiry", `batch=${near.batch_id} purpose=${near.purpose}`);
  }

  if (problems.length) {
    console.log("\n❌ موارد ناموفق:");
    problems.forEach((p) => console.log(" -", p));
    process.exit(1);
  }
  console.log("\n✅ مسیر «پیشنهاد → اجرا» در رابط ویندوز/وب واقعاً کار می‌کند");
  process.exit(0);
})().catch((e) => { console.error("THREW:", e); process.exit(1); });
