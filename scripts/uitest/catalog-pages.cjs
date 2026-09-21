// Against the disposable demo instance only. No product or stock mutations.
const assert=require('assert/strict'), puppeteer=require('puppeteer-core'), chromium=require('@sparticuz/chromium');
(async()=>{
 const browser=await puppeteer.launch({executablePath:await chromium.executablePath(),args:chromium.args,headless:true});
 try {
 const page=await browser.newPage(), errors=[];
 page.on('pageerror',e=>errors.push(e.message)); await page.setRequestInterception(true);
 page.on('request',r=>{const path=new URL(r.url()).pathname;
  if(path==='/api/setup/status')return r.respond({contentType:'application/json',body:JSON.stringify({setup_done:true,first_loading_done:true,license:{allowed:true,status:'ACTIVE'},loading_seconds:0})});
  if(path==='/api/setup/license/recheck')return r.respond({contentType:'application/json',body:'{"allowed":true}'});
  r.continue();});
 await page.setViewport({width:1440,height:900}); await page.goto('http://127.0.0.1:8000');
 await page.evaluate(async()=>{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'username=admin&password=admin123'});localStorage.setItem('token',(await r.json()).access_token);localStorage.setItem('tour.seen','["*"]');sessionStorage.setItem('sm.loading.fast','3');});
 await page.reload({waitUntil:'networkidle0'}); await page.waitForFunction(()=>!document.querySelector('#app-view').classList.contains('hidden'));
 await page.waitForSelector('#view .dcard-sys');
 await page.evaluate(async()=>{if(window.Tour)Tour.end(); await go('products')});
 assert.equal(await page.$$eval('#p-table tbody tr',a=>a.length),40);
 const total=await page.evaluate(async()=>(await api('/products?limit=1')).total);
 const lastText=await page.$eval('#p-pages button:last-child',b=>{b.click();return b.textContent});
 await page.waitForFunction(t=>document.querySelector('#p-pages [aria-current="page"]')?.textContent===t,{},lastText);
 assert.equal(await page.$$eval('#p-table tbody tr',a=>a.length),total%40 || 40);
 assert.ok(total>13570,'The test must cover the real complete catalog, not a small fixture');
 await page.type('#p-list-query','%___unlikely_367_%'); await page.waitForFunction(()=>document.querySelectorAll('#p-table tbody tr').length===0);
 assert.equal(await page.$eval('#p-pages [aria-current=page]',e=>e.textContent),'۱');
 await page.evaluate(async()=>await go('inventory'));
 await page.$eval('#i-pager button:last-child',b=>b.click());
 assert.ok(await page.$$eval('#i-table tbody tr',a=>a.length)>0);
 for(const width of [1920,1440,1024,820,640]) {
   await page.setViewport({width,height:720});
   for(const view of ['inventory','products']) {
     await page.evaluate(v=>go(v),view);
     const sizes=await page.$eval(view==='inventory'?'#i-table':'#p-table',e=>({w:e.getBoundingClientRect().width,host:e.parentElement.clientWidth}));
     assert.ok(sizes.w<=sizes.host+1,`table overflow ${view} at ${width}: ${JSON.stringify(sizes)}`);
   }
 }
 assert.deepEqual(errors,[]); console.log(`PASS: last catalog page (${total} goods), empty-search reset, numbered inventory, 10 table/window fits, no JS errors.`);
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
