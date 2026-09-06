#!/usr/bin/env node
/* Headless-Chromium screenshot tool (alternative to scripts/shoot.py when Qt
 * WebEngine cannot create a GL context). Same shots.json format.
 *
 *   cd scripts && npm i puppeteer-core @sparticuz/chromium
 *   LD_LIBRARY_PATH=<nss libs> node scripts/shoot_chromium.js scripts/shots.json
 *
 * Renders REAL pages from the running server; prints a blank-check per shot. */
const fs = require("fs"); const path = require("path");
const chromium = require("@sparticuz/chromium").default || require("@sparticuz/chromium");
const puppeteer = require("puppeteer-core");
const OUT = path.join(__dirname, "..", "docs", "screenshots");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function runSteps(page, steps) {
  for (const st of steps || []) {
    if (st.js) { try { await page.evaluate(st.js); } catch (e) { console.log("js:", e.message.slice(0, 120)); } }
    if (st.wait_ms) await sleep(st.wait_ms);
  }
}
(async () => {
  const groups = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true,
    args: [...chromium.args, "--no-sandbox", "--lang=fa", "--font-render-hinting=none"] });
  for (const g of groups) {
    const page = await browser.newPage();
    await page.setViewport({ width: g.viewport[0], height: g.viewport[1], deviceScaleFactor: 1 });
    await page.goto(g.url, { waitUntil: "networkidle0" });
    await sleep(g.settle_ms || 800);
    await runSteps(page, g.steps);
    for (const s of g.shots) {
      await runSteps(page, s.steps);
      await sleep(s.wait_ms || 600);
      const file = path.join(OUT, s.name + ".png");
      await page.screenshot({ path: file, fullPage: !!s.full_height });
      if (s.pdf) await page.pdf({ path: path.join(OUT, s.name + ".pdf"), printBackground: true, format: "A4" });
      console.log("saved", s.name, fs.statSync(file).size, "bytes");
    }
    await page.close();
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
