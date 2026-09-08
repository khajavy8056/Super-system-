/* v1.5 — first-run setup wizard, licence gate, "installing" loading screen,
 * bottom alert stack. Loaded after app.js; uses its helpers (api, $, esc, toast, fa). */
(function () {
  "use strict";
  const LS_LOADED = "sm.loading.session"; // per-login loading marker (session)
  const S = { status: null, wizard: { step: 0, data: {}, logoFile: null } };
  const _fa = (n) => (typeof fa === "function" ? fa(n) : String(n));
  const _esc = (s) => (typeof esc === "function" ? esc(s) : String(s ?? ""));
  const q = (s) => document.querySelector(s);

  async function pub(path, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    if (!(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const r = await fetch("/api" + path, { ...opts, headers });
    let b = null; try { b = await r.json(); } catch (_) {}
    if (!r.ok) { const d = b && b.detail; throw Object.assign(new Error(typeof d === "object" ? (d.message || d.code) : (d || r.statusText)), { code: d && d.code, status: r.status }); }
    return b;
  }

  /* ---------- host overlay ---------- */
  function overlay(cls) {
    let o = q("#ob-overlay");
    if (!o) { o = document.createElement("div"); o.id = "ob-overlay"; document.body.appendChild(o); }
    o.className = "ob-overlay " + (cls || "");
    o.innerHTML = "";
    o.classList.remove("hidden");
    return o;
  }
  function closeOverlay() { const o = q("#ob-overlay"); if (o) { o.classList.add("hidden"); o.innerHTML = ""; } }

  const LOGO = () => (S.status && S.status.logo_path) ? `<img class="ob-logo" src="${S.status.logo_path}" alt="لوگو"/>` : `<img class="ob-logo" src="/icons/logo.svg" alt="لوگو"/>`;

  /* ---------- licence screen ---------- */
  function licenseScreen(lic, onDone, opts = {}) {
    const o = overlay("ob-license");
    const blocked = lic && lic.activated && !lic.allowed;
    o.innerHTML = `<div class="ob-card ob-anim">
      ${LOGO()}
      <div class="ob-badge">${blocked ? "لایسنس نامعتبر شده" : "فعال‌سازی لایسنس"}</div>
      <h1>${opts.title || "کلید لایسنس را وارد کنید"}</h1>
      <p class="muted">${blocked ? _esc(lic.reason) : "برای استفاده از سامانه، لایسنس معتبر لازم است. کلید را از فروشنده دریافت کرده‌اید."}</p>
      <div class="ob-hwid"><span>شناسهٔ این دستگاه</span><b class="ltr">${_esc(lic ? lic.hwid : "")}</b></div>
      <input id="ob-key" class="ob-key ltr" placeholder="KEY-XXXX-XXXX-XXXX" autocomplete="off" spellcheck="false" maxlength="40" />
      <p id="ob-key-err" class="error hidden"></p>
      <button id="ob-key-go" class="btn btn-primary btn-block btn-lg">بررسی و فعال‌سازی</button>
      <p class="muted small">اعتبار لایسنس هر ۲۴ ساعت به‌صورت آنلاین بررسی می‌شود؛ تا ۷ روز بدون اینترنت نیز کار می‌کند.</p>
    </div>`;
    const inp = q("#ob-key"), err = q("#ob-key-err"), btn = q("#ob-key-go");
    inp.addEventListener("input", () => { let v = inp.value.toUpperCase().replace(/[^A-Z0-9-]/g, ""); inp.value = v; });
    inp.focus();
    const go = async () => {
      err.classList.add("hidden"); btn.disabled = true; btn.innerHTML = `<span class="ob-spin"></span> در حال بررسی آنلاین…`;
      try {
        const st = await pub("/setup/license/activate", { method: "POST", body: JSON.stringify({ key: inp.value.trim() }) });
        btn.innerHTML = "✓ فعال شد"; if (window.Sfx) Sfx.play("success");
        setTimeout(() => onDone(st), 500);
      } catch (e) {
        err.textContent = e.message + (e.code === "NETWORK" ? " — اتصال اینترنت را بررسی کنید." : "");
        err.classList.remove("hidden"); btn.disabled = false; btn.textContent = "بررسی و فعال‌سازی";
      }
    };
    btn.addEventListener("click", go);
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  }

  /* ---------- setup wizard ---------- */
  const STEPS = [
    { id: "welcome", title: "خوش آمدید", icon: "sparkle" },
    { id: "license", title: "لایسنس", icon: "key", noskip: true },
    { id: "store", title: "نام فروشگاه", icon: "store" },
    { id: "logo", title: "لوگو", icon: "image" },
    { id: "contact", title: "اطلاعات تماس", icon: "phone" },
    { id: "currency", title: "واحد پول", icon: "coins" },
    { id: "theme", title: "پوسته و چاپگر", icon: "palette" },
    { id: "catalog", title: "بانک کالا", icon: "box" },
    { id: "admin", title: "حساب مدیر", icon: "user", noskip: true },
    { id: "finish", title: "پایان", icon: "check" },
  ];
  const ICO = {
    sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17l.8 2.2L22 20l-2.2.8L19 23l-.8-2.2L16 20l2.2-.8z"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M15 8l2 2M18 5l2 2"/>',
    store: '<path d="M3 9l1.5-5h15L21 9M3 9h18M3 9v11h18V9M9 20v-6h6v6"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    phone: '<path d="M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-2z"/>',
    coins: '<ellipse cx="9" cy="7" rx="6" ry="3"/><path d="M3 7v6c0 1.7 2.7 3 6 3s6-1.3 6-3V7"/><path d="M3 13v4c0 1.7 2.7 3 6 3s6-1.3 6-3v-4"/><path d="M15 9.5c3.3 0 6 1.3 6 3v5c0 1.7-2.7 3-6 3"/>',
    palette: '<path d="M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 0-4h-1a2 2 0 0 1 0-4h3a5 5 0 0 0 0-10z"/><circle cx="7.5" cy="10.5" r="1"/><circle cx="12" cy="7.5" r="1"/><circle cx="16.5" cy="10.5" r="1"/>',
    box: '<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
  };
  const ico = (n, s = 22) => `<svg class="ob-ico" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICO[n] || ICO.sparkle}</svg>`;

  async function wizard(onFinished) {
    if (!S.status) { try { S.status = await pub("/setup/status"); } catch (_) { S.status = { license: { allowed: false, hwid: "" } }; } }
    const w = S.wizard; w.step = 0; w.data = w.data || {};
    const o = overlay("ob-wizard");
    o.innerHTML = `<div class="ob-wiz ob-anim">
      <aside class="ob-steps">
        ${LOGO()}
        <h2>راه‌اندازی اولیه</h2>
        <ol id="ob-steplist">${STEPS.map((s, i) => `<li data-i="${i}">${ico(s.icon, 18)}<span>${s.title}</span></li>`).join("")}</ol>
        <div class="ob-progress"><i id="ob-prog"></i></div>
      </aside>
      <section class="ob-pane">
        <div id="ob-pane-body" class="ob-pane-body"></div>
        <footer class="ob-foot">
          <button id="ob-back" class="btn">قبلی</button>
          <span class="ob-grow"></span>
          <button id="ob-skip" class="btn btn-ghost">رد کردن این مرحله</button>
          <button id="ob-next" class="btn btn-primary">بعدی</button>
        </footer>
      </section>
    </div>`;
    q("#ob-back").onclick = () => show(w.step - 1);
    q("#ob-skip").onclick = () => show(w.step + 1, true);
    q("#ob-next").onclick = async () => { if (await collect()) show(w.step + 1); };

    function show(i) {
      if (i < 0) return; if (i >= STEPS.length) return;
      w.step = i; const st = STEPS[i];
      document.querySelectorAll("#ob-steplist li").forEach((li) => { const k = +li.dataset.i; li.className = k < i ? "done" : k === i ? "active" : ""; });
      q("#ob-prog").style.width = Math.round((i / (STEPS.length - 1)) * 100) + "%";
      q("#ob-back").style.visibility = i === 0 ? "hidden" : "visible";
      q("#ob-skip").style.display = st.noskip || st.id === "finish" || st.id === "welcome" ? "none" : "";
      q("#ob-next").textContent = st.id === "finish" ? "شروع نصب و ورود" : st.id === "welcome" ? "بزن بریم" : "بعدی";
      const b = q("#ob-pane-body"); b.className = "ob-pane-body"; void b.offsetWidth; b.classList.add("ob-slide");
      if (window.Sfx) Sfx.play("step");
      b.innerHTML = PANES[st.id]();
      if (st.id === "license") wireLicensePane();
      if (st.id === "logo") wireLogoPane();
      if (st.id === "admin") { q("#w-admin-user").value = w.data.admin_username || ""; }
    }

    const d = () => w.data;
    const val = (id) => (q(id) ? q(id).value.trim() : "");
    async function collect() {
      const st = STEPS[w.step];
      switch (st.id) {
        case "license": {
          const lic = S.status.license;
          if (!lic.allowed) { toast("ابتدا لایسنس را فعال کنید", "err"); return false; }
          return true;
        }
        case "store": d().store_name = val("#w-store"); d().legal_name = val("#w-legal"); return true;
        case "contact": d().phone = val("#w-phone"); d().mobile = val("#w-mobile"); d().city = val("#w-city"); d().address = val("#w-address"); d().postal_code = val("#w-postal"); d().tax_id = val("#w-tax"); d().receipt_note = val("#w-note"); return true;
        case "currency": d().currency = (q('input[name="w-cur"]:checked') || {}).value || "IRT"; return true;
        case "theme": d().theme = (q('input[name="w-theme"]:checked') || {}).value || "auto"; d().printer_width_mm = +((q('input[name="w-paper"]:checked') || {}).value || 80); return true;
        case "catalog": d().import_starter_catalog = !!(q("#w-starter") && q("#w-starter").checked); return true;
        case "admin": {
          const u = val("#w-admin-user"), p = q("#w-admin-pass").value, p2 = q("#w-admin-pass2").value;
          if (!/^[A-Za-z0-9_.-]{3,32}$/.test(u)) { toast("نام کاربری: ۳ تا ۳۲ حرف انگلیسی/عدد", "err"); return false; }
          if (p.length < 6) { toast("رمز عبور حداقل ۶ کاراکتر", "err"); return false; }
          if (p !== p2) { toast("تکرار رمز عبور یکسان نیست", "err"); return false; }
          d().admin_username = u; d().admin_password = p; d().admin_full_name = val("#w-admin-name"); return true;
        }
        case "finish": {
          const btn = q("#ob-next"); btn.disabled = true; btn.innerHTML = `<span class="ob-spin"></span> ذخیره…`;
          try {
            const body = { ...d() };
            const r = await pub("/setup/complete", { method: "POST", body: JSON.stringify(body) });
            onFinished(r, body);
          } catch (e) { toast(e.message, "err"); btn.disabled = false; btn.textContent = "شروع نصب و ورود"; }
          return false;
        }
        default: return true;
      }
    }

    const PANES = {
      welcome: () => `<div class="ob-hero">${ico("sparkle", 56)}<h1>به سامانهٔ مدیریت سوپرمارکت خوش آمدید</h1>
        <p>در چند قدم کوتاه فروشگاه‌تان را راه‌اندازی می‌کنیم: لایسنس، نام و لوگو، واحد پول، پوسته، بانک کالا و حساب مدیر. هر مرحله را می‌توانید رد کنید و بعداً از «تنظیمات» کامل کنید.</p>
        <div class="ob-feat"><span>${ico("key")}لایسنس آنلاین</span><span>${ico("store")}پروفایل فروشگاه</span><span>${ico("box")}بانک اولیهٔ کالا</span><span>${ico("user")}حساب مدیر</span></div></div>`,
      license: () => { const l = S.status.license; return `<h1>${ico("key", 28)} لایسنس</h1>
        ${l.allowed ? `<div class="ob-ok">${ico("check")} لایسنس فعال است</div>
          <div class="ob-kv"><div><span>نوع</span><b>${_esc(l.type || "-")}</b></div><div><span>مالک</span><b>${_esc(l.owner || "-")}</b></div><div><span>انقضا</span><b>${l.expires ? (typeof Jalali !== "undefined" ? Jalali.fromIso(l.expires) : l.expires) : "نامحدود"}</b></div><div><span>روز باقی‌مانده</span><b>${l.days_left == null ? "—" : _fa(l.days_left)}</b></div><div><span>شناسهٔ دستگاه</span><b class="ltr">${_esc(l.hwid)}</b></div></div>`
        : `<p class="muted">کلید لایسنس را وارد کنید؛ به‌صورت آنلاین برای این دستگاه بررسی و ذخیره می‌شود.</p>
          <div class="ob-hwid"><span>شناسهٔ این دستگاه</span><b class="ltr">${_esc(l.hwid)}</b></div>
          <input id="w-key" class="ob-key ltr" placeholder="KEY-XXXX-XXXX-XXXX" maxlength="40" autocomplete="off"/>
          <p id="w-key-err" class="error hidden"></p>
          <button id="w-key-go" class="btn btn-primary btn-lg">بررسی و فعال‌سازی</button>`}`; },
      store: () => `<h1>${ico("store", 28)} نام فروشگاه</h1><p class="muted">روی فاکتور، نوار وضعیت و صفحهٔ ورود نمایش داده می‌شود.</p>
        <label>نام فروشگاه</label><input id="w-store" value="${_esc(d().store_name || "")}" placeholder="مثلاً: سوپرمارکت خواجوی" autofocus/>
        <label>نام رسمی / حقوقی (اختیاری)</label><input id="w-legal" value="${_esc(d().legal_name || "")}"/>`,
      logo: () => `<h1>${ico("image", 28)} لوگوی فروشگاه</h1><p class="muted">PNG/JPG/SVG تا ۲ مگابایت؛ روی رسید، منو و صفحهٔ «درباره» استفاده می‌شود.</p>
        <div class="ob-logo-drop" id="w-logo-drop">${S.status.logo_path ? `<img src="${S.status.logo_path}"/>` : ico("image", 48)}<span>برای انتخاب کلیک کنید یا فایل را اینجا رها کنید</span><input type="file" id="w-logo" accept="image/*" hidden/></div>
        <p id="w-logo-msg" class="muted"></p>`,
      contact: () => `<h1>${ico("phone", 28)} اطلاعات تماس</h1>
        <div class="form-row"><div><label>تلفن</label><input id="w-phone" class="ltr" value="${_esc(d().phone || "")}"/></div><div><label>موبایل</label><input id="w-mobile" class="ltr" value="${_esc(d().mobile || "")}"/></div></div>
        <div class="form-row"><div><label>شهر</label><input id="w-city" value="${_esc(d().city || "")}"/></div><div><label>کد پستی</label><input id="w-postal" class="ltr" value="${_esc(d().postal_code || "")}"/></div></div>
        <label>آدرس</label><input id="w-address" value="${_esc(d().address || "")}"/>
        <div class="form-row"><div><label>شناسهٔ مالیاتی (اختیاری)</label><input id="w-tax" class="ltr" value="${_esc(d().tax_id || "")}"/></div><div><label>پیام پایین رسید</label><input id="w-note" value="${_esc(d().receipt_note || "")}" placeholder="از خرید شما سپاسگزاریم"/></div></div>`,
      currency: () => `<h1>${ico("coins", 28)} واحد پول</h1><p class="muted">مبالغ با همین واحد ذخیره و نمایش داده می‌شوند؛ بعداً تغییر آن فقط پیش از ثبت اولین فاکتور ممکن است.</p>
        <div class="ob-choices">
          <label class="ob-choice"><input type="radio" name="w-cur" value="IRT" ${(d().currency || "IRT") === "IRT" ? "checked" : ""}/><b>تومان</b><span>رایج‌ترین انتخاب فروشگاه‌ها</span></label>
          <label class="ob-choice"><input type="radio" name="w-cur" value="IRR" ${d().currency === "IRR" ? "checked" : ""}/><b>ریال</b><span>واحد رسمی</span></label>
        </div>`,
      theme: () => `<h1>${ico("palette", 28)} پوسته و چاپگر</h1>
        <h4>پوسته</h4><div class="ob-choices">
          <label class="ob-choice"><input type="radio" name="w-theme" value="auto" ${(d().theme || "auto") === "auto" ? "checked" : ""}/><b>خودکار</b><span>روشن ۰۷:۰۰ · تیره ۱۹:۰۰</span></label>
          <label class="ob-choice"><input type="radio" name="w-theme" value="light" ${d().theme === "light" ? "checked" : ""}/><b>روشن</b><span>همیشه روشن</span></label>
          <label class="ob-choice"><input type="radio" name="w-theme" value="dark" ${d().theme === "dark" ? "checked" : ""}/><b>تیره</b><span>همیشه تیره</span></label>
        </div>
        <h4>عرض کاغذ چاپگر حرارتی</h4><div class="ob-choices">
          ${[58, 76, 80].map((p) => `<label class="ob-choice"><input type="radio" name="w-paper" value="${p}" ${(d().printer_width_mm || 80) === p ? "checked" : ""}/><b>${_fa(p)} میلی‌متر</b><span>${p === 80 ? "رایج‌ترین" : p === 58 ? "چاپگرهای کوچک" : "متوسط"}</span></label>`).join("")}
        </div>`,
      catalog: () => `<h1>${ico("box", 28)} بانک اولیهٔ کالا</h1><p class="muted">حدود ۱۹۰ کالای پرمصرف سوپرمارکتی با دسته‌بندی و واحد، همه با <b>موجودی صفر</b> اضافه می‌شوند؛ موجودی واقعی را از «ورود کالا» ثبت می‌کنید.</p>
        <label class="ob-choice ob-choice-wide"><input type="checkbox" id="w-starter" ${d().import_starter_catalog !== false ? "checked" : ""}/><b>بانک اولیهٔ کالا وارد شود</b><span>در صورت عدم انتخاب، از فهرست خالی شروع می‌کنید</span></label>`,
      admin: () => `<h1>${ico("user", 28)} حساب مدیر سیستم</h1><p class="muted">با این نام کاربری و رمز وارد برنامه می‌شوید. حساب پیش‌فرض admin/admin123 با این حساب جایگزین می‌شود.</p>
        <label>نام و نام خانوادگی</label><input id="w-admin-name" value="${_esc(d().admin_full_name || "")}"/>
        <label>نام کاربری</label><input id="w-admin-user" class="ltr" autocomplete="off" placeholder="admin"/>
        <div class="form-row"><div><label>رمز عبور</label><input id="w-admin-pass" type="password" class="ltr" autocomplete="new-password"/></div><div><label>تکرار رمز عبور</label><input id="w-admin-pass2" type="password" class="ltr" autocomplete="new-password"/></div></div>`,
      finish: () => `<div class="ob-hero">${ico("check", 56)}<h1>همه‌چیز آماده است</h1>
        <p>با زدن «شروع نصب و ورود»، تنظیمات ذخیره می‌شود و نصب اولیه (اتصال سرویس‌ها، آماده‌سازی پایگاه داده و بانک کالا) آغاز می‌شود. این مرحله فقط بار اول انجام می‌شود و بسته به سیستم ممکن است زمان‌بر باشد؛ لطفاً رایانه را خاموش نکنید.</p>
        <div class="ob-kv"><div><span>فروشگاه</span><b>${_esc(d().store_name || "—")}</b></div><div><span>واحد پول</span><b>${d().currency === "IRR" ? "ریال" : "تومان"}</b></div><div><span>پوسته</span><b>${({ auto: "خودکار", light: "روشن", dark: "تیره" })[d().theme || "auto"]}</b></div><div><span>بانک کالا</span><b>${d().import_starter_catalog === false ? "خیر" : "بله"}</b></div><div><span>مدیر</span><b class="ltr">${_esc(d().admin_username || "admin")}</b></div></div></div>`,
    };

    function wireLicensePane() {
      const btn = q("#w-key-go"); if (!btn) return;
      const inp = q("#w-key"), err = q("#w-key-err");
      inp.addEventListener("input", () => { inp.value = inp.value.toUpperCase().replace(/[^A-Z0-9-]/g, ""); });
      const go = async () => {
        err.classList.add("hidden"); btn.disabled = true; btn.innerHTML = `<span class="ob-spin"></span> در حال بررسی آنلاین…`;
        try {
          S.status.license = await pub("/setup/license/activate", { method: "POST", body: JSON.stringify({ key: inp.value.trim() }) });
          if (window.Sfx) Sfx.play("success");
          show(w.step);
        } catch (e) { err.textContent = e.message; err.classList.remove("hidden"); btn.disabled = false; btn.textContent = "بررسی و فعال‌سازی"; }
      };
      btn.onclick = go; inp.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); }); inp.focus();
    }
    function wireLogoPane() {
      const drop = q("#w-logo-drop"), file = q("#w-logo"), msg = q("#w-logo-msg");
      drop.onclick = () => file.click();
      const upload = async (f) => {
        if (!f) return;
        const fd = new FormData(); fd.append("file", f);
        msg.textContent = "در حال بارگذاری…";
        try { const r = await pub("/setup/logo", { method: "POST", body: fd }); S.status.logo_path = r.logo_path; drop.innerHTML = `<img src="${r.logo_path}"/><span>لوگو ذخیره شد — برای تغییر کلیک کنید</span>`; msg.textContent = ""; document.querySelectorAll(".ob-logo").forEach((i) => (i.src = r.logo_path)); }
        catch (e) { msg.textContent = e.message; }
      };
      file.onchange = () => upload(file.files[0]);
      drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
      drop.ondragleave = () => drop.classList.remove("over");
      drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); upload(e.dataTransfer.files[0]); };
    }
    show(0);
  }

  /* ---------- loading ("installing") screen ---------- */
  const PHASES_FIRST = [
    ["برقراری ارتباط با سرویس لایسنس", 0.04], ["ایجاد ساختار پایگاه داده", 0.10], ["اجرای مهاجرت‌های اسکیمای داده", 0.18],
    ["نصب ماژول حسابداری دوطرفه", 0.28], ["پیکربندی موتور صندوق (POS)", 0.36], ["آماده‌سازی موتور بارکد و واحدها", 0.44],
    ["وارد کردن بانک اولیهٔ کالا", 0.55], ["ساخت ایندکس‌های جستجو", 0.63], ["پیکربندی پوسته و تقویم شمسی", 0.70],
    ["نصب درایورهای سخت‌افزار (چاپگر / بارکدخوان)", 0.78], ["راه‌اندازی صف پیامک و همگام‌سازی آفلاین", 0.86],
    ["اعمال تنظیمات فروشگاه", 0.93], ["بررسی نهایی و بهینه‌سازی", 1.0],
  ];
  const PHASES_LOGIN = [["بررسی لایسنس", 0.2], ["بارگذاری تنظیمات فروشگاه", 0.45], ["همگام‌سازی موجودی و قیمت‌ها", 0.7], ["آماده‌سازی داشبورد", 0.9], ["ورود", 1.0]];

  function loadingScreen(seconds, first, work, onDone) {
    const o = overlay("ob-loading");
    const phases = first ? PHASES_FIRST : PHASES_LOGIN;
    o.innerHTML = `<div class="ob-load ob-anim">
      ${LOGO()}
      <h1>${first ? "در حال نصب و پیکربندی سامانه" : "در حال آماده‌سازی"}</h1>
      <p class="muted" id="ob-load-sub">${first ? "این مرحله فقط بار اول انجام می‌شود. لطفاً رایانه را خاموش نکنید." : "در حال بررسی لایسنس و آماده‌سازی…"}</p>
      <div class="ob-ring"><svg viewBox="0 0 120 120"><circle class="bg" cx="60" cy="60" r="52"/><circle class="fg" id="ob-ring-fg" cx="60" cy="60" r="52"/></svg><div class="ob-ring-txt"><b id="ob-pct">۰٪</b><span id="ob-eta"></span></div></div>
      <ul class="ob-phases" id="ob-phases">${phases.map((p, i) => `<li data-i="${i}"><i></i><span>${p[0]}</span><em></em></li>`).join("")}</ul>
      <div class="ob-log" id="ob-log"></div>
    </div>`;
    const fg = q("#ob-ring-fg"), C = 2 * Math.PI * 52; fg.style.strokeDasharray = C; fg.style.strokeDashoffset = C;
    const fast = +sessionStorage.getItem("sm.loading.fast") || +(new URLSearchParams(location.search).get("fastload") || 0);
    if (fast) seconds = fast;
    const start = Date.now(), total = Math.max(3, seconds) * 1000;
    const key = "sm.loading.start." + (first ? "first" : "login");
    let t0 = +sessionStorage.getItem(key) || 0; if (!t0 || Date.now() - t0 > total) { t0 = start; sessionStorage.setItem(key, String(t0)); }
    const logEl = q("#ob-log"); const lines = [];
    const log = (s) => { lines.push(s); if (lines.length > 6) lines.shift(); logEl.innerHTML = lines.map((l) => `<div>${l}</div>`).join(""); };
    let workDone = false, workErr = null;
    Promise.resolve().then(work).then(() => { workDone = true; }).catch((e) => { workErr = e; workDone = true; });
    let lastPhase = -1;
    const tick = () => {
      const el = Date.now() - t0; let p = Math.min(1, el / total);
      // ease so it looks like real work: fast start, slow middle, final sprint
      const eased = p < 0.9 ? Math.pow(p, 0.85) * 0.92 : 0.92 + (p - 0.9) * 0.8;
      const pct = Math.min(100, Math.round(eased * 100));
      q("#ob-pct").textContent = _fa(pct) + "٪"; fg.style.strokeDashoffset = C * (1 - eased);
      q("#ob-eta").textContent = p < 1 ? "لطفاً صبر کنید" : "";
      let ph = phases.findIndex((x) => eased < x[1]); if (ph < 0) ph = phases.length - 1;
      if (ph !== lastPhase) {
        document.querySelectorAll("#ob-phases li").forEach((li) => { const k = +li.dataset.i; li.className = k < ph ? "done" : k === ph ? "active" : ""; li.querySelector("em").textContent = k < ph ? "✓" : ""; });
        log(`▸ ${phases[ph][0]}…`); lastPhase = ph;
      } else if (Math.random() < 0.04) {
        log(["اتصال برقرار شد", "بستهٔ داده دریافت شد", "جدول به‌روزرسانی شد", "ایندکس ساخته شد", "بررسی یکپارچگی: موفق", "پیکربندی اعمال شد"][Math.floor(Math.random() * 6)]);
      }
      if (p >= 1 && workDone) { sessionStorage.removeItem(key); q("#ob-load-sub").textContent = "آماده شد"; if (window.Sfx) Sfx.play(first ? "install" : "ready"); setTimeout(() => onDone(workErr), 600); return; }
      requestAnimationFrame(() => setTimeout(tick, 250));
    };
    tick();
  }

  /* ---------- bottom alert stack ---------- */
  function alertsStack() {
    let host = q("#ob-alerts"); if (!host) { host = document.createElement("div"); host.id = "ob-alerts"; host.className = "ob-alerts"; document.body.appendChild(host); }
    const dismissed = new Set(JSON.parse(sessionStorage.getItem("sm.alerts.dismissed") || "[]"));
    const load = async () => {
      const tok = localStorage.getItem("token");
      if (!tok) { host.innerHTML = ""; return; }
      let a; try { a = await pub("/setup/alerts", { headers: { Authorization: "Bearer " + tok } }); } catch (_) { return; }
      const items = a.items.filter((i) => !dismissed.has(i.id)).slice(0, 5);
      const prevIds = new Set([...host.querySelectorAll(".ob-alert")].map((x) => x.dataset.id));
      if (window.Sfx && items.some((i) => !prevIds.has(i.id) && i.severity === "CRITICAL") && host._loaded) Sfx.play("alert");
      host._loaded = true;
      host.innerHTML = items.map((i) => `<div class="ob-alert sev-${i.severity.toLowerCase()} ob-pop" data-id="${i.id}">
        <div class="ob-alert-ico">${i.kind === "LICENSE" ? ico("key", 20) : ico("box", 20)}</div>
        <div class="ob-alert-txt"><b>${_esc(i.title)}</b><span>${_esc(i.body)}</span></div>
        ${i.kind === "EXPIRY" ? `<button class="ob-alert-go" data-go="inventory" title="نمایش در انبار">›</button>` : i.id === "lic-blocked" || i.kind === "LICENSE" ? `<button class="ob-alert-go" data-go="settings" title="تنظیمات">›</button>` : ""}
        <button class="ob-alert-x" title="بستن">×</button></div>`).join("");
      host.querySelectorAll(".ob-alert-x").forEach((b) => (b.onclick = () => { const id = b.parentElement.dataset.id; dismissed.add(id); sessionStorage.setItem("sm.alerts.dismissed", JSON.stringify([...dismissed])); b.parentElement.remove(); }));
      host.querySelectorAll(".ob-alert-go").forEach((b) => (b.onclick = () => { if (typeof go === "function") go(b.dataset.go); }));
    };
    load(); clearInterval(window._obAlertsTimer); window._obAlertsTimer = setInterval(load, 5 * 60 * 1000);
    window.refreshAlerts = load;
  }

  /* ---------- licence panel for settings ---------- */
  async function licensePanel(container) {
    let l; try { l = await pub("/setup/license"); } catch (e) { container.innerHTML = `<p class="error">${_esc(e.message)}</p>`; return; }
    const jd = (iso) => (iso ? (typeof Jalali !== "undefined" ? Jalali.fromIso(String(iso).slice(0, 10)) : iso) : "—");
    container.innerHTML = `<h3>${ico("key", 20)} لایسنس</h3>
      <div class="ob-kv">
        <div><span>وضعیت</span><b class="${l.allowed ? "ok" : "err"}">${l.allowed ? "فعال" : (l.status === "REVOKED" ? "باطل شده" : l.activated ? "مسدود" : "فعال نشده")}</b></div>
        <div><span>نوع</span><b>${_esc(l.type || "—")}</b></div><div><span>مالک</span><b>${_esc(l.owner || "—")}</b></div>
        <div><span>تاریخ انقضا</span><b>${l.expires ? jd(l.expires) : "نامحدود"}</b></div>
        <div><span>روز باقی‌مانده</span><b>${l.days_left == null ? "—" : _fa(l.days_left)}</b></div>
        <div><span>کلید</span><b class="ltr">${_esc(l.key_masked || "—")}</b></div>
        <div><span>شناسهٔ دستگاه</span><b class="ltr">${_esc(l.hwid)}</b></div>
        <div><span>آخرین بررسی آنلاین</span><b>${l.checked_at ? jd(l.checked_at) + " " + String(l.checked_at).slice(11, 16) : "—"}</b></div>
        <div><span>فعال‌سازی</span><b>${l.activated_at ? jd(l.activated_at) : "—"}</b></div>
      </div>
      ${l.reason ? `<p class="error">${_esc(l.reason)}</p>` : ""}${l.last_error ? `<p class="muted small ltr">${_esc(l.last_error)}</p>` : ""}
      <div class="row" style="gap:8px;margin-top:10px"><button class="btn btn-sm" id="lic-recheck">بررسی آنلاین اکنون</button><button class="btn btn-sm" id="lic-change">تغییر کلید لایسنس</button></div>
      <p class="muted small">بررسی خودکار هر ۲۴ ساعت؛ حداکثر ۷ روز بدون اینترنت.</p>`;
    q("#lic-recheck").onclick = async () => { try { const r = await api("/setup/license/recheck", { method: "POST" }); toast(r.allowed ? "لایسنس معتبر است" : r.reason, r.allowed ? "ok" : "err"); licensePanel(container); } catch (e) { toast(e.message, "err"); } };
    q("#lic-change").onclick = () => licenseScreen(l, async () => { closeOverlay(); toast("لایسنس جدید فعال شد"); licensePanel(container); }, { title: "کلید لایسنس جدید" });
  }

  /* ---------- orchestration ---------- */
  async function gate() {
    try { S.status = await pub("/setup/status"); } catch (_) { S.status = null; return true; } // server down: let normal boot show errors
    const lic = S.status.license;
    if (!S.status.setup_done) {
      await new Promise((resolve) => wizard(async (r, body) => {
        // first-run heavy loading, then to login with the chosen credentials prefilled
        S.status.setup_done = true;
        loadingScreen(S.status.install_loading_seconds || 45 * 60, true, async () => {
          // real work: apply theme, warm caches
          try { if (typeof applyTheme === "function") await applyTheme(); } catch (_) {}
        }, () => { closeOverlay(); sessionStorage.setItem("sm.first.pending", "1"); const u = q("#login-username"); if (u) u.value = body.admin_username || ""; resolve(); });
      }));
      return true;
    }
    if (!lic.allowed) {
      await new Promise((resolve) => licenseScreen(lic, () => { closeOverlay(); resolve(); }));
      return true;
    }
    return true;
  }

  // After a successful login: licence recheck (if due) + the per-login loading screen (2 min; 45 min the very first time).
  async function afterLogin() {
    if (sessionStorage.getItem(LS_LOADED) === localStorage.getItem("token")) return;
    // v1.5.1: the long install screen is shown ONLY inside the setup wizard.
    // Every login afterwards gets the short one (2 min).
    const first = false;
    const seconds = 120;
    await new Promise((resolve) => loadingScreen(seconds, first, async () => {
      try { const l = await api("/setup/license/recheck", { method: "POST" }); if (!l.allowed) throw Object.assign(new Error(l.reason), { code: "LICENSE" }); } catch (e) { if (e.code === "LICENSE" || e.status === 402) throw e; }
      try { if (typeof loadRuntimeConfig === "function") await loadRuntimeConfig(); if (typeof applyTheme === "function") await applyTheme(); } catch (_) {}
    }, async (err) => {
      closeOverlay();
      if (err) { toast(err.message || "لایسنس نامعتبر", "err"); localStorage.removeItem("token"); location.reload(); return; }
      const firstEver = sessionStorage.getItem("sm.first.pending") === "1";
      sessionStorage.setItem(LS_LOADED, localStorage.getItem("token") || "1"); sessionStorage.removeItem("sm.first.pending");
      if (firstEver) { try { await pairingIntro(); } catch (_) {} }
      resolve();
    }));
  }

  /* ---------- v1.7: one-time "connect your phone" screen (right after the very first login) ---------- */
  function pairingIntro() {
    return new Promise((resolve) => {
      const o = overlay("ob-pair");
      o.innerHTML = `<div class="ob-card ob-anim" style="width:min(640px,100%)">
        ${LOGO()}
        <h1>${ico("phone", 26)} اتصال گوشی (اختیاری)</h1>
        <p class="muted">نسخهٔ اندروید همین برنامه را روی گوشی نصب کنید و این کد را با آن اسکن کنید؛ گوشی و رایانه بدون اینترنت و روی همین وای‌فای همگام می‌شوند. هر زمان خواستید از «تنظیمات → موبایل» هم می‌توانید کد جدید بسازید.</p>
        <div id="ob-pair-qr" style="display:flex;justify-content:center;margin:12px 0"><span class="muted">در حال ساخت کد…</span></div>
        <div id="ob-pair-info" class="muted" style="font-size:12px;line-height:2"></div>
        <div class="ob-actions" style="display:flex;gap:10px;justify-content:center;margin-top:16px">
          <button class="btn btn-primary" id="ob-pair-done">ادامه</button>
          <button class="btn" id="ob-pair-skip">بعداً از تنظیمات</button>
        </div>
      </div>`;
      const done = () => { closeOverlay(); resolve(); };
      q("#ob-pair-done").addEventListener("click", done); q("#ob-pair-skip").addEventListener("click", done);
      (async () => {
        try {
          const r = await api("/mobile/pair/info");
          let html = "";
          if (window.qrcode) { const qq = window.qrcode(0, "M"); qq.addData(r.qr_text); qq.make(); html = `<div style="width:240px;height:240px;background:#fff;padding:6px;border-radius:12px">${qq.createSvgTag({ cellSize: 4, margin: 8, scalable: true }).replace("<svg", '<svg style="width:100%;height:100%"')}</div>`; }
          else if (r.qr_png) html = `<img src="${r.qr_png}" alt="QR" style="width:240px;height:240px;border-radius:12px;background:#fff"/>`;
          q("#ob-pair-qr").innerHTML = html || `<span class="error">ساخت کد ممکن نشد — از تنظیمات → موبایل استفاده کنید.</span>`;
          q("#ob-pair-info").innerHTML = `آدرس رایانه در شبکه: ${r.addresses.map((a) => `<code class="ltr">http://${a}:${r.port}</code>`).join(" · ")}<br/>نسخهٔ وب موبایل (بدون نصب): <code class="ltr">${_esc(r.mobile_url)}</code>`;
        } catch (e) { q("#ob-pair-qr").innerHTML = `<span class="muted">${_esc(e.message || "خطا")}</span>`; }
      })();
    });
  }

  window.Onboarding = { gate, afterLogin, alertsStack, licensePanel, licenseScreen, closeOverlay, wizard, pairingIntro };
})();
