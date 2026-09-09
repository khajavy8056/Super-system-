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

    private Db(Context c) { super(c, "supermarket_native.db", null, 1); }

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
    }
    @Override public void onUpgrade(SQLiteDatabase d, int a, int b) {}

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
        putBatch(b, true); return b;
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
            JSONArray pays = payload.optJSONArray("payments"); cv.put("payment", pays != null && pays.length() > 0 ? pays.optJSONObject(0).optString("method", "CASH") : "CASH");
            cv.put("at", now()); cv.put("synced", 0); cv.put("json", payload.toString()); d.insert("invoices", null, cv);
            d.setTransactionSuccessful(); return no;
        } finally { d.endTransaction(); }
    }
    public static void markInvoiceSynced(String localNo, String invoiceNumber) { ContentValues cv = new ContentValues(); cv.put("synced", 1); cv.put("invoice_number", invoiceNumber); w().update("invoices", cv, "local_no=?", new String[]{localNo}); }
    public static List<JSONObject> localInvoices() {
        List<JSONObject> out = new ArrayList<>();
        try (Cursor c = w().rawQuery("SELECT local_no,total,item_count,payment,at,synced,invoice_number FROM invoices ORDER BY at DESC LIMIT 200", null)) {
            while (c.moveToNext()) { JSONObject o = new JSONObject(); try { o.put("local_no", c.getString(0)); o.put("total", c.getDouble(1)); o.put("items", c.getInt(2)); o.put("payment", c.getString(3)); o.put("at", c.getString(4)); o.put("synced", c.getInt(5) == 1); o.put("invoice_number", c.isNull(6) ? null : c.getString(6)); } catch (Exception ignore) {} out.add(o); }
        }
        return out;
    }
    public static double[] todayStats() {  // {count, total, unsynced}
        String day = now().substring(0, 10);
        try (Cursor c = w().rawQuery("SELECT COUNT(*), IFNULL(SUM(total),0), (SELECT COUNT(*) FROM invoices WHERE synced=0) FROM invoices WHERE substr(at,1,10)=?", new String[]{day})) { return c.moveToFirst() ? new double[]{c.getDouble(0), c.getDouble(1), c.getDouble(2)} : new double[]{0, 0, 0}; }
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
    static String norm(String s) {
        if (s == null) return ""; StringBuilder b = new StringBuilder();
        for (char ch : s.trim().toCharArray()) { if (ch >= '۰' && ch <= '۹') b.append((char) ('0' + ch - '۰')); else if (ch == 'ي') b.append('ی'); else if (ch == 'ك') b.append('ک'); else b.append(ch); }
        return b.toString();
    }
}
