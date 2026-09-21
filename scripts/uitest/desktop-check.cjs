// Run ONLY against a disposable demo database. Creates a test stocktake session.
// UI_TEST_ALLOW_WRITES=1 LD_LIBRARY_PATH=... node scripts/uitest/desktop-check.cjs
if(process.env.UI_TEST_ALLOW_WRITES !== '1') throw new Error('Use an isolated demo DB and set UI_TEST_ALLOW_WRITES=1');
const puppeteer=require('puppeteer-core'),chromium=require('@sparticuz/chromium'),fs=require('fs');
(async()=>{
const browser=await puppeteer.launch({executablePath:await chromium.executablePath(),args:chromium.args,headless:true});
let mode='live', analysisPosts=0;
const page=await browser.newPage();const errors=[]; page.on('pageerror',e=>errors.push(e.message));
await page.setRequestInterception(true);
page.on('request',r=>{
 const url=new URL(r.url());
 if(url.pathname==='/api/insights/run') analysisPosts++;
 if(mode==='empty' && url.pathname==='/api/insights/summary') return r.respond({contentType:'application/json',body:JSON.stringify({open:0,accepted:0,measured:0,total_gain:0,month_gain:0,expected_open:0})});
 if(mode==='empty' && url.pathname==='/api/insights') return r.respond({contentType:'application/json',body:'[]'});
 if(mode==='error' && url.pathname==='/api/insights/summary') return r.respond({status:503,contentType:'application/json',body:'{"detail":"Temporary failure"}'});
 if(r.url().endsWith('/api/setup/license/recheck')) return r.respond({contentType:'application/json',body:'{"allowed":true}'}); if(r.url().endsWith('/api/setup/status')) return r.respond({contentType:'application/json',body:JSON.stringify({setup_done:true,first_loading_done:true,license:{allowed:true,status:'ACTIVE'},loading_seconds:0})}); return r.continue(); });
await page.setViewport({width:1366,height:900});
await page.goto('http://127.0.0.1:8000');
await page.evaluate(async()=>{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'username=admin&password=admin123'});localStorage.setItem('token',(await r.json()).access_token);localStorage.setItem('tour.seen','["*"]');sessionStorage.setItem('sm.loading.fast','3')});
await page.reload({waitUntil:'networkidle0'});
await page.waitForFunction(()=>!document.querySelector('#app-view').classList.contains('hidden') && (!document.querySelector('#ob-overlay') || document.querySelector('#ob-overlay').classList.contains('hidden')), {timeout:30000});
await page.evaluate(()=>{if(window.Tour)Tour.end()});
const results=[];
for(const width of [1440,1024,820,390]) {
 await page.setViewport({width,height:900});
 { await page.reload({waitUntil:'networkidle0'}); await page.waitForFunction(()=>!document.querySelector('#app-view').classList.contains('hidden')); await page.evaluate(()=>{if(window.Tour)Tour.end()}); }
 for(const view of ['dashboard','insights','inventory','products','batches','pos','customers','invoices','marketing','accounting','reports','settings','hardware','users','audit','diagnostics','support','insightsPlan','insightsCustomers']) {
  await page.evaluate(v=>go(v),view);
  const info=await page.$eval('#view',e=>({error:e.querySelector('p.error')?.textContent,overflow:e.scrollWidth-e.clientWidth,chars:e.textContent.length}));
  results.push({width,view,...info}); if(info.error||info.overflow>3)console.log('ISSUE',width,view,info);
  if(['insights','inventory'].includes(view) && [1440,390].includes(width)) await page.screenshot({path:`/home/user/${view}-${width}.png`});
 }
}
// Empty shops must render without starting a write/analyzer loop.
mode='empty'; await page.evaluate(()=>go('insights'));
await new Promise(r=>setTimeout(r,400));
if(analysisPosts!==0 || !(await page.$('#ins-hero .ins-kpis'))) throw new Error('Empty insight page loops or fails');
mode='error'; await page.evaluate(()=>go('insights'));
if(!(await page.$('#ins-retry'))) throw new Error('No accessible retry state');
mode='live'; await page.click('#ins-retry'); await page.waitForSelector('#ins-list .ins-card');
if((await page.$$('#ins-list .ins-body')).length!==12) throw new Error('Paged card callback hides evidence/body');
const session=await page.evaluate(async()=>{
 const stock=await api('/inventory/stock');const product=stock.find(p=>p.total_stock>0);
 return api('/inventory/stocktakes',{method:'POST',body:JSON.stringify({name:'UI regression test',product_ids:[product.product_id],include_zero:false})});
});
for(const width of [1440,1024,390]) {
 await page.setViewport({width,height:900});
 await page.reload({waitUntil:'networkidle0'}); await page.waitForFunction(()=>!document.querySelector('#app-view').classList.contains('hidden')); await page.evaluate(()=>{if(window.Tour)Tour.end()});
 await page.evaluate(id=>window._stWizard(id),session.id);
 const overflow=await page.$eval('#view',e=>e.scrollWidth-e.clientWidth);
 if(overflow>3 || !(await page.$('#st-save'))) throw new Error('Stocktake wizard layout failure '+width);
 await page.screenshot({path:`/home/user/stocktake-${width}.png`});
 results.push({width,view:'stocktake-wizard',overflow});
 const reachable=await page.$eval('#st-save',e=>{e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))});
 if(!reachable) throw new Error('Save button is clipped/unreachable at '+width);
}
await page.setViewport({width:1366,height:900}); await page.reload({waitUntil:'networkidle0'});
await page.waitForFunction(()=>!document.querySelector('#app-view').classList.contains('hidden'));
await page.evaluate(async()=>{if(window.Tour)Tour.end();await applyTheme('dark')});
for(const view of ['insights','inventory','accounting']) {
 await page.evaluate(v=>go(v),view);
 const info=await page.$eval('#view',e=>({error:e.querySelector('p.error')?.textContent,overflow:e.scrollWidth-e.clientWidth}));
 results.push({width:1366,theme:'dark',view,...info});
}
await page.screenshot({path:'/home/user/desktop-dark.png'});
await page.evaluate(()=>applyTheme('light'));
fs.writeFileSync('/home/user/desktop-layout-results.json',JSON.stringify({results,errors},null,2));
console.log('Measured',results.length,'pages; empty/failure/retry/paged cards verified. Page errors:',errors);
if(errors.length||results.some(r=>r.error||r.overflow>3))process.exitCode=1;
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
