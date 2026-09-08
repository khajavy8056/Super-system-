const { JSDOM } = require("jsdom"); const fs=require("fs"); const FE="/home/user/Super-system-/frontend"; const BASE="http://127.0.0.1:8000";
(async()=>{ const dom=new JSDOM(fs.readFileSync(FE+"/index.html","utf8"),{url:BASE+"/",runScripts:"outside-only",pretendToBeVisual:true}); const {window}=dom;
window.addEventListener("error",e=>console.log("ERR",e.message)); window.fetch=async(i,init)=>fetch(typeof i==="string"&&i.startsWith("http")?i:BASE+i,init);
window.matchMedia=()=>({matches:false,addEventListener(){},addListener(){}}); window.navigator.serviceWorker={register:async()=>{}}; window.requestAnimationFrame=(f)=>setTimeout(f,16);
window.__NO_AUTOBOOT=true;
window.eval(fs.readFileSync(FE+"/jalali.js","utf8")+"\n;"+fs.readFileSync(FE+"/onboarding.js","utf8")+"\n;"+fs.readFileSync(FE+"/app.js","utf8"));
window.Onboarding.gate(); await new Promise(r=>setTimeout(r,800));
const $=s=>window.document.querySelector(s);
console.log("welcome:", ($("#ob-pane-body")||{}).textContent?.slice(0,40));
try{ $("#ob-next").click(); }catch(e){console.log("click err",e.message)}
await new Promise(r=>setTimeout(r,300));
console.log("license:", JSON.stringify(($("#ob-pane-body")||{}).innerHTML?.slice(0,120)));
})();
