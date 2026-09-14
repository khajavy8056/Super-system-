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

    /** Wipe the phone's business tables and fill them from the attached PC file. Runs inside one transaction. */
    static JSONObject run(File pc) throws Exception {
        SQLiteDatabase d = Db.db();
        d.execSQL("ATTACH DATABASE ? AS pc", new Object[]{pc.getPath()});
        d.beginTransaction();
        try {
            for (String t : new String[]{"products", "batches", "customers", "invoices", "invoice_items", "movements", "ledger", "categories", "brands", "units",
                    "campaigns", "coupons", "expenses", "expense_categories", "suppliers", "cheques", "journal", "price_history", "cache", "ops", "conflicts", "ai_insights"})
                try { d.execSQL("DELETE FROM " + t); } catch (Exception ignore) {}
            // ---- catalogue ----
            d.execSQL("INSERT INTO units(id,name,symbol,allow_decimal,decimals,is_active) SELECT id,name,symbol,allow_decimal,decimals,is_active FROM pc.units");
            d.execSQL("INSERT INTO categories(id,name) SELECT id,name FROM pc.categories WHERE deleted_at IS NULL");
            d.execSQL("INSERT INTO brands(id,name) SELECT id,name FROM pc.brands WHERE deleted_at IS NULL");
            d.execSQL("INSERT INTO products(id,barcode,name,sku,unit_id,category_id,brand_id,min_stock_alert,image_url,is_active,is_local,json,updated_at) " +
                    "SELECT id,barcode,name,sku,unit_id,category_id,brand_id,IFNULL(min_stock_alert,0),image_url,is_active,1,'{}'," +
                    "IFNULL(updated_at,created_at) FROM pc.products WHERE deleted_at IS NULL");
            d.execSQL("INSERT INTO batches(id,product_id,batch_number,current_qty,sell_price,consumer_price,buy_price,expiry_date,status,is_local,json,updated_at,warehouse_id,quantity_received,received_at) " +
                    "SELECT id,product_id,batch_number,current_qty,sell_price,IFNULL(consumer_price,sell_price),buy_price,expiry_date,status,1,'{}'," +
                    "IFNULL(updated_at,created_at),IFNULL(warehouse_id,1),quantity_received,received_at FROM pc.product_batches");
            // ---- customers ----
            d.execSQL("INSERT INTO customers(id,name,last_name,phone,credit_limit,is_local,json,address) " +
                    "SELECT id,name,last_name,phone,IFNULL(credit_limit,0),1,'{}',address FROM pc.customers WHERE is_active=1");
            rebuildJson(d);
            // ---- sales ----  (phone invoices key on rowid; we keep the PC id as rowid so lines/returns line up)
            d.execSQL("INSERT INTO invoices(rowid,local_no,total,item_count,payment,at,synced,invoice_number,json,status,payment_status,customer_id,subtotal,discount,tax,user,coupon) " +
                    "SELECT i.id,i.invoice_number,i.total_amount,(SELECT COUNT(*) FROM pc.invoice_items x WHERE x.invoice_id=i.id),i.payment_method,replace(substr(i.created_at,1,19),' ','T'),1,i.invoice_number,'{}'," +
                    "CASE WHEN i.status='VOID' THEN 'VOID' ELSE 'PAID' END,CASE WHEN i.payment_status='ON_ACCOUNT' THEN 'PENDING' WHEN i.status='VOID' THEN 'VOID' ELSE 'PAID' END,i.customer_id,i.subtotal,IFNULL(i.discount,0)+IFNULL(i.invoice_discount,0),IFNULL(i.tax,0)," +
                    "(SELECT IFNULL(full_name,username) FROM pc.users u WHERE u.id=i.created_by),NULL FROM pc.invoices i");
            d.execSQL("INSERT INTO invoice_items(id,inv,product_id,batch_id,qty,unit_sell_price,unit_buy_price,discount,subtotal,returned_qty) " +
                    "SELECT ii.id,ii.invoice_id,ii.product_id,ii.batch_id,ii.qty,ii.unit_sell_price,ii.unit_buy_price,IFNULL(ii.discount,0),ii.subtotal," +
                    "IFNULL((SELECT SUM(r.qty) FROM pc.returns r WHERE r.invoice_item_id=ii.id AND r.status<>'REJECTED'),0) FROM pc.invoice_items ii");
            d.execSQL("INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,reason,user,created_at) " +
                    "SELECT product_id,batch_id,movement_type,quantity,reference_type,CAST(reference_id AS TEXT),note,(SELECT IFNULL(full_name,username) FROM pc.users u WHERE u.id=m.created_by),replace(substr(m.created_at,1,19),' ','T') FROM pc.stock_movements m");
            d.execSQL("INSERT INTO ledger(customer_id,entry_type,amount,note,ref,created_at) " +
                    "SELECT customer_id,entry_type,amount,note,CAST(invoice_id AS TEXT),replace(substr(created_at,1,19),' ','T') FROM pc.customer_ledger_entries");
            // ---- marketing ----
            d.execSQL("INSERT INTO campaigns(id,name,discount_type,discount_value,min_purchase,max_discount,valid_until,status,auto_issue_threshold,created_at) " +
                    "SELECT id,name,discount_type,discount_value,IFNULL(min_purchase,0),max_discount,valid_until,status,auto_issue_threshold,created_at FROM pc.campaigns");
            d.execSQL("INSERT INTO coupons(id,code,discount_type,discount_value,min_purchase,customer_phone,valid_until,usage_limit,used_count,status,created_at) " +
                    "SELECT c.id,c.code,c.discount_type,c.discount_value,IFNULL(c.min_purchase,0),IFNULL(c.customer_phone,(SELECT phone FROM pc.customers k WHERE k.id=c.customer_id)),c.valid_until,IFNULL(c.usage_limit,1),IFNULL(c.used_count,0),c.status,c.created_at FROM pc.coupons c");
            // ---- accounting side tables ----
            d.execSQL("INSERT INTO expense_categories(id,name) SELECT id,name FROM pc.acc_expense_categories");
            d.execSQL("INSERT INTO expenses(id,category_id,amount,description,paid_from,expense_date) SELECT id,category_id,amount,description,paid_from,expense_date FROM pc.acc_expenses");
            d.execSQL("INSERT INTO suppliers(id,name,phone,address,balance) SELECT id,name,phone,address,0 FROM pc.acc_suppliers WHERE is_active=1");
            d.execSQL("INSERT INTO cheques(id,direction,number,amount,due_date,bank_name,party_name,status,created_at) SELECT id,direction,number,amount,due_date,bank_name,party_name,status,created_at FROM pc.acc_cheques");
            // ---- journal: rebuilt in the phone's chart of accounts (sale / cogs / expense) ----
            rebuildJournal(d);
            // ---- users (bcrypt hashes cannot be verified on the phone → keep names, phone login stays with the local admin) ----
            try { d.execSQL("INSERT OR IGNORE INTO users(id,username,full_name,pass_hash,roles,is_active,created_at) SELECT id,username,full_name,'',?,is_active,created_at FROM pc.users WHERE username<>'admin'", new Object[]{"[\"Cashier\"]"}); } catch (Exception ignore) {}
            // ---- settings (store name, SMS templates, insights toggles …) ----
            d.execSQL("INSERT OR REPLACE INTO settings(k,v) SELECT key,value FROM pc.system_settings WHERE is_secret=0 AND key NOT LIKE 'network.%' AND key NOT LIKE 'update.%' AND key NOT LIKE 'printer.%'");
            // ---- AI insights history (measured effects) ----
            try {
                d.execSQL(Insights.DDL);
                d.execSQL("INSERT INTO ai_insights(id,kind,dedupe_key,title,body,priority,evidence,actions,expected_gain,metric,status,accepted_at,snoozed_until,baseline,result,measured_at,measured_gain,last_seen_at,narrative,created_at) " +
                        "SELECT id,kind,dedupe_key,title,body,priority,evidence,actions,expected_gain,metric,status,replace(substr(accepted_at,1,19),' ','T'),snoozed_until,baseline,result,measured_at,measured_gain,replace(substr(last_seen_at,1,19),' ','T'),narrative,replace(substr(created_at,1,19),' ','T') FROM pc.ai_insights");
            } catch (Exception ignore) {}
            // counters so new local rows never collide with imported ids
            for (String[] c : new String[][]{{"pid", "products"}, {"bid", "batches"}, {"cid", "customers"}}) {
                try (Cursor cu = d.rawQuery("SELECT IFNULL(MAX(id),0) FROM " + c[1], null)) { cu.moveToFirst(); Db.kv(c[0], String.valueOf(Math.max(cu.getLong(0), 0))); }
            }
            try (Cursor cu = d.rawQuery("SELECT COUNT(*) FROM invoices", null)) { cu.moveToFirst(); Db.kv("inv_no", String.valueOf(cu.getLong(0))); }
            d.setTransactionSuccessful();
        } finally {
            d.endTransaction();
            try { d.execSQL("DETACH DATABASE pc"); } catch (Exception ignore) {}
        }
        JSONObject out = new JSONObject();
        for (String t : new String[]{"products", "batches", "customers", "invoices", "invoice_items", "movements", "expenses", "cheques", "ai_insights"}) out.put(t, Local.count(t));
        return out;
    }


    /** Fill the per-row JSON snapshots the phone screens read (small tables; done in Java so no json1 dependency). */
    private static void rebuildJson(SQLiteDatabase d) throws Exception {
        for (JSONObject p : Local.rows("SELECT id,barcode,name,sku,unit_id,category_id,brand_id,min_stock_alert,image_url,is_active FROM products")) { p.put("is_active", p.optInt("is_active") == 1); p.put("_local", true); d.execSQL("UPDATE products SET json=? WHERE id=?", new Object[]{p.toString(), p.optLong("id")}); }
        for (JSONObject b : Local.rows("SELECT id,product_id,batch_number,current_qty,sell_price,consumer_price,buy_price,expiry_date,status,quantity_received,received_at FROM batches")) d.execSQL("UPDATE batches SET json=? WHERE id=?", new Object[]{b.toString(), b.optLong("id")});
        for (JSONObject c : Local.rows("SELECT id,name,last_name,phone,address,credit_limit FROM customers")) { c.put("_local", true); d.execSQL("UPDATE customers SET json=? WHERE id=?", new Object[]{c.toString(), c.optLong("id")}); }
    }
    private static String line(String code, double debit, double credit) {
        return "{\"code\":\"" + code + "\",\"name\":\"" + Local.accName(code) + "\",\"debit\":" + debit + ",\"credit\":" + credit + "}";
    }
    private static void rebuildJournal(SQLiteDatabase d) {
        android.database.sqlite.SQLiteStatement st = d.compileStatement("INSERT INTO journal(number,date,description,kind,status,total,lines,ref) VALUES(?,?,?,?,?,?,?,?)");
        int n = 0;
        try (Cursor c = d.rawQuery("SELECT i.id,i.invoice_number,replace(substr(i.created_at,1,19),' ','T'),i.total_amount,i.payment_method,i.status," +
                "IFNULL((SELECT SUM(qty*unit_buy_price) FROM pc.invoice_items x WHERE x.invoice_id=i.id),0) FROM pc.invoices i ORDER BY i.id", null)) {
            while (c.moveToNext()) {
                double total = c.getDouble(3), cogs = c.getDouble(6); String pm = c.getString(4) == null ? "CASH" : c.getString(4);
                String cash = "CARD".equals(pm) ? "1030" : ("ACCOUNT".equals(pm) || "CREDIT".equals(pm)) ? "1100" : "1010";
                String lines = "[" + line(cash, total, 0) + "," + line("4000", 0, total) + (cogs > 0 ? "," + line("5000", cogs, 0) + "," + line("1200", 0, cogs) : "") + "]";
                st.clearBindings(); st.bindLong(1, ++n); st.bindString(2, c.getString(2)); st.bindString(3, "فروش " + c.getString(1)); st.bindString(4, "SALE");
                st.bindString(5, "VOID".equals(c.getString(5)) ? "REVERSED" : "POSTED"); st.bindDouble(6, total); st.bindString(7, lines); st.bindString(8, c.getString(1)); st.executeInsert();
            }
        }
        try (Cursor c = d.rawQuery("SELECT id,expense_date,IFNULL(description,'هزینه'),amount,IFNULL(paid_from,'CASH') FROM pc.acc_expenses ORDER BY id", null)) {
            while (c.moveToNext()) {
                double amt = c.getDouble(3); String pf = c.getString(4); String acc = "BANK".equals(pf) ? "1020" : "CARD".equals(pf) ? "1030" : "1010";
                st.clearBindings(); st.bindLong(1, ++n); st.bindString(2, c.getString(1) + "T09:00:00"); st.bindString(3, c.getString(2)); st.bindString(4, "EXPENSE"); st.bindString(5, "POSTED");
                st.bindDouble(6, amt); st.bindString(7, "[" + line("6000", amt, 0) + "," + line(acc, 0, amt) + "]"); st.bindString(8, "EXP-" + c.getLong(0)); st.executeInsert();
            }
        }
        st.close();
    }
}
