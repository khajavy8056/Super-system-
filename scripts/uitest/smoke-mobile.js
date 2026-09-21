const { JSDOM } = require("jsdom");
const fs = require("fs");
const BASE = "http://127.0.0.1:8000";
(async () => {
  const html = fs.readFileSync("" + require("path").join(__dirname, "..", "..", "frontend") + "/mobile/index.html", "utf8");
  const dom = new JSDOM(html, { url: BASE + "/m/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  const errors = [];
  window.addEventListener("error", (e) => errors.push("onerror: " + e.message));
  window.fetch = async (input, init) => { const u = typeof input==="string"&&input.startsWith("http")?input:BASE+input; return fetch(u, init); };
  window.matchMedia = window.matchMedia || (() => ({ matches:false, addEventListener(){}, addListener(){} }));
  window.navigator.serviceWorker = { register: async()=>{} };
  const login = await fetch(BASE+"/api/auth/login",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:"username=admin&password=admin123"});
  window.localStorage.setItem("token",(await login.json()).access_token);
  try { window.eval(fs.readFileSync("" + require("path").join(__dirname, "..", "..", "frontend") + "/mobile/app.js","utf8")); }
  catch(e){ errors.push("eval: "+e.message); }
  await new Promise(r=>setTimeout(r,1500));
  const app=window.document.getElementById("app");
  console.log("mobile app populated:", app && app.innerHTML.trim().length>20);
  console.log("snippet:", (app?app.textContent:"").replace(/\s+/g," ").trim().slice(0,60));
  if(errors.length){ console.log("ERRORS:"); errors.forEach(e=>console.log(" -",e)); process.exit(1);}
  console.log("MOBILE NO RUNTIME ERRORS"); process.exit(0);
})();
