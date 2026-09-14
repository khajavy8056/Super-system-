package ir.khajavy.supermarket;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import org.json.JSONObject;

import java.io.File;

/**
 * v3.1 — import a <b>Windows</b> backup (the PC SQLite schema: products / product_batches / invoices /
 * invoice_items / customers / acc_* …) into the phone's own schema, so the same file restores on both
 * platforms (the bundled one-year demo store included).
 *
 * The PC file is attached to the phone database with {@code ATTACH DATABASE} and copied table by
 * table with plain SQL — no per-row Java objects, so 40 k invoices / 140 k lines import in seconds.
 * Everything the phone knows how to show is carried over: catalogue, batches, customers, invoices +
 * lines, stock movements, customer ledger, expenses, cheques, suppliers, campaigns, coupons, users,
 * settings, the AI insights history (so the measured profit effects are visible right away), and a
 * journal rebuilt from the invoices/expenses so the accounting screens are populated.
 */
final class PcImport {
    private PcImport() {}

    /** True when the file looks like a Windows backup (PC schema) rather than a phone one. */
    static boolean isPcBackup(File f) {
        SQLiteDatabase d = null;
        try {
            d = SQLiteDatabase.openDatabase(f.getPath(), null, SQLiteDatabase.OPEN_READONLY);
            return tables(d, "product_batches", "invoice_items", "products", "invoices") == 4;
        } catch (Exception e) { return false; } finally { if (d != null) d.close(); }
    }
    static boolean isPhoneBackup(File f) {
        SQLiteDatabase d = null;
        try {
            d = SQLiteDatabase.openDatabase(f.getPath(), null, SQLiteDatabase.OPEN_READONLY);
            return tables(d, "products", "invoices", "batches") == 3;
        } catch (Exception e) { return false; } finally { if (d != null) d.close(); }
    }
    private static int tables(SQLiteDatabase d, String... names) {
        StringBuilder in = new StringBuilder(); for (String n : names) in.append(in.length() == 0 ? "'" : ",'").append(n).append("'");
        try (Cursor c = d.rawQuery("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN (" + in + ")", null)) { c.moveToFirst(); return c.getInt(0); }
    }

    /** Progress sink (message + 0..100). */
    interface Progress { void at(int pct, String msg); }

    /**
     * v3.3 — the import builds a <b>fresh</b> database file next to the live one and swaps it in only when
     * everything succeeded. The live database is never half-wiped, a crash / OOM / power loss mid-way leaves
     * the current data untouched, and the UI keeps working while the import runs (WAL readers don't block).
     * All heavy work (per-row JSON snapshots, journal + posting lines, COGS) is done in SQL — no per-row Java
     * objects — so a year of a busy store (40 k invoices / 120 k lines / 125 k movements) lands in seconds.
     */
    static JSONObject run(android.content.Context ctx, File pc, Progress pr) throws Exception {
        File fresh = new File(ctx.getCacheDir(), "import-" + System.currentTimeMillis() + ".db"); fresh.delete();
        File live = Db.file(ctx); JSONObject out = new JSONObject();
        SQLiteDatabase d = null;
        try {
            pr.at(2, "ساخت پایگاه دادهٔ جدید…");
            d = SQLiteDatabase.openOrCreateDatabase(fresh, null);
            d.execSQL("PRAGMA journal_mode=OFF"); d.execSQL("PRAGMA synchronous=OFF"); d.execSQL("PRAGMA temp_store=MEMORY"); d.execSQL("PRAGMA cache_size=-16000");
            Db.schema(d);
            // ---- carry over what a Windows backup does not contain: device settings, license/kv, local users, bank, audit … ----
            d.execSQL("ATTACH DATABASE ? AS cur", new Object[]{live.getPath()});
            for (String t : new String[]{"kv", "settings", "users", "bank", "warehouses", "locations", "audit", "cash_sessions", "stocktakes", "stocktake_items"})
                try { d.execSQL("INSERT OR REPLACE INTO " + t + " SELECT * FROM cur." + t); } catch (Exception ignore) {}
            d.execSQL("DETACH DATABASE cur");
            d.execSQL("ATTACH DATABASE ? AS pc", new Object[]{pc.getPath()});
            pr.at(8, "کالاها و بچ‌ها…");
            tx(d, "DELETE FROM units", "DELETE FROM categories", "DELETE FROM brands", "INSERT INTO units(id,name,symbol,allow_decimal,decimals,is_active) SELECT id,name,symbol,allow_decimal,decimals,is_active FROM pc.units",
                  "INSERT INTO categories(id,name) SELECT id,name FROM pc.categories WHERE deleted_at IS NULL",
                  "INSERT INTO brands(id,name) SELECT id,name FROM pc.brands WHERE deleted_at IS NULL",
                  "INSERT INTO products(id,barcode,name,sku,unit_id,category_id,brand_id,min_stock_alert,image_url,is_active,is_local,json,updated_at) " +
                    "SELECT id,barcode,name,sku,unit_id,category_id,brand_id,IFNULL(min_stock_alert,0),image_url,is_active,1,'{}',IFNULL(updated_at,created_at) FROM pc.products WHERE deleted_at IS NULL",
                  "INSERT INTO batches(id,product_id,batch_number,current_qty,sell_price,consumer_price,buy_price,expiry_date,status,is_local,json,updated_at,warehouse_id,quantity_received,received_at) " +
                    "SELECT id,product_id,batch_number,current_qty,sell_price,IFNULL(consumer_price,sell_price),buy_price,expiry_date,status,1,'{}',IFNULL(updated_at,created_at),IFNULL(warehouse_id,1),quantity_received,received_at FROM pc.product_batches",
                  "INSERT INTO customers(id,name,last_name,phone,credit_limit,is_local,json,address) SELECT id,name,last_name,phone,IFNULL(credit_limit,0),1,'{}',address FROM pc.customers WHERE is_active=1");
            pr.at(18, "تصاویر دادهٔ کالاها…");
            rebuildJson(d);
            pr.at(30, "فاکتورها…");
            tx(d, "CREATE TEMP TABLE ic AS SELECT invoice_id, COUNT(*) AS n FROM pc.invoice_items GROUP BY invoice_id", "CREATE INDEX temp.ix_ic ON ic(invoice_id)",
                  "CREATE TEMP TABLE un AS SELECT id, IFNULL(full_name,username) AS nm FROM pc.users", "CREATE INDEX temp.ix_un ON un(id)",
                  "INSERT INTO invoices(rowid,local_no,total,item_count,payment,at,synced,invoice_number,json,status,payment_status,customer_id,subtotal,discount,tax,user,coupon) " +
                    "SELECT i.id,i.invoice_number,i.total_amount,IFNULL((SELECT n FROM ic WHERE ic.invoice_id=i.id),0),i.payment_method,replace(substr(i.created_at,1,19),' ','T'),1,i.invoice_number,'{}'," +
                    "CASE WHEN i.status='VOID' THEN 'VOID' ELSE 'PAID' END,CASE WHEN i.payment_status='ON_ACCOUNT' THEN 'PENDING' WHEN i.status='VOID' THEN 'VOID' ELSE 'PAID' END,i.customer_id,i.subtotal,IFNULL(i.discount,0)+IFNULL(i.invoice_discount,0),IFNULL(i.tax,0)," +
                    "(SELECT nm FROM un WHERE un.id=i.created_by),NULL FROM pc.invoices i");
            pr.at(42, "اقلام فاکتور…");
            tx(d, "CREATE TEMP TABLE rq AS SELECT invoice_item_id, SUM(qty) AS q FROM pc.returns WHERE status<>'REJECTED' GROUP BY invoice_item_id", "CREATE INDEX temp.ix_rq ON rq(invoice_item_id)",
                  "INSERT INTO invoice_items(id,inv,product_id,batch_id,qty,unit_sell_price,unit_buy_price,discount,subtotal,returned_qty) " +
                    "SELECT ii.id,ii.invoice_id,ii.product_id,ii.batch_id,ii.qty,ii.unit_sell_price,ii.unit_buy_price,IFNULL(ii.discount,0),ii.subtotal,IFNULL((SELECT q FROM rq WHERE rq.invoice_item_id=ii.id),0) FROM pc.invoice_items ii");
            pr.at(55, "گردش انبار و دفتر مشتریان…");
            tx(d, "INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,reason,user,created_at) " +
                    "SELECT product_id,batch_id,movement_type,quantity,reference_type,CAST(reference_id AS TEXT),note,(SELECT nm FROM un WHERE un.id=m.created_by),replace(substr(m.created_at,1,19),' ','T') FROM pc.stock_movements m",
                  "INSERT INTO ledger(customer_id,entry_type,amount,note,ref,created_at) SELECT customer_id,entry_type,amount,note,CAST(invoice_id AS TEXT),replace(substr(created_at,1,19),' ','T') FROM pc.customer_ledger_entries");
            pr.at(66, "بازاریابی و حسابداری…");
            tx(d, "INSERT INTO campaigns(id,name,discount_type,discount_value,min_purchase,max_discount,valid_until,status,auto_issue_threshold,created_at) " +
                    "SELECT id,name,discount_type,discount_value,IFNULL(min_purchase,0),max_discount,valid_until,status,auto_issue_threshold,created_at FROM pc.campaigns",
                  "INSERT INTO coupons(id,code,discount_type,discount_value,min_purchase,customer_phone,valid_until,usage_limit,used_count,status,created_at) " +
                    "SELECT c.id,c.code,c.discount_type,c.discount_value,IFNULL(c.min_purchase,0),IFNULL(c.customer_phone,(SELECT phone FROM pc.customers k WHERE k.id=c.customer_id)),c.valid_until,IFNULL(c.usage_limit,1),IFNULL(c.used_count,0),c.status,c.created_at FROM pc.coupons c",
                  "DELETE FROM expense_categories", "INSERT INTO expense_categories(id,name) SELECT id,name FROM pc.acc_expense_categories",
                  "INSERT INTO expenses(id,category_id,amount,description,paid_from,expense_date) SELECT id,category_id,amount,description,paid_from,expense_date FROM pc.acc_expenses",
                  "INSERT INTO suppliers(id,name,phone,address,balance) SELECT id,name,phone,address,0 FROM pc.acc_suppliers WHERE is_active=1",
                  "INSERT INTO cheques(id,direction,number,amount,due_date,bank_name,party_name,status,created_at) SELECT id,direction,number,amount,due_date,bank_name,party_name,status,created_at FROM pc.acc_cheques");
            pr.at(74, "دفتر روزنامه…");
            rebuildJournal(d);
            pr.at(86, "کاربران، تنظیمات و هوش فروشگاه…");
            try { d.execSQL("INSERT OR IGNORE INTO users(id,username,full_name,pass_hash,roles,is_active,created_at) SELECT id,username,full_name,'',?,is_active,created_at FROM pc.users WHERE username<>'admin'", new Object[]{"[\"Cashier\"]"}); } catch (Exception ignore) {}
            try { d.execSQL("INSERT OR REPLACE INTO settings(k,v) SELECT key,value FROM pc.system_settings WHERE is_secret=0 AND key NOT LIKE 'network.%' AND key NOT LIKE 'update.%' AND key NOT LIKE 'printer.%'"); } catch (Exception ignore) {}
            try {
                d.execSQL("INSERT INTO ai_insights(id,kind,dedupe_key,title,body,priority,evidence,actions,expected_gain,metric,status,accepted_at,snoozed_until,baseline,result,measured_at,measured_gain,last_seen_at,narrative,created_at) " +
                        "SELECT id,kind,dedupe_key,title,body,priority,evidence,actions,expected_gain,metric,status,replace(substr(accepted_at,1,19),' ','T'),snoozed_until,baseline,result,measured_at,measured_gain,replace(substr(last_seen_at,1,19),' ','T'),narrative,replace(substr(created_at,1,19),' ','T') FROM pc.ai_insights");
            } catch (Exception ignore) {}
            // counters so new local rows never collide with imported ids; cache/ops/conflicts start empty
            for (String[] c : new String[][]{{"pid", "products"}, {"bid", "batches"}, {"cid", "customers"}, {"inv_no", "invoices"}}) {
                try (Cursor cu = d.rawQuery("SELECT IFNULL(MAX(" + ("inv_no".equals(c[0]) ? "rowid" : "id") + "),0) FROM " + c[1], null)) { cu.moveToFirst(); d.execSQL("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", new Object[]{c[0], String.valueOf(Math.max(cu.getLong(0), 0))}); }
            }
            d.execSQL("INSERT OR REPLACE INTO kv(k,v) VALUES('cursor',NULL)");
            d.execSQL("DETACH DATABASE pc");
            for (String t : new String[]{"products", "batches", "customers", "invoices", "invoice_items", "movements", "expenses", "cheques", "ai_insights", "journal"}) try (Cursor cu = d.rawQuery("SELECT COUNT(*) FROM " + t, null)) { cu.moveToFirst(); out.put(t, cu.getLong(0)); }
            pr.at(94, "بهینه‌سازی نمایه‌ها…");
            d.execSQL("ANALYZE"); d.execSQL("PRAGMA journal_mode=DELETE");
            d.close(); d = null;
            // ---- atomic swap ----
            pr.at(97, "جایگزینی پایگاه داده…");
            Db.swapping = true;
            try {
                Db.shutdown();
                for (String sfx : new String[]{"", "-wal", "-shm", "-journal"}) new File(live.getPath() + sfx).delete();
                if (!fresh.renameTo(live)) { copy(fresh, live); fresh.delete(); }
            } finally { Db.swapping = false; }
            Db.db();   // reopen → onOpen(): DDL/indexes are idempotent
            pr.at(100, "انجام شد");
            return out;
        } catch (Throwable e) {
            if (d != null) try { d.close(); } catch (Exception ignore) {}
            fresh.delete();
            throw new Exception(e instanceof OutOfMemoryError ? "حافظهٔ گوشی برای این فایل کافی نبود" : String.valueOf(e.getMessage()));
        }
    }
    /** run every statement in ONE transaction (each call is a bounded chunk of the import) */
    private static void tx(SQLiteDatabase d, String... sql) {
        d.beginTransaction(); try { for (String q : sql) d.execSQL(q); d.setTransactionSuccessful(); } finally { d.endTransaction(); }
    }
    private static void copy(File a, File b) throws java.io.IOException {
        try (java.io.InputStream in = new java.io.FileInputStream(a); java.io.OutputStream os = new java.io.FileOutputStream(b)) { byte[] buf = new byte[1 << 16]; int n; while ((n = in.read(buf)) > 0) os.write(buf, 0, n); }
    }

    /** Per-row JSON snapshots the phone screens read — built in SQL with json_object (Android's SQLite ships JSON1);
     *  falls back to a streamed Java loop with compiled statements if JSON1 is unavailable. */
    private static void rebuildJson(SQLiteDatabase d) throws Exception {
        try {
            tx(d, "UPDATE products SET json=json_object('id',id,'barcode',barcode,'name',name,'sku',sku,'unit_id',unit_id,'category_id',category_id,'brand_id',brand_id,'min_stock_alert',min_stock_alert,'image_url',image_url,'is_active',json(CASE WHEN is_active=1 THEN 'true' ELSE 'false' END),'_local',json('true'))",
                  "UPDATE batches SET json=json_object('id',id,'product_id',product_id,'batch_number',batch_number,'current_qty',current_qty,'sell_price',sell_price,'consumer_price',consumer_price,'buy_price',buy_price,'expiry_date',expiry_date,'status',status,'quantity_received',quantity_received,'received_at',received_at)",
                  "UPDATE customers SET json=json_object('id',id,'name',name,'last_name',last_name,'phone',phone,'address',address,'credit_limit',credit_limit,'_local',json('true'))");
            return;
        } catch (Exception noJson1) { /* fall through */ }
        android.database.sqlite.SQLiteStatement up = d.compileStatement("UPDATE products SET json=? WHERE id=?");
        d.beginTransaction();
        try (Cursor c = d.rawQuery("SELECT id,barcode,name,sku,unit_id,category_id,brand_id,min_stock_alert,image_url,is_active FROM products", null)) {
            while (c.moveToNext()) { JSONObject p = row(c); p.put("is_active", c.getInt(9) == 1); p.put("_local", true); up.clearBindings(); up.bindString(1, p.toString()); up.bindLong(2, c.getLong(0)); up.execute(); }
            d.setTransactionSuccessful();
        } finally { d.endTransaction(); up.close(); }
        up = d.compileStatement("UPDATE batches SET json=? WHERE id=?");
        d.beginTransaction();
        try (Cursor c = d.rawQuery("SELECT id,product_id,batch_number,current_qty,sell_price,consumer_price,buy_price,expiry_date,status,quantity_received,received_at FROM batches", null)) {
            while (c.moveToNext()) { up.clearBindings(); up.bindString(1, row(c).toString()); up.bindLong(2, c.getLong(0)); up.execute(); }
            d.setTransactionSuccessful();
        } finally { d.endTransaction(); up.close(); }
        up = d.compileStatement("UPDATE customers SET json=? WHERE id=?");
        d.beginTransaction();
        try (Cursor c = d.rawQuery("SELECT id,name,last_name,phone,address,credit_limit FROM customers", null)) {
            while (c.moveToNext()) { JSONObject o = row(c); o.put("_local", true); up.clearBindings(); up.bindString(1, o.toString()); up.bindLong(2, c.getLong(0)); up.execute(); }
            d.setTransactionSuccessful();
        } finally { d.endTransaction(); up.close(); }
    }
    private static JSONObject row(Cursor c) throws Exception {
        JSONObject o = new JSONObject(); String[] cols = c.getColumnNames();
        for (int i = 0; i < cols.length; i++) switch (c.getType(i)) { case Cursor.FIELD_TYPE_NULL: o.put(cols[i], JSONObject.NULL); break; case Cursor.FIELD_TYPE_INTEGER: o.put(cols[i], c.getLong(i)); break; case Cursor.FIELD_TYPE_FLOAT: o.put(cols[i], c.getDouble(i)); break; default: o.put(cols[i], c.getString(i)); }
        return o;
    }
    private static String ln(String code, String debitExpr, String creditExpr) {
        return "'{\"code\":\"" + code + "\",\"name\":\"' || '" + Local.accName(code).replace("'", "''") + "' || '\",\"debit\":' || (" + debitExpr + ") || ',\"credit\":' || (" + creditExpr + ") || '}'";
    }
    /** Journal (phone chart of accounts: sale / COGS / expense) + journal_lines — pure SQL, COGS pre-aggregated once. */
    private static void rebuildJournal(SQLiteDatabase d) {
        String acc = "CASE WHEN i.payment_method='CARD' THEN '1030' WHEN i.payment_method IN ('ACCOUNT','CREDIT') THEN '1100' ELSE '1010' END";
        tx(d, "CREATE TEMP TABLE cg AS SELECT invoice_id, SUM(qty*unit_buy_price) AS c FROM pc.invoice_items GROUP BY invoice_id", "CREATE INDEX temp.ix_cg ON cg(invoice_id)",
              "CREATE TEMP TABLE js AS SELECT i.id AS iid, i.invoice_number AS no, replace(substr(i.created_at,1,19),' ','T') AS at, IFNULL(i.total_amount,0)*1.0 AS total, IFNULL((SELECT c FROM cg WHERE cg.invoice_id=i.id),0)*1.0 AS cogs, " + acc + " AS acc, CASE WHEN i.status='VOID' THEN 'REVERSED' ELSE 'POSTED' END AS st FROM pc.invoices i ORDER BY i.id",
              "INSERT INTO journal(id,number,date,description,kind,status,total,lines,ref) SELECT iid, iid, at, 'فروش ' || no, 'SALE', st, total, " +
                "'[' || CASE WHEN acc='1030' THEN " + ln("1030", "total", "0") + " WHEN acc='1100' THEN " + ln("1100", "total", "0") + " ELSE " + ln("1010", "total", "0") + " END || ',' || " + ln("4000", "0", "total") +
                " || CASE WHEN cogs>0 THEN ',' || " + ln("5000", "cogs", "0") + " || ',' || " + ln("1200", "0", "cogs") + " ELSE '' END || ']', no FROM js",
              "INSERT INTO journal_lines(jid,code,debit,credit) SELECT iid, acc, total, 0 FROM js",
              "INSERT INTO journal_lines(jid,code,debit,credit) SELECT iid, '4000', 0, total FROM js",
              "INSERT INTO journal_lines(jid,code,debit,credit) SELECT iid, '5000', cogs, 0 FROM js WHERE cogs>0",
              "INSERT INTO journal_lines(jid,code,debit,credit) SELECT iid, '1200', 0, cogs FROM js WHERE cogs>0",
              "CREATE TEMP TABLE ex AS SELECT (SELECT IFNULL(MAX(id),0) FROM journal) + e.id AS jid, e.id AS eid, IFNULL(e.expense_date,'') || 'T09:00:00' AS at, IFNULL(e.description,'هزینه') AS ds, IFNULL(e.amount,0)*1.0 AS amt, CASE WHEN e.paid_from='BANK' THEN '1020' WHEN e.paid_from='CARD' THEN '1030' ELSE '1010' END AS acc FROM pc.acc_expenses e",
              "INSERT INTO journal(id,number,date,description,kind,status,total,lines,ref) SELECT jid, jid, at, ds, 'EXPENSE', 'POSTED', amt, '[' || " + ln("6000", "amt", "0") + " || ',' || CASE WHEN acc='1020' THEN " + ln("1020", "0", "amt") + " WHEN acc='1030' THEN " + ln("1030", "0", "amt") + " ELSE " + ln("1010", "0", "amt") + " END || ']', 'EXP-' || eid FROM ex",
              "INSERT INTO journal_lines(jid,code,debit,credit) SELECT jid, '6000', amt, 0 FROM ex",
              "INSERT INTO journal_lines(jid,code,debit,credit) SELECT jid, acc, 0, amt FROM ex",
              "DROP TABLE cg", "DROP TABLE js", "DROP TABLE ex", "DROP TABLE ic", "DROP TABLE un", "DROP TABLE rq");
    }
}
