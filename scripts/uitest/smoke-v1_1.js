const { JSDOM } = require("jsdom"); const fs = require("fs"); const BASE="http://127.0.0.1:8000";
(async () => {
  const html = fs.readFileSync("" + require("path").join(__dirname, "..", "..", "frontend") + "/index.html","utf8");
  const dom = new JSDOM(html,{url:BASE+"/",runScripts:"outside-only",pretendToBeVisual:true});
  const {window}=dom; const errors=[];
  window.addEventListener("error",e=>errors.push("onerror: "+e.message));
  window.fetch=async(i,init)=>{const u=typeof i==="string"&&i.startsWith("http")?i:BASE+i;return fetch(u,init);};
  window.matchMedia=window.matchMedia||(()=>({matches:false,addEventListener(){},addListener(){}}));
  window.navigator.serviceWorker={register:async()=>{}};
  window.HTMLElement.prototype.requestFullscreen=async()=>{};
  const login=await fetch(BASE+"/api/auth/login",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:"username=admin&password=admin123"});
  window.localStorage.setItem("token",(await login.json()).access_token);
  window.eval(fs.readFileSync("" + require("path").join(__dirname, "..", "..", "frontend") + "/app.js","utf8"));
  await new Promise(r=>setTimeout(r,1500));
  // inventory -> warehouses card
  await window.go("inventory"); await new Promise(r=>setTimeout(r,1500));
  const wh=window.document.getElementById("wh-body");
  console.log("warehouse card:", wh && wh.textContent.includes("انبار اصلی"), "| transfer btn:", !!window.document.getElementById("wh-transfer"));
  // settings -> tabs count + sms panel
  await window.go("settings"); await new Promise(r=>setTimeout(r,1200));
  const tabs=[...window.document.querySelectorAll(".set-tab")].map(b=>b.textContent);
  console.log("settings tabs:", tabs.length, tabs.join(" | "));
  const smsTab=[...window.document.querySelectorAll(".set-tab")].find(b=>b.textContent==="پیامک"); smsTab.click();
  await new Promise(r=>setTimeout(r,1200));
  console.log("sms tools:", !!window.document.getElementById("sms-test"), !!window.document.getElementById("sms-report"), "| log rows:", window.document.querySelectorAll("#sms-log tbody tr").length);
  const secTab=[...window.document.querySelectorAll(".set-tab")].find(b=>b.textContent==="امنیت"); secTab.click(); await new Promise(r=>setTimeout(r,500));
  console.log("security rows:", window.document.querySelectorAll("#set-body .kv-row").length);
  // POS: invoice discount option exists
  await window.go("pos"); await new Promise(r=>setTimeout(r,1200));
  window.posDiscountModal ? window.posDiscountModal() : window.eval("posDiscountModal()"); await new Promise(r=>setTimeout(r,300));
  console.log("discount modal (empty cart -> toast):", window.document.body.textContent.includes("سبد خالی"));
  await window.go("invoices"); await new Promise(r=>setTimeout(r,1200));
  const voidBtn=[...window.document.querySelectorAll("button")].find(b=>b.textContent==="ابطال");
  if(voidBtn){voidBtn.click(); await new Promise(r=>setTimeout(r,300)); console.log("void modal asks password:", !!window.document.getElementById("void-pass") || window.document.body.textContent.includes("ابطال فاکتور"));}
  if(errors.length){console.log("ERRORS:");errors.forEach(e=>console.log(" -",e));process.exit(1);}
  console.log("UI v1.1 SMOKE OK"); process.exit(0);
})().catch(e=>{console.log("FATAL",e);process.exit(1);});
