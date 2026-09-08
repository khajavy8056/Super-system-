/* v1.8.1 — LOCAL-FIRST data layer for the Android app.
 *
 * The phone owns a full copy of the catalogue (products, batches/prices,
 * customers) in IndexedDB and can sell, receive stock, register customers and
 * look items up with NO PC and NO network. Every write is applied locally AND
 * queued as an operation; the queue is replayed to the shop PC over LAN
 * (POST /api/mobile/sync) or, when the PC is unreachable, through the optional
 * Google-Drive mailbox (cloudSync). The PC's answer (snapshot / pull) refreshes
 * the local copy — so both sides converge without anyone doing anything.
 *
 * Loaded BEFORE app.js (shares the lexical scope). Exposes window.Local. */
(function () {
  "use strict";
  const DBN = "supermarket_local", VER = 1;
  function open() {
    return new Promise((res, rej) => {
      const r = indexedDB.open(DBN, VER);
      r.onupgradeneeded = () => {
        const d = r.result;
        if (!d.objectStoreNames.contains("products")) { const s = d.createObjectStore("products", { keyPath: "id" }); s.createIndex("barcode", "barcode", { unique: false }); }
        if (!d.objectStoreNames.contains("batches")) { const s = d.createObjectStore("batches", { keyPath: "id" }); s.createIndex("product_id", "product_id", { unique: false }); }
        if (!d.objectStoreNames.contains("customers")) { const s = d.createObjectStore("customers", { keyPath: "id" }); s.createIndex("phone", "phone", { unique: false }); }
        if (!d.objectStoreNames.contains("invoices")) d.createObjectStore("invoices", { keyPath: "local_no" });
        if (!d.objectStoreNames.contains("meta")) d.createObjectStore("meta", { keyPath: "k" });
      };
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
  }
  let _db = null;
  const db = async () => (_db || (_db = await open()));
  function tx(store, mode, fn) {
    return db().then((d) => new Promise((res, rej) => {
      const t = d.transaction(store, mode); const s = t.objectStore(store); const out = fn(s);
      t.oncomplete = () => res(out && out.result !== undefined ? out.result : out); t.onerror = () => rej(t.error);
    }));
  }
  const all = (store) => tx(store, "readonly", (s) => s.getAll());
  const get = (store, key) => tx(store, "readonly", (s) => s.get(key));
  const put = (store, obj) => tx(store, "readwrite", (s) => s.put(obj));
  const bulkPut = (store, rows) => tx(store, "readwrite", (s) => { rows.forEach((r) => s.put(r)); return rows.length; });
  const metaGet = async (k) => { const r = await get("meta", k); return r ? r.v : null; };
  const metaSet = (k, v) => put("meta", { k, v });

  /* ---------- catalogue merge (from LAN pull or cloud snapshot) ---------- */
  async function applyPull(pull, full) {
    if (!pull) return;
    if (full) {  // snapshot = whole truth; drop local copies that vanished
      await tx("products", "readwrite", (s) => s.clear()); await tx("batches", "readwrite", (s) => s.clear()); await tx("customers", "readwrite", (s) => s.clear());
    }
    if (pull.products) await bulkPut("products", pull.products.map((p) => ({ ...p, _local: false })));
    if (pull.batches) await bulkPut("batches", pull.batches.map((b) => ({ ...b, _local: false })));
    if (pull.customers) await bulkPut("customers", pull.customers.map((c) => ({ ...c, _local: false })));
    await metaSet("last_pull", new Date().toISOString());
  }

  /* ---------- local reads (same shapes the screens already use) ---------- */
  const norm = (s) => String(s || "").toLowerCase().replace(/[\u064A]/g, "\u06CC").replace(/[\u0643]/g, "\u06A9").replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d));
  async function search(q, limit = 8) {
    q = norm(q).trim(); if (!q) return [];
    const [prods, batches] = await Promise.all([all("products"), all("batches")]);
    const byProd = {}; for (const b of batches) { if ((b.status || "ACTIVE") === "ACTIVE" && b.current_qty > 0) (byProd[b.product_id] = byProd[b.product_id] || []).push(b); }
    const exact = prods.filter((p) => p.barcode === q || (p.sku && norm(p.sku) === q));
    const fuzzy = exact.length ? [] : prods.filter((p) => norm(p.name).includes(q) || (p.barcode || "").includes(q));
    return [...exact, ...fuzzy].slice(0, limit).map((p) => toSearchItem(p, byProd[p.id] || []));
  }
  function toSearchItem(p, bs) {
    const sorted = bs.slice().sort((a, b) => (a.expiry_date || "9999").localeCompare(b.expiry_date || "9999") || (a.id - b.id));
    const prices = new Set(sorted.map((b) => Number(b.unit_sell_price || b.sell_price || 0)));
    return { product_id: p.id, name: p.name, barcode: p.barcode, sku: p.sku, unit_id: p.unit_id, unit: p.unit || null,
      available_qty: sorted.reduce((a, b) => a + Number(b.current_qty || 0), 0), price_count: prices.size, _local: true,
      batches: sorted.map((b, i) => ({ batch_id: b.id, batch_number: b.batch_number, sell_price: Number(b.unit_sell_price || b.sell_price || 0), consumer_price: Number(b.consumer_price || 0),
        current_qty: Number(b.current_qty || 0), expiry_date: b.expiry_date, is_recommended: i === 0, days_left: b.expiry_date ? Math.ceil((new Date(b.expiry_date) - Date.now()) / 864e5) : null })) };
  }
  async function byBarcode(code) { const r = await search(code, 1); return r[0] && r[0].barcode === code ? r[0] : null; }
  async function stockRows() {
    const [prods, batches] = await Promise.all([all("products"), all("batches")]);
    const sum = {}; for (const b of batches) if (b.current_qty > 0) sum[b.product_id] = (sum[b.product_id] || 0) + Number(b.current_qty);
    return prods.filter((p) => p.is_active !== false).map((p) => ({ id: p.id, name: p.name, barcode: p.barcode, total_stock: sum[p.id] || 0, min_stock_alert: p.min_stock_alert || 0 })).sort((a, b) => a.name.localeCompare(b.name, "fa"));
  }
  async function products(limit = 200) { return (await all("products")).filter((p) => p.is_active !== false).sort((a, b) => b.id - a.id).slice(0, limit); }
  async function customers() { return (await all("customers")).sort((a, b) => a.name.localeCompare(b.name, "fa")); }
  async function counts() { const [p, b, c, i] = await Promise.all([all("products"), all("batches"), all("customers"), all("invoices")]); return { products: p.length, batches: b.length, customers: c.length, invoices: i.length, last_pull: await metaGet("last_pull") }; }

  /* ---------- local writes (temporary negative ids until the PC assigns real ones) ---------- */
  const nextLocalId = async (k) => { const n = ((await metaGet(k)) || 0) - 1; await metaSet(k, n); return n; };
  async function localProduct(fields) {
    const id = await nextLocalId("pid");
    const p = { id, name: fields.name, barcode: fields.barcode || ("INT-L" + String(-id).padStart(5, "0")), sku: fields.sku || null, unit_id: fields.unit_id || null, category_id: null, is_active: true, _local: true, updated_at: new Date().toISOString() };
    await put("products", p); return p;
  }
  async function localBatch(product_id, fields) {
    const id = await nextLocalId("bid");
    const b = { id, product_id, batch_number: "L-" + String(-id).padStart(5, "0"), current_qty: Number(fields.quantity_received || 0), unit_sell_price: Number(fields.sell_price || 0), consumer_price: Number(fields.consumer_price || 0),
      expiry_date: fields.expiry_date || null, status: "ACTIVE", _local: true, updated_at: new Date().toISOString() };
    await put("batches", b); return b;
  }
  async function localCustomer(fields) {
    const id = await nextLocalId("cid");
    const c = { id, name: fields.name, phone: fields.phone || null, _local: true }; await put("customers", c); return c;
  }
  /** Apply a sale locally (decrement batch qty, keep a local invoice for the day's list). */
  async function localSale(payload, total) {
    for (const it of payload.items) {
      const b = it.batch_id ? await get("batches", it.batch_id) : null;
      if (b) { b.current_qty = Math.max(0, Number(b.current_qty) - Number(it.quantity)); await put("batches", b); }
    }
    const n = ((await metaGet("inv_no")) || 0) + 1; await metaSet("inv_no", n);
    const local_no = "M-" + String(n).padStart(6, "0");
    await put("invoices", { local_no, total, items: payload.items.length, at: new Date().toISOString(), payment: (payload.payments[0] || {}).method || "CASH", synced: false });
    return local_no;
  }
  async function markInvoiceSynced(local_no, invoice_number) { const i = await get("invoices", local_no); if (i) { i.synced = true; i.invoice_number = invoice_number; await put("invoices", i); } }
  const invoices = () => all("invoices").then((r) => r.sort((a, b) => b.at.localeCompare(a.at)));
  async function todayStats() {
    const inv = await all("invoices"); const day = new Date().toISOString().slice(0, 10);
    const t = inv.filter((i) => i.at.slice(0, 10) === day);
    return { count: t.length, total: t.reduce((a, i) => a + Number(i.total || 0), 0), unsynced: inv.filter((i) => !i.synced).length };
  }

  window.Local = { applyPull, search, byBarcode, stockRows, products, customers, counts, localProduct, localBatch, localCustomer, localSale, markInvoiceSynced, invoices, todayStats, metaGet, metaSet };
})();
