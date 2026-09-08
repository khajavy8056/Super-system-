/* v1.8 — guided tour ("راهنمای گام‌به‌گام") for EVERY section.
 *  - Spotlight + card tooltip, keyboard (→ / ← / Esc), RTL-aware positioning.
 *  - Auto-runs the first time a user opens a section (persisted per user);
 *    a permanent «راهنما» button in the top bar replays it any time.
 *  - Steps reference DOM selectors; missing elements are skipped so the tour
 *    never dead-ends when a role hides a card.
 * Loaded after app.js; uses its helpers ($, esc, state). */
(function () {
  "use strict";
  const ST = () => (typeof state !== "undefined" ? state : (window.state || null));  // app.js top-level const
  const KEY = () => "sm.tour.seen." + ((ST() && ST().user && ST().user.username) || "anon");
  const seen = () => { try { return JSON.parse(localStorage.getItem(KEY()) || "{}"); } catch (_) { return {}; } };
  const markSeen = (view) => { const s = seen(); s[view] = Date.now(); localStorage.setItem(KEY(), JSON.stringify(s)); };
  const _esc = (s) => (typeof esc === "function" ? esc(s) : String(s ?? ""));

  /* ---------------------------------------------------------------- step definitions */
  const T = {};
  T.dashboard = { title: "داشبورد", steps: [
    ["#nav", "منوی اصلی", "همهٔ بخش‌های سامانه از این‌جا در دسترس‌اند. بخش فعال پررنگ است؛ نشان قرمز روی «درخواست پشتیبانی» یعنی پاسخ جدید دارید."],
    [".dcard-gauge", "فروش امروز", "مبلغ فروش امروز نسبت به میانگین ماه؛ عقربه پر شود یعنی روز خوبی داشته‌اید."],
    [".dcard-trend", "روند ۷ روز", "نمودار فروش هفت روز اخیر برای مقایسهٔ سریع."],
    [".dcard-expiry", "نزدیک انقضا", "بچ‌هایی که به تاریخ انقضا نزدیک‌اند؛ کلیک کنید تا به انبار بروید و تخفیف یا ضایعات ثبت کنید."],
    [".dcard-low", "کسری موجودی", "کالاهایی که زیر حداقل تعریف‌شده رسیده‌اند و باید سفارش داده شوند."],
    [".dcard-quick", "دسترسی سریع", "میان‌برهای پرکاربرد: صندوق، ورود کالا، انبارگردانی و گزارش‌ها."],
    ["#dash-alarms", "هشدارها", "هشدارهای مهم (انقضا، لایسنس، همگام‌سازی) این‌جا نمایش داده می‌شوند."],
    ["#statusbar", "نوار وضعیت", "وضعیت شبکه، تاریخ شمسی/میلادی به وقت فروشگاه (تهران) و وضعیت سیستم."],
  ] };
  T.pos = { title: "صندوق فروش", steps: [
    ["#pos-scan", "اسکن یا جستجو", "بارکد را اسکن کنید یا نام کالا را بنویسید؛ با Enter به سبد اضافه می‌شود. کالای وزنی مقدار می‌پرسد."],
    ["#pos-cart-table", "سبد خرید", "اقلام فاکتور فعلی؛ روی تعداد بزنید تا ویرایش کنید، Del آخرین قلم را حذف می‌کند."],
    ["#pos-totals", "جمع فاکتور", "جمع، تخفیف و مبلغ قابل پرداخت. در صندوق سود نمایش داده نمی‌شود."],
    ["#pos-pay", "پرداخت (F2)", "نقد، کارت، اعتباری یا ترکیبی؛ بعد از تأیید، رسید چاپ و کشو باز می‌شود."],
    ["#pos-customer-btn", "مشتری (F8)", "مشتری ثبت‌شده را انتخاب کنید تا امتیاز، اعتبار و دفتر بدهی اعمال شود. بدون انتخاب، فروش آزاد است."],
    ["#pos-coupon-btn", "کوپن (F9)", "کد کوپن جشنواره را وارد کنید؛ شرایط آن به‌صورت خودکار بررسی می‌شود."],
    ["#pos-hold-btn", "نگه‌داشتن فاکتور (F6)", "فاکتور نیمه‌تمام را کنار بگذارید (تا ۱۰ فاکتور) و مشتری بعدی را حساب کنید."],
    ["#pos-held", "فاکتورهای نگه‌داشته", "فاکتورهای کنارگذاشته با زمان و مبلغ این‌جا می‌مانند؛ با یک کلیک دوباره باز می‌شوند."],
    ["#pos-kiosk-btn", "قفل صندوق", "حالت تمام‌صفحهٔ صندوق‌دار؛ خروج از آن رمز مدیر می‌خواهد."],
  ] };
  T.products = { title: "کالاها", steps: [
    ["#p-barcode", "بارکد کالا", "بارکد را اسکن کنید؛ اگر کالا بارکد ندارد خالی بگذارید تا بارکد داخلی INT-000001 ساخته شود."],
    ["#p-category", "دسته‌بندی و واحد", "دسته، برند و واحد (عدد/گرم/کیلوگرم/لیتر/متر…) را مشخص کنید؛ واحد روی نحوهٔ فروش اثر دارد."],
    ["#p-image-box", "تصویر کالا", "تصویر را بکشید و رها کنید یا از آدرس اینترنتی بگیرید."],
    ["#p-add", "ثبت کالا", "کالا «تعریف» می‌شود؛ موجودی و قیمت با «ورود کالا» (بچ) اضافه می‌شود — کالا ≠ بچ."],
    ["#p-csv", "ورود گروهی CSV", "صدها کالا را یک‌جا از فایل CSV وارد کنید؛ نمونهٔ فایل قابل دانلود است."],
    ["#p-table", "فهرست کالاها", "جستجو، ویرایش، تاریخچهٔ قیمت (غیرقابل تغییر) و چاپ برچسب بارکد از این‌جا."],
  ] };
  T.batches = { title: "ورود کالا (بچ)", steps: [
    ["#b-barcode", "انتخاب کالا", "بارکد را اسکن کنید تا کالا انتخاب شود؛ اگر تعریف نشده باشد پیشنهاد ساخت می‌دهد."],
    ["#b-qty", "مقدار و قیمت خرید", "مقدار دریافتی و بهای خرید هر واحد؛ روی سود و ارزش انبار اثر دارد."],
    ["#b-sell", "قیمت فروش و مصرف‌کننده", "قیمت فروش این بچ و قیمت درج‌شده روی کالا؛ تغییر قیمت در تاریخچه ثبت می‌شود."],
    ["#b-expiry", "تاریخ انقضا", "تاریخ شمسی انقضا؛ هشدارها و پیشنهاد تخفیف بر اساس آن ساخته می‌شود. فروش به روش FIFO است."],
    ["#b-receive", "ثبت ورود", "بچ با شمارهٔ یکتا ساخته و حرکت انبار IN ثبت می‌شود."],
  ] };
  T.inventory = { title: "انبار و انبارگردانی", steps: [
    ["#i-q", "جستجوی موجودی", "موجودی لحظه‌ای هر کالا به تفکیک بچ و انبار."],
    ["#i-table", "جدول موجودی", "اصلاح موجودی، ثبت ضایعات و انتقال بین انبارها از همین ردیف‌ها."],
    [".st-plan", "برنامهٔ انبارگردانی", "انبارگردانی را زمان‌بندی کنید؛ یادآور روی داشبورد می‌آید."],
    ["#st-create", "شروع انبارگردانی", "شمارش قابل توقف و ادامه است؛ در پایان مغایرت‌ها با یک تأیید اصلاح می‌شوند."],
    ["#st-list", "انبارگردانی‌های قبلی", "شمارش‌های باز را ادامه دهید یا گزارش مغایرت نهایی را ببینید."],
    ["#wh-body", "انبارها", "چند انبار تعریف کنید و کالا را بین آن‌ها منتقل کنید (حرکت TRANSFER)."],
  ] };
  T.invoices = { title: "فاکتورها", steps: [
    ["#inv-table", "فهرست فاکتورها", "همهٔ فاکتورها با وضعیت (کامل، معلق، مرجوع، باطل). کلیک کنید تا جزئیات، چاپ مجدد، مرجوعی یا ابطال را انجام دهید."],
  ] };
  T.customers = { title: "مشتریان", steps: [
    ["#cu-q", "جستجو", "با نام یا شماره همراه مشتری را پیدا کنید."],
    ["#cu-new", "مشتری جدید", "نام، شماره و سقف اعتبار؛ مشتری ثبت‌شده امتیاز می‌گیرد و می‌تواند نسیه بخرد."],
    ["#cu-table", "دفتر مشتریان", "بدهی، امتیاز و تاریخچهٔ خرید؛ تسویهٔ جزئی یا کامل بدهی از همین‌جا."],
  ] };
  T.marketing = { title: "جشنواره و کوپن", steps: [
    ["#mk-new-camp", "جشنوارهٔ جدید", "تخفیف درصدی/مبلغی روی دسته یا کالا در بازهٔ زمانی مشخص."],
    ["#mk-new-coupon", "کوپن جدید", "کد کوپن با شرایط: حداقل خرید، تعداد استفاده، مشتری خاص، تاریخ اعتبار."],
    ["#mk-stats", "آمار", "میزان استفاده و اثر هر جشنواره روی فروش."],
    ["#mk-coupons", "کوپن‌ها", "وضعیت هر کوپن و امکان غیرفعال کردن."],
  ] };
  T.reports = { title: "گزارش‌ها", steps: [
    ["#rep-tabs", "نوع گزارش", "فروش روزانه/هفتگی/ماهانهٔ شمسی، سود به تفکیک بچ، ارزش موجودی، انقضا، ضایعات و گردش کالا."],
    ["#rep-start", "بازهٔ تاریخ", "تاریخ شمسی شروع و پایان؛ روزها به وقت فروشگاه (تهران) گروه‌بندی می‌شوند."],
    ["#rep-refresh", "نمایش", "گزارش را بسازید؛ خروجی CSV و چاپ در بالای هر گزارش هست."],
    ["#rep-out", "نتیجه", "جدول‌ها و نمودارها این‌جا نمایش داده می‌شوند."],
  ] };
  T.accounting = { title: "حسابداری", steps: [
    ["#acc-tabs", "بخش‌های حسابداری", "دفتر روزنامه، تراز آزمایشی، سود و زیان، هزینه‌ها، دوره‌های مالی و بستن دوره."],
    ["#acc-body", "محتوا", "هر فروش و خرید به‌صورت خودکار سند می‌خورد؛ سند دستی هم می‌توانید ثبت کنید."],
  ] };
  T.hardware = { title: "سخت‌افزار", steps: [
    ["#h-status", "وضعیت دستگاه‌ها", "چاپگر، کشوی پول، بارکدخوان و ترازو؛ وضعیت اتصال هر کدام."],
    ["#h-type", "افزودن دستگاه", "نوع، نام و اتصال (USB/شبکه/سریال) را انتخاب کنید."],
    ["#h-test-print", "تست چاپ و کشو", "رسید آزمایشی چاپ کنید و کشو را باز کنید تا از اتصال مطمئن شوید."],
    [".scanner-card", "بارکدخوان", "شناسایی خودکار بارکدخوان و تست اسکن؛ در صندوق هم نشانگر وضعیت دارد."],
  ] };
  T.users = { title: "کاربران", steps: [
    ["#u-username", "کاربر جدید", "نام کاربری، نام کامل و رمز؛ نقش تعیین می‌کند به کدام بخش‌ها دسترسی دارد."],
    ["#u-role", "نقش‌ها", "مدیر، صندوق‌دار، انباردار…؛ صندوق‌دار سود و بهای خرید را نمی‌بیند."],
    ["#u-table", "فهرست کاربران", "غیرفعال کردن، تغییر رمز و تغییر نقش."],
  ] };
  T.settings = { title: "تنظیمات", steps: [
    ["#set-tabs", "دسته‌های تنظیمات", "مشخصات فروشگاه، واحد پول، تم، صدا، پیامک، به‌روزرسانی، پشتیبان‌گیری، منطقهٔ زمانی، همگام‌سازی موبایل و…"],
    ["#set-body", "محتوای هر دسته", "هر تغییر با «ذخیره» اعمال می‌شود؛ تغییرات حساس در لاگ حسابرسی ثبت می‌شوند."],
    ["#theme-box", "تم", "روشن/تیره یا خودکار (۰۷:۰۰ روشن، ۱۹:۰۰ تیره)."],
    ["#sfx-on", "صداها", "صداهای ملایم رویدادها؛ می‌توانید بلندی را کم یا خاموش کنید."],
  ] };
  T.diagnostics = { title: "تست اتصالات", steps: [
    ["#dg-run", "اجرای تست", "پایگاه داده، چاپگر، بارکدخوان، اینترنت، سرویس پیامک و همگام‌سازی موبایل بررسی می‌شوند."],
    ["#dg-results", "نتیجه", "هر مورد سبز/زرد/قرمز با راهنمای رفع مشکل."],
    ["#dg-history", "تاریخچه", "تست‌های قبلی برای مقایسه."],
  ] };
  T.support = { title: "درخواست پشتیبانی", steps: [
    ["#sup-form", "ثبت درخواست", "خرابی، سؤال یا پیشنهاد را بنویسید؛ همراه با نام فروشگاه و کد نصب برای پشتیبانی ارسال می‌شود (بدون اینترنت هم ذخیره و بعداً ارسال می‌شود)."],
    ["#sup-geo", "موقعیت مکانی", "برای مراجعهٔ حضوری، موقعیت دقیق فروشگاه را هم بفرستید."],
    ["#sup-list", "گفتگو با پشتیبانی", "پاسخ پشتیبانی همین‌جا زیر هر درخواست می‌آید (با نشان «پاسخ جدید»). می‌توانید ادامه دهید و عکس یا فایل پیوست کنید."],
  ] };
  T.audit = { title: "لاگ‌ها", steps: [
    ["#a-table", "لاگ حسابرسی", "چه کسی، چه زمانی، چه کاری کرد: ورود، فروش، ابطال، تغییر قیمت، تغییر تنظیمات و…؛ غیرقابل ویرایش."],
  ] };

  /* ---------------------------------------------------------------- engine */
  let cur = null; // {view, steps, i}
  function els() {
    let o = document.getElementById("tour-layer");
    if (!o) {
      o = document.createElement("div"); o.id = "tour-layer"; o.className = "tour-layer hidden";
      o.innerHTML = `<div class="tour-hole" id="tour-hole"></div><div class="tour-card" id="tour-card" role="dialog" aria-live="polite"></div>`;
      document.body.appendChild(o);
      o.addEventListener("click", (e) => { if (e.target === o) end(); });
    }
    return o;
  }
  function visible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
  function place() {
    if (!cur) return;
    const [sel, title, body] = cur.steps[cur.i];
    const el = document.querySelector(sel);
    const layer = els(); const hole = document.getElementById("tour-hole"); const card = document.getElementById("tour-card");
    layer.classList.remove("hidden");
    let r;
    if (el && visible(el)) {
      el.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" });
      r = el.getBoundingClientRect();
      const pad = 6;
      hole.style.cssText = `top:${r.top - pad}px;left:${r.left - pad}px;width:${r.width + pad * 2}px;height:${r.height + pad * 2}px;opacity:1`;
    } else {
      r = { top: innerHeight / 2 - 40, left: innerWidth / 2 - 100, width: 200, height: 80, bottom: innerHeight / 2 + 40, right: innerWidth / 2 + 100 };
      hole.style.cssText = "opacity:0;top:0;left:0;width:0;height:0";
    }
    const n = cur.steps.length, i = cur.i;
    const fa = (x) => String(x).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
    card.innerHTML = `<div class="tour-head"><span class="tour-step">${fa(i + 1)} از ${fa(n)}</span><b>${_esc(title)}</b><button class="tour-x" title="بستن (Esc)" onclick="Tour.end()">✕</button></div>
      <p>${_esc(body)}</p>
      <div class="tour-dots">${cur.steps.map((_, k) => `<i class="${k === i ? "on" : ""}"></i>`).join("")}</div>
      <div class="tour-actions">
        <button class="btn btn-sm" onclick="Tour.prev()" ${i === 0 ? "disabled" : ""}>قبلی</button>
        <button class="btn btn-sm btn-ghost" onclick="Tour.end()">رد کردن</button>
        <button class="btn btn-sm btn-primary" onclick="Tour.next()">${i === n - 1 ? "پایان" : "بعدی"}</button>
      </div>`;
    // position: below → above → beside (for tall targets like the sidebar) → clamp
    card.style.visibility = "hidden"; card.style.display = "block";
    const cw = card.offsetWidth, ch = card.offsetHeight, M = 12;
    let top, left;
    if (r.bottom + M + ch <= innerHeight - 8) { top = r.bottom + M; left = r.left + r.width / 2 - cw / 2; }
    else if (r.top - M - ch >= 8) { top = r.top - M - ch; left = r.left + r.width / 2 - cw / 2; }
    else if (r.left - M - cw >= 8) { left = r.left - M - cw; top = Math.max(8, Math.min(innerHeight - ch - 8, r.top + r.height / 2 - ch / 2)); }
    else if (r.right + M + cw <= innerWidth - 8) { left = r.right + M; top = Math.max(8, Math.min(innerHeight - ch - 8, r.top + r.height / 2 - ch / 2)); }
    else { top = Math.max(8, innerHeight - ch - 8); left = r.left + r.width / 2 - cw / 2; }
    left = Math.max(8, Math.min(innerWidth - cw - 8, left));
    card.style.top = top + "px"; card.style.left = left + "px"; card.style.visibility = "visible";
  }
  function start(view, opts = {}) {
    const def = T[view]; if (!def) return false;
    // keep only steps whose target exists (roles may hide cards); always keep at least one
    const steps = def.steps.filter(([sel]) => document.querySelector(sel));
    if (!steps.length) return false;
    cur = { view, steps, i: 0 };
    if (!opts.replay) markSeen(view);
    place();
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", place);
    return true;
  }
  function end() {
    if (cur) markSeen(cur.view);
    cur = null; const l = document.getElementById("tour-layer"); if (l) l.classList.add("hidden");
    window.removeEventListener("keydown", onKey, true); window.removeEventListener("resize", place);
  }
  function next() { if (!cur) return; if (cur.i >= cur.steps.length - 1) { end(); return; } cur.i++; place(); }
  function prev() { if (!cur || cur.i === 0) return; cur.i--; place(); }
  function onKey(e) {
    if (!cur) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); end(); }
    else if (e.key === "ArrowLeft" || e.key === "Enter") { e.preventDefault(); e.stopPropagation(); next(); } // RTL: ← = forward
    else if (e.key === "ArrowRight") { e.preventDefault(); e.stopPropagation(); prev(); }
  }
  /* called by app.go() after a view rendered */
  let timer = null;
  function onView(view) {
    clearTimeout(timer);
    const bar = document.getElementById("topbar-actions");
    if (bar && T[view] && !document.getElementById("tour-btn")) {
      const b = document.createElement("button"); b.id = "tour-btn"; b.className = "btn btn-sm tour-btn"; b.title = "راهنمای این بخش";
      b.innerHTML = `<span aria-hidden="true">?</span> راهنما`; b.onclick = () => start(view, { replay: true });
      bar.prepend(b);
    }
    if (cur) end();
    if (T[view] && !seen()[view] && !document.body.classList.contains("kiosk")) {
      timer = setTimeout(() => { if (ST() && ST().view === view) start(view); }, 700);
    }
  }
  function reset() { localStorage.removeItem(KEY()); }
  window.Tour = { start, end, next, prev, onView, reset, has: (v) => !!T[v], sections: Object.keys(T) };
})();
