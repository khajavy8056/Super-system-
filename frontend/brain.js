/* v4.0 — «مغز فروشگاه» (Business Brain): Decision Center + admin chat.
 *
 * Depends on app.js globals: api, $, el, esc, money, icon, toast, can, go,
 * RENDER, NAV, NAV_GROUPS, openModal, closeModal, faDateTime, state.
 *
 * Two rules from the brief are visible in this file and must stay that way:
 *
 * 1. the chat is an **admin surface** — the nav entry needs `settings.manage`,
 *    so a cashier never renders it, and the API refuses them anyway;
 * 2. the manager only ever sees the answer, the numbers behind it and the four
 *    buttons (بررسی / اجرا / بعداً / رد). Tool calls, JSON and the model's
 *    reasoning text stay server-side; when the brain degrades, that is shown
 *    in plain Persian instead of being hidden.
 */
(function () {
  const fa = (n) => String(n ?? "").replace(/\d/g, (x) => "۰۱۲۳۴۵۶۷۸۹"[x]);
  const STATUS = {
    NEEDS_DECISION: ["نیازمند تصمیم", "badge-amber"],
    WAITING_APPROVAL: ["منتظر تأیید", "badge-red"],
    RUNNING: ["در حال اجرا", "badge-blue"],
    MONITORING: ["در حال پایش", "badge-blue"],
    COMPLETED: ["اجرا شد", "badge-green"],
    MEASURED: ["اندازه‌گیری شد", "badge-green"],
    FAILED: ["اجرا ناموفق", "badge-red"],
    RESOLVED: ["بسته‌شده", "badge-gray"],
    NO_ACTION: ["بدون اقدام", "badge-gray"],
  };
  const PRIO = { 1: "فوری", 2: "مهم", 3: "پیشنهاد", 4: "نکته" };
  const RISK = { none: "بی‌ریسک", low: "کم", medium: "متوسط", high: "بالا" };
  const FLAG_FA = {
    CASH_PRESSURE_HIGH: "فشار نقدینگی", CASH_GAP_AHEAD: "احتمال کسری نقدی",
    CASH_FRAGILE: "حاشیهٔ نقدی نازک", CASH_NEGATIVE_AHEAD: "منفی شدن موجودی",
    CASH_BELOW_RESERVE: "زیر کف نقدینگی", EXPIRY_RISK: "کالای نزدیک انقضا",
    STOCKOUT_RISK: "خطر اتمام موجودی", SALES_DROP: "افت فروش", CHEQUE_OVERDUE: "چک سررسیدگذشته",
    DATA_QUALITY_BLOCKED: "مشکل بحرانی داده", DATA_QUALITY_CRITICAL: "خطای مهم داده",
  };
  const MODE_FA = {
    local_only: "فقط محلی (پیش‌فرض)", local_preferred: "محلی، با اولویت محلی",
    cloud_fallback: "محلی + ابر در صورت نیاز", cloud_only: "فقط ابر",
  };

  if (typeof NAV !== "undefined" && !NAV.some((n) => n[0] === "brain")) {
    NAV.splice(1, 0, ["brain", "مغز فروشگاه", "settings.manage", "brain"]);
    const grp = (typeof NAV_GROUPS !== "undefined" ? NAV_GROUPS : []).find((g) => g[0] === "رشد و تحلیل");
    if (grp) grp[1].splice(1, 0, "brain");
  }
  if (typeof ICONS !== "undefined") {
    ICONS.brain = ICONS.brain || '<path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0 0 6v1a3 3 0 0 0 3 3h1V4z"/><path d="M15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 0 6v1a3 3 0 0 1-3 3h-1V4z"/>';
    ICONS.mic = ICONS.mic || '<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>';
    ICONS.volume = ICONS.volume || '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>';
  }

  let brainTab = "OPEN";
  let chatHistory = [];

  // v4.2.1 — the owner's branding: the model is called «مدل تخصصی سوپری‌من»
  // (light variant: «سوپری‌من لایت») in everything the user sees. The technical
  // id stays in code (it pins the exact file + sha256); it is not a product name.
  const BRAND = (id) => ({ "qwen2.5-1.5b-instruct-q4_k_m": "مدل تخصصی سوپری‌من",
                           "qwen2.5-1.5b-instruct-q3_k_m": "سوپری‌من لایت" }[id] || id || "—");

  // ---------------------------------------------------------------- status strip
  function statusStrip(st) {
    const mode = MODE_FA[st.local_mode] || st.local_mode || "—";
    const runtime = st.runtime || {};
    const model = st.model || {};
    const flags = (st.flags || []).map((f) => `<span class="badge badge-amber">${esc(FLAG_FA[f] || f)}</span>`).join(" ");
    const dq = st.data_quality && st.data_quality !== "OK"
      ? `<span class="badge badge-amber">کیفیت داده: ${esc(st.data_quality)}</span>` : "";
    const cards = [
      ["حالت هوش مصنوعی", mode, runtime.provider === "deterministic" ? "پاسخ‌ها از موتور قطعی می‌آید" : (runtime.model_id || "")],
      ["تصمیم‌های باز", fa((st.decisions || {}).open || 0), "در مرکز تصمیم"],
      ["پیگیری‌های سررسید", fa(((st.followups || {}).overdue || 0)), "نیازمند ثبت نتیجه"],
      ["مدل محلی", model.active ? (model.ready ? "آماده" : "نصب‌شده، آماده‌نشدن") : "نصب نشده",
        model.recommended ? `پیشنهاد این دستگاه: ${BRAND(model.recommended)}` : ""],
    ];
    const host = el("section", { class: "ins-hero" });
    host.innerHTML = `<div class="ins-hero-grid">${cards.map(([t, v, s]) => `
        <div class="ins-hero-card"><span class="muted">${esc(t)}</span><b>${esc(String(v))}</b>
          ${s ? `<span class="muted">${esc(s)}</span>` : ""}</div>`).join("")}</div>
      <div class="ins-hero-flags">${flags} ${dq}</div>
      ${(st.notes || []).map((n) => `<p class="muted">${esc(n)}</p>`).join("")}`;
    return host;
  }

  // ---------------------------------------------------------------- decision cards
  function card(d) {
    const [label, cls] = STATUS[d.status] || [d.status, "badge-gray"];
    const c = el("article", { class: "ins-card" + (d.priority === 1 ? " ins-urgent" : "") });
    const gain = Number(d.expected_gain || 0);
    c.innerHTML = `
      <header><span class="ins-ic">${icon("brain", 20)}</span>
        <div class="ins-head"><span class="ins-kind">${esc(d.decision_kind || "تصمیم")} · ${esc(PRIO[d.priority] || "")}</span>
          <h4>${esc(d.title)}</h4></div>
        <span class="badge ${cls}">${esc(label)}</span></header>
      <p class="ins-body">${esc(d.reason || "")}</p>
      <div class="ins-foot">
        ${gain > 0 ? `<span class="ins-gain muted">اثر تخمینی: <b>${money(gain)}</b></span>` : ""}
        ${d.followup_due ? `<span class="muted">اندازه‌گیری: ${faDateTime(d.followup_due, false)}</span>` : ""}
        ${d.local_decision ? `<span class="badge badge-blue">تصمیم محلی</span>` : ""}
        ${d.pending_sync ? `<span class="badge badge-amber">در انتظار همگام‌سازی</span>` : ""}
      </div>
      <div class="ins-actions"></div>`;
    const act = c.querySelector(".ins-actions");
    act.append(el("button", { class: "btn btn-sm btn-ghost", text: "بررسی", onclick: () => detail(d.id) }));
    if (["NEEDS_DECISION", "WAITING_APPROVAL", "MONITORING"].includes(d.status)) {
      act.append(el("button", { class: "btn btn-sm btn-primary", text: "اجرا", onclick: (e) => approve(d, e.currentTarget) }));
      act.append(el("button", {
        class: "btn btn-sm", text: "بعداً",
        onclick: async (e) => {
          e.currentTarget.disabled = true;
          try { await api(`/brain/decisions/${d.id}/snooze`, { method: "POST", body: JSON.stringify({ days: 3 }) }); toast("سه روز به تعویق افتاد"); RENDER.brain(); }
          catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
        },
      }));
      act.append(el("button", {
        class: "btn btn-sm btn-ghost", text: "رد",
        onclick: async (e) => {
          e.currentTarget.disabled = true;
          try { await api(`/brain/decisions/${d.id}/reject`, { method: "POST", body: JSON.stringify({ reason: "مدیر رد کرد" }) }); toast("رد شد"); RENDER.brain(); }
          catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
        },
      }));
    }
    if (["COMPLETED", "MONITORING", "MEASURED"].includes(d.status)) {
      act.append(el("button", {
        class: "btn btn-sm", text: "اندازه‌گیری نتیجه",
        onclick: async (e) => {
          e.currentTarget.disabled = true;
          try {
            const r = await api(`/brain/decisions/${d.id}/measure`, { method: "POST" });
            toast(r.summary || "نتیجه ثبت شد");
            RENDER.brain();
          } catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
        },
      }));
    }
    return c;
  }

  async function approve(d, button) {
    if (!confirm(`اجرای «${d.title}» تأیید می‌شود؟`)) return;
    button.disabled = true;
    try {
      const r = await api(`/brain/decisions/${d.id}/approve`, { method: "POST", body: JSON.stringify({}) });
      toast(r.status === "COMPLETED" ? "اجرا و تأیید شد" : "در حال اجرا", r.status === "FAILED" ? "err" : "ok");
      RENDER.brain();
    } catch (e) { toast(e.message, "err"); button.disabled = false; }
  }

  async function detail(id) {
    let d;
    try { d = await api(`/brain/decisions/${id}`); }
    catch (e) { toast(e.message, "err"); return; }
    const box = el("div", { class: "ins-detail" });
    const option = (o) => `<li><b>${esc(o.label)}</b>
        <span class="muted">${esc(o.description || "")}</span>
        ${(o.economics || {}).gain_toman ? `<span class="ins-band">اثر: ${money(o.economics.gain_toman)}</span>` : ""}
        <span class="badge badge-gray">ریسک: ${esc(RISK[o.risk] || o.risk || "—")}</span>
        ${o.requires_approval ? '<span class="badge badge-amber">نیازمند تأیید</span>' : ""}</li>`;
    box.innerHTML = `
      <h3>${esc(d.title)}</h3>
      <p class="muted">${esc(d.problem || "")}</p>
      <h4>وضعیت</h4><pre class="kv">${esc(JSON.stringify(d.situation || {}, null, 1)).slice(0, 1800)}</pre>
      <h4>دلیل</h4><p>${esc(d.reason || "")}</p>
      <h4>گزینه‌ها</h4><ul>${(d.options || []).map(option).join("")}</ul>
      ${(d.risks || []).length ? `<h4>ریسک‌ها</h4><ul>${d.risks.map((r) => `<li>${esc(r.statement || r)}</li>`).join("")}</ul>` : ""}
      ${d.policy_verdict && d.policy_verdict.reason ? `<h4>سیاست فروشگاه</h4><p>${esc(d.policy_verdict.reason)}</p>` : ""}
      ${d.execution && d.execution.executions ? `<h4>اجرا</h4><pre class="kv">${esc(JSON.stringify(d.execution, null, 1)).slice(0, 1200)}</pre>` : ""}
      ${d.result ? `<h4>نتیجهٔ اندازه‌گیری</h4><pre class="kv">${esc(JSON.stringify(d.result, null, 1)).slice(0, 1200)}</pre>` : ""}
      ${d.measurement && d.measurement.metric ? `<p class="muted">قرارداد اندازه‌گیری: ${esc(d.measurement.metric)} در ${fa(d.measurement.window_days || 14)} روز</p>` : ""}`;
    openModal(`تصمیم #${fa(d.id)}`, box);
  }

  // ---------------------------------------------------------------- chat
  const nowTime = () => new Date().toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });

  function bubble(role, text, meta) {
    const user = role === "USER";
    const b = el("div", { class: "brain-bubble brain-" + (user ? "user" : "brain") });
    b.innerHTML =
      (user ? "" : `<div class="b-head"><img src="/icons/model-192.png" alt="" /><b>مغز فروشگاه</b></div>`) +
      `<p>${esc(text).replace(/\n/g, "<br>")}</p>` +
      `<div class="b-meta"><span>${user ? "شما" : ""}</span><span>${nowTime()}</span>` +
      (meta ? `<span>· ${esc(meta)}</span>` : "") + `</div>` +
      (user ? "" : `<button type="button" class="btn btn-sm brain-read" title="خواندن صوتی این پاسخ">${icon("volume", 14)} بخوان</button>`);
    const rb = b.querySelector(".brain-read");
    if (rb) rb.addEventListener("click", () => speakFa(text));
    return b;
  }

  /* ---------------- v4.3 — voice: same model, ears + mouth ----------------
   * The owner's rule: the AI model stays EXACTLY as it is (no heavier model).
   * Voice is I/O around it: the browser/OS listens (fa-IR) and reads THE SAME
   * answer text aloud («همون متن به صورت صوتی می‌خونه»). */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  let recognition = null;
  let voiceMode = localStorage.getItem("brainVoiceMode") !== "0";

  function speakFa(text) {
    if (!("speechSynthesis" in window)) {
      toast("خواندن صوتی در این مرورگر پشتیبانی نمی‌شود", "err");
      return;
    }
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(String(text || ""));
      u.lang = "fa-IR";
      u.rate = 1;
      const v = (window.speechSynthesis.getVoices() || []).find((x) => (x.lang || "").toLowerCase().startsWith("fa"));
      if (v) u.voice = v;
      window.speechSynthesis.speak(u);
    } catch (e) { toast(e.message, "err"); }
  }

  /** v4.2.1 — animated "typing" indicator (three pulsing dots) while thinking. */
  function typingBubble(label) {
    const b = el("div", { class: "brain-bubble brain-brain brain-typing-b" });
    b.innerHTML = `<div class="b-head"><img src="/icons/model-192.png" alt="" /><b>مغز فروشگاه</b></div>
      <div class="brain-typing" aria-label="${esc(label || "در حال پاسخ")}"><i></i><i></i><i></i></div>`;
    return b;
  }

  function chatBox() {
    const wrap = el("section", { class: "brain-chat" });
    wrap.innerHTML = `<header class="brain-chat-head">
        <img src="/icons/model-192.png" alt="مدل سوپری‌من" />
        <div><h3>گفت‌وگو با مغز فروشگاه</h3>
        <span class="muted" id="brain-mode">مدل تخصصی سوپری‌من — محلی و آفلاین</span></div>
        <button type="button" class="btn btn-sm brain-vm" id="brain-vm"></button></header>
      <div class="brain-log" id="brain-log" aria-live="polite"></div>
      <form class="brain-form" id="brain-form">
        <button type="button" class="btn brain-mic" id="brain-mic" title="صحبت کنید به جای تایپ">${icon("mic", 18)}</button>
        <input id="brain-q" class="input" autocomplete="off"
               placeholder="مثلاً: این هفته چقدر پول لازم دارم؟" />
        <button class="btn btn-primary" type="submit">بپرس</button>
      </form>
      <p class="muted">پاسخ‌ها از دادهٔ همین فروشگاه ساخته می‌شود؛ عددی که از ابزار نیامده باشد نمایش داده نمی‌شود.</p>`;
    const log = () => wrap.querySelector("#brain-log");
    const vmBtn = () => wrap.querySelector("#brain-vm");
    const micBtn = () => wrap.querySelector("#brain-mic");
    const paintVm = () => {
      const b = vmBtn(); if (!b) return;
      b.innerHTML = `${icon("volume", 15)} ${voiceMode ? "صوتی: روشن" : "صوتی: خاموش"}`;
      b.classList.toggle("brain-vm-on", voiceMode);
    };
    if (vmBtn()) vmBtn().addEventListener("click", () => {
      voiceMode = !voiceMode;
      localStorage.setItem("brainVoiceMode", voiceMode ? "1" : "0");
      if (!voiceMode && "speechSynthesis" in window) window.speechSynthesis.cancel();
      paintVm();
      toast(voiceMode ? "حالت صوتی روشن شد — گفتار شما فرستاده می‌شود و پاسخ بلند خوانده می‌شود"
          : "حالت صوتی خاموش شد");
    });
    paintVm();
    if (micBtn()) micBtn().addEventListener("click", () => {
      if (!SR) {
        toast("شنیدن گفتار در این محیط پشتیبانی نمی‌شود — در مرورگر کروم/اج یا در اپ اندروید کار می‌کند", "err");
        return;
      }
      if (recognition) { try { recognition.stop(); } catch (e) {} recognition = null; micBtn().classList.remove("listening"); return; }
      try {
        recognition = new SR();
        recognition.lang = "fa-IR";
        recognition.interimResults = false;
        recognition.onresult = (event) => {
          const said = event.results[0][0].transcript;
          const input = wrap.querySelector("#brain-q");
          if (input) input.value = said;
          if (voiceMode) wrap.querySelector("#brain-form").requestSubmit();
        };
        recognition.onend = () => { recognition = null; micBtn().classList.remove("listening"); };
        recognition.onerror = (event) => {
          micBtn().classList.remove("listening");
          toast(event.error === "not-allowed" ? "اجازهٔ میکروفون داده نشده"
              : event.error === "no-speech" ? "صدایی تشخیص داده نشد — دوباره تلاش کنید"
              : `شنیدن صوتی ناموفق بود (${event.error})`, "err");
        };
        recognition.start();
        micBtn().classList.add("listening");
      } catch (e) { recognition = null; toast(e.message, "err"); }
    });
    chatHistory.forEach((m) => log().append(bubble(m.role, m.content,
      m.role === "ASSISTANT" && m.meta ? `${m.meta.intent || ""} · ${m.meta.mode || ""}` : "")));
    wrap.querySelector("#brain-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = wrap.querySelector("#brain-q");
      const question = (input.value || "").trim();
      if (!question) return;
      input.value = "";
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();   // v4.3
      log().append(bubble("USER", question));
      const thinking = typingBubble("در حال بررسی داده‌های فروشگاه…");
      log().append(thinking);
      try {
        const answer = await api("/brain/chat", { method: "POST", body: JSON.stringify({ question }) });
        thinking.remove();
        const meta = [answer.intent, answer.mode === "llm" ? "پاسخ با مدل محلی" : "پاسخ قطعی",
          answer.ms ? `${fa(answer.ms)} میلی‌ثانیه` : ""].filter(Boolean).join(" · ");
        log().append(bubble("ASSISTANT", answer.text, meta));
        if (voiceMode) speakFa(answer.text);   // v4.3 — the same text, read aloud
        if (answer.warnings && answer.warnings.length) {
          log().append(el("div", { class: "view-feedback", role: "alert",
            text: `نکته: ${answer.warnings.map((w) => ({ MODEL_FAILED: "مدل محلی پاسخ نداد؛ پاسخ قطعی نمایش داده شد", NUMBER_REJECTED: "عددی که منبع نداشت حذف شد", DATA_QUALITY: "کیفیت داده پایین است" }[w] || w)).join("، ")}` }));
        }
        if (answer.degraded && answer.degraded.length) {
          log().append(el("div", { class: "view-feedback", role: "alert", text: "بخشی از داده‌ها ناقص است؛ نتیجه با احتیاط خوانده شود." }));
        }
        log().scrollTop = log().scrollHeight;
      } catch (e) {
        thinking.remove();
        log().append(bubble("ASSISTANT", `نتوانستم پاسخ بدهم: ${e.message}`));
      }
    });
    return wrap;
  }

  // ---------------------------------------------------------------- follow-ups + memory + model
  function followupsBox(items) {
    const box = el("section", { class: "ins-grid" });
    if (!items.length) box.append(el("p", { class: "muted", text: "پیگیری بازی نیست." }));
    items.forEach((f) => {
      const c = el("article", { class: "ins-card" });
      const due = f.due_at ? new Date(f.due_at) : null;
      const late = due && due < new Date();
      c.innerHTML = `<header><span class="ins-ic">${icon("clock", 20)}</span>
        <div class="ins-head"><span class="ins-kind">${esc(f.kind || "پیگیری")}</span><h4>${esc(f.title)}</h4></div>
        ${late ? '<span class="badge badge-red">سررسید گذشته</span>' : '<span class="badge badge-gray">باز</span>'}</header>
        <p class="ins-body">${esc(f.note || "")}</p>` +
        (f.decision_id ? `<div class="ins-foot"><span class="muted">تصمیم #${fa(f.decision_id)}</span></div>` : "");
      const act = el("div", { class: "ins-actions" });
      act.append(el("button", {
        class: "btn btn-sm", text: "ثبت نتیجه",
        onclick: async (e) => {
          const result = prompt("چه اتفاقی افتاد؟ (مثلاً: مشتری پرداخت کرد، فروش ۱۵٪ بالا رفت)", "");
          if (result == null) return;
          e.currentTarget.disabled = true;
          try { await api(`/brain/followups/${f.id}/resolve`, { method: "POST", body: JSON.stringify({ result }) }); toast("ثبت شد"); RENDER.brain(); }
          catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
        },
      }));
      c.append(act);
      box.append(c);
    });
    return box;
  }

  function memoryBox(memory) {
    const box = el("section", { class: "ins-grid" });
    const groups = [["چیزهایی که فروشگاه یاد گرفته", memory.facts || []],
      ["سیاست‌های فعال", memory.policies || []]];
    groups.forEach(([title, rows]) => {
      const c = el("article", { class: "ins-card" });
      c.innerHTML = `<header><span class="ins-ic">${icon("sparkle", 20)}</span>
        <div class="ins-head"><h4>${esc(title)}</h4></div></header>` +
        (rows.length ? `<ul>${rows.slice(0, 30).map((r) => `<li>${esc(r.label || r.key || r.title || "")}
            <span class="muted">${esc(String(r.value ?? r.summary ?? ""))}</span></li>`).join("")}</ul>`
          : '<p class="muted">هنوز چیزی ثبت نشده.</p>');
      box.append(c);
    });
    return box;
  }

  function modelBox(model) {
    const c = el("article", { class: "ins-card" });
    const active = model.active || null;
    c.innerHTML = `<header><img class="ins-ic-img" src="/icons/model-192.png" alt="مدل سوپری‌من" />
      <div class="ins-head"><span class="ins-kind">مدل هوش مصنوعی</span><h4>${esc(active ? `مدل فعال: ${model.active_name || BRAND(active.model_id || active)}` : "مدلی نصب نشده")}</h4></div>
      ${model.binary ? '<span class="badge badge-green">موتور محلی موجود</span>' : '<span class="badge badge-amber">موتور محلی نصب نیست</span>'}</header>
      <p class="ins-body">پیشنهاد برای این دستگاه: <b>${esc(BRAND(model.recommended))}</b>
        · زمینهٔ متن: ${fa(model.context || 4096)} توکن · سقف حجم فایل: ۲ گیگابایت</p>`;
    const act = el("div", { class: "ins-actions" });
    act.append(el("button", {
      class: "btn btn-sm", text: "دریافت مدل پیشنهادی",
      onclick: async (e) => { e.currentTarget.disabled = true; try { const r = await api("/brain/model/download", { method: "POST", body: JSON.stringify({}) }); toast(r.message || "دریافت شد", r.ok ? "ok" : "err"); RENDER.brain(); } catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; } },
    }));
    act.append(el("button", {
      class: "btn btn-sm", text: "سنجش سرعت",
      onclick: async (e) => { e.currentTarget.disabled = true; try { const r = await api("/brain/model/benchmark", { method: "POST", body: JSON.stringify({}) }); toast(r.ok ? "سنجش انجام شد" : (r.message || "سنجش انجام نشد"), r.ok ? "ok" : "err"); RENDER.brain(); } catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; } },
    }));
    c.append(act);
    if (model.notes && model.notes.length) {
      c.append(el("p", { class: "muted", text: model.notes.join(" · ") }));
    }
    const wrap = el("section", { class: "ins-grid" });
    wrap.append(c);
    return wrap;
  }

  // ---------------------------------------------------------------- view
  const TABS = [["OPEN", "روی میز"], ["COMPLETED,MEASURED,MONITORING", "اجراشده"],
    ["RESOLVED,NO_ACTION", "بسته‌شده"], ["FOLLOWUPS", "پیگیری‌ها"], ["MEMORY", "حافظه"], ["MODEL", "مدل"]];

  RENDER.brain = async () => {
    const v = $("#view");
    v.innerHTML = `<div class="ins-wrap">
      <div class="page-intro"><div><span class="eyebrow">تصمیم، نه دستور</span><h2>مغز فروشگاه</h2>
        <p>وضعیت فروشگاه را می‌خواند، گزینه‌ها را می‌سازد و پیش از هر اقدامی از شما تأیید می‌گیرد.</p></div>
        <span class="intro-badge">مخصوص مدیر</span></div>
      <div id="brain-status"><div class="muted">در حال خواندن وضعیت…</div></div>
      <div class="set-tabs" id="brain-tabs"></div>
      <div id="brain-body"></div></div>`;
    $("#topbar-actions").innerHTML = "";
    $("#topbar-actions").append(el("button", {
      class: "btn btn-sm btn-primary", text: "بررسی الان",
      onclick: async (e) => {
        e.currentTarget.disabled = true;
        try { const r = await api("/brain/proactive/run?force=true", { method: "POST" }); toast(`${fa(r.alerts.length)} مورد بررسی شد`); RENDER.brain(); }
        catch (err) { toast(err.message, "err"); } finally { e.currentTarget.disabled = false; }
      },
    }));

    let status;
    try { status = await api("/brain/status"); }
    catch (e) {
      $("#brain-status").innerHTML = `<div class="view-feedback" role="alert">
        <h3>دسترسی به مغز فروشگاه ممکن نشد</h3><p>${esc(e.message)}</p>
        <button class="btn" onclick="RENDER.brain()">تلاش دوباره</button></div>`;
      return;
    }
    $("#brain-status").innerHTML = "";
    $("#brain-status").append(statusStrip(status));

    const tabs = $("#brain-tabs");
    tabs.innerHTML = "";
    TABS.forEach(([key, label]) => tabs.append(el("button", {
      class: "set-tab" + (key === brainTab ? " active" : ""), text: label,
      onclick: () => { brainTab = key; RENDER.brain(); },
    })));

    const body = $("#brain-body");
    if (brainTab === "FOLLOWUPS") {
      let items = [];
      try { items = await api("/brain/followups"); } catch (e) { toast(e.message, "err"); }
      body.append(followupsBox(Array.isArray(items) ? items : []));
      return;
    }
    if (brainTab === "MEMORY") {
      let memory = { facts: [], policies: [] };
      try { memory = await api("/brain/memory"); } catch (e) { toast(e.message, "err"); }
      body.append(memoryBox(memory));
      body.append(chatBox());
      return;
    }
    if (brainTab === "MODEL") {
      let model = {};
      try { model = await api("/brain/model"); } catch (e) { toast(e.message, "err"); }
      body.append(modelBox(model));
      return;
    }

    let list = [];
    try {
      const query = brainTab === "OPEN"
        ? "NEEDS_DECISION,WAITING_APPROVAL,RUNNING,MONITORING" : brainTab;
      list = await api(`/brain/decisions?status=${encodeURIComponent(query)}&limit=100`);
    } catch (e) { toast(e.message, "err"); }
    list = Array.isArray(list) ? list : [];
    if (!list.length) {
      body.append(el("div", { class: "view-feedback", role: "status",
        text: brainTab === "OPEN"
          ? "الان تصمیمی روی میز نیست. اگر وضعیت فروشگاه عادی باشد، همین پاسخ درست است."
          : "موردی در این بخش ثبت نشده." }));
    } else {
      const grid = el("div", { class: "ins-grid" });
      list.forEach((d) => grid.append(card(d)));
      body.append(grid);
    }
    body.append(chatBox());
  };

  window.BrainCenter = { refresh: () => RENDER.brain(), open: (id) => detail(id) };
})();
