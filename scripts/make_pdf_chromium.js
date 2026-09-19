#!/usr/bin/env node
/* Build docs/SCREENSHOTS.pdf from docs/SCREENSHOTS.md with headless Chromium
 * (same markdown subset as scripts/make_pdf.py). Fonts: the bundled Vazirmatn. */
const fs = require("fs"); const path = require("path");
const chromium = require("@sparticuz/chromium").default || require("@sparticuz/chromium");
const puppeteer = require("puppeteer-core");
const DOCS = path.join(__dirname, "..", "docs");
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function mdToHtml(md) {
  const out = []; let inCode = false, inList = false;
  const inline = (t) => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  for (const line of md.split("\n")) {
    if (line.startsWith("```")) { inCode = !inCode; out.push(inCode ? '<pre class="code">' : "</pre>"); continue; }
    if (inCode) { out.push(esc(line)); continue; }
    let m;
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) { if (inList) { out.push("</ul>"); inList = false; } out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); continue; }
    if ((m = line.trim().match(/^!\[[^\]]*\]\((screenshots\/[^)]+)\)$/))) {
      const b64 = fs.readFileSync(path.join(DOCS, m[1])).toString("base64");
      out.push(`<img src="data:image/png;base64,${b64}"/>`); continue; }
    if (line.startsWith("> ")) {
      const last = out[out.length - 1];
      if (last && last.startsWith("<blockquote>")) out[out.length - 1] = last.replace(/<\/blockquote>$/, " " + inline(line.slice(2)) + "</blockquote>");
      else out.push(`<blockquote>${inline(line.slice(2))}</blockquote>`);
      continue; }
    if (line.startsWith("- ")) { if (!inList) { out.push("<ul>"); inList = true; } out.push(`<li>${inline(line.slice(2))}</li>`); continue; }
    if (inList && line.trim() === "") { out.push("</ul>"); inList = false; continue; }
    if (line.trim() === "---") { out.push('<hr/>'); continue; }
    if (line.trim() === "") { out.push(""); continue; }
    out.push(`<p>${inline(line)}</p>`);
  }
  if (inList) out.push("</ul>");
  return out.join("\n");
}
(async () => {
  let md = fs.readFileSync(path.join(DOCS, "SCREENSHOTS.md"), "utf8");
  const cut = md.indexOf("## نحوهٔ تولید مجدد تصاویر");
  if (cut > 0) { const after = md.indexOf("\n---", cut); md = md.slice(0, cut) + (after > 0 ? md.slice(after) : ""); }
  const font = (f) => fs.readFileSync(path.join(__dirname, "..", "frontend", "fonts", f)).toString("base64");
  const css = `
@font-face{font-family:V;src:url(data:font/woff2;base64,${font("Vazirmatn-Regular.woff2")}) format("woff2");font-weight:400}
@font-face{font-family:V;src:url(data:font/woff2;base64,${font("Vazirmatn-Bold.woff2")}) format("woff2");font-weight:700}
body{font-family:V,sans-serif;direction:rtl;text-align:right;font-size:12.5px;line-height:1.9;color:#111;margin:0}
h1{font-size:22px;border-bottom:2px solid #2563eb;padding-bottom:6px}h2{font-size:17px;margin-top:26px;page-break-before:always}h1+h2,h2:first-of-type{page-break-before:auto}
h3{font-size:14px;margin-top:18px;color:#1e3a8a}img{max-width:100%;border:1px solid #d1d5db;border-radius:6px;margin:6px 0 14px;page-break-inside:avoid}
code{font-family:monospace;background:#f3f4f6;padding:1px 4px;border-radius:3px;direction:ltr;unicode-bidi:embed}
pre.code{background:#f3f4f6;padding:10px;direction:ltr;text-align:left;font-size:11px;white-space:pre-wrap}
blockquote{border-right:3px solid #2563eb;margin:8px 0;padding:4px 10px;background:#eff6ff}
.footer{position:fixed;bottom:0;font-size:10px;color:#666}`;
  const html = `<!doctype html><html lang="fa"><head><meta charset="utf-8"><title>راهنمای تصویری سامانه سوپرمارکت</title><style>${css}</style></head><body>${mdToHtml(md)}<p class="muted" style="margin-top:30px;color:#666">طراحی و توسعه توسط خواجوی — نسخهٔ ${process.env.APP_VERSION || ""}</p></body></html>`;
  const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true, args: [...chromium.args, "--no-sandbox"] });
  const page = await browser.newPage();
  await page.setContent(html, { waitUntil: "load" });
  await page.evaluateHandle("document.fonts.ready");
  const out = path.join(DOCS, "SCREENSHOTS.pdf");
  await page.pdf({ path: out, format: "A4", printBackground: true, margin: { top: "14mm", bottom: "14mm", left: "12mm", right: "12mm" },
    displayHeaderFooter: true, headerTemplate: "<span></span>", footerTemplate: '<div style="font-size:9px;width:100%;text-align:center;color:#666"><span class="pageNumber"></span> / <span class="totalPages"></span></div>' });
  console.log("wrote", out, fs.statSync(out).size, "bytes");
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
