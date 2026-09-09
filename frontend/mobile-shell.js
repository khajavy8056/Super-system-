/* =============================================================================
 * v1.9 — MOBILE SHELL (JS) for the full panel on Android.
 *
 * Zero feature duplication: every section is the SAME RENDER[view] the Windows
 * panel uses, talking to the paired shop PC. This file only adds the phone
 * chrome around it: bottom tab bar (5 primary), a drawer with EVERY section,
 * a floating native-scanner button, table → card labelling, Android back
 * button routing, and a graceful hand-off to the local-first phone app
 * (/mobile/) when the PC cannot be reached.
 *
 * Runs after app.js + accounting.js (shares `state`, `NAV`, `go`, `icon`, …).
 * ========================================================================== */
(function () {
  "use strict";
  const NATIVE = window.SupermarketAndroid || null;
  const isPhone = () => NATIVE || window.matchMedia("(max-width: 760px)").matches || /Android|iPhone/i.test(navigator.userAgent) && window.matchMedia("(max-width: 1024px)").matches;
  if (!isPhone()) return;
  document.documentElement.classList.add("m-shell");

  const $ = (s) => document.querySelector(s);
  const TABS = [["dashboard", "خانه"], ["pos", "فروش"], ["products", "کالاها"], ["inventory", "انبار"], ["__more", "بیشتر"]];
  const GROUPS = [
    ["فروش و مشتری", ["pos", "invoices", "customers", "marketing"]],
    ["کالا و انبار", ["products", "batches", "inventory"]],
    ["مدیریت", ["dashboard", "reports", "accounting", "users", "audit"]],
    ["سیستم", ["settings", "hardware", "diagnostics", "support"]],
  ];
  const ICON_MORE = '<path d="M4 6h16M4 12h16M4 18h16"/>';
  const ICON_PHONE = '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>';
  const ICON_CAM = '<path d="M4 8V5h3M20 8V5h-3M4 16v3h3M20 16v3h-3"/><path d="M7 12h10"/>';

  /* ---------- chrome ---------- */
  function mount() {
    if ($("#m-tabbar")) return;
    const app = $("#app-view");
    // top bar: hamburger on the right (RTL start)
    const tb = $(".topbar");
    if (tb && !$("#m-menu")) {
      const b = document.createElement("button"); b.id = "m-menu"; b.className = "m-menu-btn"; b.setAttribute("aria-label", "منو");
      b.innerHTML = `<svg class="ic" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round">${ICON_MORE}</svg>`;
      b.onclick = () => drawer(true);
      tb.prepend(b);
    }
    // bottom tabs
    const nav = document.createElement("nav"); nav.id = "m-tabbar"; nav.className = "m-tabbar";
    app.append(nav);
    // drawer
    const bg = document.createElement("div"); bg.className = "m-drawer-bg"; bg.onclick = () => drawer(false);
    const dr = document.createElement("aside"); dr.className = "m-drawer"; dr.id = "m-drawer";
    app.append(bg, dr);
    // scanner FAB (native only — the browser build keeps the in-page ZXing scanner of /mobile/)
    if (NATIVE && NATIVE.hasNativeScanner && NATIVE.hasNativeScanner()) {
      const fab = document.createElement("button"); fab.className = "m-scan-fab"; fab.id = "m-scan-fab"; fab.setAttribute("aria-label", "اسکن بارکد");
      fab.innerHTML = `<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round">${ICON_CAM}</svg>`;
      fab.onclick = () => NATIVE.scan(state.view === "pos" ? "اسکن کالا برای فروش" : "اسکن بارکد");
      app.append(fab);
    }
    renderTabs(); renderDrawer();
  }

  function tabIcon(key) {
    if (key === "__more") return `<svg class="ic" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round">${ICON_MORE}</svg>`;
    const ico = (NAV.find((n) => n[0] === key) || [])[3] || "dashboard";
    return icon(ico, 24);
  }
  function renderTabs() {
    const nav = $("#m-tabbar"); if (!nav) return;
    const perm = Object.fromEntries(NAV.map((n) => [n[0], n[2]]));
    nav.innerHTML = TABS.map(([k, l]) => {
      if (k !== "__more" && !can(perm[k])) return `<button class="m-tab" disabled style="opacity:.3">${tabIcon(k)}<span>${l}</span></button>`;
      const active = k === "__more" ? !TABS.some((t) => t[0] === state.view) : state.view === k;
      return `<button class="m-tab ${active ? "active" : ""}" data-k="${k}">${tabIcon(k)}<span>${l}</span>${k === "__more" ? `<i class="m-badge hidden" id="m-more-badge"></i>` : ""}</button>`;
    }).join("");
    nav.querySelectorAll(".m-tab[data-k]").forEach((b) => b.onclick = () => (b.dataset.k === "__more" ? drawer(true) : go(b.dataset.k)));
  }
  function renderDrawer() {
    const dr = $("#m-drawer"); if (!dr) return;
    const by = Object.fromEntries(NAV.map((n) => [n[0], n]));
    const store = (state.store && state.store.name) || (NATIVE && NATIVE.getStoreName && NATIVE.getStoreName()) || "سوپرمارکت";
    dr.innerHTML = `
      <div class="m-drawer-head"><img src="/icons/logo.svg" alt=""><div><b>${esc(store)}</b><span>${esc(state.user ? state.user.full_name || state.user.username : "")}</span></div></div>
      <div class="m-drawer-list">
        ${GROUPS.map(([title, keys]) => { const items = keys.filter((k) => by[k] && can(by[k][2])); return items.length ? `<div class="m-sec">${title}</div>` + items.map((k) => `<button class="nav-item ${state.view === k ? "active" : ""}" data-k="${k}">${icon(by[k][3], 20)}<span>${esc(by[k][1])}</span>${k === "support" ? `<i class="nav-badge hidden" id="nav-sup-badge"></i>` : ""}</button>`).join("") : ""; }).join("")}
        <div class="m-sec">گوشی</div>
        <button class="nav-item" data-act="phone"><svg class="ic" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round">${ICON_PHONE}</svg><span>حالت سریع گوشی (آفلاین / شمارش)</span></button>
        ${NATIVE ? `<button class="nav-item" data-act="unpair">${icon("scanner", 20)}<span>اتصال دوباره به رایانه (QR)</span></button>` : ""}
      </div>
      <div class="m-drawer-foot">
        <div class="m-sync"><i id="m-sync-dot"></i><span id="m-sync-txt">اتصال به رایانهٔ فروشگاه…</span></div>
        <button class="btn btn-sm" data-act="theme">پوسته</button>
        <button class="btn btn-sm btn-ghost" data-act="logout">خروج از حساب</button>
      </div>`;
    dr.querySelectorAll(".nav-item[data-k]").forEach((b) => b.onclick = () => { drawer(false); go(b.dataset.k); });
    dr.querySelector('[data-act="phone"]').onclick = () => { location.href = "/mobile/index.html"; };
    const up = dr.querySelector('[data-act="unpair"]'); if (up) up.onclick = () => { if (confirm("به صفحهٔ اتصال می‌روید؛ داده‌های گوشی حفظ می‌شود.")) { ["m_server", "m_token", "m_device", "m_store", "m_cursor", "m_standalone"].forEach((k) => localStorage.removeItem(k)); NATIVE.unpair(); } };
    dr.querySelector('[data-act="theme"]').onclick = () => { const t = $("#sb-theme"); t && t.click(); };
    dr.querySelector('[data-act="logout"]').onclick = () => { drawer(false); const l = $("#logout"); l && l.click(); };
    pingServer();
  }
  function drawer(open) { $(".m-drawer-bg").classList.toggle("open", open); $("#m-drawer").classList.toggle("open", open); if (open) renderDrawer(); }

  /* ---------- reachability: the PC is the source of truth; if it goes away, hand off to the phone app ---------- */
  let failStreak = 0;
  async function pingServer() {
    const dot = $("#m-sync-dot"), txt = $("#m-sync-txt");
    const c = new AbortController(); const t = setTimeout(() => c.abort(), 3500);
    try {
      const r = await fetch((window.SM_SERVER || "") + "/health", { signal: c.signal, cache: "no-store" });
      if (!r.ok) throw new Error();
      failStreak = 0;
      if (dot) dot.classList.add("on"); if (txt) txt.textContent = "متصل به رایانهٔ فروشگاه · همگام";
    } catch (_) {
      failStreak++;
      if (dot) dot.classList.remove("on"); if (txt) txt.textContent = "رایانه در دسترس نیست";
      if (NATIVE && failStreak >= 3 && !window.__mHandoff) {
        window.__mHandoff = true;
        toast("رایانهٔ فروشگاه در دسترس نیست — به حالت آفلاین گوشی می‌روید");
        setTimeout(() => { location.href = "/mobile/index.html"; }, 1500);
      }
    } finally { clearTimeout(t); }
  }
  setInterval(pingServer, 15000);

  /* ---------- table → cards: copy header text into data-l so cells are labelled ---------- */
  function labelTables(root) {
    (root || document).querySelectorAll("table").forEach((tbl) => {
      const heads = [...tbl.querySelectorAll("thead th")].map((th) => th.textContent.trim());
      if (!heads.length) return;
      if (heads.length <= 2) tbl.classList.add("m-kv");
      tbl.querySelectorAll("tbody tr").forEach((tr) => [...tr.children].forEach((td, i) => { if (i > 0 && heads[i] && !td.hasAttribute("colspan")) td.setAttribute("data-l", heads[i]); }));
    });
  }
  const mo = new MutationObserver((muts) => { for (const m of muts) m.addedNodes.forEach((n) => { if (n.nodeType === 1 && (n.matches("table, .table-wrap, .card, .view, .modal") || n.querySelector("table"))) labelTables(n.parentNode || n); }); });
  mo.observe(document.body, { childList: true, subtree: true });

  /* ---------- hook the panel's navigation ---------- */
  const _go = window.go || go;
  window.go = async function (view) { const r = await _go(view); renderTabs(); const d = $("#m-drawer"); if (d && d.classList.contains("open")) renderDrawer(); labelTables(); window.scrollTo({ top: 0 }); history.pushState({ v: view }, "", "#" + view); return r; };
  const _showApp = window.showApp;
  if (typeof showApp === "function") window.showApp = function () { _showApp(); mount(); renderTabs(); };
  window.addEventListener("popstate", () => { if ($("#m-drawer") && $("#m-drawer").classList.contains("open")) { drawer(false); return; } if (!$("#modal").classList.contains("hidden")) { closeModal(); return; } });
  // Android back → close sheet/drawer, else previous view (history), else confirm exit (native)
  window.__androidBack = () => {
    if ($("#m-drawer") && $("#m-drawer").classList.contains("open")) { drawer(false); return true; }
    if (!$("#modal").classList.contains("hidden")) { closeModal(); return true; }
    if (state.view !== "dashboard") { go("dashboard"); return true; }
    return false;
  };
  // native scanner result → the panel's own scan router (POS/products/batches/inventory)
  window.__nativeScan = (code) => { if (typeof scanDeliver === "function") scanDeliver(String(code || "").trim()); };
  window.__nativeScanCancel = () => {};

  // Login screen on an Android phone whose PC is unreachable → the local-first phone app (never a dead end)
  const lv = $("#login-view");
  new MutationObserver(async () => {
    if (!NATIVE || lv.classList.contains("hidden") || window.__mHandoff) return;
    try { const r = await fetch((window.SM_SERVER || "") + "/health", { cache: "no-store" }); if (!r.ok) throw 0; }
    catch (_) { window.__mHandoff = true; location.replace("/mobile/index.html"); }
  }).observe(lv, { attributes: true, attributeFilter: ["class"] });

  // if the panel is already showing (script loaded after boot), mount now
  const obs = new MutationObserver(() => { if (!$("#app-view").classList.contains("hidden")) { mount(); renderTabs(); } });
  obs.observe($("#app-view"), { attributes: true, attributeFilter: ["class"] });
  if (!$("#app-view").classList.contains("hidden")) { mount(); renderTabs(); }
})();
