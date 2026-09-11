package ir.khajavy.supermarket;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * v2.4 — the phone's OWN API. In standalone mode every request the screens make
 * (the same paths as the Windows backend) is answered here from the phone's SQLite,
 * so no section depends on a PC. Connecting a PC is optional (sync only).
 *
 * Contract: {@link #handle(String, String, String)} returns the same JSON shapes
 * the Windows API returns for that path, or throws {@link Api.ApiError}.
 */
public final class Local {
    private Local() {}

    /* ===================== dispatch ===================== */
    public static Object handle(String method, String rawPath, String body) throws Api.ApiError {
        String path = rawPath, qs = "";
        int qi = rawPath.indexOf('?'); if (qi >= 0) { path = rawPath.substring(0, qi); qs = rawPath.substring(qi + 1); }
        if (path.endsWith("/") && path.length() > 1) path = path.substring(0, path.length() - 1);
        JSONObject b = new JSONObject(); try { if (body != null && body.trim().startsWith("{")) b = new JSONObject(body); } catch (Exception ignore) {}
        JSONObject q = query(qs);
        String[] seg = path.startsWith("/") ? path.substring(1).split("/") : path.split("/");
        try {
            switch (seg[0]) {
                case "health": return obj("status", "ok", "mode", "standalone");
                case "auth": return auth(method, seg, body);
                case "settings": return settings(method, seg, b);
                case "reports": return reports(seg, q);
                case "pos": return pos(method, seg, q, b);
                case "invoices": return invoices(method, seg, q, b);
                case "returns": return returns(b);
                case "customers": return customers(method, seg, q, b);
                case "marketing": return marketing(method, seg, b);
                case "units": return units(method, b);
                case "products": return products(method, seg, b);
                case "barcode": throw new Api.ApiError(404, "STANDALONE", "جست‌وجوی منابع بارکد فقط با رایانه/اینترنت در دسترس است");
                case "prices": return priceHistory(seg);
                case "inventory": return inventory(method, seg, b);
                case "warehouses": return warehouses(method, seg, b);
                case "accounting": return accounting(method, seg, q, b);
                case "users": return users(method, seg, b);
                case "audit": return audit(q);
                case "hardware": return hardware(method, seg, b);
                case "diagnostics": return diagnostics(method, seg, q);
                case "system": return obj("status", "ok", "message", "نسخهٔ گوشی " + Version.NAME + " — به‌روزرسانی از GitHub Releases", "current_version", Version.NAME);
                case "sms": return sms(method, seg, b);
                case "mobile": if ("devices".equals(seg[1])) return new JSONArray(); break;
                case "cloud": return obj("provider_label", "Google Drive", "configured", CloudSync.available(), "connected", CloudSync.available(), "account", CloudSync.account());
                case "setup": return obj("status", Lic.allowed() ? "ACTIVE" : "EXPIRED", "type", Prefs.get("lic_type", "گوشی"), "expires", Lic.expires(), "key_masked", Lic.masked(), "hwid", Lic.hwid());
                case "support": return support(method, seg, b);
            }
        } catch (Api.ApiError e) { throw e;
        } catch (Exception e) { throw new Api.ApiError(500, "LOCAL", "خطای داخلی گوشی: " + e.getMessage()); }
        throw new Api.ApiError(404, "NOT_FOUND", "این بخش روی گوشی در دسترس نیست: " + path);
    }

    /* ===================== auth / users / roles ===================== */
    static final String[] PERMS = {"products.manage", "products.view", "batches.manage", "inventory.adjust", "inventory.stocktake", "inventory.approve_stocktake", "inventory.view", "pricing.manage", "pricing.view_cost", "pos.sell", "pos.void_unpaid", "pos.void_paid", "pos.return", "customers.manage", "customers.ledger", "customers.settle", "reports.view", "accounting.view", "accounting.post", "accounting.close", "settings.manage", "users.manage", "audit.view"};
    static final String[][] ROLES = {
        {"Administrator", "مدیر سیستم", "*"},
        {"Manager", "مدیر فروشگاه", "products.manage,products.view,batches.manage,inventory.adjust,inventory.stocktake,inventory.approve_stocktake,inventory.view,pricing.manage,pricing.view_cost,pos.sell,pos.void_unpaid,pos.void_paid,pos.return,customers.manage,customers.ledger,customers.settle,reports.view,settings.manage,audit.view,accounting.view,accounting.post,accounting.close"},
        {"Cashier", "صندوق‌دار", "products.view,inventory.view,pos.sell,pos.void_unpaid,customers.manage,customers.ledger,customers.settle,reports.view"},
        {"Inventory Operator", "انباردار", "products.view,batches.manage,inventory.adjust,inventory.stocktake,inventory.view,pricing.view_cost,reports.view"},
        {"Viewer", "ناظر", "products.view,inventory.view,reports.view"}};
    static JSONArray permsFor(JSONArray roles) {
        java.util.LinkedHashSet<String> out = new java.util.LinkedHashSet<>();
        for (int i = 0; roles != null && i < roles.length(); i++) for (String[] r : ROLES) if (r[0].equals(roles.optString(i))) { if ("*".equals(r[2])) out.addAll(java.util.Arrays.asList(PERMS)); else out.addAll(java.util.Arrays.asList(r[2].split(","))); }
        return new JSONArray(out);
    }
    static String sha(String s) { try { java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256"); byte[] d = md.digest(s.getBytes("UTF-8")); StringBuilder sb = new StringBuilder(); for (byte x : d) sb.append(String.format("%02x", x)); return "sha:" + sb; } catch (Exception e) { return "plain:" + s; } }
    /** the admin created by the wizard becomes users row #1 the first time anyone asks. */
    static void seedUsers() {
        if (count("users") > 0) return;
        try { JSONObject u = new JSONObject(Prefs.get("user_json", "{}")); String un = u.optString("username", "admin"); if (un.isEmpty()) un = "admin";
            exec("INSERT INTO users(username,full_name,pass_hash,roles,is_active,created_at) VALUES(?,?,?,?,1,?)", un, u.optString("full_name", "مدیر"), Prefs.get("local_admin_hash", ""), "[\"Administrator\"]", Db.now()); } catch (Exception ignore) {}
    }
    static boolean passOk(JSONObject u, String username, String pass) {
        String h = u.optString("pass_hash", ""); if (h.startsWith("sha:")) return h.equals(sha(username + "|" + pass));
        return h.equals(Lic.hwid() + ":" + Integer.toHexString((username + "|" + pass).hashCode()));   // wizard-era hash
    }
    static JSONObject userOut(JSONObject u) throws Exception { JSONArray roles = new JSONArray(u.optString("roles", "[]")); JSONObject o = new JSONObject(); o.put("id", u.optLong("id")); o.put("username", u.optString("username")); o.put("full_name", u.optString("full_name")); o.put("roles", roles); o.put("permissions", permsFor(roles)); o.put("is_active", u.optInt("is_active", 1) == 1); return o; }
    static Object auth(String method, String[] seg, String body) throws Exception {
        seedUsers();
        if ("login".equals(seg[1])) {
            String un = "", pw = ""; for (String kv : (body == null ? "" : body).split("&")) { int e = kv.indexOf('='); if (e < 0) continue; String k = kv.substring(0, e), v = java.net.URLDecoder.decode(kv.substring(e + 1), "UTF-8"); if ("username".equals(k)) un = v; if ("password".equals(k)) pw = v; }
            JSONObject u = one("SELECT * FROM users WHERE username=?", un);
            if (u == null || u.optInt("is_active", 1) == 0 || !passOk(u, un, pw)) { audit("LOGIN_FAILED", "User", un, null, null); throw new Api.ApiError(401, "AUTH", "نام کاربری یا رمز اشتباه است"); }
            Prefs.set("user_json", userOut(u).toString()); audit("LOGIN", "User", un, null, null);
            return obj("access_token", "local-" + u.optLong("id") + "-" + System.currentTimeMillis(), "token_type", "bearer");
        }
        if ("me".equals(seg[1])) { JSONObject cur = new JSONObject(Prefs.get("user_json", "{}")); JSONObject u = one("SELECT * FROM users WHERE username=?", cur.optString("username")); return u == null ? cur : userOut(u); }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    static Object users(String method, String[] seg, JSONObject b) throws Exception {
        seedUsers();
        if (seg.length > 1 && "roles".equals(seg[1])) { JSONArray a = new JSONArray(); for (String[] r : ROLES) { JSONObject o = new JSONObject(); o.put("name", r[0]); o.put("label", r[1]); o.put("permissions", permsFor(new JSONArray().put(r[0]))); a.put(o); } return a; }
        if ("GET".equals(method)) { JSONArray a = new JSONArray(); for (JSONObject u : rows("SELECT * FROM users ORDER BY id")) a.put(userOut(u)); return a; }
        if ("POST".equals(method)) { if (one("SELECT id FROM users WHERE username=?", b.optString("username")) != null) throw new Api.ApiError(409, "DUP", "این نام کاربری قبلاً ثبت شده"); exec("INSERT INTO users(username,full_name,pass_hash,roles,is_active,created_at) VALUES(?,?,?,?,1,?)", b.optString("username"), b.optString("full_name"), sha(b.optString("username") + "|" + b.optString("password")), String.valueOf(b.optJSONArray("roles") == null ? new JSONArray().put("Cashier") : b.optJSONArray("roles")), Db.now()); audit("USER_CREATE", "User", b.optString("username"), null, b); return userOut(one("SELECT * FROM users WHERE username=?", b.optString("username"))); }
        if (seg.length > 1) { long id = Long.parseLong(seg[1]); JSONObject u = one("SELECT * FROM users WHERE id=?", id); if (u == null) throw new Api.ApiError(404, "NOT_FOUND", "کاربر نیست");
            if (b.has("full_name")) exec("UPDATE users SET full_name=? WHERE id=?", b.optString("full_name"), id);
            if (b.has("roles")) exec("UPDATE users SET roles=? WHERE id=?", String.valueOf(b.optJSONArray("roles")), id);
            if (!b.optString("password").isEmpty()) exec("UPDATE users SET pass_hash=? WHERE id=?", sha(u.optString("username") + "|" + b.optString("password")), id);
            if (b.has("is_active")) exec("UPDATE users SET is_active=? WHERE id=?", b.optBoolean("is_active") ? 1 : 0, id);
            audit("USER_UPDATE", "User", u.optString("username"), u, b); JSONObject nu = userOut(one("SELECT * FROM users WHERE id=?", id));
            JSONObject cur = new JSONObject(Prefs.get("user_json", "{}")); if (cur.optString("username").equals(nu.optString("username"))) Prefs.set("user_json", nu.toString());
            return nu; }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    static void audit(String action, String et, String eid, Object before, Object after) { try { exec("INSERT INTO audit(action,entity_type,entity_id,reference,user,before,after,created_at) VALUES(?,?,?,?,?,?,?,?)", action, et, eid, eid, Screens.userName(), before == null ? null : String.valueOf(before), after == null ? null : String.valueOf(after), Db.now()); } catch (Exception ignore) {} }
    static Object audit(JSONObject q) { String f = q.optString("action"); JSONArray a = new JSONArray(); for (JSONObject r : rows(f.isEmpty() ? "SELECT * FROM audit ORDER BY id DESC LIMIT 150" : "SELECT * FROM audit WHERE action=? ORDER BY id DESC LIMIT 150", f.isEmpty() ? new Object[0] : new Object[]{f})) { try { r.put("user_id", r.optString("user")); } catch (Exception ignore) {} a.put(r); } return a; }

    /* ===================== settings ===================== */
    static final String[][] DEFAULTS = {
        {"store.name", "", "نام فروشگاه"}, {"store.phone", "", "تلفن فروشگاه"}, {"store.mobile", "", "موبایل فروشگاه"}, {"store.address", "", "آدرس (روی رسید چاپ می‌شود)"}, {"store.city", "", "شهر"}, {"store.postal_code", "", "کد پستی"}, {"store.tax_id", "", "شناسهٔ مالیاتی"}, {"store.receipt_note", "از خرید شما سپاسگزاریم", "پانوشت رسید"},
        {"time.timezone", "Asia/Tehran", "منطقهٔ زمانی"}, {"time.calendar", "jalali", "تقویم نمایش"},
        {"pos.tax_rate", "0", "درصد مالیات صندوق"}, {"pos.currency", "IRT", "واحد پول: IRT تومان | IRR ریال"}, {"pos.coupon_enabled", "true", "کوپن در صندوق فعال باشد"}, {"pos.print_after_checkout", "false", "چاپ خودکار رسید پس از ثبت (روی گوشی: اشتراک‌گذاری متن رسید)"}, {"pos.allow_negative_stock", "false", "اجازهٔ موجودی منفی"}, {"pos.allocation_policy", "FEFO", "سیاست برداشت بچ: FEFO | FIFO | MANUAL"},
        {"expiry.block_sale", "true", "جلوگیری از فروش کالای منقضی"}, {"expiry.days.three", "3", "آستانهٔ ۳ روز"}, {"expiry.days.seven", "7", "آستانهٔ ۷ روز"}, {"expiry.days.thirty", "30", "آستانهٔ ۳۰ روز"},
        {"inventory.default_min_stock", "5", "حداقل موجودی پیش‌فرض کالای جدید"}, {"inventory.low_stock_alert", "true", "هشدار کمبود در داشبورد"}, {"stocktake.require_approval", "true", "اعمال اختلاف انبارگردانی نیاز به تأیید مدیر دارد"},
        {"products.autofill_requires_confirm", "true", "تکمیل خودکار مشخصات باید تأیید شود"}, {"images.auto_find", "true", "یافتن خودکار تصویر کالا (بر اساس نام/برند/بارکد) هنگام ثبت"}, {"images.web_fallback", "true", "در نبود نتیجه از OpenFoodFacts/ویکی‌مدیا، جست‌وجوی تصویر وب بدون کلید (DuckDuckGo) هم استفاده شود"}, {"pricing.default_margin_percent", "20", "درصد سود پیشنهادی برای قیمت فروش"}, {"pricing.round_to", "1000", "گرد کردن قیمت پیشنهادی"},
        {"barcode.scanner.min_interval_ms", "30", "حداقل فاصلهٔ کلید برای تشخیص اسکنر"},
        {"customers.default_credit_limit", "0", "سقف اعتبار پیش‌فرض مشتری (۰ = نامحدود)"}, {"ledger.block_over_limit", "true", "جلوگیری از فروش نسیهٔ بیش از سقف"},
        {"marketing.coupon_prefix", "SM", "پیشوند کد کوپن"}, {"marketing.max_discount_percent", "50", "سقف درصد تخفیف کوپن"},
        {"sms.provider", "", "سرویس پیامک: melipayamak | kavenegar"}, {"sms.send_invoice", "true", "ارسال پیامک فاکتور به محض تأیید"}, {"sms.admin_phone", "", "شمارهٔ مدیر برای گزارش‌ها"}, {"sms.low_stock_alert", "false", "پیامک هشدار کمبود به مدیر"},
        {"printer.paper_width_mm", "58", "عرض کاغذ چاپگر بلوتوث"}, {"printer.header", "", "سربرگ رسید"}, {"printer.footer", "", "پانوشت رسید"},
        {"network.lan_port", "8765", "پورت سرویس LAN همین گوشی (برای گوشی‌های دیگر)"}, {"network.lan_server", "false", "این گوشی سرویس‌دهندهٔ گوشی‌های دیگر باشد"},
        {"security.session_minutes", "720", "طول نشست (دقیقه)"}, {"security.idle_minutes", "30", "قفل خودکار گوشی پس از این مدت بی‌کاری (دقیقه) — نیاز به ورود مجدد"}, {"security.require_admin_for_void_paid", "true", "ابطال فاکتور پرداخت‌شده رمز مدیر می‌خواهد"},
        {"backup.keep", "10", "تعداد نسخهٔ پشتیبان نگه‌داری‌شده"}, {"backup.auto_daily", "true", "پشتیبان‌گیری خودکار روزانه روی گوشی"},
        {"ui.theme", "auto", "پوسته: auto | light | dark"}, {"ui.theme_light_at", "07:00", "ساعت پوستهٔ روشن"}, {"ui.theme_dark_at", "19:00", "ساعت پوستهٔ تیره"},
        {"update.channel", "github", "کانال به‌روزرسانی"}, {"license.auto_recheck", "true", "بررسی خودکار لایسنس"}, {"mobile.sync_interval_seconds", "20", "فاصلهٔ همگام‌سازی"}, {"cloud.provider", "gdrive", "سرویس ابری"}};
    public static String setting(String k, String def) { JSONObject r = one("SELECT v FROM settings WHERE k=?", k); if (r != null) return r.optString("v"); for (String[] d : DEFAULTS) if (d[0].equals(k)) return d[1]; if (k.startsWith("sms.")) return SmsLocal.get(k, def); return def; }
    public static void setSetting(String k, String v) { exec("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", k, v); if (k.startsWith("sms.")) SmsLocal.set(k, v); if ("store.name".equals(k) && !v.isEmpty()) Prefs.set("store_name", v); if ("pos.currency".equals(k)) { Ui.currencyLabel = "IRT".equals(v) ? "تومان" : "ریال"; Prefs.set("currency_label", Ui.currencyLabel); } }
    static Object settings(String method, String[] seg, JSONObject b) throws Exception {
        if (seg.length == 1) {
            if ("PUT".equals(method) || "POST".equals(method)) { setSetting(b.optString("key"), b.optString("value")); audit("SETTINGS_UPDATE", "Setting", b.optString("key"), null, b.optString("value")); return obj("key", b.optString("key"), "value", b.optString("value")); }
            JSONArray a = new JSONArray(); java.util.LinkedHashMap<String, String[]> all = new java.util.LinkedHashMap<>(); for (String[] d : DEFAULTS) all.put(d[0], d); for (String k : SmsLocal.KEYS) if (!all.containsKey(k)) all.put(k, new String[]{k, "", "تنظیم پیامک"});
            for (String[] d : all.values()) { boolean secret = d[0].contains("password") || d[0].contains("api_key"); String v = setting(d[0], d[1]); JSONObject o = new JSONObject(); o.put("key", d[0]); o.put("value", secret ? "" : v); o.put("description", d[2]); o.put("is_secret", secret); o.put("has_value", !v.isEmpty()); a.put(o); }
            return a;
        }
        switch (seg[1]) {
            case "currency": return obj("code", setting("pos.currency", "IRT"), "label", Ui.currencyLabel);
            case "theme": if ("PUT".equals(method)) { setSetting("ui.theme", b.optString("theme", "auto")); Prefs.set("theme_pref", b.optString("theme", "auto")); } { String t = setting("ui.theme", "auto"); int h = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY); String res = "light".equals(t) ? "light" : "dark".equals(t) ? "dark" : (h >= 7 && h < 19 ? "light" : "dark"); return obj("theme", t, "resolved", res); }
            case "time": { java.util.TimeZone tz = java.util.TimeZone.getDefault(); return obj("timezone", tz.getID(), "utc_offset", "+03:30", "jalali", Jalali.todayLong(), "calendar", "شمسی (جلالی)"); }
            case "about": return obj("version", Version.NAME, "store_name", Prefs.get("store_name", ""), "developer", "طراحی و توسعه توسط خواجوی", "mode", "standalone");
            case "store-profile": {
                if (seg.length > 2 && "logo".equals(seg[2])) { setSetting("store.logo_path", ""); return obj("ok", true); }
                if ("PUT".equals(method) || "POST".equals(method)) { java.util.Iterator<String> it = b.keys(); while (it.hasNext()) { String k = it.next(); setSetting("store." + k, b.optString(k)); } audit("STORE_PROFILE_UPDATE", "Store", "1", null, b); }
                JSONObject o = new JSONObject(); for (String k : new String[]{"name", "legal_name", "phone", "mobile", "address", "city", "postal_code", "tax_id", "logo_path", "receipt_note"}) o.put(k, setting("store." + k, "name".equals(k) ? Prefs.get("store_name", "") : "")); return o; }
        }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }

    /* ===================== POS / invoices / returns ===================== */
    static Object pos(String method, String[] seg, JSONObject q, JSONObject b) throws Exception {
        if ("search".equals(seg[1])) { JSONArray a = new JSONArray(); for (JSONObject p : Db.searchProducts(q.optString("q"), q.optInt("limit", 8))) a.put(p); return obj("items", a); }
        if ("checkout".equals(seg[1])) { double total = 0; JSONArray items = b.optJSONArray("items"); for (int i = 0; items != null && i < items.length(); i++) total += items.optJSONObject(i).optDouble("quantity", 1) * items.optJSONObject(i).optDouble("price", 0) - items.optJSONObject(i).optDouble("discount", 0); String no = Db.localSale(b, Math.max(0, total - b.optDouble("invoice_discount", 0))); return invoiceOut(one("SELECT rowid AS id,* FROM invoices WHERE local_no=?", no)); }
        if ("kiosk".equals(seg[1])) return obj("shortcut", "", "enabled", false);
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    static JSONObject invoiceOut(JSONObject r) throws Exception {
        if (r == null) throw new Api.ApiError(404, "NOT_FOUND", "فاکتور نیست");
        JSONObject o = new JSONObject(); long id = r.optLong("id");
        o.put("id", id); o.put("invoice_id", id); o.put("invoice_number", r.isNull("invoice_number") || r.optString("invoice_number").isEmpty() ? r.optString("local_no") : r.optString("invoice_number")); o.put("local_no", r.optString("local_no"));
        o.put("created_at", r.optString("at")); o.put("status", r.optString("status", "PAID")); o.put("payment_status", r.optString("payment_status", "PAID")); o.put("payment_method", r.optString("payment")); o.put("subtotal", r.optDouble("subtotal", r.optDouble("total"))); o.put("discount", r.optDouble("discount", 0)); o.put("tax", r.optDouble("tax", 0)); o.put("total_amount", r.optDouble("total")); o.put("customer_id", r.isNull("customer_id") ? JSONObject.NULL : r.optLong("customer_id")); o.put("cashier", r.optString("user")); o.put("synced", r.optInt("synced") == 1);
        JSONArray its = new JSONArray(); for (JSONObject it : rows("SELECT * FROM invoice_items WHERE inv=?", id)) { it.put("returned_qty", it.optDouble("returned_qty", 0)); JSONObject p = Db.productById(it.optLong("product_id")); it.put("name", p == null ? "" : p.optString("name")); its.put(it); } o.put("items", its);
        if (!r.isNull("customer_id")) { JSONObject c = one("SELECT * FROM customers WHERE id=?", r.optLong("customer_id")); if (c != null) { o.put("customer_name", c.optString("name")); o.put("customer_phone", c.optString("phone")); } }
        return o;
    }
    static Object invoices(String method, String[] seg, JSONObject q, JSONObject b) throws Exception {
        if (seg.length == 1) { JSONArray a = new JSONArray(); for (JSONObject r : rows("SELECT rowid AS id,* FROM invoices ORDER BY at DESC LIMIT " + q.optInt("limit", 100))) a.put(invoiceOut(r)); return a; }
        long id = Long.parseLong(seg[1]); JSONObject r = one("SELECT rowid AS id,* FROM invoices WHERE rowid=?", id); JSONObject inv = invoiceOut(r);
        if (seg.length == 2) return inv;
        switch (seg[2]) {
            case "receipt": return obj("receipt_text", receipt(inv));
            case "print": { String txt = receipt(inv); Api.ui(() -> { try { android.content.Intent i = new android.content.Intent(android.content.Intent.ACTION_SEND); i.setType("text/plain"); i.putExtra(android.content.Intent.EXTRA_TEXT, txt); android.content.Intent ch = android.content.Intent.createChooser(i, "چاپ / اشتراک رسید"); ch.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK); Ui.ctx.startActivity(ch); } catch (Exception ignore) {} }); return obj("status", "SHARED", "message", "رسید برای چاپ بلوتوثی/اشتراک ارسال شد"); }
            case "void": {
                if ("VOID".equals(inv.optString("status"))) throw new Api.ApiError(409, "VOID", "این فاکتور قبلاً باطل شده");
                if ("PAID".equals(inv.optString("payment_status")) && "true".equals(setting("security.require_admin_for_void_paid", "true"))) { seedUsers(); JSONObject adm = null; for (JSONObject u : rows("SELECT * FROM users WHERE roles LIKE '%Administrator%' AND is_active=1")) if (passOk(u, u.optString("username"), b.optString("admin_password"))) adm = u; if (adm == null) throw new Api.ApiError(403, "ADMIN", "رمز مدیر برای ابطال فاکتور پرداخت‌شده لازم است"); }
                SQLiteDatabase d = Db.db(); d.beginTransaction();
                try { JSONArray its = inv.optJSONArray("items"); for (int i = 0; i < its.length(); i++) { JSONObject it = its.optJSONObject(i); double q0 = it.optDouble("qty") - it.optDouble("returned_qty", 0); if (it.optLong("batch_id") != 0) d.execSQL("UPDATE batches SET current_qty=current_qty+? WHERE id=?", new Object[]{q0, it.optLong("batch_id")}); d.execSQL("INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,reason,user,created_at) VALUES(?,?,'RETURN_IN',?,'InvoiceVoid',?,?,?,?)", new Object[]{it.optLong("product_id"), it.optLong("batch_id"), q0, inv.optString("invoice_number"), b.optString("reason"), Screens.userName(), Db.now()}); }
                    d.execSQL("UPDATE invoices SET status='VOID', void_reason=? WHERE rowid=?", new Object[]{b.optString("reason"), id});
                    if (!inv.isNull("customer_id")) d.execSQL("INSERT INTO ledger(customer_id,entry_type,amount,note,ref,created_at) SELECT customer_id,'ADJUSTMENT_CREDIT',amount,'ابطال فاکتور',ref,? FROM ledger WHERE ref=? AND entry_type='CHARGE'", new Object[]{Db.now(), inv.optString("local_no")});
                    d.setTransactionSuccessful(); } finally { d.endTransaction(); }
                reverseJournal("Invoice:" + inv.optString("local_no"), "ابطال فاکتور " + inv.optString("invoice_number")); audit("INVOICE_VOID", "Invoice", inv.optString("invoice_number"), null, b.optString("reason"));
                return obj("ok", true, "invoice_number", inv.optString("invoice_number"), "status", "VOID"); }
        }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    static Object returns(JSONObject b) throws Exception {
        long inv = b.optLong("invoice_id"), itemId = b.optLong("invoice_item_id"); double qty = b.optDouble("qty", 1);
        JSONObject it = one("SELECT * FROM invoice_items WHERE id=? AND inv=?", itemId, inv); if (it == null) throw new Api.ApiError(404, "NOT_FOUND", "قلم فاکتور یافت نشد");
        double left = it.optDouble("qty") - it.optDouble("returned_qty", 0); if (qty <= 0 || qty > left) throw new Api.ApiError(400, "QTY", "حداکثر مرجوعی " + Ui.num(left));
        double refund = b.has("refund_amount") ? b.optDouble("refund_amount") : qty * it.optDouble("unit_sell_price");
        JSONObject r = one("SELECT rowid AS id,* FROM invoices WHERE rowid=?", inv);
        exec("UPDATE invoice_items SET returned_qty=returned_qty+? WHERE id=?", qty, itemId);
        if (it.optLong("batch_id") != 0) exec("UPDATE batches SET current_qty=current_qty+? WHERE id=?", qty, it.optLong("batch_id"));
        exec("INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,reason,user,created_at) VALUES(?,?,'RETURN_IN',?,'Return',?,?,?,?)", it.optLong("product_id"), it.optLong("batch_id"), qty, r.optString("local_no"), b.optString("reason"), Screens.userName(), Db.now());
        journal("RETURN", "مرجوعی " + r.optString("local_no"), refund, "Return:" + r.optString("local_no") + ":" + itemId, new String[][]{{"4000", String.valueOf(refund), "0"}, {payAcc(r.optString("payment")), "0", String.valueOf(refund)}, {"1200", String.valueOf(qty * it.optDouble("unit_buy_price")), "0"}, {"5000", "0", String.valueOf(qty * it.optDouble("unit_buy_price"))}});
        audit("RETURN", "Invoice", r.optString("local_no"), null, b); return obj("ok", true, "refund_amount", refund, "movement_type", "RETURN_IN");
    }
    static String receipt(JSONObject inv) {
        StringBuilder sb = new StringBuilder(); String store = Prefs.get("store_name", "فروشگاه"); String hdr = setting("printer.header", "");
        sb.append(center(store)).append('\n'); if (!hdr.isEmpty()) sb.append(center(hdr)).append('\n'); String addr = setting("store.address", ""); if (!addr.isEmpty()) sb.append(center(addr)).append('\n'); String tel = setting("store.phone", ""); if (!tel.isEmpty()) sb.append(center("تلفن: " + tel)).append('\n');
        sb.append("--------------------------------\n").append("فاکتور: ").append(inv.optString("invoice_number")).append('\n').append("تاریخ: ").append(Ui.jdate(inv.optString("created_at"))).append('\n').append("صندوق‌دار: ").append(inv.optString("cashier")).append('\n');
        if (!inv.optString("customer_name").isEmpty()) sb.append("مشتری: ").append(inv.optString("customer_name")).append('\n');
        sb.append("--------------------------------\n"); JSONArray its = inv.optJSONArray("items");
        for (int i = 0; its != null && i < its.length(); i++) { JSONObject it = its.optJSONObject(i); sb.append(it.optString("name")).append('\n').append("  ").append(Ui.num(it.optDouble("qty"))).append(" × ").append(Ui.money(it.optDouble("unit_sell_price"))).append(it.optDouble("discount") > 0 ? " − " + Ui.money(it.optDouble("discount")) : "").append(" = ").append(Ui.money(it.optDouble("subtotal"))).append('\n'); }
        sb.append("--------------------------------\n").append("جمع: ").append(Ui.money(inv.optDouble("subtotal"))).append('\n'); if (inv.optDouble("discount") > 0) sb.append("تخفیف: ").append(Ui.money(inv.optDouble("discount"))).append('\n'); if (inv.optDouble("tax") > 0) sb.append("مالیات: ").append(Ui.money(inv.optDouble("tax"))).append('\n');
        sb.append("قابل پرداخت: ").append(Ui.money(inv.optDouble("total_amount"))).append('\n').append("پرداخت: ").append(Screens.Screen.label(inv.optString("payment_method"), Screens.Screen.PAY)).append('\n');
        if ("VOID".equals(inv.optString("status"))) sb.append("*** باطل شده ***\n");
        sb.append("--------------------------------\n").append(center(setting("store.receipt_note", "از خرید شما سپاسگزاریم"))).append('\n'); String ft = setting("printer.footer", ""); if (!ft.isEmpty()) sb.append(center(ft)).append('\n');
        return sb.toString();
    }
    static String center(String s) { int w = 32; if (s.length() >= w) return s; int pad = (w - s.length()) / 2; StringBuilder b = new StringBuilder(); for (int i = 0; i < pad; i++) b.append(' '); return b + s; }

    /* ===================== customers + ledger ===================== */
    static double balance(long cid) { JSONObject r = one("SELECT IFNULL(SUM(CASE WHEN entry_type IN ('CHARGE','ADJUSTMENT_DEBIT') THEN amount ELSE -amount END),0) AS b FROM ledger WHERE customer_id=?", cid); return r == null ? 0 : r.optDouble("b"); }
    static Object customers(String method, String[] seg, JSONObject q, JSONObject b) throws Exception {
        if (seg.length == 1) { if ("POST".equals(method)) { JSONObject c = Db.localCustomer(b.optString("name"), Db.norm(b.optString("phone"))); exec("UPDATE customers SET last_name=?, address=?, credit_limit=? WHERE id=?", b.optString("last_name"), b.optString("address"), b.optDouble("credit_limit", 0), c.optLong("id")); return one("SELECT * FROM customers WHERE id=?", c.optLong("id")); } JSONArray a = new JSONArray(); for (JSONObject c : Db.customers(q.optString("q"))) a.put(c); return a; }
        if ("debtors".equals(seg[1])) { JSONArray a = new JSONArray(); for (JSONObject c : rows("SELECT c.*, IFNULL((SELECT SUM(CASE WHEN entry_type IN ('CHARGE','ADJUSTMENT_DEBIT') THEN amount ELSE -amount END) FROM ledger l WHERE l.customer_id=c.id),0) AS balance FROM customers c")) if (c.optDouble("balance") > 0.5) a.put(c); return a; }
        long id = Long.parseLong(seg[1]); JSONObject c = one("SELECT * FROM customers WHERE id=?", id); if (c == null) throw new Api.ApiError(404, "NOT_FOUND", "مشتری نیست");
        if (seg.length == 2) { if ("PATCH".equals(method) || "PUT".equals(method)) { for (String k : new String[]{"name", "last_name", "phone", "address"}) if (b.has(k)) exec("UPDATE customers SET " + k + "=? WHERE id=?", b.optString(k), id); if (b.has("credit_limit")) exec("UPDATE customers SET credit_limit=? WHERE id=?", b.optDouble("credit_limit"), id); JSONObject n = one("SELECT * FROM customers WHERE id=?", id); try { JSONObject j = new JSONObject(n.optString("json", "{}")); java.util.Iterator<String> it = n.keys(); while (it.hasNext()) { String k = it.next(); if (!"json".equals(k)) j.put(k, n.opt(k)); } exec("UPDATE customers SET json=? WHERE id=?", j.toString(), id); n = j; } catch (Exception ignore) {} audit("CUSTOMER_UPDATE", "Customer", String.valueOf(id), c, b); return n; } try { JSONObject j = new JSONObject(c.optString("json", "{}")); j.put("balance", balance(id)); return j; } catch (Exception e) { return c; } }
        switch (seg[2]) {
            case "ledger": { JSONObject o = new JSONObject(); o.put("balance", balance(id)); JSONObject t = one("SELECT IFNULL(SUM(CASE WHEN entry_type IN ('CHARGE','ADJUSTMENT_DEBIT') THEN amount ELSE 0 END),0) AS ch, IFNULL(SUM(CASE WHEN entry_type IN ('PAYMENT','SETTLEMENT','ADJUSTMENT_CREDIT') THEN amount ELSE 0 END),0) AS pd FROM ledger WHERE customer_id=?", id); o.put("total_charged", t.optDouble("ch")); o.put("total_paid", t.optDouble("pd")); o.put("credit_limit", c.optDouble("credit_limit")); JSONArray en = new JSONArray(); for (JSONObject e : rows("SELECT * FROM ledger WHERE customer_id=? ORDER BY id DESC LIMIT 100", id)) { e.put("type", e.optString("entry_type")); en.put(e); } o.put("entries", en); return o; }
            case "invoices": { JSONArray a = new JSONArray(); for (JSONObject r : rows("SELECT rowid AS id,* FROM invoices WHERE customer_id=? ORDER BY at DESC LIMIT 50", id)) a.put(invoiceOut(r)); return a; }
            case "settle": { double bal = balance(id); double amt = b.has("amount") ? b.optDouble("amount") : bal; if (amt <= 0) throw new Api.ApiError(400, "AMT", "مبلغ نامعتبر"); exec("INSERT INTO ledger(customer_id,entry_type,amount,note,ref,created_at) VALUES(?,'SETTLEMENT',?,?,?,?)", id, amt, b.optString("note"), b.optString("method", "CASH"), Db.now()); journal("SETTLEMENT", "تسویهٔ " + c.optString("name"), amt, "Settle:" + id + ":" + System.currentTimeMillis(), new String[][]{{payAcc(b.optString("method", "CASH")), String.valueOf(amt), "0"}, {"1100", "0", String.valueOf(amt)}}); audit("CUSTOMER_SETTLE", "Customer", String.valueOf(id), null, b); return obj("ok", true, "balance", balance(id)); }
            case "debt-reminder": { double bal = balance(id); if (bal <= 0) throw new Api.ApiError(400, "NO_DEBT", "بدهی ندارد"); String t = setting("sms.template.debt_reminder", "{customer} گرامی، مانده بدهی شما نزد {store} مبلغ {amount} {currency} است. با تشکر.").replace("{customer}", c.optString("name")).replace("{store}", Prefs.get("store_name", "فروشگاه")).replace("{amount}", Ui.num(bal)).replace("{currency}", Ui.currencyLabel); SmsLocal.enqueueAndSend(c.optString("phone"), t, "debt-" + id); return obj("ok", true, "queued", true); }
            case "adjust": { exec("INSERT INTO ledger(customer_id,entry_type,amount,note,ref,created_at) VALUES(?,?,?,?,?,?)", id, b.optString("entry_type", "ADJUSTMENT_DEBIT"), b.optDouble("amount"), b.optString("note"), "manual", Db.now()); audit("LEDGER_ADJUST", "Customer", String.valueOf(id), null, b); return obj("ok", true, "balance", balance(id)); }
        }
        if (seg.length > 3 && "ledger".equals(seg[2]) && "adjust".equals(seg[3])) { exec("INSERT INTO ledger(customer_id,entry_type,amount,note,ref,created_at) VALUES(?,?,?,?,?,?)", id, b.optString("entry_type", "ADJUSTMENT_DEBIT"), b.optDouble("amount"), b.optString("note"), "manual", Db.now()); audit("LEDGER_ADJUST", "Customer", String.valueOf(id), null, b); return obj("ok", true, "balance", balance(id)); }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }

    /* ===================== marketing ===================== */
    static Object marketing(String method, String[] seg, JSONObject b) throws Exception {
        String what = seg[1];
        if ("stats".equals(what)) { JSONObject o = new JSONObject(); o.put("campaigns", count("campaigns")); o.put("total_coupons", count("coupons")); JSONObject rv = one("SELECT IFNULL(SUM(CASE WHEN discount_type='FIXED' THEN discount_value*used_count ELSE 0 END),0) AS v FROM coupons"); o.put("redeemed_value", rv.optDouble("v")); JSONObject bs = new JSONObject(); for (JSONObject r : rows("SELECT status, COUNT(*) AS n FROM coupons GROUP BY status")) bs.put(r.optString("status"), r.optInt("n")); o.put("by_status", bs); return o; }
        if ("campaigns".equals(what)) {
            if (seg.length == 2) { if ("POST".equals(method)) { exec("INSERT INTO campaigns(name,discount_type,discount_value,min_purchase,max_discount,valid_until,status,auto_issue_threshold,created_at) VALUES(?,?,?,?,?,?,'ACTIVE',?,?)", b.optString("name"), b.optString("discount_type", "PERCENT"), b.optDouble("discount_value"), b.optDouble("min_purchase", 0), b.has("max_discount") ? b.optDouble("max_discount") : null, b.optString("valid_until", null), b.has("auto_issue_threshold") ? b.optDouble("auto_issue_threshold") : null, Db.now()); return one("SELECT * FROM campaigns ORDER BY id DESC LIMIT 1"); } return arr(rows("SELECT * FROM campaigns ORDER BY id DESC")); }
            long id = Long.parseLong(seg[2]); if (b.has("status")) exec("UPDATE campaigns SET status=? WHERE id=?", b.optString("status"), id); return one("SELECT * FROM campaigns WHERE id=?", id);
        }
        if ("coupons".equals(what)) {
            if (seg.length == 2) { if ("POST".equals(method)) { String code = b.optString("code"); if (code.isEmpty()) code = setting("marketing.coupon_prefix", "SM") + "-" + Long.toString(System.currentTimeMillis() % 100000000L, 36).toUpperCase(); exec("INSERT INTO coupons(code,discount_type,discount_value,min_purchase,customer_phone,valid_until,usage_limit,used_count,status,created_at) VALUES(?,?,?,?,?,?,?,0,'ACTIVE',?)", code, b.optString("discount_type", "PERCENT"), b.optDouble("discount_value"), b.optDouble("min_purchase", 0), b.optString("customer_phone", null), b.optString("valid_until", null), b.optInt("usage_limit", 1), Db.now()); JSONObject cp = one("SELECT * FROM coupons WHERE code=?", code); if (!b.optString("customer_phone").isEmpty()) SmsLocal.enqueueAndSend(b.optString("customer_phone"), setting("sms.template.coupon", "{store} | کد تخفیف شما: {code} | تا {until} معتبر است").replace("{store}", Prefs.get("store_name", "فروشگاه")).replace("{code}", code).replace("{until}", b.optString("valid_until").isEmpty() ? "همیشه" : Ui.jdate(b.optString("valid_until"))), "coupon"); return cp; } return arr(rows("SELECT * FROM coupons ORDER BY id DESC")); }
            if ("validate".equals(seg[2])) { JSONObject cp = one("SELECT * FROM coupons WHERE code=?", b.optString("code")); double total = b.optDouble("total", b.optDouble("subtotal", 0)); if (cp == null) return obj("valid", false, "reason", "کوپن یافت نشد"); if (!"ACTIVE".equals(cp.optString("status"))) return obj("valid", false, "reason", "کوپن فعال نیست"); if (!cp.isNull("valid_until") && !cp.optString("valid_until").isEmpty() && cp.optString("valid_until").compareTo(Db.now()) < 0) { exec("UPDATE coupons SET status='EXPIRED' WHERE id=?", cp.optLong("id")); return obj("valid", false, "reason", "کوپن منقضی شده"); } if (total < cp.optDouble("min_purchase")) return obj("valid", false, "reason", "حداقل خرید " + Ui.money(cp.optDouble("min_purchase"))); if (!cp.optString("customer_phone").isEmpty() && !b.optString("customer_phone").isEmpty() && !cp.optString("customer_phone").equals(Db.norm(b.optString("customer_phone")))) return obj("valid", false, "reason", "این کوپن برای مشتری دیگری است"); double disc = "PERCENT".equals(cp.optString("discount_type")) ? total * cp.optDouble("discount_value") / 100 : cp.optDouble("discount_value"); return obj("valid", true, "ok", true, "discount", Math.min(disc, total), "code", cp.optString("code")); }
            long id = Long.parseLong(seg[2]); if (seg.length > 3 && "block".equals(seg[3])) exec("UPDATE coupons SET status='BLOCKED' WHERE id=?", id); return one("SELECT * FROM coupons WHERE id=?", id);
        }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }

    /* ===================== products / units / taxonomy / prices ===================== */
    static Object units(String method, JSONObject b) throws Exception {
        if ("POST".equals(method)) { exec("INSERT INTO units(name,symbol,allow_decimal,decimals,is_active) VALUES(?,?,?,?,1)", b.optString("name"), b.optString("symbol"), b.optBoolean("allow_decimal") ? 1 : 0, b.optInt("decimals", 0)); }
        JSONArray a = new JSONArray(); for (JSONObject u : rows("SELECT * FROM units ORDER BY id")) { u.put("allow_decimal", u.optInt("allow_decimal") == 1); u.put("is_active", u.optInt("is_active") == 1); a.put(u); } Db.kv("local_units", a.toString()); StockScreens.units = a; return a;
    }
    static Object products(String method, String[] seg, JSONObject b) throws Exception {
        if (seg.length > 1 && ("categories".equals(seg[1]) || "brands".equals(seg[1]))) { String t = seg[1]; if ("POST".equals(method)) exec("INSERT INTO " + t + "(name) VALUES(?)", b.optString("name")); return arr(rows("SELECT * FROM " + t + " ORDER BY name")); }
        if (seg.length > 1 && "images".equals(seg[1])) { if (seg.length > 2 && "backfill".equals(seg[2])) return obj("queued", Images.backfill(), "missing", Images.missing()); int total = count("products"); return obj("total", total, "missing", Images.missing(), "with_image", total - Images.missing(), "jobs", obj("PENDING", Images.queued()), "auto_find", "true".equals(setting("images.auto_find", "true")), "web_fallback", "true".equals(setting("images.web_fallback", "true"))); }
        if (seg.length > 3 && "image".equals(seg[2]) && "find".equals(seg[3])) { JSONObject rep = Images.findNow(Ui.ctx, Long.parseLong(seg[1])); return rep; }
        if (seg.length == 1) { if ("POST".equals(method)) { JSONObject p = Db.localProduct(b.optString("barcode"), b.optString("name"), b.has("unit_id") ? b.optLong("unit_id") : null); Images.findLater(p.optLong("id")); return p; } return arr(Db.searchProducts("", 500)); }
        long id = Long.parseLong(seg[1]); JSONObject p = Db.productById(id); if (p == null) throw new Api.ApiError(404, "NOT_FOUND", "کالا نیست");
        if (seg.length == 2) {
            if ("DELETE".equals(method)) { exec("UPDATE products SET is_active=0 WHERE id=?", id); audit("PRODUCT_DELETE", "Product", String.valueOf(id), p, null); return obj("ok", true); }
            if ("PATCH".equals(method) || "PUT".equals(method)) { java.util.Iterator<String> it = b.keys(); while (it.hasNext()) { String k = it.next(); p.put(k, b.opt(k)); } Db.putProduct(p, p.optBoolean("_local") || id < 0); audit("PRODUCT_UPDATE", "Product", String.valueOf(id), null, b); return Db.productById(id); }
            return p;
        }
        if ("detail".equals(seg[2])) { p.put("depleted_batches", arr(rows("SELECT *, batch_number, received_at, quantity_received FROM batches WHERE product_id=? AND (current_qty<=0 OR status<>'ACTIVE') ORDER BY id DESC LIMIT 20", id))); return p; }
        if ("quick-price".equals(seg[2])) { if (b.has("sell_price")) { exec("UPDATE batches SET sell_price=? WHERE product_id=? AND status='ACTIVE' AND current_qty>0", b.optDouble("sell_price"), id); exec("UPDATE price_history SET is_active=0 WHERE product_id=? AND price_type='SELL'", id); exec("INSERT INTO price_history(product_id,price_type,price,effective_from,is_active) VALUES(?,'SELL',?,?,1)", id, b.optDouble("sell_price"), Db.now()); } if (b.has("consumer_price")) { exec("UPDATE batches SET consumer_price=? WHERE product_id=? AND status='ACTIVE' AND current_qty>0", b.optDouble("consumer_price"), id); exec("UPDATE price_history SET is_active=0 WHERE product_id=? AND price_type='CONSUMER'", id); exec("INSERT INTO price_history(product_id,price_type,price,effective_from,is_active) VALUES(?,'CONSUMER',?,?,1)", id, b.optDouble("consumer_price"), Db.now()); } refreshBatchJson(id); audit("PRICE_UPDATE", "Product", String.valueOf(id), null, b); return obj("ok", true); }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    /** batches keep a json copy for the catalogue reads — refresh it after SQL updates. */
    static void refreshBatchJson(long productId) { for (JSONObject bt : rows("SELECT * FROM batches WHERE product_id=?", productId)) { try { JSONObject j = new JSONObject(bt.optString("json", "{}")); for (String k : new String[]{"current_qty", "sell_price", "consumer_price", "buy_price", "status", "expiry_date"}) j.put(k, bt.opt(k)); exec("UPDATE batches SET json=? WHERE id=?", j.toString(), bt.optLong("id")); } catch (Exception ignore) {} } }
    static Object priceHistory(String[] seg) { long pid = Long.parseLong(seg[2]); return arr(rows("SELECT * FROM price_history WHERE product_id=? ORDER BY id DESC", pid)); }
    /** called by Db.localBatch so every receipt writes the immutable price history. */
    public static void onBatchReceived(long productId, long batchId, double qty, double buy, double sell, double consumer) {
        try { for (String[] pt : new String[][]{{"BUY", String.valueOf(buy)}, {"SELL", String.valueOf(sell)}, {"CONSUMER", String.valueOf(consumer)}}) { JSONObject last = one("SELECT price FROM price_history WHERE product_id=? AND price_type=? AND is_active=1", productId, pt[0]); if (last == null || Math.abs(last.optDouble("price") - Double.parseDouble(pt[1])) > 0.001) { exec("UPDATE price_history SET is_active=0 WHERE product_id=? AND price_type=?", productId, pt[0]); exec("INSERT INTO price_history(product_id,price_type,price,effective_from,is_active) VALUES(?,?,?,?,1)", productId, pt[0], Double.parseDouble(pt[1]), Db.now()); } }
            exec("UPDATE batches SET quantity_received=?, received_at=?, warehouse_id=1 WHERE id=?", qty, Db.now(), batchId);
            exec("INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,user,created_at) VALUES(?,?,'IN',?,'Batch',?,?,?)", productId, batchId, qty, String.valueOf(batchId), Screens.userName(), Db.now());
            journal("PURCHASE", "ورود کالا (بچ " + batchId + ")", qty * buy, "Batch:" + batchId, new String[][]{{"1200", String.valueOf(qty * buy), "0"}, {"2100", "0", String.valueOf(qty * buy)}});
        } catch (Exception ignore) {}
    }

    /* ===================== inventory: stocktake / waste / adjust / movements ===================== */
    static Object inventory(String method, String[] seg, JSONObject b) throws Exception {
        String what = seg[1];
        if ("movements".equals(what)) return arr(rows("SELECT * FROM movements ORDER BY id DESC LIMIT 150"));
        if ("waste".equals(what) || "adjust".equals(what)) {
            long bid = b.optLong("batch_id"); JSONObject bt = one("SELECT * FROM batches WHERE id=?", bid); if (bt == null) throw new Api.ApiError(404, "NOT_FOUND", "بچ نیست");
            double cur = bt.optDouble("current_qty"), nq = b.optDouble("new_current_qty", b.has("quantity") ? cur - b.optDouble("quantity") : cur); if ("waste".equals(what) && b.has("quantity") && !b.has("new_current_qty")) nq = cur - b.optDouble("quantity"); double delta = nq - cur;
            exec("UPDATE batches SET current_qty=? WHERE id=?", Math.max(0, nq), bid); refreshBatchJson(bt.optLong("product_id"));
            exec("INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,reason,user,created_at) VALUES(?,?,?,?,?,?,?,?,?)", bt.optLong("product_id"), bid, "waste".equals(what) ? "WASTE" : "ADJUSTMENT", delta, "Manual", String.valueOf(bid), b.optString("reason"), Screens.userName(), Db.now());
            double val = Math.abs(delta) * bt.optDouble("buy_price"); if (delta < 0) journal("WASTE".equals(what.toUpperCase()) ? "WASTE" : "ADJUST", ("waste".equals(what) ? "ضایعات" : "اصلاح موجودی") + " بچ " + bid, val, "Adj:" + bid + ":" + System.currentTimeMillis(), new String[][]{{"6000", String.valueOf(val), "0"}, {"1200", "0", String.valueOf(val)}});
            audit("waste".equals(what) ? "STOCK_WASTE" : "STOCK_ADJUST", "Batch", String.valueOf(bid), cur, nq); return obj("ok", true, "movement_type", "waste".equals(what) ? "WASTE" : "ADJUSTMENT", "delta", delta);
        }
        if (!"stocktakes".equals(what)) throw new Api.ApiError(404, "NOT_FOUND", "");
        if (seg.length == 2) {
            if ("POST".equals(method)) { exec("INSERT INTO stocktakes(name,area,status,scheduled_for,created_at) VALUES(?,?,'DRAFT',?,?)", b.optString("name"), b.optString("area"), b.optString("scheduled_for", null), Db.now()); JSONObject st = one("SELECT * FROM stocktakes ORDER BY id DESC LIMIT 1"); long id = st.optLong("id"); for (JSONObject bt : rows("SELECT * FROM batches WHERE status='ACTIVE'" + (b.optBoolean("include_zero", true) ? "" : " AND current_qty>0"))) exec("INSERT INTO stocktake_items(st,product_id,batch_id,system_qty) VALUES(?,?,?,?)", id, bt.optLong("product_id"), bt.optLong("id"), bt.optDouble("current_qty")); audit("STOCKTAKE_CREATE", "Stocktake", String.valueOf(id), null, b); return st; }
            return arr(rows("SELECT * FROM stocktakes ORDER BY id"));
        }
        if ("count".equals(seg[2])) { JSONObject it = one("SELECT * FROM stocktake_items WHERE id=?", b.optLong("item_id")); if (it == null) throw new Api.ApiError(404, "NOT_FOUND", "ردیف نیست"); JSONObject st = one("SELECT status FROM stocktakes WHERE id=?", it.optLong("st")); if (!"IN_PROGRESS".equals(st.optString("status"))) throw new Api.ApiError(409, "STATE", "شمارش شروع نشده"); exec("UPDATE stocktake_items SET physical_qty=?, reason=?, counted_at=? WHERE id=?", b.optDouble("physical_qty"), b.optString("reason"), Db.now(), it.optLong("id")); return obj("ok", true); }
        long id = Long.parseLong(seg[2]); JSONObject st = one("SELECT * FROM stocktakes WHERE id=?", id); if (st == null) throw new Api.ApiError(404, "NOT_FOUND", "انبارگردانی نیست");
        if (seg.length == 3) return st;
        switch (seg[3]) {
            case "progress": { JSONObject t = one("SELECT COUNT(*) AS total, SUM(physical_qty IS NOT NULL) AS counted, MIN(CASE WHEN physical_qty IS NULL THEN id END) AS next_id FROM stocktake_items WHERE st=?", id); st.put("total", t.optInt("total")); st.put("counted", t.optInt("counted")); st.put("remaining", t.optInt("total") - t.optInt("counted")); st.put("percent", t.optInt("total") == 0 ? 100 : Math.round(1000.0 * t.optInt("counted") / t.optInt("total")) / 10.0); st.put("next_item_id", t.isNull("next_id") ? 0 : t.optLong("next_id")); return st; }
            case "items": return arr(stItems(id, null));
            case "start": exec("UPDATE stocktakes SET status='IN_PROGRESS', started_at=? WHERE id=? AND status='DRAFT'", Db.now(), id); return one("SELECT * FROM stocktakes WHERE id=?", id);
            case "complete": exec("UPDATE stocktakes SET status='COMPLETED', completed_at=? WHERE id=? AND status='IN_PROGRESS'", Db.now(), id); return one("SELECT * FROM stocktakes WHERE id=?", id);
            case "cancel": exec("UPDATE stocktakes SET status='CANCELLED' WHERE id=?", id); return one("SELECT * FROM stocktakes WHERE id=?", id);
            case "approve": { if (!"COMPLETED".equals(st.optString("status"))) throw new Api.ApiError(409, "STATE", "ابتدا شمارش را تمام کنید"); int n = 0; for (JSONObject it : rows("SELECT * FROM stocktake_items WHERE st=? AND physical_qty IS NOT NULL", id)) { double diff = it.optDouble("physical_qty") - it.optDouble("system_qty"); if (Math.abs(diff) < 0.0001) continue; exec("UPDATE batches SET current_qty=? WHERE id=?", it.optDouble("physical_qty"), it.optLong("batch_id")); refreshBatchJson(it.optLong("product_id")); exec("INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,reason,user,created_at) VALUES(?,?,'ADJUSTMENT',?,'Stocktake',?,?,?,?)", it.optLong("product_id"), it.optLong("batch_id"), diff, String.valueOf(id), it.optString("reason"), Screens.userName(), Db.now()); n++; } exec("UPDATE stocktakes SET status='APPROVED', approved_at=? WHERE id=?", Db.now(), id); audit("STOCKTAKE_APPROVE", "Stocktake", String.valueOf(id), null, n); return obj("ok", true, "adjusted", n); }
            case "differences": { JSONArray a = new JSONArray(); double tv = 0; for (JSONObject it : stItems(id, null)) { double diff = it.isNull("physical_qty") ? -it.optDouble("system_qty") : it.optDouble("physical_qty") - it.optDouble("system_qty"); if (Math.abs(diff) < 0.0001) continue; it.put("difference", diff); JSONObject bt = one("SELECT buy_price FROM batches WHERE id=?", it.optLong("batch_id")); double v = diff * (bt == null ? 0 : bt.optDouble("buy_price")); it.put("value_diff", v); tv += v; a.put(it); } return obj("items", a, "total_value_diff", tv); }
            case "item-by-barcode": { JSONObject p = Db.productByBarcode(seg.length > 4 ? java.net.URLDecoder.decode(seg[4], "UTF-8") : ""); if (p == null) return obj("items", new JSONArray()); JSONObject o = new JSONObject(); o.put("product", p); o.put("items", arr(stItems(id, p.optLong("id")))); return o; }
        }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    static List<JSONObject> stItems(long id, Long productId) throws Exception { List<JSONObject> out = new ArrayList<>(); for (JSONObject it : rows(productId == null ? "SELECT * FROM stocktake_items WHERE st=? ORDER BY id" : "SELECT * FROM stocktake_items WHERE st=? AND product_id=? ORDER BY id", productId == null ? new Object[]{id} : new Object[]{id, productId})) { JSONObject p = Db.productById(it.optLong("product_id")); it.put("product_name", p == null ? "کالا #" + it.optLong("product_id") : p.optString("name")); it.put("barcode", p == null ? "" : p.optString("barcode")); JSONObject bt = one("SELECT batch_number FROM batches WHERE id=?", it.optLong("batch_id")); it.put("batch_number", bt == null ? "" : bt.optString("batch_number")); if (!it.isNull("physical_qty")) it.put("difference", it.optDouble("physical_qty") - it.optDouble("system_qty")); out.add(it); } return out; }

    /* ===================== warehouses ===================== */
    static Object warehouses(String method, String[] seg, JSONObject b) throws Exception {
        if (seg.length == 1) { if ("POST".equals(method)) exec("INSERT INTO warehouses(name,code,address,is_default) VALUES(?,?,?,0)", b.optString("name"), b.optString("code"), b.optString("address")); JSONArray a = new JSONArray(); for (JSONObject w : rows("SELECT * FROM warehouses ORDER BY id")) { w.put("is_default", w.optInt("is_default") == 1); JSONObject t = one("SELECT IFNULL(SUM(current_qty),0) AS q, IFNULL(SUM(current_qty*buy_price),0) AS v FROM batches WHERE status='ACTIVE' AND IFNULL(warehouse_id,1)=?", w.optLong("id")); w.put("total_qty", t.optDouble("q")); w.put("stock_value", t.optDouble("v")); w.put("locations", arr(rows("SELECT * FROM locations WHERE warehouse_id=?", w.optLong("id")))); a.put(w); } return a; }
        if ("transfer".equals(seg[1])) { long bid = b.optLong("batch_id"); JSONObject bt = one("SELECT * FROM batches WHERE id=?", bid); if (bt == null) throw new Api.ApiError(404, "NOT_FOUND", "بچ نیست"); double q = b.optDouble("quantity"); if (q <= 0 || q > bt.optDouble("current_qty")) throw new Api.ApiError(400, "QTY", "مقدار انتقال نامعتبر"); long to = b.optLong("to_warehouse_id"); if (q >= bt.optDouble("current_qty") - 0.0001) exec("UPDATE batches SET warehouse_id=? WHERE id=?", to, bid); else { exec("UPDATE batches SET current_qty=current_qty-? WHERE id=?", q, bid); JSONObject nb = Db.localBatch(bt.optLong("product_id"), q, bt.optDouble("sell_price"), bt.optDouble("consumer_price"), bt.optDouble("buy_price"), bt.isNull("expiry_date") ? null : bt.optString("expiry_date")); exec("UPDATE batches SET warehouse_id=?, batch_number=? WHERE id=?", to, bt.optString("batch_number") + "-T", nb.optLong("id")); } refreshBatchJson(bt.optLong("product_id")); exec("INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,reason,user,created_at) VALUES(?,?,'TRANSFER_OUT',?,'Warehouse',?,?,?,?)", bt.optLong("product_id"), bid, -q, String.valueOf(to), b.optString("reason"), Screens.userName(), Db.now()); exec("INSERT INTO movements(product_id,batch_id,movement_type,quantity,reference_type,reference_id,reason,user,created_at) VALUES(?,?,'TRANSFER_IN',?,'Warehouse',?,?,?,?)", bt.optLong("product_id"), bid, q, String.valueOf(to), b.optString("reason"), Screens.userName(), Db.now()); return obj("ok", true); }
        long id = Long.parseLong(seg[1]); if (seg.length > 2 && "locations".equals(seg[2])) { exec("INSERT INTO locations(warehouse_id,name) VALUES(?,?)", id, b.optString("name")); return arr(rows("SELECT * FROM locations WHERE warehouse_id=?", id)); }
        return one("SELECT * FROM warehouses WHERE id=?", id);
    }

    /* ===================== accounting (double-entry journal on the phone) ===================== */
    static final String[][] ACCOUNTS = {{"1000", "دارایی‌ها", "1"}, {"1010", "صندوق", "0"}, {"1020", "بانک", "0"}, {"1030", "کارت‌خوان", "0"}, {"1100", "حساب‌های دریافتنی (مشتریان)", "0"}, {"1200", "موجودی کالا", "0"}, {"2000", "بدهی‌ها", "1"}, {"2100", "حساب‌های پرداختنی (تأمین‌کنندگان)", "0"}, {"2200", "چک‌های پرداختنی", "0"}, {"3000", "سرمایه", "1"}, {"3010", "سرمایهٔ مالک", "0"}, {"4000", "درآمد فروش", "0"}, {"5000", "بهای تمام‌شدهٔ کالای فروخته‌شده", "0"}, {"6000", "هزینه‌ها", "0"}};
    static String payAcc(String m) { return "CARD".equals(m) ? "1030" : "TRANSFER".equals(m) || "BANK".equals(m) ? "1020" : "CREDIT".equals(m) ? "1100" : "1010"; }
    static String accName(String code) { for (String[] a : ACCOUNTS) if (a[0].equals(code)) return a[1]; return code; }
    /** lines: {code, debit, credit} */
    public static void journal(String kind, String desc, double total, String ref, String[][] lines) {
        try { if (ref != null && one("SELECT id FROM journal WHERE ref=?", ref) != null) return; JSONArray ls = new JSONArray(); for (String[] l : lines) { JSONObject o = new JSONObject(); o.put("code", l[0]); o.put("name", accName(l[0])); o.put("debit", Double.parseDouble(l[1])); o.put("credit", Double.parseDouble(l[2])); ls.put(o); } JSONObject n = one("SELECT IFNULL(MAX(number),0)+1 AS n FROM journal"); exec("INSERT INTO journal(number,date,description,kind,status,total,lines,ref) VALUES(?,?,?,?,'POSTED',?,?,?)", n.optInt("n"), Db.now(), desc, kind, total, ls.toString(), ref); } catch (Exception ignore) {}
    }
    /** sale posting — called from Db.localSale. */
    public static void postSale(String no, double total, double cogs, JSONArray pays) {
        try { List<String[]> ls = new ArrayList<>(); for (int i = 0; pays != null && i < pays.length(); i++) { JSONObject p = pays.optJSONObject(i); if (p.optDouble("amount") <= 0) continue; ls.add(new String[]{payAcc(p.optString("method")), String.valueOf(p.optDouble("amount")), "0"}); } ls.add(new String[]{"4000", "0", String.valueOf(total)}); if (cogs > 0) { ls.add(new String[]{"5000", String.valueOf(cogs), "0"}); ls.add(new String[]{"1200", "0", String.valueOf(cogs)}); } journal("SALE", "فروش " + no, total, "Invoice:" + no, ls.toArray(new String[0][])); } catch (Exception ignore) {}
    }
    static void reverseJournal(String ref, String desc) { try { JSONObject j = one("SELECT * FROM journal WHERE ref=? AND status='POSTED'", ref); if (j == null) return; JSONArray ls = new JSONArray(j.optString("lines", "[]")); List<String[]> rev = new ArrayList<>(); for (int i = 0; i < ls.length(); i++) { JSONObject l = ls.optJSONObject(i); rev.add(new String[]{l.optString("code"), String.valueOf(l.optDouble("credit")), String.valueOf(l.optDouble("debit"))}); } exec("UPDATE journal SET status='REVERSED' WHERE id=?", j.optLong("id")); journal("REVERSAL", desc, j.optDouble("total"), ref + ":rev" + System.currentTimeMillis(), rev.toArray(new String[0][])); } catch (Exception ignore) {} }
    static double acc(String code, String from, String to) { double d = 0; for (JSONObject j : rows("SELECT lines FROM journal WHERE status='POSTED'" + (from == null ? "" : " AND date>=?") + (to == null ? "" : " AND date<=?"), from == null ? (to == null ? new Object[0] : new Object[]{to + "T23:59:59"}) : (to == null ? new Object[]{from} : new Object[]{from, to + "T23:59:59"}))) { try { JSONArray ls = new JSONArray(j.optString("lines", "[]")); for (int i = 0; i < ls.length(); i++) { JSONObject l = ls.optJSONObject(i); if (l.optString("code").equals(code) || (code.endsWith("000") && l.optString("code").startsWith(code.substring(0, 1)))) d += l.optDouble("debit") - l.optDouble("credit"); } } catch (Exception ignore) {} } return d; }
    static Object accounting(String method, String[] seg, JSONObject q, JSONObject b) throws Exception {
        String what = seg[1]; String m0 = Jalali.daysAgoIso(30);
        switch (what) {
            case "overview": { JSONObject o = new JSONObject(); o.put("cash", acc("1010", null, null)); o.put("bank", acc("1020", null, null)); o.put("card", acc("1030", null, null)); o.put("receivables", acc("1100", null, null)); o.put("payables", -acc("2100", null, null) - acc("2200", null, null)); JSONObject mo = new JSONObject(); double rev = -acc("4000", m0, null), cogs = acc("5000", m0, null), exp = acc("6000", m0, null); mo.put("revenue", rev); mo.put("cogs", cogs); mo.put("expenses", exp); mo.put("net_profit", rev - cogs - exp); mo.put("gross_margin_pct", rev > 0 ? Math.round((rev - cogs) * 1000 / rev) / 10.0 : 0); o.put("month", mo); JSONObject iv = one("SELECT IFNULL(SUM(current_qty*buy_price),0) AS v FROM batches WHERE status='ACTIVE'"); o.put("inventory_value", iv.optDouble("v")); JSONObject cq = new JSONObject(); JSONObject rc = one("SELECT COUNT(*) AS n, IFNULL(SUM(amount),0) AS a FROM cheques WHERE direction='RECEIVED' AND status='PENDING'"); JSONObject ic = one("SELECT COUNT(*) AS n, IFNULL(SUM(amount),0) AS a FROM cheques WHERE direction='ISSUED' AND status='PENDING'"); cq.put("received_count", rc.optInt("n")); cq.put("received_pending", rc.optDouble("a")); cq.put("issued_count", ic.optInt("n")); cq.put("issued_pending", ic.optDouble("a")); cq.put("overdue", arr(rows("SELECT * FROM cheques WHERE status='PENDING' AND due_date<?", Jalali.todayIso()))); o.put("cheques", cq); return o; }
            case "cash-sessions": {
                if (seg.length == 2) { if ("GET".equals(method)) return arr(rows("SELECT * FROM cash_sessions ORDER BY id DESC LIMIT 30")); }
                if (seg.length > 2 && "current".equals(seg[2])) { JSONObject s = one("SELECT * FROM cash_sessions WHERE status='OPEN' ORDER BY id DESC LIMIT 1"); if (s == null) return JSONObject.NULL; JSONObject cs = one("SELECT IFNULL(SUM(total),0) AS t FROM invoices WHERE at>=? AND status<>'VOID' AND payment IN ('CASH','MIXED')", s.optString("opened_at")); s.put("cash_sales", cs.optDouble("t")); s.put("expected_cash", s.optDouble("opening_float") + cs.optDouble("t")); return s; }
                if (seg.length > 2 && "open".equals(seg[2])) { if (one("SELECT id FROM cash_sessions WHERE status='OPEN'") != null) throw new Api.ApiError(409, "OPEN", "یک شیفت باز است"); exec("INSERT INTO cash_sessions(opened_at,opening_float,status) VALUES(?,?,'OPEN')", Db.now(), b.optDouble("opening_float", 0)); audit("CASH_OPEN", "CashSession", "", null, b); return one("SELECT * FROM cash_sessions ORDER BY id DESC LIMIT 1"); }
                long id = Long.parseLong(seg[2]); if (seg.length > 3 && "close".equals(seg[3])) { JSONObject s = one("SELECT * FROM cash_sessions WHERE id=?", id); JSONObject cs = one("SELECT IFNULL(SUM(total),0) AS t FROM invoices WHERE at>=? AND status<>'VOID' AND payment IN ('CASH','MIXED')", s.optString("opened_at")); double expected = s.optDouble("opening_float") + cs.optDouble("t"), counted = b.optDouble("counted_cash", expected); exec("UPDATE cash_sessions SET closed_at=?, counted_cash=?, expected_cash=?, difference=?, status='CLOSED', note=? WHERE id=?", Db.now(), counted, expected, counted - expected, b.optString("note"), id); audit("CASH_CLOSE", "CashSession", String.valueOf(id), expected, counted); return one("SELECT * FROM cash_sessions WHERE id=?", id); }
                return one("SELECT * FROM cash_sessions WHERE id=?", id); }
            case "expense-categories": if ("POST".equals(method)) exec("INSERT INTO expense_categories(name) VALUES(?)", b.optString("name")); return arr(rows("SELECT * FROM expense_categories ORDER BY name"));
            case "expenses": { if ("POST".equals(method)) { exec("INSERT INTO expenses(category_id,amount,description,paid_from,expense_date) VALUES(?,?,?,?,?)", b.optLong("category_id"), b.optDouble("amount"), b.optString("description"), b.optString("paid_from", "CASH"), b.optString("expense_date", Db.now())); JSONObject e = one("SELECT * FROM expenses ORDER BY id DESC LIMIT 1"); journal("EXPENSE", "هزینه: " + b.optString("description"), b.optDouble("amount"), "Expense:" + e.optLong("id"), new String[][]{{"6000", String.valueOf(b.optDouble("amount")), "0"}, {payAcc(b.optString("paid_from", "CASH")), "0", String.valueOf(b.optDouble("amount"))}}); audit("EXPENSE", "Expense", String.valueOf(e.optLong("id")), null, b); } JSONArray a = new JSONArray(); double t = 0; for (JSONObject e : rows("SELECT e.*, c.name AS category_name FROM expenses e LEFT JOIN expense_categories c ON c.id=e.category_id ORDER BY e.id DESC LIMIT 200")) { t += e.optDouble("amount"); a.put(e); } return obj("total", t, "items", a); }
            case "suppliers": { if (seg.length == 2) { if ("POST".equals(method)) exec("INSERT INTO suppliers(name,phone,address,balance) VALUES(?,?,?,0)", b.optString("name"), b.optString("phone"), b.optString("address")); return arr(rows("SELECT * FROM suppliers ORDER BY name")); } long id = Long.parseLong(seg[2]); if (seg.length > 3 && "pay".equals(seg[3])) { exec("UPDATE suppliers SET balance=balance-? WHERE id=?", b.optDouble("amount"), id); journal("SUPPLIER_PAY", "پرداخت به تأمین‌کننده #" + id, b.optDouble("amount"), "SupPay:" + id + ":" + System.currentTimeMillis(), new String[][]{{"2100", String.valueOf(b.optDouble("amount")), "0"}, {payAcc(b.optString("method", "CASH")), "0", String.valueOf(b.optDouble("amount"))}}); audit("SUPPLIER_PAY", "Supplier", String.valueOf(id), null, b); } return one("SELECT * FROM suppliers WHERE id=?", id); }
            case "cheques": { if (seg.length == 2) { if ("POST".equals(method)) { exec("INSERT INTO cheques(direction,number,amount,due_date,bank_name,party_name,status,created_at) VALUES(?,?,?,?,?,?,'PENDING',?)", b.optString("direction", "RECEIVED"), b.optString("number"), b.optDouble("amount"), b.optString("due_date"), b.optString("bank_name"), b.optString("party_name"), Db.now()); audit("CHEQUE_CREATE", "Cheque", b.optString("number"), null, b); } return arr(rows("SELECT * FROM cheques ORDER BY due_date")); } long id = Long.parseLong(seg[2]); JSONObject ch = one("SELECT * FROM cheques WHERE id=?", id); if (ch == null) throw new Api.ApiError(404, "NOT_FOUND", "چک نیست"); if (seg.length > 3) { boolean rec = "RECEIVED".equals(ch.optString("direction")); if ("clear".equals(seg[3])) { exec("UPDATE cheques SET status='CLEARED' WHERE id=?", id); journal("CHEQUE", "وصول چک " + ch.optString("number"), ch.optDouble("amount"), "Cheque:" + id, rec ? new String[][]{{"1020", String.valueOf(ch.optDouble("amount")), "0"}, {"1100", "0", String.valueOf(ch.optDouble("amount"))}} : new String[][]{{"2200", String.valueOf(ch.optDouble("amount")), "0"}, {"1020", "0", String.valueOf(ch.optDouble("amount"))}}); } if ("bounce".equals(seg[3])) exec("UPDATE cheques SET status='BOUNCED' WHERE id=?", id); audit("CHEQUE_" + seg[3].toUpperCase(), "Cheque", ch.optString("number"), null, null); } return one("SELECT * FROM cheques WHERE id=?", id); }
            case "journal": { if (seg.length == 2) { JSONArray a = new JSONArray(); for (JSONObject j : rows("SELECT * FROM journal ORDER BY id DESC LIMIT " + q.optInt("limit", 60))) { j.put("lines", new JSONArray(j.optString("lines", "[]"))); a.put(j); } return a; } long id = Long.parseLong(seg[2]); JSONObject j = one("SELECT * FROM journal WHERE id=?", id); if (seg.length > 3 && "reverse".equals(seg[3])) { reverseJournal(j.optString("ref"), "معکوس سند " + j.optInt("number") + ": " + b.optString("reason")); audit("JOURNAL_REVERSE", "Journal", String.valueOf(id), null, b); } return one("SELECT * FROM journal WHERE id=?", id); }
            case "trial-balance": { JSONArray rows = new JSONArray(); double td = 0, tc = 0; for (String[] a : ACCOUNTS) { double bal = acc(a[0], null, null); JSONObject r = new JSONObject(); r.put("code", a[0]); r.put("name", a[1]); r.put("is_group", "1".equals(a[2])); r.put("debit", bal > 0 ? bal : 0); r.put("credit", bal < 0 ? -bal : 0); r.put("balance", bal); if (!"1".equals(a[2])) { td += bal > 0 ? bal : 0; tc += bal < 0 ? -bal : 0; } rows.put(r); } return obj("rows", rows, "total_debit", td, "total_credit", tc, "balanced", Math.abs(td - tc) < 1); }
            case "income-statement": { String from = q.optString("start", m0), to = q.optString("end", Jalali.todayIso()); double rev = -acc("4000", from, to), cogs = acc("5000", from, to), exp = acc("6000", from, to); JSONObject o = new JSONObject(); o.put("period", Ui.jdate(from) + " تا " + Ui.jdate(to)); o.put("revenue", rev); o.put("cogs", cogs); o.put("gross_profit", rev - cogs); o.put("expenses", exp); o.put("net_profit", rev - cogs - exp); JSONArray ex = new JSONArray(); for (JSONObject e : rows("SELECT c.name, IFNULL(SUM(e.amount),0) AS amount FROM expenses e LEFT JOIN expense_categories c ON c.id=e.category_id WHERE e.expense_date BETWEEN ? AND ? GROUP BY c.name", from, to + "T23:59:59")) ex.put(e); o.put("expense_breakdown", ex); return o; }
            case "balance-sheet": { JSONObject o = new JSONObject(); JSONObject as = new JSONObject(); for (String c : new String[]{"1010", "1020", "1030", "1100", "1200"}) as.put(accName(c), acc(c, null, null)); JSONObject li = new JSONObject(); for (String c : new String[]{"2100", "2200"}) li.put(accName(c), -acc(c, null, null)); double ta = 0, tl = 0; java.util.Iterator<String> it = as.keys(); while (it.hasNext()) ta += as.optDouble(it.next()); it = li.keys(); while (it.hasNext()) tl += li.optDouble(it.next()); o.put("assets", as); o.put("liabilities", li); o.put("total_assets", ta); o.put("total_liabilities", tl); o.put("equity", ta - tl); return o; }
            case "accounts": { JSONArray a = new JSONArray(); for (String[] ac : ACCOUNTS) { JSONObject r = new JSONObject(); r.put("code", ac[0]); r.put("name", ac[1]); r.put("is_postable", !"1".equals(ac[2])); r.put("balance", acc(ac[0], null, null)); a.put(r); } return a; }
        }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }

    /* ===================== reports ===================== */
    static Object reports(String[] seg, JSONObject q) throws Exception {
        String what = seg[1]; String today = Jalali.todayIso();
        switch (what) {
            case "dashboard": {
                JSONObject d = new JSONObject(); JSONObject sales = new JSONObject(); JSONObject t = one("SELECT COUNT(*) AS n, IFNULL(SUM(total),0) AS s FROM invoices WHERE substr(at,1,10)=? AND status<>'VOID'", today); sales.put("today", t.optDouble("s")); sales.put("invoice_count_today", t.optInt("n")); JSONObject m = one("SELECT IFNULL(SUM(total),0) AS s FROM invoices WHERE at>=? AND status<>'VOID'", Jalali.daysAgoIso(30)); sales.put("month", m.optDouble("s")); d.put("sales", sales);
                JSONObject inv = new JSONObject(); inv.put("product_count", Db.count("products")); JSONObject iv = one("SELECT IFNULL(SUM(current_qty*buy_price),0) AS v FROM batches WHERE status='ACTIVE'"); inv.put("value", iv.optDouble("v")); int low = 0, none = 0; for (JSONObject r : Db.stockRows()) { if (r.optDouble("total_stock") <= 0) none++; else if (r.optDouble("total_stock") <= r.optDouble("min_stock_alert")) low++; } inv.put("low_stock_count", low); inv.put("no_stock_count", none); d.put("inventory", inv);
                JSONObject rec = new JSONObject(); double debt = 0; int dn = 0; for (JSONObject c : rows("SELECT customer_id, SUM(CASE WHEN entry_type IN ('CHARGE','ADJUSTMENT_DEBIT') THEN amount ELSE -amount END) AS b FROM ledger GROUP BY customer_id")) if (c.optDouble("b") > 0.5) { debt += c.optDouble("b"); dn++; } rec.put("customer_debt", debt); rec.put("debtor_count", dn); JSONObject pn = one("SELECT COUNT(*) AS n, IFNULL(SUM(total),0) AS s FROM invoices WHERE payment_status='PENDING' AND status<>'VOID'"); rec.put("pending_count", pn.optInt("n")); rec.put("pending_amount", pn.optDouble("s")); d.put("receivables", rec);
                d.put("expiry", expiryBuckets()); JSONObject pr = new JSONObject(); JSONObject tp = one("SELECT IFNULL(SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount),0) AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE substr(i.at,1,10)=? AND i.status<>'VOID'", today); JSONObject mp = one("SELECT IFNULL(SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount),0) AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE i.at>=? AND i.status<>'VOID'", Jalali.daysAgoIso(30)); pr.put("today", tp.optDouble("p")); pr.put("month", mp.optDouble("p")); d.put("profit", pr);
                JSONArray top = new JSONArray(); for (JSONObject r : rows("SELECT ii.product_id, SUM(ii.qty) AS qty, SUM(ii.subtotal) AS revenue FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE i.status<>'VOID' AND i.at>=? GROUP BY ii.product_id ORDER BY revenue DESC LIMIT 5", Jalali.daysAgoIso(30))) { JSONObject p = Db.productById(r.optLong("product_id")); r.put("name", p == null ? "کالا" : p.optString("name")); top.put(r); } d.put("top_products", top);
                JSONArray trend = new JSONArray(); for (int i = 6; i >= 0; i--) { String day = Jalali.daysAgoIso(i); JSONObject s = one("SELECT IFNULL(SUM(total),0) AS s, COUNT(*) AS n FROM invoices WHERE substr(at,1,10)=? AND status<>'VOID'", day); JSONObject o = new JSONObject(); o.put("date", day); o.put("label", Ui.jdate(day)); o.put("sales", s.optDouble("s")); o.put("count", s.optInt("n")); trend.put(o); } d.put("trend", trend);
                JSONArray ri = new JSONArray(); for (JSONObject r : rows("SELECT rowid AS id,* FROM invoices ORDER BY at DESC LIMIT 5")) { JSONObject o = new JSONObject(); o.put("invoice_number", r.optString("invoice_number").isEmpty() || r.isNull("invoice_number") ? r.optString("local_no") : r.optString("invoice_number")); o.put("created_at", r.optString("at")); o.put("total", r.optDouble("total")); o.put("status", r.optString("status", "PAID")); ri.put(o); } d.put("recent_invoices", ri);
                JSONObject sys = new JSONObject(); sys.put("version", Version.NAME); sys.put("status", "OK"); android.os.StatFs st = new android.os.StatFs(android.os.Environment.getDataDirectory().getPath()); sys.put("disk_free_gb", Math.round(st.getAvailableBytes() / 1e8) / 10.0); sys.put("sync_queued", Db.opCount()); sys.put("sync_failed", 0); d.put("system", sys);
                JSONObject sms = new JSONObject(); sms.put("configured", SmsLocal.configured()); int pend = 0; JSONArray sq = SmsLocal.queue(); for (int i = 0; i < sq.length(); i++) if (!"SENT".equals(sq.optJSONObject(i).optString("status"))) pend++; sms.put("pending", pend); d.put("sms", sms);
                JSONObject ac = new JSONObject(); ac.put("cash", acc("1010", null, null)); ac.put("bank", acc("1020", null, null) + acc("1030", null, null)); ac.put("payables", -acc("2100", null, null)); d.put("accounting", ac); d.put("pricing", obj("price_conflict_count", 0)); return d; }
            case "sales": { String from = q.optString("start", today), to = q.optString("end", today); String grp = q.optString("group", "daily"); JSONObject o = new JSONObject(); JSONObject t = one("SELECT COUNT(*) AS n, IFNULL(SUM(total),0) AS s FROM invoices WHERE substr(at,1,10) BETWEEN ? AND ? AND status<>'VOID'", from, to); o.put("total_sales", t.optDouble("s")); o.put("invoice_count", t.optInt("n")); JSONArray g = new JSONArray(); if ("product".equals(grp)) { for (JSONObject r : rows("SELECT ii.product_id, SUM(ii.qty) AS qty, SUM(ii.subtotal) AS total FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE substr(i.at,1,10) BETWEEN ? AND ? AND i.status<>'VOID' GROUP BY ii.product_id ORDER BY total DESC", from, to)) { JSONObject p = Db.productById(r.optLong("product_id")); r.put("name", p == null ? "کالا" : p.optString("name")); g.put(r); } } else for (JSONObject r : rows("SELECT substr(at,1,10) AS date, COUNT(*) AS invoice_count, SUM(total) AS total FROM invoices WHERE substr(at,1,10) BETWEEN ? AND ? AND status<>'VOID' GROUP BY date ORDER BY date", from, to)) g.put(r); o.put("groups", g); return o; }
            case "cashiers": { JSONArray a = new JSONArray(); for (JSONObject r : rows("SELECT IFNULL(user,'—') AS username, COUNT(*) AS invoice_count, SUM(total) AS total_sales, SUM(discount) AS total_discount FROM invoices WHERE status<>'VOID' GROUP BY user")) { JSONObject p = one("SELECT IFNULL(SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount),0) AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE IFNULL(i.user,'—')=? AND i.status<>'VOID'", r.optString("username")); r.put("profit", p.optDouble("p")); a.put(r); } return a; }
            case "inventory": { JSONArray a = new JSONArray(); for (JSONObject r : Db.stockRows()) { JSONObject v = one("SELECT IFNULL(SUM(current_qty*buy_price),0) AS v FROM batches WHERE product_id=? AND status='ACTIVE'", r.optLong("product_id")); r.put("total_qty", r.optDouble("total_stock")); r.put("value_at_cost", v.optDouble("v")); a.put(r); } return a; }
            case "expiry": return expiryBuckets();
            case "low-stock": { JSONArray a = new JSONArray(); for (JSONObject r : Db.stockRows()) if (r.optDouble("total_stock") <= r.optDouble("min_stock_alert")) a.put(r); return a; }
            case "batches": { JSONArray a = new JSONArray(); for (JSONObject bt : rows("SELECT * FROM batches WHERE status='ACTIVE' ORDER BY (expiry_date IS NULL), expiry_date LIMIT 300")) { JSONObject p = Db.productById(bt.optLong("product_id")); JSONObject o = new JSONObject(); o.put("product_name", p == null ? "" : p.optString("name")); o.put("batch_number", bt.optString("batch_number")); o.put("quantity", bt.optDouble("current_qty")); o.put("buy_price", bt.optDouble("buy_price")); o.put("sell_price", bt.optDouble("sell_price")); o.put("expiry_date", bt.isNull("expiry_date") ? JSONObject.NULL : bt.optString("expiry_date")); o.put("received_at", bt.optString("received_at")); a.put(o); } return a; }
            case "profit": { JSONArray a = new JSONArray(); for (JSONObject r : rows("SELECT ii.product_id, ii.batch_id, SUM(ii.qty) AS qty, SUM(ii.subtotal) AS revenue, SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount) AS profit FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE i.status<>'VOID' GROUP BY ii.product_id, ii.batch_id ORDER BY profit DESC")) a.put(r); return a; }
            case "purchase-cost": { JSONArray a = new JSONArray(); for (JSONObject r : rows("SELECT substr(IFNULL(received_at,updated_at),1,7) AS month, COUNT(*) AS count, SUM(IFNULL(quantity_received,current_qty)*buy_price) AS total_cost FROM batches GROUP BY month ORDER BY month DESC")) a.put(r); return a; }
            case "adjustments": return arr(rows("SELECT m.*, (SELECT name FROM products p WHERE p.id=m.product_id) AS product_name FROM movements m WHERE movement_type IN ('ADJUSTMENT','WASTE') ORDER BY id DESC LIMIT 200"));
            case "stocktakes": { JSONArray a = new JSONArray(); for (JSONObject st : rows("SELECT * FROM stocktakes ORDER BY id DESC")) { JSONObject t = one("SELECT COUNT(*) AS items, SUM(physical_qty IS NOT NULL) AS counted, IFNULL(SUM(CASE WHEN physical_qty IS NOT NULL THEN physical_qty-system_qty ELSE 0 END),0) AS difference FROM stocktake_items WHERE st=?", st.optLong("id")); st.put("items", t.optInt("items")); st.put("counted", t.optInt("counted")); st.put("difference", t.optDouble("difference")); a.put(st); } return a; }
        }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    static JSONObject expiryBuckets() throws Exception {
        JSONObject o = new JSONObject(); String[] keys = {"EXPIRED", "EXPIRING_TODAY", "EXPIRING_3_DAYS", "EXPIRING_7_DAYS", "EXPIRING_30_DAYS"}; for (String k : keys) o.put(k, new JSONArray());
        String today = Jalali.todayIso(); java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US); long t0 = f.parse(today).getTime();
        for (JSONObject bt : rows("SELECT * FROM batches WHERE status='ACTIVE' AND current_qty>0 AND expiry_date IS NOT NULL AND expiry_date<>'' ORDER BY expiry_date")) { long days; try { days = Math.round((f.parse(bt.optString("expiry_date").substring(0, 10)).getTime() - t0) / 86400000.0); } catch (Exception e) { continue; } String k = days < 0 ? "EXPIRED" : days == 0 ? "EXPIRING_TODAY" : days <= 3 ? "EXPIRING_3_DAYS" : days <= 7 ? "EXPIRING_7_DAYS" : days <= 30 ? "EXPIRING_30_DAYS" : null; if (k == null) continue; JSONObject p = Db.productById(bt.optLong("product_id")); bt.put("product_name", p == null ? "" : p.optString("name")); bt.put("barcode", p == null ? "" : p.optString("barcode")); bt.put("days_left", days); o.optJSONArray(k).put(bt); }
        return o;
    }

    /* ===================== hardware / diagnostics / sms / support ===================== */
    static Object hardware(String method, String[] seg, JSONObject b) throws Exception {
        if (seg.length == 1) { if ("POST".equals(method)) { JSONArray a = new JSONArray(Db.kv("hw_devices") == null ? "[]" : Db.kv("hw_devices")); b.put("id", a.length() + 1); b.put("is_enabled", true); a.put(b); Db.kv("hw_devices", a.toString()); } return new JSONArray(Db.kv("hw_devices") == null ? "[]" : Db.kv("hw_devices")); }
        switch (seg[1]) {
            case "health": { boolean bt = false; try { android.bluetooth.BluetoothAdapter ad = android.bluetooth.BluetoothAdapter.getDefaultAdapter(); bt = ad != null && ad.isEnabled(); } catch (Exception ignore) {} return obj("printer", bt ? "CONNECTED" : "DISCONNECTED", "scanner", "CONNECTED", "cash_drawer", "UNKNOWN", "note", "چاپگر: از طریق بلوتوث/اشتراک‌گذاری رسید"); }
            case "test": { if (seg.length > 2 && "print".equals(seg[2])) { JSONObject fake = new JSONObject(); fake.put("invoice_number", "TEST"); fake.put("created_at", Db.now()); fake.put("cashier", Screens.userName()); fake.put("items", new JSONArray()); fake.put("subtotal", 0); fake.put("total_amount", 0); fake.put("payment_method", "CASH"); String txt = receipt(fake); Api.ui(() -> { try { android.content.Intent i = new android.content.Intent(android.content.Intent.ACTION_SEND); i.setType("text/plain"); i.putExtra(android.content.Intent.EXTRA_TEXT, txt); android.content.Intent ch = android.content.Intent.createChooser(i, "چاپ آزمایشی"); ch.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK); Ui.ctx.startActivity(ch); } catch (Exception ignore) {} }); return obj("message", "رسید آزمایشی برای چاپگر بلوتوثی/اشتراک ارسال شد"); } return obj("message", "کشوی پول فقط با رایانه/چاپگر ESC/POS قابل فرمان است"); }
            case "scanner": return new JSONArray().put(obj("name", "دوربین گوشی (ZXing)", "connection", "camera"));
        }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    static Object diagnostics(String method, String[] seg, JSONObject q) throws Exception {
        if ("history".equals(seg[1])) return new JSONArray(Db.kv("diag_history") == null ? "[]" : Db.kv("diag_history"));
        if ("sync".equals(seg[1])) { if (seg.length > 2 && "run".equals(seg[2])) { Sync.kick(); Api.bg(SmsLocal::flush); } return obj("pending", Db.opCount(), "failed", Db.conflicts().size()); }
        if ("runs".equals(seg[1])) { JSONArray h = new JSONArray(Db.kv("diag_history") == null ? "[]" : Db.kv("diag_history")); for (int i = 0; i < h.length(); i++) if (String.valueOf(h.optJSONObject(i).optLong("id")).equals(seg[2])) return h.optJSONObject(i); throw new Api.ApiError(404, "NOT_FOUND", ""); }
        if ("run".equals(seg[1])) {
            boolean ext = "true".equals(q.optString("include_external")); JSONArray checks = new JSONArray(); int pass = 0, fail = 0, skip = 0;
            java.util.List<String[]> cs = new java.util.ArrayList<>();
            try { Db.count("products"); cs.add(new String[]{"پایگاه دادهٔ گوشی", "PASS", Db.count("products") + " کالا، " + Db.count("batches") + " بچ، " + count("invoices") + " فاکتور"}); } catch (Exception e) { cs.add(new String[]{"پایگاه دادهٔ گوشی", "FAIL", e.getMessage()}); }
            cs.add(new String[]{"API داخلی گوشی", "PASS", "مسیرها روی خود گوشی پاسخ می‌دهند"});
            cs.add(new String[]{"لایسنس", Lic.allowed() ? "PASS" : "FAIL", Lic.allowed() ? "معتبر تا " + Ui.jdate(Lic.expires()) : Lic.reason()});
            cs.add(new String[]{"پیامک", SmsLocal.configured() ? "PASS" : "WARN", SmsLocal.configured() ? "پیکربندی کامل" : "سرویس پیامک تنظیم نشده"});
            if (ext && SmsLocal.configured()) { try { cs.add(new String[]{"اتصال به سرویس پیامک", "PASS", "اعتبار: " + SmsLocal.melipayamakCredit()}); } catch (Exception e) { cs.add(new String[]{"اتصال به سرویس پیامک", "FAIL", String.valueOf(e.getMessage())}); } } else cs.add(new String[]{"اتصال به سرویس پیامک", "SKIP", "بدون اینترنت"});
            android.os.StatFs st = new android.os.StatFs(android.os.Environment.getDataDirectory().getPath()); double gb = st.getAvailableBytes() / 1e9; cs.add(new String[]{"فضای آزاد", gb > 0.5 ? "PASS" : "WARN", String.format(java.util.Locale.US, "%.1f GB", gb)});
            cs.add(new String[]{"دوربین / اسکنر", Ui.ctx.getPackageManager().hasSystemFeature(android.content.pm.PackageManager.FEATURE_CAMERA_ANY) ? "PASS" : "FAIL", "ZXing"});
            cs.add(new String[]{"پشتیبان", Db.kv("last_backup") == null ? "WARN" : "PASS", Db.kv("last_backup") == null ? "هنوز پشتیبان گرفته نشده" : "آخرین: " + Ui.jdate(Db.kv("last_backup"))});
            cs.add(new String[]{"زمان دستگاه", "PASS", Jalali.todayLong()});
            cs.add(new String[]{"رایانهٔ فروشگاه", "SKIP", "حالت مستقل — اختیاری"});
            for (String[] c : cs) { JSONObject o = new JSONObject(); o.put("name", c[0]); o.put("status", c[1]); o.put("detail", c[2]); checks.put(o); if ("PASS".equals(c[1])) pass++; else if ("FAIL".equals(c[1])) fail++; else skip++; }
            JSONObject run = new JSONObject(); run.put("id", System.currentTimeMillis()); run.put("run_id", run.optLong("id")); run.put("started_at", Db.now()); run.put("passed", pass); run.put("failed", fail); run.put("skipped", skip); run.put("checks", checks);
            JSONArray h = new JSONArray(Db.kv("diag_history") == null ? "[]" : Db.kv("diag_history")); JSONArray nh = new JSONArray().put(run); for (int i = 0; i < Math.min(9, h.length()); i++) nh.put(h.optJSONObject(i)); Db.kv("diag_history", nh.toString()); return run;
        }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    static Object sms(String method, String[] seg, JSONObject b) throws Exception {
        if (seg.length == 1) { if ("GET".equals(method)) { JSONArray q = SmsLocal.queue(), a = new JSONArray(); for (int i = q.length() - 1; i >= 0; i--) { JSONObject m = q.optJSONObject(i); m.put("created_at", m.optString("at")); a.put(m); } return a; } }
        switch (seg[1]) {
            case "guide": { JSONObject st = new JSONObject(); st.put("provider", SmsLocal.get("sms.provider", "")); st.put("ready", SmsLocal.configured()); JSONArray miss = new JSONArray(); if (!SmsLocal.configured()) { if (SmsLocal.get("sms.provider", "").isEmpty()) miss.put("sms.provider"); else { if (SmsLocal.get("sms.username", "").isEmpty()) miss.put("sms.username"); if (SmsLocal.get("sms.password", "").isEmpty()) miss.put("sms.password"); } } st.put("missing", miss); JSONArray steps = new JSONArray(); int n = 1; for (String[] g : SmsLocal.GUIDE) { JSONObject s = new JSONObject(); s.put("n", n++); s.put("title", g[0]); s.put("text", g[1]); steps.put(s); } return obj("state", st, "steps", steps); }
            case "send": SmsLocal.enqueueAndSend(b.optString("phone"), b.optString("text"), "manual"); return obj("ok", true);
            case "dispatch": return obj("sent", SmsLocal.flush());
            case "test-connection": try { return obj("status", "OK", "message", "اعتبار پنل: " + SmsLocal.melipayamakCredit(), "detail", "اتصال برقرار است"); } catch (Exception e) { throw new Api.ApiError(502, "SMS", "خطا: " + e.getMessage()); }
            case "templates": { JSONArray a = new JSONArray(); String[][] T = {{"invoice", "sms.template.invoice", "{store} {invoice} {amount} {currency}"}, {"coupon", "sms.template.coupon", "{store} {code} {until}"}, {"debt_reminder", "sms.template.debt_reminder", "{customer} {store} {amount} {currency}"}, {"low_stock", "sms.template.low_stock", "{store} {count} {items}"}, {"daily_report", "sms.template.daily_report", "{store} {date} {invoices} {sales} {profit} {debt} {currency}"}}; for (String[] t : T) { JSONObject o = new JSONObject(); o.put("kind", t[0]); o.put("key", t[1]); o.put("value", setting(t[1], "invoice".equals(t[0]) ? SmsLocal.DEFAULT_TEMPLATE : "")); o.put("placeholders", new JSONArray(java.util.Arrays.asList(t[2].split(" ")))); a.put(o); } return a; }
            case "daily-report": { String adm = setting("sms.admin_phone", Prefs.get("store_mobile", "")); if (adm.isEmpty()) throw new Api.ApiError(400, "NO_PHONE", "شمارهٔ مدیر تنظیم نشده"); JSONObject t = one("SELECT COUNT(*) AS n, IFNULL(SUM(total),0) AS s FROM invoices WHERE substr(at,1,10)=? AND status<>'VOID'", Jalali.todayIso()); JSONObject p = one("SELECT IFNULL(SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount),0) AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE substr(i.at,1,10)=? AND i.status<>'VOID'", Jalali.todayIso()); double debt = 0; for (JSONObject c : rows("SELECT SUM(CASE WHEN entry_type IN ('CHARGE','ADJUSTMENT_DEBIT') THEN amount ELSE -amount END) AS b FROM ledger GROUP BY customer_id")) if (c.optDouble("b") > 0) debt += c.optDouble("b"); String txt = setting("sms.template.daily_report", "{store} | گزارش {date}: {invoices} فاکتور | فروش {sales} {currency} | سود {profit} {currency} | بدهی مشتریان {debt} {currency}").replace("{store}", Prefs.get("store_name", "فروشگاه")).replace("{date}", Jalali.todayLong()).replace("{invoices}", Ui.num(t.optInt("n"))).replace("{sales}", Ui.num(t.optDouble("s"))).replace("{profit}", Ui.num(p.optDouble("p"))).replace("{debt}", Ui.num(debt)).replace("{currency}", Ui.currencyLabel); SmsLocal.enqueueAndSend(adm, txt, "daily"); return obj("ok", true); }
        }
        if (seg.length > 2 && "retry".equals(seg[2])) { SmsLocal.retry(seg[1]); return obj("ok", true); }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }
    static Object support(String method, String[] seg, JSONObject b) throws Exception {
        if ("status".equals(seg[1])) return obj("configured", true, "inbox_ready", true, "pending", 0);
        if ("types".equals(seg[1])) { JSONArray t = new JSONArray(); for (String[] x : AdminScreens.LOCAL_TYPES) t.put(obj("id", x[0], "label", x[1])); return obj("types", t, "priorities", new JSONArray().put(obj("id", "NORMAL", "label", "عادی")).put(obj("id", "HIGH", "label", "فوری"))); }
        if ("tickets".equals(seg[1]) && seg.length == 2 && "GET".equals(method)) return SupportRelay.tickets();
        if ("poll".equals(seg[1])) return obj("new", SupportRelay.poll());
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }

    /* ===================== backup / restore (phone) ===================== */
    public static java.io.File backup(android.content.Context c) throws Exception {
        java.io.File dir = new java.io.File(c.getExternalFilesDir(null), "backups"); dir.mkdirs();
        java.io.File src = c.getDatabasePath("supermarket_native.db"); java.io.File out = new java.io.File(dir, "supery-" + Db.now().replace(":", "").replace("T", "-") + ".db");
        Db.db().execSQL("VACUUM"); try (java.io.InputStream in = new java.io.FileInputStream(src); java.io.OutputStream os = new java.io.FileOutputStream(out)) { byte[] buf = new byte[65536]; int n; while ((n = in.read(buf)) > 0) os.write(buf, 0, n); }
        java.io.File[] all = dir.listFiles(); if (all != null && all.length > Integer.parseInt(setting("backup.keep", "10"))) { java.util.Arrays.sort(all, (x, y) -> Long.compare(x.lastModified(), y.lastModified())); for (int i = 0; i < all.length - 10; i++) all[i].delete(); }
        Db.kv("last_backup", Db.now()); audit("BACKUP", "Db", out.getName(), null, null); return out;
    }
    public static int bootstrapUnits() { seedUsers(); return count("units"); }

    /* ===================== SQL helpers ===================== */
    static JSONObject query(String qs) { JSONObject o = new JSONObject(); if (qs == null || qs.isEmpty()) return o; for (String kv : qs.split("&")) { int e = kv.indexOf('='); try { o.put(e < 0 ? kv : kv.substring(0, e), e < 0 ? "" : java.net.URLDecoder.decode(kv.substring(e + 1), "UTF-8")); } catch (Exception ignore) {} } return o; }
    static JSONObject obj(Object... kv) { JSONObject o = new JSONObject(); try { for (int i = 0; i + 1 < kv.length; i += 2) o.put(String.valueOf(kv[i]), kv[i + 1] == null ? JSONObject.NULL : kv[i + 1]); } catch (Exception ignore) {} return o; }
    static JSONArray arr(List<JSONObject> l) { JSONArray a = new JSONArray(); for (JSONObject o : l) a.put(o); return a; }
    static String[] args(Object... a) { String[] s = new String[a.length]; for (int i = 0; i < a.length; i++) s[i] = a[i] == null ? null : String.valueOf(a[i]); return s; }
    public static List<JSONObject> rows(String sql, Object... a) {
        List<JSONObject> out = new ArrayList<>();
        try (Cursor c = Db.db().rawQuery(sql, args(a))) { String[] cols = c.getColumnNames(); while (c.moveToNext()) { JSONObject o = new JSONObject(); for (int i = 0; i < cols.length; i++) { try { switch (c.getType(i)) { case Cursor.FIELD_TYPE_NULL: o.put(cols[i], JSONObject.NULL); break; case Cursor.FIELD_TYPE_INTEGER: o.put(cols[i], c.getLong(i)); break; case Cursor.FIELD_TYPE_FLOAT: o.put(cols[i], c.getDouble(i)); break; default: o.put(cols[i], c.getString(i)); } } catch (Exception ignore) {} } out.add(o); } }
        catch (Exception e) { android.util.Log.w("Local", "sql: " + sql + " → " + e); }
        return out;
    }
    public static JSONObject one(String sql, Object... a) { List<JSONObject> r = rows(sql, a); return r.isEmpty() ? null : r.get(0); }
    public static void exec(String sql, Object... a) { Db.db().execSQL(sql, a); }
    static int count(String table) { JSONObject r = one("SELECT COUNT(*) AS n FROM " + table); return r == null ? 0 : r.optInt("n"); }
}
