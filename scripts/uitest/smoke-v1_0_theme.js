/**
 * v1.0.0 (RASA) — بازبینی پوسته (Light/Dark) و هویت برند، با DOM واقعی.
 *
 * باگ گزارش‌شدهٔ مالک: «وقتی ویندوز را روی حالت روشن می‌گذارم، بعضی جاها — مخصوصاً
 * نوار کناری — تیره می‌ماند.» این تست همان چیزی را می‌سنجد که کاربر می‌بیند:
 * HTML و همهٔ CSSها را در jsdom بار می‌کند، `data-theme` را بین dark و light
 * جابه‌جا می‌کند و بررسی می‌کند که رنگ نوار کناری/سرصفحه/نوار وضعیت **از روی
 * توکن پوسته** تغییر کند و در حالت روشن هیچ گرادیان تیرهٔ دستی نمانده باشد.
 *
 * اجرا:  cd scripts && npm run smoke-v100
 * (نیازی به سرور زنده ندارد؛ این تست فقط پوسته و برند را می‌سنجد.)
 */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const FRONT = path.join(__dirname, "..", "..", "frontend");

const problems = [];
const ok = (label, cond, extra = "") => {
  console.log(`${cond ? "✅" : "❌"} ${label}${extra ? " — " + extra : ""}`);
  if (!cond) problems.push(label);
};

const html = fs.readFileSync(path.join(FRONT, "index.html"), "utf8");
const dom = new JSDOM(html, { url: "http://127.0.0.1/", runScripts: "outside-only", pretendToBeVisual: true });
const { window } = dom;
const { document } = window;

// ------------------------------------------------------------------ brand
ok("عنوان صفحه نام کامل فارسی است", document.title.includes("رسا سیستم"), document.title);
const loginCard = document.querySelector("#login-view h1");
ok("صفحهٔ ورود نام برند را نشان می‌دهد", /رسا سیستم/.test(loginCard ? loginCard.textContent : ""),
   loginCard ? loginCard.textContent.trim() : "—");
ok("لوگوی صفحهٔ ورود به نشان جدید اشاره می‌کند",
   (document.querySelector("#login-view img") || {}).getAttribute?.("src") === "/icons/logo.svg");
ok("نوار کناری با برند جدید شروع می‌شود",
   /رسا سیستم/.test((document.querySelector(".sidebar .brand span") || {}).textContent || ""));

// ------------------------------------------------------------------ stylesheets
const links = [...document.querySelectorAll('link[rel="stylesheet"]')].map((l) => l.getAttribute("href"));
const EXPECT_LAYERS = ["styles.css", "theme-pro.css", "mobile-shell.css", "desktop.css", "ui-refresh.css", "rasa-ui.css"];
ok("شش لایهٔ CSS به ترتیب بار می‌شود", links.length === EXPECT_LAYERS.length
   && EXPECT_LAYERS.every((f, i) => (links[i] || "").indexOf(f) === 0), links.join(", "));
ok("لایهٔ طراحی RASA آخر از همه است", /rasa-ui\.css/.test(links[links.length - 1] || ""), links[links.length - 1] || "—");
const css = {};
for (const href of links) {
  const file = path.join(FRONT, href.replace(/^\//, "").split("?")[0]);
  css[href] = fs.readFileSync(file, "utf8");
  // jsdom only cascades stylesheets that are IN the document — inject them in the
  // same order the browser loads them, so getComputedStyle() means something.
  const style = document.createElement("style");
  style.textContent = css[href];
  document.head.appendChild(style);
}
const all = Object.values(css).join("\n");

// ------------------------------------------------------------------ shell tokens
const SHELL_TOKENS = ["--shell-bg", "--shell-fg", "--shell-muted", "--shell-hover",
                      "--shell-active-bg", "--shell-active-fg", "--topbar-bg", "--statusbar-bg"];
const declaredInLight = new Set();
const declaredInDark = new Set();
for (const text of Object.values(css)) {
  for (const m of text.matchAll(/^([^{}]*?)\{([^{}]*)\}/gms)) {
    const scope = m[1];
    const block = m[2] || "";
    if (!/data-theme|:root/.test(scope)) continue;
    if (!/--/.test(block)) continue;
    const target = /data-theme="light"|data-theme=light/.test(scope) ? declaredInLight : declaredInDark;
    for (const v of block.matchAll(/(--[a-z0-9-]+)\s*:/gi)) target.add(v[1].toLowerCase());
  }
}
const missingLight = SHELL_TOKENS.filter((t) => declaredInLight.has(t) === false);
ok("توکن‌های پوسته در پالت روشن تعریف شده‌اند", missingLight.length === 0, missingLight.join(", ") || "همه تعریف شده");
ok("توکن‌های پوسته در پالت تیره تعریف شده‌اند",
   SHELL_TOKENS.every((t) => declaredInDark.has(t)));

// light palette values must actually be light
const lightBlock = [...all.matchAll(/\[data-theme="light"\]\s*\{([^{}]*)\}/g)].map((m) => m[1]).join(";");
const lightShellBg = (lightBlock.match(/--shell-bg:\s*([^;]+)/) || [])[1] || "";
const lum = (value) => {
  if (!value) return null;
  const nums = [];
  for (const m of value.matchAll(/#([0-9a-f]{6})/gi)) {
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255);
    nums.push(0.2126 * r + 0.7152 * g + 0.0722 * b);
  }
  for (const m of value.matchAll(/rgba?\(([^)]+)\)/gi)) {
    const p = m[1].split(",").map((x) => x.trim());
    if (p.length < 3) continue;
    const [r, g, b] = p.slice(0, 3).map((x) => Number(x) / 255);
    const a = p.length > 3 ? Number(p[3]) : 1;
    nums.push((0.2126 * r + 0.7152 * g + 0.0722 * b) * a + (1 - a));
  }
  return nums.length ? Math.max(...nums) : null;
};
ok("پس‌زمینهٔ نوار کناری در حالت روشن روشن است",
   lum(lightShellBg) !== null && lum(lightShellBg) > 0.7, lightShellBg.trim());
ok("متن پوسته در حالت روشن تیره است",
   /--shell-fg:\s*#1[0-9a-f]{5}/i.test(lightBlock), (lightBlock.match(/--shell-fg:\s*([^;]+)/) || [])[1]);

// ------------------------------------------------------------------ no dark literals left in shell rules
const SHELL_SEL = [".sidebar", ".brand", ".topbar", ".statusbar", ".nav-item"];
const offenders = [];
for (const [href, text] of Object.entries(css)) {
  for (const m of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const sel = m[1].replace(/\s+/g, " ").trim();
    if (/\[data-theme="dark"\]/.test(sel)) continue;
    if (!SHELL_SEL.some((s) => sel.includes(s))) continue;
    const body = m[2];
    for (const decl of body.split(";")) {
      const [prop, ...rest] = decl.split(":");
      const value = rest.join(":").trim();
      if (!/^(background|background-color|color)$/.test((prop || "").trim())) continue;
      if (/var\(--/.test(value)) continue;
      const dark = [...value.matchAll(/#[0-9a-f]{6}|rgba?\([^)]*\)/gi)]
        .map((x) => x[0]).filter((c) => { const l = lum(c); return l !== null && l < 0.32; });
      if (dark.length) offenders.push(`${path.basename(href)} → ${sel}: ${prop}: ${value.slice(0, 48)}`);
    }
  }
}
ok("هیچ قاعدهٔ پوسته‌ای رنگ تیرهٔ دستی ندارد", offenders.length === 0, offenders.slice(0, 3).join(" | "));

// ------------------------------------------------------------------ theme switching actually changes the shell
// jsdom توکن‌های CSS را حل نمی‌کند، پس همان کاری را می‌کنیم که مرورگر می‌کند:
// مقدار var(--shell-bg) را از بلوک پالت همان پوسته بیرون می‌کشیم و مقایسه می‌کنیم.
const blockOf = (theme) => Object.values(css)
  .flatMap((t) => [...t.matchAll(/^([^{}]*?)\{([^{}]*)\}/gms)])
  .filter((m) => new RegExp(`data-theme="${theme}"`).test(m[1]))
  .map((m) => m[2]).join(";");
const resolveToken = (theme, token) => {
  const m = blockOf(theme).match(new RegExp(`${token}:\\s*([^;]+)`));
  return m ? m[1].trim() : null;
};
document.documentElement.setAttribute("data-theme", "dark");
const darkSidebar = window.getComputedStyle(document.querySelector(".sidebar")).background;
document.documentElement.setAttribute("data-theme", "light");
const lightSidebar = window.getComputedStyle(document.querySelector(".sidebar")).background;
const darkValue = resolveToken("dark", "--shell-bg");
const lightValue = resolveToken("light", "--shell-bg");
ok("نوار کناری در دو پوسته یک چیز نیست", darkValue !== lightValue, `${darkValue} / ${lightValue}`);
ok("مقدار حالت تیره واقعاً تیره است", lum(darkValue) !== null && lum(darkValue) < 0.25, darkValue);
ok("رنگ نوار کناری از توکن می‌آید (نه عدد دستی)", /var\(--shell-bg\)/.test(lightSidebar), lightSidebar);

console.log(problems.length ? `\n❌ ${problems.length} مشکل` : "\n✅ پوسته و برند سالم است");
process.exit(problems.length ? 1 : 0);
