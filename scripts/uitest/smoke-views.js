const { JSDOM } = require("jsdom");
const fs = require("fs");
const BASE = "http://127.0.0.1:8000";

(async () => {
  const html = fs.readFileSync("" + require("path").join(__dirname, "..", "..", "frontend") + "/index.html", "utf8");
  const dom = new JSDOM(html, { url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  const errors = [];
  window.addEventListener("error", (e) => errors.push("onerror: " + e.message));
  window.fetch = async (input, init) => {
    const url = typeof input === "string" && input.startsWith("http") ? input : BASE + input;
    return fetch(url, init);
  };
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener(){}, addListener(){} }));
  window.navigator.serviceWorker = { register: async () => {} };

  const login = await fetch(BASE + "/api/auth/login", { method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "username=admin&password=admin123" });
  window.localStorage.setItem("token", (await login.json()).access_token);

  window.eval(fs.readFileSync("" + require("path").join(__dirname, "..", "..", "frontend") + "/app.js", "utf8"));
  await new Promise((r) => setTimeout(r, 800));

  const views = ["dashboard", "settings", "pos", "products", "customers", "marketing", "reports", "diagnostics", "inventory", "invoices", "batches", "hardware", "users", "audit"];
  for (const v of views) {
    try {
      await window.go(v);
      await new Promise((r) => setTimeout(r, 400));
      const txt = window.document.getElementById("view").textContent || "";
      if (window.document.querySelector("#view p.error")) errors.push("view "+v+" shows error card: "+window.document.querySelector("#view p.error").textContent);
      console.log(v.padEnd(12), "rendered:", txt.trim().length > 10, "| snippet:", txt.replace(/\s+/g," ").trim().slice(0,40));
    } catch (e) { errors.push("go("+v+"): " + e.message); console.log(v, "THREW:", e.message); }
  }

  if (errors.length) { console.log("ERRORS:"); errors.forEach((e)=>console.log(" -", e)); process.exit(1); }
  console.log("ALL VIEWS RENDERED WITHOUT ERRORS");
  process.exit(0);
})();
