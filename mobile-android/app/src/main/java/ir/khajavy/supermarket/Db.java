package ir.khajavy.supermarket;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * v2.0 — the phone's OWN database (SQLite). Fully independent of the PC:
 *  - catalogue: products / batches / customers (mirror of the PC, or created here)
 *  - invoices made on the phone (offline numbers M-000001…)
 *  - ops: outgoing operation queue replayed by {@link Sync}
 *  - cache: last JSON of every GET so EVERY section opens offline
 *  - kv: cursor, counters, settings snapshot
 */
public final class Db extends SQLiteOpenHelper {
    private static Db I;
    public static synchronized void init(Context c) { if (I == null) I = new Db(c.getApplicationContext()); }
    private static SQLiteDatabase w() { return I.getWritableDatabase(); }
    /** v2.4: the local API router ({@link Local}) works directly on the database. */
    public static SQLiteDatabase db() { return w(); }

    private Db(Context c) { super(c, "supermarket_native.db", null, 2); }

    /** v2.4 — full standalone schema: every Windows section has a table on the phone. */
    static final String[] V2 = {
        "CREATE TABLE IF NOT EXISTS invoice_items(id INTEGER PRIMARY KEY AUTOINCREMENT, inv INTEGER, product_id INTEGER, batch_id INTEGER, qty REAL, unit_sell_price REAL, unit_buy_price REAL, discount REAL DEFAULT 0, subtotal REAL, returned_qty REAL DEFAULT 0)",
        "CREATE INDEX IF NOT EXISTS ix_ii_inv ON invoice_items(inv)",
        "CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, batch_id INTEGER, movement_type TEXT, quantity REAL, reference_type TEXT, reference_id TEXT, reason TEXT, user TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, entry_type TEXT, amount REAL, note TEXT, ref TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)",
        "CREATE TABLE IF NOT EXISTS brands(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)",
        "CREATE TABLE IF NOT EXISTS units(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, symbol TEXT, allow_decimal INTEGER DEFAULT 0, decimals INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, discount_type TEXT, discount_value REAL, min_purchase REAL DEFAULT 0, max_discount REAL, valid_until TEXT, status TEXT DEFAULT 'ACTIVE', auto_issue_threshold REAL, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS coupons(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, discount_type TEXT, discount_value REAL, min_purchase REAL DEFAULT 0, customer_phone TEXT, valid_until TEXT, usage_limit INTEGER DEFAULT 1, used_count INTEGER DEFAULT 0, status TEXT DEFAULT 'ACTIVE', created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS price_history(id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, price_type TEXT, price REAL, effective_from TEXT, is_active INTEGER DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS stocktakes(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, area TEXT, status TEXT DEFAULT 'DRAFT', scheduled_for TEXT, created_at TEXT, started_at TEXT, completed_at TEXT, approved_at TEXT)",
        "CREATE TABLE IF NOT EXISTS stocktake_items(id INTEGER PRIMARY KEY AUTOINCREMENT, st INTEGER, product_id INTEGER, batch_id INTEGER, system_qty REAL, physical_qty REAL, reason TEXT, counted_at TEXT)",
        "CREATE TABLE IF NOT EXISTS warehouses(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, code TEXT, address TEXT, is_default INTEGER DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS locations(id INTEGER PRIMARY KEY AUTOINCREMENT, warehouse_id INTEGER, name TEXT)",
        "CREATE TABLE IF NOT EXISTS expense_categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)",
        "CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, amount REAL, description TEXT, paid_from TEXT, expense_date TEXT)",
        "CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, address TEXT, balance REAL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS cheques(id INTEGER PRIMARY KEY AUTOINCREMENT, direction TEXT, number TEXT, amount REAL, due_date TEXT, bank_name TEXT, party_name TEXT, status TEXT DEFAULT 'PENDING', created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY AUTOINCREMENT, number INTEGER, date TEXT, description TEXT, kind TEXT, status TEXT DEFAULT 'POSTED', total REAL, lines TEXT, ref TEXT)",
        "CREATE TABLE IF NOT EXISTS cash_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, opened_at TEXT, closed_at TEXT, opening_float REAL DEFAULT 0, counted_cash REAL, expected_cash REAL, difference REAL, status TEXT DEFAULT 'OPEN', note TEXT)",
        "CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, full_name TEXT, pass_hash TEXT, roles TEXT, is_active INTEGER DEFAULT 1, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, entity_type TEXT, entity_id TEXT, reference TEXT, user TEXT, before TEXT, after TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)",
    };
    static final String[] V2_ALTER = {
        "ALTER TABLE invoices ADD COLUMN status TEXT DEFAULT 'PAID'", "ALTER TABLE invoices ADD COLUMN payment_status TEXT DEFAULT 'PAID'",
        "ALTER TABLE invoices ADD COLUMN customer_id INTEGER", "ALTER TABLE invoices ADD COLUMN subtotal REAL DEFAULT 0", "ALTER TABLE invoices ADD COLUMN discount REAL DEFAULT 0",
        "ALTER TABLE invoices ADD COLUMN tax REAL DEFAULT 0", "ALTER TABLE invoices ADD COLUMN user TEXT", "ALTER TABLE invoices ADD COLUMN void_reason TEXT", "ALTER TABLE invoices ADD COLUMN coupon TEXT",
        "ALTER TABLE customers ADD COLUMN address TEXT", "ALTER TABLE batches ADD COLUMN warehouse_id INTEGER DEFAULT 1", "ALTER TABLE batches ADD COLUMN quantity_received REAL", "ALTER TABLE batches ADD COLUMN received_at TEXT",
    };
    static void v2(SQLiteDatabase d) {
        for (String q : V2) d.execSQL(q);
        for (String q : V2_ALTER) { try { d.execSQL(q); } catch (Exception ignore) {} }
        try (Cursor c = d.rawQuery("SELECT COUNT(*) FROM warehouses", null)) { if (c.moveToFirst() && c.getInt(0) == 0) d.execSQL("INSERT INTO warehouses(name,code,address,is_default) VALUES('انبار اصلی','MAIN','',1)"); }
        try (Cursor c = d.rawQuery("SELECT COUNT(*) FROM expense_categories", null)) { if (c.moveToFirst() && c.getInt(0) == 0) for (String n : new String[]{"اجاره", "حقوق", "آب و برق و گاز", "حمل و نقل", "تعمیرات", "متفرقه"}) d.execSQL("INSERT INTO expense_categories(name) VALUES(?)", new Object[]{n}); }
        try (Cursor c = d.rawQuery("SELECT COUNT(*) FROM units", null)) { if (c.moveToFirst() && c.getInt(0) == 0) { Object[][] us = {{"عدد", "عدد", 0, 0}, {"کیلوگرم", "kg", 1, 3}, {"گرم", "g", 1, 0}, {"لیتر", "L", 1, 2}, {"بسته", "بسته", 0, 0}, {"کارتن", "کارتن", 0, 0}, {"متر", "m", 1, 2}}; for (Object[] u : us) d.execSQL("INSERT INTO units(name,symbol,allow_decimal,decimals,is_active) VALUES(?,?,?,?,1)", u); } }
    }

    @Override public void onCreate(SQLiteDatabase d) {
        d.execSQL("CREATE TABLE products(id INTEGER PRIMARY KEY, barcode TEXT, name TEXT, sku TEXT, unit_id INTEGER, category_id INTEGER, brand_id INTEGER, min_stock_alert REAL DEFAULT 0, image_url TEXT, is_active INTEGER DEFAULT 1, is_local INTEGER DEFAULT 0, json TEXT, updated_at TEXT)");
        d.execSQL("CREATE INDEX ix_p_bc ON products(barcode)");
        d.execSQL("CREATE TABLE batches(id INTEGER PRIMARY KEY, product_id INTEGER, batch_number TEXT, current_qty REAL, sell_price REAL, consumer_price REAL, buy_price REAL, expiry_date TEXT, status TEXT, is_local INTEGER DEFAULT 0, json TEXT, updated_at TEXT)");
        d.execSQL("CREATE INDEX ix_b_p ON batches(product_id)");
        d.execSQL("CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, last_name TEXT, phone TEXT, credit_limit REAL, is_local INTEGER DEFAULT 0, json TEXT)");
        d.execSQL("CREATE TABLE invoices(local_no TEXT PRIMARY KEY, total REAL, item_count INTEGER, payment TEXT, at TEXT, synced INTEGER DEFAULT 0, invoice_number TEXT, json TEXT)");
        d.execSQL("CREATE TABLE ops(id TEXT PRIMARY KEY, type TEXT, payload TEXT, label TEXT, local_no TEXT, created_at TEXT, last_error TEXT)");
        d.execSQL("CREATE TABLE cache(path TEXT PRIMARY KEY, json TEXT, at TEXT)");
        d.execSQL("CREATE TABLE kv(k TEXT PRIMARY KEY, v TEXT)");
        d.execSQL("CREATE TABLE conflicts(id INTEGER PRIMARY KEY AUTOINCREMENT, op_id TEXT, label TEXT, message TEXT, at TEXT)");
        v2(d);
    }
    @Override public void onUpgrade(SQLiteDatabase d, int a, int b) { if (a < 2) v2(d); }

    /* ---------------- kv ---------------- */
    public static String kv(String k) { try (Cursor c = w().rawQuery("SELECT v FROM kv WHERE k=?", new String[]{k})) { return c.moveToFirst() ? c.getString(0) : null; } }
    public static void kv(String k, String v) { ContentValues cv = new ContentValues(); cv.put("k", k); cv.put("v", v); w().insertWithOnConflict("kv", null, cv, SQLiteDatabase.CONFLICT_REPLACE); }
    private static long counter(String k) { long n = 0; String v = kv(k); if (v != null) n = Long.parseLong(v); n++; kv(k, String.valueOf(n)); return n; }

    /* ---------------- cache ---------------- */
    public static void cachePut(String path, String json) { ContentValues cv = new ContentValues(); cv.put("path", path); cv.put("json", json); cv.put("at", now()); w().insertWithOnConflict("cache", null, cv, SQLiteDatabase.CONFLICT_REPLACE); }
    public static String cacheGet(String path) { try (Cursor c = w().rawQuery("SELECT json FROM cache WHERE path=?", new String[]{path})) { return c.moveToFirst() ? c.getString(0) : null; } }

    /* ---------------- catalogue merge from PC ---------------- */
    public static void applyPull(JSONObject pull, boolean full) {
        SQLiteDatabase d = w(); d.beginTransaction();
        try {
            if (full) { d.delete("products", "is_local=0", null); d.delete("batches", "is_local=0", null); d.delete("customers", "is_local=0", null); }
            JSONArray ps = pull.optJSONArray("products"); if (ps != null) for (int i = 0; i < ps.length(); i++) putProduct(ps.optJSONObject(i), false);
            JSONArray bs = pull.optJSONArray("batches"); if (bs != null) for (int i = 0; i < bs.length(); i++) putBatch(bs.optJSONObject(i), false);
            JSONArray cs = pull.optJSONArray("customers"); if (cs != null) for (int i = 0; i < cs.length(); i++) putCustomer(cs.optJSONObject(i), false);
            if (full) {
                // temp rows created offline are superseded once the PC has the real ones
                d.execSQL("DELETE FROM products WHERE is_local=1 AND barcode IN (SELECT barcode FROM products WHERE is_local=0)");
                d.execSQL("DELETE FROM customers WHERE is_local=1 AND phone IS NOT NULL AND phone<>'' AND phone IN (SELECT phone FROM customers WHERE is_local=0)");
                if (count("ops") == 0) { d.execSQL("DELETE FROM batches WHERE is_local=1"); d.execSQL("DELETE FROM products WHERE is_local=1 AND barcode LIKE 'INT-L%'"); }
            }
            kv("last_pull", now()); d.setTransactionSuccessful();
        } finally { d.endTransaction(); }
    }
    public static void putProduct(JSONObject p, boolean local) {
        if (p == null) return; ContentValues cv = new ContentValues();
        cv.put("id", p.optLong("id")); cv.put("barcode", p.optString("barcode", "")); cv.put("name", p.optString("name", "")); cv.put("sku", p.isNull("sku") ? null : p.optString("sku"));
        cv.put("unit_id", p.isNull("unit_id") ? null : p.optLong("unit_id")); cv.put("category_id", p.isNull("category_id") ? null : p.optLong("category_id")); cv.put("brand_id", p.isNull("brand_id") ? null : p.optLong("brand_id"));
        cv.put("min_stock_alert", p.optDouble("min_stock_alert", 0)); cv.put("image_url", p.isNull("image_url") ? null : p.optString("image_url")); cv.put("is_active", p.optBoolean("is_active", true) ? 1 : 0);
        cv.put("is_local", local ? 1 : 0); cv.put("json", p.toString()); cv.put("updated_at", now());
        w().insertWithOnConflict("products", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
    }
    public static void putBatch(JSONObject b, boolean local) {
        if (b == null) return; ContentValues cv = new ContentValues();
        cv.put("id", b.optLong("id")); cv.put("product_id", b.optLong("product_id")); cv.put("batch_number", b.optString("batch_number", ""));
        cv.put("current_qty", b.optDouble("current_qty", 0)); cv.put("sell_price", b.optDouble("sell_price", b.optDouble("unit_sell_price", 0))); cv.put("consumer_price", b.optDouble("consumer_price", 0)); cv.put("buy_price", b.optDouble("buy_price", 0));
        cv.put("expiry_date", b.isNull("expiry_date") ? null : b.optString("expiry_date")); cv.put("status", b.optString("status", "ACTIVE")); cv.put("is_local", local ? 1 : 0); cv.put("json", b.toString()); cv.put("updated_at", now());
        w().insertWithOnConflict("batches", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
    }
    public static void putCustomer(JSONObject c, boolean local) {
        if (c == null) return; ContentValues cv = new ContentValues();
        cv.put("id", c.optLong("id")); cv.put("name", c.optString("name", "")); cv.put("last_name", c.isNull("last_name") ? null : c.optString("last_name")); cv.put("phone", c.isNull("phone") ? null : c.optString("phone"));
        cv.put("credit_limit", c.optDouble("credit_limit", 0)); cv.put("is_local", local ? 1 : 0); cv.put("json", c.toString());
        w().insertWithOnConflict("customers", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
    }

    /** v2.1 standalone: bundled starter catalogue (same CSV as the Windows wizard) → local products. */
    public static int importStarter(Context ctx) {
        int n = 0; SQLiteDatabase d = w(); d.beginTransaction();
        try (java.io.BufferedReader br = new java.io.BufferedReader(new java.io.InputStreamReader(ctx.getAssets().open("starter_catalog.csv"), "UTF-8"))) {
            String line = br.readLine(); // header: category,subcategory,name,brand,unit,min_stock_alert,barcode
            java.util.Map<String, Long> units = new java.util.HashMap<>(); java.util.Map<String, Long> cats = new java.util.HashMap<>();
            while ((line = br.readLine()) != null) {
                String[] f = line.split(",", -1); if (f.length < 5 || f[2].trim().isEmpty()) continue;
                String unit = f[4].trim().isEmpty() ? "عدد" : f[4].trim(); if (!units.containsKey(unit)) units.put(unit, (long) units.size() + 1);
                String cat = f[0].trim() + (f[1].trim().isEmpty() ? "" : " / " + f[1].trim()); if (!cats.containsKey(cat)) cats.put(cat, (long) cats.size() + 1);
                long id = -counter("pid"); JSONObject p = new JSONObject();
                try { p.put("id", id); p.put("name", f[2].trim()); p.put("barcode", f.length > 6 && !f[6].trim().isEmpty() ? f[6].trim() : "INT-L" + pad5(-id)); p.put("unit_id", units.get(unit)); p.put("unit_name", unit); p.put("category_id", cats.get(cat)); p.put("category_name", cat); if (!f[3].trim().isEmpty()) p.put("brand_name", f[3].trim()); p.put("min_stock_alert", f.length > 5 && !f[5].trim().isEmpty() ? Double.parseDouble(f[5].trim()) : 0); p.put("is_active", true); p.put("_local", true); p.put("has_own_barcode", f.length > 6 && !f[6].trim().isEmpty()); } catch (Exception ignore) {}
                putProduct(p, true); n++; try { kv("imgq_" + id, "0"); } catch (Exception ignore) {}   // v2.5: picture looked up in the background
            }
            try { JSONArray ua = new JSONArray(); for (java.util.Map.Entry<String, Long> e : units.entrySet()) { JSONObject u = new JSONObject(); u.put("id", e.getValue()); u.put("name", e.getKey()); u.put("allow_decimal", e.getKey().contains("کیلو") || e.getKey().contains("گرم") || e.getKey().contains("لیتر") || e.getKey().contains("متر")); ua.put(u); } kv("local_units", ua.toString()); } catch (Exception ignore) {}
            kv("starter_imported", "1"); d.setTransactionSuccessful();
        } catch (Exception ignore) {
        } finally { d.endTransaction(); }
        return n;
    }

    /* ---------------- local reads ---------------- */
    public static List<JSONObject> searchProducts(String q, int limit) {
        List<JSONObject> out = new ArrayList<>(); q = norm(q);
        String sql = q.isEmpty() ? "SELECT json FROM products WHERE is_active=1 ORDER BY id DESC LIMIT ?" : "SELECT json FROM products WHERE is_active=1 AND (barcode=? OR sku=? OR name LIKE ? OR barcode LIKE ?) ORDER BY (barcode=?) DESC, name LIMIT ?";
        String[] args = q.isEmpty() ? new String[]{String.valueOf(limit)} : new String[]{q, q, "%" + q + "%", "%" + q + "%", q, String.valueOf(limit)};
        try (Cursor c = w().rawQuery(sql, args)) { while (c.moveToNext()) out.add(withBatches(c.getString(0))); }
        return out;
    }
    public static JSONObject productByBarcode(String bc) {
        try (Cursor c = w().rawQuery("SELECT json FROM products WHERE barcode=? LIMIT 1", new String[]{norm(bc)})) { return c.moveToFirst() ? withBatches(c.getString(0)) : null; }
    }
    public static JSONObject productById(long id) {
        try (Cursor c = w().rawQuery("SELECT json FROM products WHERE id=?", new String[]{String.valueOf(id)})) { return c.moveToFirst() ? withBatches(c.getString(0)) : null; }
    }
    /** product json + "batches": [active batches with stock, FEFO order] + available_qty. */
    private static JSONObject withBatches(String json) {
        try {
            JSONObject p = new JSONObject(json); JSONArray bs = new JSONArray(); double total = 0;
            try (Cursor c = w().rawQuery("SELECT json, current_qty FROM batches WHERE product_id=? AND status='ACTIVE' AND current_qty>0 ORDER BY (expiry_date IS NULL), expiry_date, id", new String[]{String.valueOf(p.optLong("id"))})) {
                while (c.moveToNext()) { JSONObject b = new JSONObject(c.getString(0)); b.put("batch_id", b.optLong("id")); if (!b.has("sell_price")) b.put("sell_price", b.optDouble("unit_sell_price", 0)); b.put("is_recommended", bs.length() == 0); bs.put(b); total += c.getDouble(1); }
            }
            p.put("batches", bs); p.put("available_qty", total); p.put("product_id", p.optLong("id")); return p;
        } catch (Exception e) { return new JSONObject(); }
    }
    public static List<JSONObject> stockRows() {
        List<JSONObject> out = new ArrayList<>();
        try (Cursor c = w().rawQuery("SELECT p.id, p.name, p.barcode, p.min_stock_alert, IFNULL((SELECT SUM(current_qty) FROM batches b WHERE b.product_id=p.id AND b.status='ACTIVE'),0) FROM products p WHERE p.is_active=1 ORDER BY p.name", null)) {
            while (c.moveToNext()) { JSONObject o = new JSONObject(); try { o.put("product_id", c.getLong(0)); o.put("name", c.getString(1)); o.put("barcode", c.getString(2)); o.put("min_stock_alert", c.getDouble(3)); o.put("total_stock", c.getDouble(4)); } catch (Exception ignore) {} out.add(o); }
        }
        return out;
    }
    public static JSONObject customerByPhone(String phone) { try (Cursor c = w().rawQuery("SELECT json FROM customers WHERE phone=? LIMIT 1", new String[]{norm(phone)})) { if (c.moveToFirst()) return new JSONObject(c.getString(0)); } catch (Exception ignore) {} return null; }
    public static List<JSONObject> customers(String q) {
        List<JSONObject> out = new ArrayList<>(); q = norm(q);
        try (Cursor c = w().rawQuery("SELECT json FROM customers WHERE name LIKE ? OR phone LIKE ? ORDER BY name LIMIT 200", new String[]{"%" + q + "%", "%" + q + "%"})) { while (c.moveToNext()) { try { out.add(new JSONObject(c.getString(0))); } catch (Exception ignore) {} } }
        return out;
    }
    public static int count(String table) { try (Cursor c = w().rawQuery("SELECT COUNT(*) FROM " + table, null)) { return c.moveToFirst() ? c.getInt(0) : 0; } }

    /* ---------------- local writes (negative temp ids) ---------------- */
    public static JSONObject localProduct(String barcode, String name, Long unitId) {
        long id = -counter("pid");
        JSONObject p = Api.obj("name", name, "barcode", (barcode == null || barcode.isEmpty()) ? "INT-L" + pad5(-id) : barcode, "sku", null);
        try { p.put("id", id); if (unitId != null) p.put("unit_id", unitId); p.put("is_active", true); p.put("_local", true); } catch (Exception ignore) {}
        putProduct(p, true); return p;
    }
    public static JSONObject localBatch(long productId, double qty, double sell, double consumer, double buy, String expiry) {
        long id = -counter("bid");
        JSONObject b = new JSONObject();
        try { b.put("id", id); b.put("product_id", productId); b.put("batch_number", "L-" + pad5(-id)); b.put("current_qty", qty); b.put("sell_price", sell); b.put("consumer_price", consumer); b.put("buy_price", buy); if (expiry != null) b.put("expiry_date", expiry); b.put("status", "ACTIVE"); } catch (Exception ignore) {}
        putBatch(b, true); Local.onBatchReceived(productId, id, qty, buy, sell, consumer); return b;
    }
    public static JSONObject localCustomer(String name, String phone) {
        long id = -counter("cid"); JSONObject c = Api.obj("name", name, "phone", phone);
        try { c.put("id", id); c.put("_local", true); } catch (Exception ignore) {}
        putCustomer(c, true); return c;
    }
    /** Apply a sale locally: decrement batches, store the invoice; returns the local number. */
    public static String localSale(JSONObject payload, double total) {
        SQLiteDatabase d = w(); d.beginTransaction();
        try {
            JSONArray items = payload.optJSONArray("items");
            for (int i = 0; items != null && i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i); long bid = it.optLong("batch_id", 0);
                if (bid != 0) d.execSQL("UPDATE batches SET current_qty=MAX(0, current_qty-?) WHERE id=?", new Object[]{it.optDouble("quantity", 1), bid});
            }
            String no = "M-" + String.format("%06d", counter("inv_no"));
            ContentValues cv = new ContentValues(); cv.put("local_no", no); cv.put("total", total); cv.put("item_count", items == null ? 0 : items.length());
            JSONArray pays = payload.optJSONArray("payments"); String method = pays != null && pays.length() > 0 ? pays.optJSONObject(0).optString("method", "CASH") : "CASH";
            boolean credit = false; if (pays != null) for (int i = 0; i < pays.length(); i++) if ("CREDIT".equals(pays.optJSONObject(i).optString("method"))) credit = true;
            if (pays != null && pays.length() > 1) method = credit ? "CREDIT" : "MIXED";
            cv.put("payment", method); cv.put("status", "PAID"); cv.put("payment_status", credit ? "PENDING" : "PAID");
            if (payload.has("customer_id")) cv.put("customer_id", payload.optLong("customer_id"));
            double sub = 0, disc = payload.optDouble("invoice_discount", 0);
            for (int i = 0; items != null && i < items.length(); i++) { JSONObject it = items.optJSONObject(i); sub += it.optDouble("quantity", 1) * it.optDouble("price", 0); disc += it.optDouble("discount", 0); }
            cv.put("subtotal", sub > 0 ? sub : total); cv.put("discount", disc); cv.put("tax", 0); cv.put("user", Screens.userName()); cv.put("coupon", payload.optString("coupon_code", null));
            cv.put("at", now()); cv.put("synced", 0); cv.put("json", payload.toString()); long rid = d.insert("invoices", null, cv);
            for (int i = 0; items != null && i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i); long bid = it.optLong("batch_id", 0); double q = it.optDouble("quantity", 1), pr = it.optDouble("price", 0), buy = 0;
                if (bid != 0) try (Cursor c = d.rawQuery("SELECT buy_price FROM batches WHERE id=?", new String[]{String.valueOf(bid)})) { if (c.moveToFirst()) buy = c.getDouble(0); }
                d.execSQL("INSERT INTO invoice_items(inv,product_id,batch_id,qty,unit_sell_price,unit_buy_price,discount,subtotal) VALUES(?,?,?,?,?,?,?,?)", new Object[]{rid, it.optLong("product_id"), bid, q, pr, buy, it.optDouble("discount", 0), q * pr - it.optDouble("discount", 0)});
                d.execSQL("INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,user,created_at) VALUES(?,?,'SALE_OUT',?,'Invoice',?,?,?)", new Object[]{it.optLong("product_id"), bid, -q, no, Screens.userName(), now()});
            }
            if (credit && payload.has("customer_id")) { double cr = 0; for (int i = 0; i < pays.length(); i++) if ("CREDIT".equals(pays.optJSONObject(i).optString("method"))) cr += pays.optJSONObject(i).optDouble("amount"); d.execSQL("INSERT INTO ledger(customer_id,entry_type,amount,note,ref,created_at) VALUES(?,'CHARGE',?,?,?,?)", new Object[]{payload.optLong("customer_id"), cr, "خرید نسیه", no, now()}); }
            if (!payload.optString("coupon_code").isEmpty()) d.execSQL("UPDATE coupons SET used_count=used_count+1, status=CASE WHEN used_count+1>=usage_limit THEN 'USED' ELSE status END WHERE code=?", new Object[]{payload.optString("coupon_code")});
            d.setTransactionSuccessful();
            double cogs = 0; try (Cursor c = d.rawQuery("SELECT IFNULL(SUM(qty*unit_buy_price),0) FROM invoice_items WHERE inv=?", new String[]{String.valueOf(rid)})) { if (c.moveToFirst()) cogs = c.getDouble(0); }
            final double fc = cogs; Local.postSale(no, total, fc, pays);
            return no;
        } finally { d.endTransaction(); }
    }
    public static void markInvoiceSynced(String localNo, String invoiceNumber) { ContentValues cv = new ContentValues(); cv.put("synced", 1); cv.put("invoice_number", invoiceNumber); w().update("invoices", cv, "local_no=?", new String[]{localNo}); }
    public static List<JSONObject> localInvoices() {
        List<JSONObject> out = new ArrayList<>();
        try (Cursor c = w().rawQuery("SELECT local_no,total,item_count,payment,at,synced,invoice_number,rowid,status FROM invoices ORDER BY at DESC LIMIT 200", null)) {
            while (c.moveToNext()) { JSONObject o = new JSONObject(); try { o.put("local_no", c.getString(0)); o.put("total", c.getDouble(1)); o.put("items", c.getInt(2)); o.put("payment", c.getString(3)); o.put("at", c.getString(4)); o.put("synced", c.getInt(5) == 1); o.put("invoice_number", c.isNull(6) ? null : c.getString(6)); o.put("id", c.getLong(7)); o.put("status", c.getString(8)); } catch (Exception ignore) {} out.add(o); }
        }
        return out;
    }
    public static double[] todayStats() {  // {count, total, unsynced}
        String day = now().substring(0, 10);
        try (Cursor c = w().rawQuery("SELECT COUNT(*), IFNULL(SUM(total),0), (SELECT COUNT(*) FROM invoices WHERE synced=0) FROM invoices WHERE substr(at,1,10)=?", new String[]{day})) { return c.moveToFirst() ? new double[]{c.getDouble(0), c.getDouble(1), c.getDouble(2)} : new double[]{0, 0, 0}; }
    }

    /** sales totals for the last 7 days (oldest first) — dashboard sparkline. */
    public static double[] weekSales() {
        double[] out = new double[7]; java.util.Calendar cal = java.util.Calendar.getInstance();
        for (int i = 6; i >= 0; i--) { String day = String.format(java.util.Locale.US, "%04d-%02d-%02d", cal.get(java.util.Calendar.YEAR), cal.get(java.util.Calendar.MONTH) + 1, cal.get(java.util.Calendar.DAY_OF_MONTH)); try (Cursor c = w().rawQuery("SELECT IFNULL(SUM(total),0) FROM invoices WHERE substr(at,1,10)=?", new String[]{day})) { out[i] = c.moveToFirst() ? c.getDouble(0) : 0; } cal.add(java.util.Calendar.DAY_OF_MONTH, -1); }
        return out;
    }
    /** "name|qty" of today's best sellers (from local invoice JSON). */
    public static String[] topSellingToday(int n) {
        java.util.Map<String, Double> m = new java.util.HashMap<>(); String day = now().substring(0, 10);
        try (Cursor c = w().rawQuery("SELECT json FROM invoices WHERE substr(at,1,10)=?", new String[]{day})) { while (c.moveToNext()) { try { JSONArray it = new JSONObject(c.getString(0)).optJSONArray("items"); for (int i = 0; it != null && i < it.length(); i++) { JSONObject x = it.optJSONObject(i); String k = x.optString("name"); m.put(k, (m.containsKey(k) ? m.get(k) : 0) + x.optDouble("quantity", 0)); } } catch (Exception ignore) {} } }
        java.util.List<java.util.Map.Entry<String, Double>> l = new java.util.ArrayList<>(m.entrySet()); java.util.Collections.sort(l, (x, y) -> Double.compare(y.getValue(), x.getValue()));
        String[] out = new String[Math.min(n, l.size())]; for (int i = 0; i < out.length; i++) out[i] = l.get(i).getKey() + "|" + Ui.num(l.get(i).getValue()); return out;
    }
    /** batches with stock whose expiry is within `days` (0 = already expired). */
    public static int expiringCount(int days) {
        java.util.Calendar cal = java.util.Calendar.getInstance(); String today = now().substring(0, 10); cal.add(java.util.Calendar.DAY_OF_MONTH, days);
        String lim = String.format(java.util.Locale.US, "%04d-%02d-%02d", cal.get(java.util.Calendar.YEAR), cal.get(java.util.Calendar.MONTH) + 1, cal.get(java.util.Calendar.DAY_OF_MONTH));
        String sql = days == 0 ? "SELECT COUNT(*) FROM batches WHERE current_qty>0 AND expiry_date IS NOT NULL AND expiry_date<?" : "SELECT COUNT(*) FROM batches WHERE current_qty>0 AND expiry_date IS NOT NULL AND expiry_date>=? AND expiry_date<=?";
        try (Cursor c = w().rawQuery(sql, days == 0 ? new String[]{today} : new String[]{today, lim})) { return c.moveToFirst() ? c.getInt(0) : 0; }
    }
    /** names of batches expiring within `days` (for notifications). */
    public static java.util.List<String> expiringNames(int days, int limit) {
        java.util.List<String> out = new java.util.ArrayList<>(); java.util.Calendar cal = java.util.Calendar.getInstance(); cal.add(java.util.Calendar.DAY_OF_MONTH, days);
        String lim = String.format(java.util.Locale.US, "%04d-%02d-%02d", cal.get(java.util.Calendar.YEAR), cal.get(java.util.Calendar.MONTH) + 1, cal.get(java.util.Calendar.DAY_OF_MONTH));
        try (Cursor c = w().rawQuery("SELECT p.name, b.expiry_date FROM batches b JOIN products p ON p.id=b.product_id WHERE b.current_qty>0 AND b.expiry_date IS NOT NULL AND b.expiry_date<=? ORDER BY b.expiry_date LIMIT " + limit, new String[]{lim})) { while (c.moveToNext()) out.add(c.getString(0) + " (" + Ui.jdate(c.getString(1)) + ")"); }
        return out;
    }
    /** products whose total stock is at/below their alert threshold. */
    public static java.util.List<String> lowStockNames(int limit) {
        java.util.List<String> out = new java.util.ArrayList<>();
        try (Cursor c = w().rawQuery("SELECT p.name, IFNULL(SUM(b.current_qty),0) q, p.min_stock_alert FROM products p LEFT JOIN batches b ON b.product_id=p.id WHERE p.is_active=1 AND p.min_stock_alert>0 GROUP BY p.id HAVING q<=p.min_stock_alert LIMIT " + limit, null)) { while (c.moveToNext()) out.add(c.getString(0) + " (" + Ui.num(c.getDouble(1)) + ")"); }
        return out;
    }

    /* ---------------- op queue ---------------- */
    public static String opAdd(String type, JSONObject payload, String label, String localNo) {
        String id = "op" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        ContentValues cv = new ContentValues(); cv.put("id", id); cv.put("type", type); cv.put("payload", payload.toString()); cv.put("label", label); cv.put("local_no", localNo); cv.put("created_at", now());
        w().insert("ops", null, cv); return id;
    }
    public static List<JSONObject> ops() {
        List<JSONObject> out = new ArrayList<>();
        try (Cursor c = w().rawQuery("SELECT id,type,payload,label,local_no,created_at,last_error FROM ops ORDER BY created_at", null)) {
            while (c.moveToNext()) { JSONObject o = new JSONObject(); try { o.put("id", c.getString(0)); o.put("type", c.getString(1)); o.put("payload", new JSONObject(c.getString(2))); o.put("label", c.getString(3)); o.put("local_no", c.isNull(4) ? null : c.getString(4)); o.put("created_at", c.getString(5)); o.put("last_error", c.isNull(6) ? null : c.getString(6)); } catch (Exception ignore) {} out.add(o); }
        }
        return out;
    }
    public static void opDelete(String id) { w().delete("ops", "id=?", new String[]{id}); }
    public static void opError(String id, String err) { ContentValues cv = new ContentValues(); cv.put("last_error", err); w().update("ops", cv, "id=?", new String[]{id}); }
    public static int opCount() { return count("ops"); }
    public static void conflictAdd(String opId, String label, String msg) { ContentValues cv = new ContentValues(); cv.put("op_id", opId); cv.put("label", label); cv.put("message", msg); cv.put("at", now()); w().insert("conflicts", null, cv); }
    public static List<JSONObject> conflicts() {
        List<JSONObject> out = new ArrayList<>();
        try (Cursor c = w().rawQuery("SELECT id,label,message,at FROM conflicts ORDER BY id DESC", null)) { while (c.moveToNext()) { JSONObject o = new JSONObject(); try { o.put("id", c.getLong(0)); o.put("label", c.getString(1)); o.put("message", c.getString(2)); o.put("at", c.getString(3)); } catch (Exception ignore) {} out.add(o); } }
        return out;
    }
    public static void conflictDelete(long id) { w().delete("conflicts", "id=?", new String[]{String.valueOf(id)}); }

    /* ---------------- util ---------------- */
    public static String now() { return new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US).format(new java.util.Date()); }
    private static String pad5(long n) { return String.format("%05d", n); }
    public static String norm(String s) {
        if (s == null) return ""; StringBuilder b = new StringBuilder();
        for (char ch : s.trim().toCharArray()) { if (ch >= '۰' && ch <= '۹') b.append((char) ('0' + ch - '۰')); else if (ch == 'ي') b.append('ی'); else if (ch == 'ك') b.append('ک'); else b.append(ch); }
        return b.toString();
    }
}
