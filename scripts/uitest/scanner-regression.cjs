const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root, 'frontend/app.js'), 'utf8');
const wedge = source.slice(source.indexOf('const SCAN_TARGETS ='), source.indexOf('/* ---------- products ---------- */'));
function scan(code, {view='pos', startFocused=false, gap=10}={}) {
  let handler, now=1000, deliveries=[];
  const body = {tagName:'BODY', matches:()=>false, classList:{contains:()=>false}};
  const input = {tagName:'INPUT', value:'', matches:()=>true, classList:{contains:()=>true,add(){},remove(){}},
    focus(){document.activeElement=this}, closest(){return this},
    dispatchEvent(e){ handler(e); deliveries.push({code:this.value, scanned:e.scanBarcode}); this.value=''; }};
  const document = {activeElement:startFocused?input:body, querySelector:()=>input, addEventListener:(name,cb)=>{handler=cb}};
  const ctx={state:{user:{},view},document,performance:{now:()=>now},
    $:()=>({classList:{contains:()=>true}}),setTimeout:()=>1,clearTimeout(){},
    api:()=>Promise.resolve({}),can:()=>true,go:()=>Promise.resolve(),
    KeyboardEvent:class {constructor(type,opts){Object.assign(this,opts)}},console};
  vm.runInNewContext(wedge,ctx);
  for (const key of code) {
    const wasInput=document.activeElement===input;
    const e={key,preventDefault(){this.prevented=true},stopPropagation(){this.stopped=true}};
    handler(e);
    // Actual POS focuses the field on bubble, AFTER capture/default target
    // selection: the first digit can be lost from the field, but not the wedge.
    document.activeElement=input;
    if(wasInput&&!e.prevented) input.value+=key;
    now+=gap;
  }
  const enter={key:'Enter',preventDefault(){this.prevented=true},stopPropagation(){this.stopped=true}};
  handler(enter);
  return {deliveries,enter};
}
for (const code of ['001234567890','6261234567890','Hy-40312350','12345678901234567890']) {
  for (const view of ['pos','batches']) for (const startFocused of [false,true]) {
    const result=scan(code,{view,startFocused});
    assert.deepEqual(result.deliveries,[{code,scanned:true}]);
    assert.equal(result.enter.prevented,true); assert.equal(result.enter.stopped,true);
  }
}
assert.equal(scan('123456789',{gap:120,startFocused:true}).deliveries.length,0,'slow typing must remain typing');
assert(source.includes('scanned ? posAddByBarcode(term) : posAddByTerm(term)'), 'hardware scans bypass fuzzy search');
const mobile=fs.readFileSync(path.join(root,'frontend/mobile/app.js'),'utf8');
const fn=mobile.slice(mobile.indexOf('async function exactScanProduct('),mobile.indexOf('function onScanHit(raw)'));
(async()=>{
  const context={window:{Local:{byBarcode:async()=>null}},state:{online:true},encodeURIComponent,
    api:async()=>({items:[{barcode:'0012345',product_id:1}]})};
  context.Local=context.window.Local;
  vm.createContext(context); vm.runInContext(fn,context);
  assert.equal(await context.exactScanProduct('12345'),null,'partial match must not enter cart');
  context.api=async()=>({items:[{barcode:'0012345',product_id:2}]});
  assert.equal((await context.exactScanProduct('0012345')).product_id,2);
  context.state.online=false; context.window.Local.byBarcode=async bc=>({barcode:bc,product_id:3});
  assert.equal((await context.exactScanProduct('Hy-40312350')).barcode,'Hy-40312350');
  console.log('PASS: full burst capture, leading zeros, focus changes, single delivery, slow typing, exact mobile scans');
})().catch(e=>{console.error(e);process.exitCode=1});
