/* v1.8 — mobile guided tour: auto on first visit of each screen (keyed by
 * screen title, per user) + permanent «?» button in the top bar. Shares the
 * same spotlight approach as the desktop tour, tuned for touch. */
(function () {
  "use strict";
  const ST = () => (typeof state !== "undefined" ? state : (window.state || null));
  const KEY = () => "m_tour_seen_" + ((ST() && ST().user && ST().user.username) || "anon");
  const seen = () => { try { return JSON.parse(localStorage.getItem(KEY()) || "{}"); } catch (_) { return {}; } };
  const mark = (k) => { const s = seen(); s[k] = 1; localStorage.setItem(KEY(), JSON.stringify(s)); };
  const esc_ = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const T = {
    "خانه": [[".kpi-grid", "آمار امروز", "فروش، تعداد فاکتور و هشدارهای امروز به وقت فروشگاه."], [".btn-row", "دسترسی سریع", "میان‌برهای پرکاربرد."], [".tabbar", "منوی پایین", "فروش، شمارش، انبار و «بیشتر» — با انگشت شست در دسترس."], ["#sync-pill", "همگام‌سازی", "وضعیت اتصال به رایانهٔ فروشگاه؛ بدون اتصال هم کار می‌کنید و بعداً خودکار همگام می‌شود."]],
    "فروش": [["#m-search", "جستجو یا اسکن", "نام یا بارکد را بنویسید یا دکمهٔ دوربین را بزنید؛ اسکن سریع با دوربین گوشی."], [".card", "سبد خرید", "با + و − تعداد را تغییر دهید؛ کالای وزنی مقدار می‌پرسد."], [".pay-bar", "پرداخت و نگه‌داشتن", "پرداخت نقد/کارت، یا فاکتور را نگه دارید و از «بیشتر ← فاکتورهای نگه‌داشته» برگردانید."]],
    "شمارش": [[".card", "انبارگردانی", "شمارش جدید بسازید یا شمارش باز را ادامه دهید؛ آفلاین هم کار می‌کند و بعداً همگام می‌شود."], [".tabbar", "بازگشت", "با منوی پایین به بخش‌های دیگر بروید."]],
    "انبار": [["#inv-q", "جستجوی موجودی", "موجودی هر کالا به تفکیک بچ."], ["#si-barcode", "ورود سریع کالا", "بارکد را اسکن کنید و مقدار و قیمت خرید را وارد کنید تا بچ ثبت شود."], ["#inv-list", "فهرست", "روی هر ردیف بزنید تا اصلاح، ضایعات یا انتقال ثبت کنید."]],
    "بیشتر": [[".menu-list", "همهٔ بخش‌ها", "فاکتورها، مشتریان، گزارش‌ها، حسابداری، تنظیمات، پشتیبانی و…؛ همان امکانات نسخهٔ ویندوز."]],
    "درخواست پشتیبانی": [[".card", "ثبت درخواست", "مشکل یا سؤال را بنویسید؛ با نام فروشگاه و کد نصب ارسال می‌شود."], ["#tk-list", "گفتگو", "پاسخ پشتیبانی زیر هر درخواست می‌آید (💬)؛ می‌توانید عکس یا فایل هم بفرستید."]],
    "گزارش‌ها": [[".card", "گزارش", "نوع و بازهٔ شمسی را انتخاب کنید؛ روزها به وقت فروشگاه گروه‌بندی می‌شوند."]],
    "تنظیمات": [[".card", "تنظیمات", "پروفایل فروشگاه، پول، پیامک، سخت‌افزار، لایسنس و همگام‌سازی."]],
    "فاکتورها": [[".card, #inv", "فاکتورها", "جزئیات، مرجوعی و چاپ مجدد."]],
    "مشتریان": [[".card, #cu", "مشتریان", "بدهی، امتیاز و تسویه."]],
    "حسابداری": [[".card", "حسابداری", "دفتر روزنامه، تراز و سود و زیان."]],
  };
  let cur = null;
  function layer() {
    let o = document.getElementById("mt-layer");
    if (!o) { o = document.createElement("div"); o.id = "mt-layer"; o.className = "mt-layer hidden"; o.innerHTML = `<div class="mt-hole" id="mt-hole"></div><div class="mt-card" id="mt-card"></div>`; document.body.appendChild(o); }
    return o;
  }
  function place() {
    if (!cur) return;
    const [sel, title, body] = cur.steps[cur.i];
    const el = document.querySelector(sel); const o = layer(); o.classList.remove("hidden");
    const hole = document.getElementById("mt-hole"), card = document.getElementById("mt-card");
    let r = null;
    if (el) { el.scrollIntoView({ block: "center" }); r = el.getBoundingClientRect(); hole.style.cssText = `top:${r.top - 6}px;left:${r.left - 6}px;width:${r.width + 12}px;height:${r.height + 12}px;opacity:1`; }
    else hole.style.cssText = "opacity:0";
    const n = cur.steps.length, i = cur.i, fa = (x) => String(x).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
    card.innerHTML = `<div class="mt-head"><span class="mt-step">${fa(i + 1)}/${fa(n)}</span><b>${esc_(title)}</b></div><p>${esc_(body)}</p>
      <div class="mt-actions"><button class="btn" onclick="MTour.end()">رد کردن</button><button class="btn" onclick="MTour.prev()" ${i === 0 ? "disabled" : ""}>قبلی</button><button class="btn btn-primary" onclick="MTour.next()">${i === n - 1 ? "پایان" : "بعدی"}</button></div>`;
    const ch = card.offsetHeight; let top = r ? r.bottom + 10 : innerHeight / 2 - ch / 2;
    if (top + ch > innerHeight - 70) top = r ? Math.max(8, r.top - ch - 10) : 8;
    card.style.top = top + "px";
  }
  function start(key, replay) {
    const def = T[key]; if (!def) return false;
    const steps = def.filter(([s]) => document.querySelector(s)); if (!steps.length) return false;
    cur = { key, steps, i: 0 }; if (!replay) mark(key); place(); return true;
  }
  function end() { if (cur) mark(cur.key); cur = null; const o = document.getElementById("mt-layer"); if (o) o.classList.add("hidden"); }
  function next() { if (!cur) return; if (cur.i >= cur.steps.length - 1) return end(); cur.i++; place(); }
  function prev() { if (cur && cur.i > 0) { cur.i--; place(); } }
  let timer = null;
  function onScreen(title) {
    clearTimeout(timer); if (cur) end();
    const bar = document.querySelector(".topbar"); if (!bar || !T[title]) return;
    if (!bar.querySelector(".mt-btn")) { const b = document.createElement("button"); b.className = "icon-btn mt-btn"; b.textContent = "?"; b.title = "راهنمای این صفحه"; b.setAttribute("aria-label", "راهنما"); b.onclick = () => start(title, true); bar.appendChild(b); }
    if (!seen()[title]) timer = setTimeout(() => start(title), 600);
  }
  // observe topbar title changes (screens re-render #app innerHTML)
  const mo = new MutationObserver(() => { const h = document.querySelector(".topbar h1"); if (h) onScreen(h.textContent.trim()); });
  document.addEventListener("DOMContentLoaded", () => { const app = document.getElementById("app"); if (app) mo.observe(app, { childList: true }); });
  window.MTour = { start, end, next, prev, onScreen, reset: () => localStorage.removeItem(KEY()) };
})();
