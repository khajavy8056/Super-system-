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
    /** v3.3: set while a restore swaps the database file; every access waits instead of reopening a half-written file. */
    static volatile boolean swapping = false;
    private static SQLiteDatabase w() { while (swapping) { try { Thread.sleep(50); } catch (InterruptedException ignore) {} } return I.getWritableDatabase(); }
    public static java.io.File file(Context c) { return c.getDatabasePath("supermarket_native.db"); }
    /** v3.0: close before a restore replaces the file; the next db() call reopens and re-runs onOpen(). */
    public static synchronized void shutdown() { try { if (I != null) I.close(); } catch (Exception ignore) {} }
    @Override public void onConfigure(SQLiteDatabase d) { super.onConfigure(d); try { d.enableWriteAheadLogging(); } catch (Exception ignore) {} }   // v3.3: readers never block on a long write (restore/import)
    @Override public void onOpen(SQLiteDatabase d) { super.onOpen(d); try { d.execSQL(Insights.DDL); } catch (Exception ignore) {} try { indexes(d); } catch (Exception ignore) {} }
    /** v3.3 — indexes for stores with years of history (tens of thousands of invoices): every dashboard /
     *  report query is now a range scan on an index instead of a full-table scan. Idempotent. */
    static final String[] V4_INDEX = {
        "CREATE INDEX IF NOT EXISTS ix_inv_at ON invoices(at)", "CREATE INDEX IF NOT EXISTS ix_inv_status_at ON invoices(status, at)", "CREATE INDEX IF NOT EXISTS ix_inv_cust ON invoices(customer_id, at)",
        "CREATE INDEX IF NOT EXISTS ix_inv_paystat ON invoices(payment_status)", "CREATE INDEX IF NOT EXISTS ix_ii_pid ON invoice_items(product_id)",
        "CREATE INDEX IF NOT EXISTS ix_b_p_status ON batches(product_id, status)", "CREATE INDEX IF NOT EXISTS ix_b_status_exp ON batches(status, expiry_date)",
        "CREATE INDEX IF NOT EXISTS ix_led_cust ON ledger(customer_id)", "CREATE INDEX IF NOT EXISTS ix_jr_status_date ON journal(status, date)", "CREATE INDEX IF NOT EXISTS ix_jr_ref ON journal(ref)",
        "CREATE INDEX IF NOT EXISTS ix_mv_pid ON movements(product_id)", "CREATE INDEX IF NOT EXISTS ix_mv_at ON movements(created_at)", "CREATE INDEX IF NOT EXISTS ix_ai_status ON ai_insights(status)",
        "CREATE INDEX IF NOT EXISTS ix_p_name ON products(is_active, name)", "CREATE INDEX IF NOT EXISTS ix_c_phone ON customers(phone)",
        "CREATE TABLE IF NOT EXISTS journal_lines(jid INTEGER, code TEXT, debit REAL, credit REAL)", "CREATE INDEX IF NOT EXISTS ix_jl_code ON journal_lines(code, jid)", "CREATE INDEX IF NOT EXISTS ix_jl_jid ON journal_lines(jid)",
        // v3.5 — the default catalogue ships up to three pictures per product, so
        // the operator can pick another shot with no network lookup. Idempotent:
        // indexes() wraps every statement in try/catch, so the ALTER is a no-op
        // once the column exists.
        "ALTER TABLE products ADD COLUMN gallery TEXT",
    };
    static void indexes(SQLiteDatabase d) { for (String q : V4_INDEX) { try { d.execSQL(q); } catch (Exception ignore) {} } }
    /** v3.3 — account balances are summed in SQL from journal_lines (one row per posting line) instead of
     *  parsing the JSON of every journal row in Java; this fills the table once for journals written before 3.3. */
    static void rebuildJournalLines(SQLiteDatabase d) {
        try (Cursor n = d.rawQuery("SELECT (SELECT COUNT(*) FROM journal_lines), (SELECT COUNT(*) FROM journal)", null)) { if (n.moveToFirst() && (n.getLong(0) > 0 || n.getLong(1) == 0)) return; }
        android.database.sqlite.SQLiteStatement st = d.compileStatement("INSERT INTO journal_lines(jid,code,debit,credit) VALUES(?,?,?,?)");
        d.beginTransaction();
        try (Cursor c = d.rawQuery("SELECT id, lines FROM journal", null)) {
            while (c.moveToNext()) { try { JSONArray ls = new JSONArray(c.getString(1)); for (int i = 0; i < ls.length(); i++) { JSONObject l = ls.optJSONObject(i); st.clearBindings(); st.bindLong(1, c.getLong(0)); st.bindString(2, l.optString("code")); st.bindDouble(3, l.optDouble("debit")); st.bindDouble(4, l.optDouble("credit")); st.executeInsert(); } } catch (Exception ignore) {} }
            d.setTransactionSuccessful();
        } finally { d.endTransaction(); st.close(); }
    }
    /** v2.4: the local API router ({@link Local}) works directly on the database. */
    public static SQLiteDatabase db() { return w(); }
    /** v3.4 — wrap a large import in one transaction (catalog.pack apply). */
    public static void beginBulk() { w().beginTransaction(); }
    public static void endBulk() { SQLiteDatabase d = w(); try { d.setTransactionSuccessful(); } finally { d.endTransaction(); } }

    private Db(Context c) { super(c, "supermarket_native.db", null, VERSION); }   // v2.7: db 3 → bank table · v3.3: db 4 → indexes + journal_lines

    /** v2.4 — full standalone schema: every Windows section has a table on the phone. */
    static final String[] V2 = {
        "CREATE TABLE IF NOT EXISTS invoice_items(id INTEGER PRIMARY KEY AUTOINCREMENT, inv INTEGER, product_id INTEGER, batch_id INTEGER, qty REAL, unit_sell_price REAL, unit_buy_price REAL, discount REAL DEFAULT 0, subtotal REAL, returned_qty REAL DEFAULT 0)",
        "CREATE INDEX IF NOT EXISTS ix_ii_inv ON invoice_items(inv)",
        "CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, batch_id INTEGER, movement_type TEXT, quantity REAL, reference_type TEXT, reference_id TEXT, reason TEXT, user TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, entry_type TEXT, amount REAL, note TEXT, ref TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)",
        "CREATE TABLE IF NOT EXISTS brands(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)",
        "CREATE TABLE IF NOT EXISTS bank(barcode TEXT PRIMARY KEY, name TEXT, brand TEXT, unit TEXT, category TEXT, image_url TEXT, source TEXT, updated_at TEXT)",   // v2.7 بانک کالا
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

    @Override public void onCreate(SQLiteDatabase d) { schema(d); }
    /** v3.3: full phone schema on any SQLiteDatabase (also used by {@link PcImport} to build a fresh file off-line). */
    static void schema(SQLiteDatabase d) {
        d.execSQL("CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, barcode TEXT, name TEXT, sku TEXT, unit_id INTEGER, category_id INTEGER, brand_id INTEGER, min_stock_alert REAL DEFAULT 0, image_url TEXT, is_active INTEGER DEFAULT 1, is_local INTEGER DEFAULT 0, json TEXT, updated_at TEXT)");
        d.execSQL("CREATE INDEX IF NOT EXISTS ix_p_bc ON products(barcode)");
        d.execSQL("CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY, product_id INTEGER, batch_number TEXT, current_qty REAL, sell_price REAL, consumer_price REAL, buy_price REAL, expiry_date TEXT, status TEXT, is_local INTEGER DEFAULT 0, json TEXT, updated_at TEXT)");
        d.execSQL("CREATE INDEX IF NOT EXISTS ix_b_p ON batches(product_id)");
        d.execSQL("CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT, last_name TEXT, phone TEXT, credit_limit REAL, is_local INTEGER DEFAULT 0, json TEXT)");
        d.execSQL("CREATE TABLE IF NOT EXISTS invoices(local_no TEXT PRIMARY KEY, total REAL, item_count INTEGER, payment TEXT, at TEXT, synced INTEGER DEFAULT 0, invoice_number TEXT, json TEXT)");
        d.execSQL("CREATE TABLE IF NOT EXISTS ops(id TEXT PRIMARY KEY, type TEXT, payload TEXT, label TEXT, local_no TEXT, created_at TEXT, last_error TEXT)");
        d.execSQL("CREATE TABLE IF NOT EXISTS cache(path TEXT PRIMARY KEY, json TEXT, at TEXT)");
        d.execSQL("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)");
        d.execSQL("CREATE TABLE IF NOT EXISTS conflicts(id INTEGER PRIMARY KEY AUTOINCREMENT, op_id TEXT, label TEXT, message TEXT, at TEXT)");
        v2(d); try { d.execSQL(Insights.DDL); } catch (Exception ignore) {} indexes(d);
        try (Cursor c = d.rawQuery("PRAGMA user_version=" + VERSION, null)) { c.moveToFirst(); } catch (Exception ignore) {}
    }
    // v3.5.2 — 4 → 5. products.gallery was added to V4_INDEX, but an install
    // already sitting at user_version 4 never re-runs onUpgrade for a same-version
    // bump, so the ALTER never executed and every putProduct then threw
    // "no column named gallery", aborting the whole catalogue import. Bumping the
    // version is what makes the migration actually reach existing installs.
    static final int VERSION = 5;
    @Override public void onUpgrade(SQLiteDatabase d, int a, int b) {
        if (a < 3) v2(d);
        if (a < 4) { try { rebuildJournalLines(d); } catch (Exception ignore) {} }
        if (a < 5) indexes(d);   // idempotent: IF NOT EXISTS + try-ALTER per statement
    }

    /* ---------------- kv ---------------- */
    public static String kv(String k) { try (Cursor c = w().rawQuery("SELECT v FROM kv WHERE k=?", new String[]{k})) { return c.moveToFirst() ? c.getString(0) : null; } }
    public static void kv(String k, String v) { ContentValues cv = new ContentValues(); cv.put("k", k); cv.put("v", v); w().insertWithOnConflict("kv", null, cv, SQLiteDatabase.CONFLICT_REPLACE); }
    private static long counter(String k) { long n = 0; String v = kv(k); if (v != null) n = Long.parseLong(v); n++; kv(k, String.valueOf(n)); return n; }

    /* ---------------- cache ---------------- */
    public static void cachePut(String path, String json) { try { cachePut0(path, json); } catch (Throwable ignore) {} }   // v3.3: never let a cache write (e.g. during a restore) kill the request thread
    private static void cachePut0(String path, String json) { ContentValues cv = new ContentValues(); cv.put("path", path); cv.put("json", json); cv.put("at", now()); w().insertWithOnConflict("cache", null, cv, SQLiteDatabase.CONFLICT_REPLACE); }
    public static String cacheGet(String path) { try (Cursor c = w().rawQuery("SELECT json FROM cache WHERE path=?", new String[]{path})) { return c.moveToFirst() ? c.getString(0) : null; } }

    /* ---------------- catalogue merge from PC ---------------- */
    public static void applyPull(JSONObject pull, boolean full) {
        SQLiteDatabase d = w(); d.beginTransaction();
        try {
            if (full) { d.delete("products", "is_local=0", null); d.delete("batches", "is_local=0", null); d.delete("customers", "is_local=0", null); }
            JSONArray ps = pull.optJSONArray("products"); if (ps != null) for (int i = 0; i < ps.length(); i++) putProduct(ps.optJSONObject(i), false);
            JSONArray bs = pull.optJSONArray("batches"); if (bs != null) for (int i = 0; i < bs.length(); i++) putBatch(bs.optJSONObject(i), false);
            JSONArray cs = pull.optJSONArray("customers"); if (cs != null) for (int i = 0; i < cs.length(); i++) putCustomer(cs.optJSONObject(i), false);
            JSONArray bk = pull.optJSONArray("bank"); if (bk != null) for (int i = 0; i < bk.length(); i++) bankPut(bk.optJSONObject(i));   // v2.7
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
        // v3.5 — the extra catalogue pictures, kept as the same JSON array the PC uses
        cv.put("gallery", p.isNull("gallery") ? null : p.optJSONArray("gallery") == null ? null : p.optJSONArray("gallery").toString());
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

    /**
     * v3.5 — the bundled default catalogue: 13 570 supermarket/pharmacy products
     * built from the shop's own product sheets, each with its full name, its exact
     * GTIN, its category/sub-category and the picture(s) that shipped with it.
     * Everything is created with NO stock — stock only ever appears through a
     * receiving — so a barcode scan identifies the item and the operator records
     * what actually came in.
     *
     * The old version split each line on "," and read 7 columns. That silently
     * mangled the new file: the extra image columns were dropped and any name that
     * still held an ASCII comma shifted every field after it. Lines are parsed as
     * real CSV now and all nine columns are honoured.
     */
    /**
     * Only one import may ever be in flight.
     *
     * AppActivity fires the import on every launch and InstallService fires it
     * during the first-run wizard; both go through Api.bg, which is a 4-thread
     * pool. Without this guard the two ran concurrently on a fresh install and
     * both called beginTransaction() on the same SQLiteDatabase from different
     * threads, which is what crashed the app before the catalogue ever appeared.
     */
    private static final java.util.concurrent.atomic.AtomicBoolean CATALOG_RUNNING =
        new java.util.concurrent.atomic.AtomicBoolean(false);

    public static JSONObject importStarter(Context ctx) {
        if (!CATALOG_RUNNING.compareAndSet(false, true)) {
            JSONObject busy = new JSONObject();
            try { busy.put("created", 0); busy.put("matched_existing", 0); busy.put("images_filled", 0); busy.put("already_running", true); } catch (Exception ignore) {}
            return busy;
        }
        try { return importStarterInner(ctx); } finally { CATALOG_RUNNING.set(false); }
    }

    private static JSONObject importStarterInner(Context ctx) {
        int n = 0, matched = 0, filled = 0;
        SQLiteDatabase d = w();
        // v3.5.3 — the import used to run as ONE transaction holding ~68 000
        // statements (5 per product). That kept the write lock for so long the UI
        // thread blocked on its own reads and Android raised an ANR, and a failure
        // at row 13 000 rolled back all 13 000. Work is now committed in chunks so
        // the lock is released regularly and partial progress survives.
        final int CHUNK = 400;
        boolean inTx = false;
        // IDs used to come from counter("pid"), which did a SELECT + an INSERT on
        // kv FOR EVERY ROW — 27 000 statements just to number the products. The
        // counter is read once and written once instead.
        long seq = 0;
        try { String v = kv("pid"); if (v != null) seq = Long.parseLong(v); } catch (Exception ignore) {}
        // A killed chunked import may have committed products before saving kv(pid).
        // Never reuse their negative IDs on the next launch.
        try (Cursor c = d.rawQuery("SELECT COALESCE(-MIN(id),0) FROM products WHERE id<0", null)) {
            if (c.moveToFirst()) seq = Math.max(seq, c.getLong(0));
        }
        int pending = 0;
        android.database.sqlite.SQLiteStatement ins = null;
        android.database.sqlite.SQLiteStatement bankIns = null;
        android.database.sqlite.SQLiteStatement bankFill = null;
        java.util.regex.Pattern nonDigit = java.util.regex.Pattern.compile("[^0-9]");
        try (java.io.BufferedReader br = new java.io.BufferedReader(
                new java.io.InputStreamReader(ctx.getAssets().open(STARTER_ASSET), "UTF-8"))) {
            br.readLine();   // header: category,subcategory,name,brand,unit,min_stock_alert,barcode,image_url,images
            java.util.Map<String, Long> units = new java.util.HashMap<>();
            java.util.Map<String, Long> cats = new java.util.HashMap<>();
            java.util.HashSet<String> seen = new java.util.HashSet<>();

            ins = d.compileStatement("INSERT OR REPLACE INTO products(id,barcode,name,sku,unit_id,category_id,brand_id,"
                + "min_stock_alert,image_url,is_active,is_local,json,updated_at,gallery) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,?)");
            bankIns = d.compileStatement("INSERT OR REPLACE INTO bank(barcode,name,brand,unit,category,image_url,source,updated_at)"
                + " VALUES(?,?,?,?,?,?,?,?)");
            // bankPut() used to guard against downgrading a row the SHOP confirmed
            // (source=USER, rank 3) with a mere IMPORT (rank 2). A plain
            // INSERT OR REPLACE would have silently thrown that confirmation away,
            // so the confirmed codes are loaded once and only get their blank
            // fields filled instead of being replaced.
            bankFill = d.compileStatement("UPDATE bank SET"
                + " brand=COALESCE(NULLIF(brand,''),?),"
                + " unit=COALESCE(NULLIF(unit,''),?),"
                + " image_url=COALESCE(NULLIF(image_url,''),?)"
                + " WHERE barcode=?");
            java.util.HashSet<String> bankConfirmed = new java.util.HashSet<>();
            try (Cursor c = d.rawQuery("SELECT barcode FROM bank WHERE source='USER'", null)) {
                while (c.moveToNext()) bankConfirmed.add(c.getString(0));
            }

            // Match complete identifiers only: names and numeric substrings are
            // not product identity (Hy-40312350 must not collide with 40312350).
            java.util.HashMap<String, Long> byBarcode = new java.util.HashMap<>();
            java.util.HashMap<Long, String> imgOf = new java.util.HashMap<>();
            try (Cursor c = d.rawQuery("SELECT id, barcode, name, image_url FROM products", null)) {
                while (c.moveToNext()) {
                    long pid = c.getLong(0);
                    String bc = norm(c.getString(1));
                    if (!bc.isEmpty()) byBarcode.put(bc, pid);
                    imgOf.put(pid, c.isNull(3) ? "" : c.getString(3));
                }
            }

            String line;
            while ((line = br.readLine()) != null) {
                String[] f = csvLine(line);
                if (f.length < 3) continue;
                String name = f[2].trim();
                if (name.isEmpty()) continue;
                String barcode = f.length > 6 ? f[6].trim() : "";
                String key = barcode.isEmpty() ? (name + "\u0000" + f[0].trim()) : barcode;
                if (!seen.add(key)) continue;

                String img = f.length > 7 ? f[7].trim() : "";

                String unit = f.length > 4 && !f[4].trim().isEmpty() ? f[4].trim() : "عدد";
                if (!units.containsKey(unit)) units.put(unit, (long) units.size() + 1);
                String cat = f[0].trim() + (f.length > 1 && !f[1].trim().isEmpty() ? " / " + f[1].trim() : "");
                if (!cats.containsKey(cat)) cats.put(cat, (long) cats.size() + 1);

                // already known → do not create a second row. If the shop's own
                // copy has no picture yet, adopt the one that ships with the bank;
                // that is the whole point of reconciling instead of skipping.
                Long hit = barcode.isEmpty() ? null : byBarcode.get(norm(barcode));
                if (hit != null) {
                    matched++;
                    if (!img.isEmpty() && imgOf.get(hit).isEmpty()) {
                        if (!inTx) { d.beginTransaction(); inTx = true; }
                        ContentValues u = new ContentValues(); u.put("image_url", img);
                        d.update("products", u, "id=?", new String[]{String.valueOf(hit)});
                        imgOf.put(hit, img);
                        filled++;
                        if (++pending >= CHUNK) { d.setTransactionSuccessful(); d.endTransaction(); inTx = false; pending = 0; }
                    }
                    continue;
                }

                String gallery = f.length > 8 ? f[8].trim() : "";

                // ids come from an in-memory counter; the old counter("pid") hit the
                // kv table twice per product (27 000 statements for one import)
                long id = -(++seq);
                String code = barcode.isEmpty() ? "INT-L" + pad5(-id) : barcode;
                long unitId = units.get(unit);
                long catId = cats.get(cat);
                double alert = 0;
                try { if (f.length > 5 && !f[5].trim().isEmpty()) alert = Double.parseDouble(f[5].trim()); } catch (Exception ignore) {}
                String galleryJson = null;
                if (!gallery.isEmpty()) {
                    JSONArray g = new JSONArray();
                    for (String u : gallery.split("\\|")) { if (!u.trim().isEmpty()) g.put(u.trim()); }
                    if (g.length() > 0) galleryJson = g.toString();
                }

                // the phone's own product document — same shape the PC sends over
                // sync, so the rest of the app needs no special case for it
                JSONObject p = new JSONObject();
                try {
                    p.put("id", id);
                    p.put("name", name);
                    p.put("barcode", code);
                    p.put("has_own_barcode", !barcode.isEmpty() && !barcode.startsWith("INT-"));
                    p.put("unit_id", unitId); p.put("unit_name", unit);
                    p.put("category_id", catId); p.put("category_name", cat);
                    p.put("subcategory_name", f.length > 1 ? f[1].trim() : "");
                    if (f.length > 3 && !f[3].trim().isEmpty()) p.put("brand_name", f[3].trim());
                    p.put("min_stock_alert", alert);
                    if (!img.isEmpty()) p.put("image_url", img);
                    if (galleryJson != null) p.put("gallery", new JSONArray(galleryJson));
                    p.put("is_active", true); p.put("_local", true);
                } catch (Exception ignore) {}

                // One bad row must never abort the remaining 13 000 — and because
                // work is committed in chunks, the rows already written survive.
                try {
                    if (!inTx) { d.beginTransaction(); inTx = true; }
                    ins.clearBindings();
                    ins.bindLong(1, id);
                    ins.bindString(2, code);
                    ins.bindString(3, name);
                    ins.bindNull(4);                       // sku
                    ins.bindLong(5, unitId);
                    ins.bindLong(6, catId);
                    ins.bindNull(7);                       // brand_id
                    ins.bindDouble(8, alert);
                    if (img.isEmpty()) ins.bindNull(9); else ins.bindString(9, img);
                    ins.bindLong(10, 1);                   // is_active
                    // is_local is the literal 1 in the SQL, so it consumes no
                    // placeholder: json/updated_at/gallery bind at 11/12/13, not
                    // 12/13/14. Binding past the parameter count throws, and the
                    // per-row guard would have swallowed it for all 13 570 rows.
                    ins.bindString(11, p.toString());      // json
                    ins.bindString(12, now());
                    if (galleryJson == null) ins.bindNull(13); else ins.bindString(13, galleryJson);
                    ins.executeInsert();
                } catch (Exception e) {
                    kv("default_catalog_error", "row " + name + ": " + e);
                    continue;
                }
                // the offline barcode→name bank, so an unknown item can still be
                // named from the phone when the PC is out of reach. Written with a
                // compiled statement: bankPut() did a SELECT per row on top.
                if (!barcode.isEmpty() && !barcode.startsWith("INT-")) {
                    try {
                        if (bankConfirmed.contains(barcode)) {
                            // the shop already confirmed this barcode — never
                            // downgrade it, only fill in what it left blank
                            bankFill.clearBindings();
                            bankFill.bindNull(1); bankFill.bindNull(2);
                            if (img.isEmpty()) bankFill.bindNull(3); else bankFill.bindString(3, img);
                            bankFill.bindString(4, barcode);
                            bankFill.execute();
                        } else {
                            bankIns.clearBindings();
                            bankIns.bindString(1, barcode); bankIns.bindString(2, name);
                            bankIns.bindNull(3); bankIns.bindNull(4);
                            bankIns.bindString(5, cat);
                            if (img.isEmpty()) bankIns.bindNull(6); else bankIns.bindString(6, img);
                            bankIns.bindString(7, "IMPORT"); bankIns.bindString(8, now());
                            bankIns.executeInsert();
                        }
                    } catch (Exception ignore) {}
                }
                // remember what we just added so a later line in the same file
                // cannot create a second row for it
                if (!barcode.isEmpty()) byBarcode.put(norm(barcode), id);
                imgOf.put(id, img);
                n++;

                // release the write lock regularly so the UI thread can read
                if (++pending >= CHUNK) { d.setTransactionSuccessful(); d.endTransaction(); inTx = false; pending = 0; }
            }
            if (!inTx) { d.beginTransaction(); inTx = true; }
            try { JSONArray ua = new JSONArray(); for (java.util.Map.Entry<String, Long> e : units.entrySet()) { JSONObject u = new JSONObject(); u.put("id", e.getValue()); u.put("name", e.getKey()); u.put("allow_decimal", e.getKey().contains("کیلو") || e.getKey().contains("گرم") || e.getKey().contains("لیتر") || e.getKey().contains("متر")); ua.put(u); } kv("local_units", ua.toString()); } catch (Exception ignore) {}
            kv("starter_imported", "1");
            kv("default_catalog_count", String.valueOf(n));
            kv("pid", String.valueOf(seq));   // written once, not 13 570 times
            // Only claim success when something actually landed. 3.5.1/3.5.2 wrote
            // this marker unconditionally, so a phone where every single insert
            // failed still reported "imported" and never retried — the shop was
            // left with an empty catalogue and no way back.
            if (n > 0 || matched > 0) {
                kv("default_catalog_ver", CATALOG_VERSION);
                kv("default_catalog_error", "");
            } else {
                kv("default_catalog_error", "no rows imported — nothing matched and nothing was created");
            }
            d.setTransactionSuccessful();
        } catch (Exception e) {
            // a swallowed failure here is exactly how the shop ended up with an
            // empty catalogue and no explanation — record it so the settings
            // screen can say what happened.
            try { kv("default_catalog_error", String.valueOf(e)); } catch (Exception ignore) {}
            try { if (inTx) d.setTransactionSuccessful(); } catch (Exception ignore) {}
        } finally {
            // the work is committed in chunks, so a transaction may already have
            // been closed by the loop — ending one that is not open throws.
            try { if (inTx) d.endTransaction(); } catch (Exception ignore) {}
            try { if (ins != null) ins.close(); } catch (Exception ignore) {}
            try { if (bankIns != null) bankIns.close(); } catch (Exception ignore) {}
            try { if (bankFill != null) bankFill.close(); } catch (Exception ignore) {}
        }
        JSONObject r = new JSONObject();
        try { r.put("created", n); r.put("matched_existing", matched); r.put("images_filled", filled); } catch (Exception ignore) {}
        return r;
    }

    /**
     * Bump when the bundled catalogue changes, so an in-place app update imports
     * the new lines instead of leaving the shop on the old list. Compared against
     * the {@code default_catalog_ver} key written above.
     */
    // Bumped for 3.5.3 even though the CSV did not change. Devices that ran 3.5.1
    // or 3.5.2 wrote this marker while importing ZERO products: the per-row guard
    // swallowed every failure and the marker was then written unconditionally, so
    // catalogPending() stayed false and the phone never tried again. A new value
    // forces exactly those devices to retry with the fixed importer.
    public static final String CATALOG_VERSION = "3.6.5-16953";

    /** True when the bundled catalogue has not been imported into this database yet. */
    public static boolean catalogPending() {
        return !CATALOG_VERSION.equals(kv("default_catalog_ver"));
    }

    /** Result of the last run, for the settings screen. */
    public static JSONObject catalogStatus() {
        JSONObject o = new JSONObject();
        try {
            o.put("version", CATALOG_VERSION);
            o.put("imported_version", kv("default_catalog_ver"));
            o.put("pending", catalogPending());
            o.put("products", count("products"));
            String c = kv("default_catalog_count");
            o.put("last_created", c == null ? 0 : Integer.parseInt(c));
            String err = kv("default_catalog_error");
            if (err != null && !err.isEmpty()) o.put("error", err);
        } catch (Exception ignore) {}
        return o;
    }

    /** Name of the bundled catalogue asset; v3.5 renamed it from starter_catalog.csv. */
    static final String STARTER_ASSET = "default_catalog.csv";

    /** Minimal RFC-4180 line parser — the old {@code split(",")} shifted every
     *  field after a quoted comma and threw the image columns away. */
    static String[] csvLine(String line) {
        java.util.ArrayList<String> out = new java.util.ArrayList<>();
        StringBuilder cur = new StringBuilder();
        boolean quoted = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (quoted) {
                if (c == '"') {
                    if (i + 1 < line.length() && line.charAt(i + 1) == '"') { cur.append('"'); i++; }
                    else quoted = false;
                } else cur.append(c);
            } else if (c == '"') quoted = true;
            else if (c == ',') { out.add(cur.toString()); cur.setLength(0); }
            else cur.append(c);
        }
        out.add(cur.toString());
        return out.toArray(new String[0]);
    }

    /* ---------------- v2.7 بانک کالا (barcode → name/brand, offline) ---------------- */
    static final int[] BANK_RANK = {0};
    static int bankRank(String src) { return "USER".equals(src) ? 3 : "IMPORT".equals(src) ? 2 : "ONLINE".equals(src) ? 1 : 0; }
    public static void bankPut(JSONObject j) {
        if (j == null) return; String bc = norm(j.optString("barcode")).replaceAll("[^0-9]", ""); String name = j.optString("name", "").trim();
        if (bc.length() < 8 || bc.matches("^(02|2[0-9]).*") || name.isEmpty()) return;
        JSONObject cur = bankGet(bc); String src = j.optString("source", "ONLINE");
        if (cur != null && bankRank(src) < bankRank(cur.optString("source"))) {   // never downgrade what the shop confirmed; only fill blanks
            ContentValues f = new ContentValues();
            if (cur.optString("brand").isEmpty() && !j.optString("brand").isEmpty()) f.put("brand", j.optString("brand"));
            if (cur.optString("unit").isEmpty() && !j.optString("unit").isEmpty()) f.put("unit", j.optString("unit"));
            if (cur.optString("image_url").isEmpty() && !j.optString("image_url").isEmpty()) f.put("image_url", j.optString("image_url"));
            if (f.size() > 0) w().update("bank", f, "barcode=?", new String[]{bc});
            return;
        }
        ContentValues cv = new ContentValues(); cv.put("barcode", bc); cv.put("name", name); cv.put("brand", j.optString("brand", null)); cv.put("unit", j.optString("unit", null)); cv.put("category", j.optString("category", null));
        cv.put("image_url", j.optString("image_url", null)); cv.put("source", src); cv.put("updated_at", j.optString("updated_at", now()));
        w().insertWithOnConflict("bank", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
    }
    public static JSONObject bankGet(String barcode) {
        String bc = norm(barcode == null ? "" : barcode).replaceAll("[^0-9]", ""); if (bc.isEmpty()) return null;
        try (Cursor c = w().rawQuery("SELECT barcode,name,brand,unit,category,image_url,source,updated_at FROM bank WHERE barcode=?", new String[]{bc})) {
            if (!c.moveToFirst()) return null;
            JSONObject j = new JSONObject();
            try { j.put("barcode", c.getString(0)); j.put("name", c.getString(1)); j.put("brand", c.isNull(2) ? "" : c.getString(2)); j.put("unit", c.isNull(3) ? "" : c.getString(3)); j.put("category", c.isNull(4) ? "" : c.getString(4)); j.put("image_url", c.isNull(5) ? "" : c.getString(5)); j.put("source", c.getString(6)); j.put("updated_at", c.getString(7)); } catch (Exception ignore) {}
            return j;
        }
    }
    public static int bankCount() { return count("bank"); }
    /** v2.7 — import the bundled seed once (idempotent; never overrides higher-ranked rows). */
    public static int importBankSeed(Context ctx) {
        if ("1".equals(kv("bank_seeded"))) return 0; int n = 0; SQLiteDatabase d = w(); d.beginTransaction();
        try (java.io.BufferedReader br = new java.io.BufferedReader(new java.io.InputStreamReader(ctx.getAssets().open("product_bank_seed.csv"), "UTF-8"))) {
            String line = br.readLine(); // barcode,name,brand,unit,category,image_url
            while ((line = br.readLine()) != null) { String[] f = line.split(",", -1); if (f.length < 2) continue; bankPut(Api.obj("barcode", f[0].trim(), "name", f[1].trim(), "brand", f.length > 2 ? f[2].trim() : "", "unit", f.length > 3 ? f[3].trim() : "", "category", f.length > 4 ? f[4].trim() : "", "image_url", f.length > 5 ? f[5].trim() : "", "source", "SEED")); n++; }
            kv("bank_seeded", "1"); d.setTransactionSuccessful();
        } catch (Exception ignore) {
        } finally { d.endTransaction(); }
        return n;
    }
    /** v2.7 — remember a barcode↔name pair locally AND tell the PC (store-and-forward), so every device learns it. */
    public static void bankRemember(String barcode, String name, String brand, String unit, String category, String imageUrl, String source) {
        JSONObject j = Api.obj("barcode", barcode, "name", name, "brand", brand == null ? "" : brand, "unit", unit == null ? "" : unit, "category", category == null ? "" : category, "image_url", imageUrl == null ? "" : imageUrl, "source", source);
        String bc = norm(barcode == null ? "" : barcode).replaceAll("[^0-9]", ""); if (bc.length() < 8 || bc.matches("^(02|2[0-9]).*") || name == null || name.trim().isEmpty()) return;
        JSONObject cur = bankGet(bc); bankPut(j);
        if (cur != null && cur.optString("name").equals(name.trim()) && bankRank(cur.optString("source")) >= bankRank(source)) return;   // nothing new to share
        if (!Api.standalone()) Sync.queue("BANK_REMEMBER", j, "بانک کالا " + name, null);
    }

    /* ---------------- local reads ---------------- */
    /** v3.5.4 — one indexed probe for "does this shop hold any sellable stock at all",
     *  measured at 0.01 ms. When the answer is no — which is exactly the state of a
     *  fresh install that has just been given the 13 570-line default catalogue — the
     *  stock-first ordering has nothing to order by, so skipping it takes the product
     *  list from 4.75 ms to 0.10 ms and removes a batch query from every result row. */
    private static boolean hasAnyStock() {
        try (Cursor c = w().rawQuery("SELECT 1 FROM batches WHERE status='ACTIVE' AND current_qty>0 LIMIT 1", null)) {
            return c.moveToFirst();
        } catch (Exception e) { return false; }
    }

    /** v3.5.4 — one grouped aggregate, joined once, instead of a correlated sub-query
     *  that SQLite re-evaluated for every one of the 13 570 rows while sorting. The
     *  same lesson {@link #stockRows()} already learnt in v3.3. */
    private static final String STOCK_AGG =
        "(SELECT product_id, SUM(current_qty) s FROM batches"
        + " WHERE status='ACTIVE' AND current_qty>0 GROUP BY product_id)";

    public static List<JSONObject> searchProducts(String q, int limit) {
        List<JSONObject> out = new ArrayList<>(); q = norm(q);
        boolean stock = hasAnyStock();
        SQLiteDatabase d = w();
        if (q.isEmpty()) {
            String sql = stock
                ? "SELECT p.json FROM products p LEFT JOIN " + STOCK_AGG + " x ON x.product_id=p.id"
                  + " WHERE p.is_active=1 ORDER BY (x.s>0) DESC, p.name LIMIT ?"
                : "SELECT json FROM products WHERE is_active=1 ORDER BY name LIMIT ?";
            java.util.HashSet<Long> seen = seen();
            try (Cursor c = d.rawQuery(sql, new String[]{String.valueOf(limit)})) {
                while (c.moveToNext() && out.size() < limit) addHit(out, seen, c.getString(0), stock);
            } catch (Exception ignore) {}
            return out;
        }
        // v3.5.4 — the old statement OR-ed four predicates together
        // (barcode=? OR sku=? OR name LIKE ? OR barcode LIKE ?). SQLite can drive
        // neither ix_p_bc nor ix_p_name from an OR spanning columns, so it scanned
        // all 13 570 rows and sorted them on every keystroke: 13.8–15.2 ms measured
        // on the real catalogue. Three separate steps, each of which CAN use an
        // index and stop as soon as the page is full, return the same page in
        // 3.1–5.3 ms. Scanning still wins because the exact code is looked up first.
        java.util.HashSet<Long> seen = seen();
        String like = "%" + q + "%";
        try (Cursor c = d.rawQuery("SELECT json FROM products WHERE barcode=? OR sku=? LIMIT ?",
                                   new String[]{q, q, String.valueOf(limit)})) {
            while (c.moveToNext() && out.size() < limit) addHit(out, seen, c.getString(0), stock);
        } catch (Exception ignore) {}
        if (out.size() < limit) {
            String sql = stock
                ? "SELECT p.json FROM products p LEFT JOIN " + STOCK_AGG + " x ON x.product_id=p.id"
                  + " WHERE p.is_active=1 AND p.name LIKE ? ORDER BY (x.s>0) DESC, p.name LIMIT ?"
                : "SELECT json FROM products WHERE is_active=1 AND name LIKE ? ORDER BY name LIMIT ?";
            try (Cursor c = d.rawQuery(sql, new String[]{like, String.valueOf(limit - out.size())})) {
                while (c.moveToNext() && out.size() < limit) addHit(out, seen, c.getString(0), stock);
            } catch (Exception ignore) {}
        }
        // partial barcode, kept so a half-remembered code still finds its product
        if (out.size() < limit) {
            try (Cursor c = d.rawQuery("SELECT json FROM products WHERE is_active=1 AND barcode LIKE ? ORDER BY name LIMIT ?",
                                       new String[]{like, String.valueOf(limit - out.size())})) {
                while (c.moveToNext() && out.size() < limit) addHit(out, seen, c.getString(0), stock);
            } catch (Exception ignore) {}
        }
        return out;
    }
    private static java.util.HashSet<Long> seen() { return new java.util.HashSet<Long>(); }
    /** one result row, de-duplicated across the three look-ups above. */
    private static void addHit(List<JSONObject> out, java.util.HashSet<Long> seen, String json, boolean stock) {
        JSONObject p = withBatches(json, stock);
        if (p.length() == 0) return;
        long id = p.optLong("id", -1);
        if (id >= 0 && !seen.add(Long.valueOf(id))) return;
        out.add(p);
    }
    public static JSONObject productByBarcode(String bc) {
        try (Cursor c = w().rawQuery("SELECT json FROM products WHERE barcode=? LIMIT 1", new String[]{norm(bc)})) { return c.moveToFirst() ? withBatches(c.getString(0)) : null; }
    }
    public static JSONObject productById(long id) {
        try (Cursor c = w().rawQuery("SELECT json FROM products WHERE id=?", new String[]{String.valueOf(id)})) { return c.moveToFirst() ? withBatches(c.getString(0)) : null; }
    }
    /** product json + "batches": [active batches with stock, FEFO order] + available_qty. */
    private static JSONObject withBatches(String json) { return withBatches(json, true); }
    /** v3.5.4 — {@code loadBatches} false skips the per-row batch query entirely. A
     *  shop with no stock has nothing to look up, and the old code paid one query per
     *  result row regardless: 60 wasted round-trips for one page of the product list. */
    private static JSONObject withBatches(String json, boolean loadBatches) {
        try {
            JSONObject p = new JSONObject(json); JSONArray bs = new JSONArray(); double total = 0;
            if (loadBatches) {
                try (Cursor c = w().rawQuery("SELECT json, current_qty FROM batches WHERE product_id=? AND status='ACTIVE' AND current_qty>0 ORDER BY (expiry_date IS NULL), expiry_date, id", new String[]{String.valueOf(p.optLong("id"))})) {
                    while (c.moveToNext()) { JSONObject b = new JSONObject(c.getString(0)); b.put("batch_id", b.optLong("id")); if (!b.has("sell_price")) b.put("sell_price", b.optDouble("unit_sell_price", 0)); b.put("is_recommended", bs.length() == 0); bs.put(b); total += c.getDouble(1); }
                }
            }
            p.put("batches", bs); p.put("available_qty", total); p.put("product_id", p.optLong("id")); return p;
        } catch (Exception e) { return new JSONObject(); }
    }
    public static List<JSONObject> stockRows() { return stockRows("", false, 0); }
    /** v3.5.6 — bounded stock listing. The unbounded version returned all 13 570
     *  products and the inventory screen inflated a View per row on the UI thread,
     *  which is what hung the phone and then killed it. The search filter, the
     *  low-stock test, the stock value and the page cap now all happen in SQL, so the
     *  screen only ever builds what it can actually show and {@link Local} no longer
     *  runs one value query per product (13 571 round-trips for one call). */
    public static List<JSONObject> stockRows(String filter, boolean lowOnly, int limit) {
        List<JSONObject> out = new ArrayList<>();
        String f = norm(filter == null ? "" : filter);
        String qty = "IFNULL(SUM(CASE WHEN b.status='ACTIVE' THEN b.current_qty END),0)";
        StringBuilder sql = new StringBuilder(
            "SELECT p.id, p.name, p.barcode, p.min_stock_alert, " + qty + ","
            + " IFNULL(SUM(CASE WHEN b.status='ACTIVE' THEN b.current_qty*b.buy_price END),0)"
            + " FROM products p LEFT JOIN batches b ON b.product_id=p.id WHERE p.is_active=1");
        java.util.List<String> args = new ArrayList<>();
        if (!f.isEmpty()) { sql.append(" AND (p.name LIKE ? OR p.barcode LIKE ?)"); args.add("%" + f + "%"); args.add("%" + f + "%"); }
        sql.append(" GROUP BY p.id");
        // repeated rather than aliased: HAVING on a result alias is a SQLite
        // extension and must not be relied on across engine versions
        if (lowOnly) sql.append(" HAVING ").append(qty).append(" <= p.min_stock_alert");
        sql.append(" ORDER BY p.name");
        if (limit > 0) { sql.append(" LIMIT ?"); args.add(String.valueOf(limit)); }
        try (Cursor c = w().rawQuery(sql.toString(), args.toArray(new String[0]))) {
            while (c.moveToNext()) {
                JSONObject o = new JSONObject();
                try {
                    o.put("product_id", c.getLong(0)); o.put("name", c.getString(1)); o.put("barcode", c.getString(2));
                    o.put("min_stock_alert", c.getDouble(3)); o.put("total_stock", c.getDouble(4));
                    o.put("total_qty", c.getDouble(4)); o.put("value_at_cost", c.getDouble(5));
                } catch (Exception ignore) {}
                out.add(o);
            }
        }
        return out;
    }
    /** v3.5.6 — how many rows match, so a capped list can say what it is hiding. */
    public static int stockCount(String filter, boolean lowOnly) {
        String f = norm(filter == null ? "" : filter);
        String qty = "IFNULL(SUM(CASE WHEN b.status='ACTIVE' THEN b.current_qty END),0)";
        StringBuilder sql = new StringBuilder("SELECT COUNT(*) FROM (SELECT p.id, " + qty + " AS q, p.min_stock_alert"
            + " FROM products p LEFT JOIN batches b ON b.product_id=p.id WHERE p.is_active=1");
        java.util.List<String> args = new ArrayList<>();
        if (!f.isEmpty()) { sql.append(" AND (p.name LIKE ? OR p.barcode LIKE ?)"); args.add("%" + f + "%"); args.add("%" + f + "%"); }
        sql.append(" GROUP BY p.id");
        if (lowOnly) sql.append(" HAVING q <= p.min_stock_alert");
        sql.append(")");
        try (Cursor c = w().rawQuery(sql.toString(), args.toArray(new String[0]))) { return c.moveToFirst() ? c.getInt(0) : 0; }
        catch (Exception e) { return 0; }
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
        try (Cursor c = w().rawQuery("SELECT COUNT(*), IFNULL(SUM(total),0), (SELECT COUNT(*) FROM invoices WHERE synced=0) FROM invoices WHERE at>=? AND at<?", new String[]{day, day + "T99"})) { return c.moveToFirst() ? new double[]{c.getDouble(0), c.getDouble(1), c.getDouble(2)} : new double[]{0, 0, 0}; }
    }

    /** sales totals for the last 7 days (oldest first) — dashboard sparkline. */
    public static double[] weekSales() {
        double[] out = new double[7]; java.util.Calendar cal = java.util.Calendar.getInstance();
        for (int i = 6; i >= 0; i--) { String day = String.format(java.util.Locale.US, "%04d-%02d-%02d", cal.get(java.util.Calendar.YEAR), cal.get(java.util.Calendar.MONTH) + 1, cal.get(java.util.Calendar.DAY_OF_MONTH)); try (Cursor c = w().rawQuery("SELECT IFNULL(SUM(total),0) FROM invoices WHERE at>=? AND at<?", new String[]{day, day + "T99"})) { out[i] = c.moveToFirst() ? c.getDouble(0) : 0; } cal.add(java.util.Calendar.DAY_OF_MONTH, -1); }
        return out;
    }
    /** "name|qty" of today's best sellers (from local invoice JSON). */
    public static String[] topSellingToday(int n) {
        java.util.Map<String, Double> m = new java.util.HashMap<>(); String day = now().substring(0, 10);
        try (Cursor c = w().rawQuery("SELECT json FROM invoices WHERE at>=? AND at<?", new String[]{day, day + "T99"})) { while (c.moveToNext()) { try { JSONArray it = new JSONObject(c.getString(0)).optJSONArray("items"); for (int i = 0; it != null && i < it.length(); i++) { JSONObject x = it.optJSONObject(i); String k = x.optString("name"); m.put(k, (m.containsKey(k) ? m.get(k) : 0) + x.optDouble("quantity", 0)); } } catch (Exception ignore) {} } }
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
        for (char ch : s.trim().toCharArray()) { if (ch >= '۰' && ch <= '۹') b.append((char) ('0' + ch - '۰')); else if (ch >= '٠' && ch <= '٩') b.append((char) ('0' + ch - '٠')); else if (ch == 'ي') b.append('ی'); else if (ch == 'ك') b.append('ک'); else b.append(ch); }
        return b.toString();
    }
}
