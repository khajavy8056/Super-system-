package ir.khajavy.supermarket;

import android.content.Context;
import android.content.Intent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

/**
 * v2.0 — screen registry + shared base class + the "system" screens
 * (home/dashboard, sync, device, license, cloud, about).
 * Sales screens live in {@link SalesScreens}, stock in {@link StockScreens},
 * management/system in {@link AdminScreens}.
 */
public final class Screens {
    private Screens() {}
    static JSONObject user = new JSONObject();
    static JSONObject settings = new JSONObject();

    /* ---------------- registry ---------------- */
    public static Screen create(AppActivity a, String key) {
        switch (key) {
            case "home": return new Home(a);
            case "pos": return new SalesScreens.Pos(a);
            case "held": return new SalesScreens.Held(a);
            case "invoices": return new SalesScreens.Invoices(a);
            case "customers": return new SalesScreens.Customers(a);
            case "marketing": return new SalesScreens.Marketing(a);
            case "products": return new StockScreens.Products(a);
            case "receive": return new StockScreens.Receive(a);
            case "inventory": return new StockScreens.Inventory(a);
            case "stocktake": return new StockScreens.Stocktake(a);
            case "stockops": return new StockScreens.StockOps(a);
            case "warehouses": return new StockScreens.Warehouses(a);
            case "movements": return new StockScreens.Movements(a);
            case "reports": return new AdminScreens.Reports(a);
            case "accounting": return new AdminScreens.Accounting(a);
            case "users": return new AdminScreens.Users(a);
            case "audit": return new AdminScreens.Audit(a);
            case "settings": return new AdminScreens.Settings(a);
            case "store": return new AdminScreens.Store(a);
            case "sms": return new AdminScreens.Sms(a);
            case "hardware": return new AdminScreens.Hardware(a);
            case "diagnostics": return new AdminScreens.Diagnostics(a);
            case "support": return new AdminScreens.Support(a);
            case "license": return new License(a);
            case "sync": return new SyncScreen(a);
            case "cloud": return new Cloud(a);
            case "device": return new Device(a);
            case "about": return new About(a);
            case "notifications": return new Notifications(a);
        }
        return null;
    }
    static final String[][] PERMS = {{"pos", "pos.sell"}, {"held", "pos.sell"}, {"invoices", "reports.view"}, {"customers", "customers.manage"}, {"marketing", "settings.manage"}, {"products", "products.view"}, {"receive", "batches.manage"}, {"inventory", "inventory.view"}, {"stocktake", "inventory.stocktake"}, {"stockops", "inventory.adjust"}, {"warehouses", "inventory.view"}, {"movements", "inventory.view"}, {"reports", "reports.view"}, {"accounting", "accounting.view"}, {"users", "users.manage"}, {"audit", "audit.view"}, {"settings", "settings.manage"}, {"store", "settings.manage"}, {"sms", "settings.manage"}, {"hardware", "settings.manage"}, {"diagnostics", "settings.manage"}, {"license", "settings.manage"}, {"cloud", "settings.manage"}};
    public static boolean allowed(String key) {
        String need = null; for (String[] p : PERMS) if (p[0].equals(key)) need = p[1];
        if (need == null) return true;
        JSONArray ps = user.optJSONArray("permissions"); if (ps == null) return true; // unknown yet → show, server enforces
        for (int i = 0; i < ps.length(); i++) if (need.equals(ps.optString(i))) return true;
        return false;
    }
    public static boolean can(String perm) { JSONArray ps = user.optJSONArray("permissions"); if (ps == null) return true; for (int i = 0; i < ps.length(); i++) if (perm.equals(ps.optString(i))) return true; return false; }
    public static String userName() { String n = user.optString("full_name", ""); return n.isEmpty() ? user.optString("username", "") : n; }
    public static void loadConfig(AppActivity a) {
        try { user = new JSONObject(Prefs.get("user_json", "{}")); } catch (Exception ignore) {}
        if (Api.standalone()) return;
        Api.get("/auth/me", r -> { user = (JSONObject) r; Prefs.set("user_json", user.toString()); }, e -> {});
        Api.get("/settings/currency", r -> { JSONObject c = (JSONObject) r; String code = c.optString("code", "IRR"); Ui.currencyLabel = "IRT".equals(code) ? "تومان" : "ریال"; Prefs.set("currency_label", Ui.currencyLabel); }, e -> {});
        if (Prefs.get("theme_mode", "").isEmpty()) Api.get("/settings/theme", r -> { String res = ((JSONObject) r).optString("resolved", "dark"); if (!res.equals(Prefs.get("theme_resolved", "dark"))) { Prefs.set("theme_resolved", res); a.recreate(); } }, e -> {});
        Api.get("/settings/store-profile", r -> Prefs.set("store_name", ((JSONObject) r).optString("name", "")), e -> {});
    }

    /* ---------------- base ---------------- */
    public abstract static class Screen {
        protected final AppActivity a; protected final LinearLayout body; protected final Context c;
        protected Screen(AppActivity a) { this.a = a; this.c = a; body = Ui.col(a); body.setPadding(Ui.dp(14), Ui.dp(14), Ui.dp(14), Ui.dp(24)); }
        public abstract String key();
        public abstract String title();
        public View view() { return Ui.scroll(a, body); }
        public void load() {}
        public void refresh() { load(); }
        public boolean autoRefresh() { return false; }
        protected void clear() { body.removeAllViews(); }
        protected void loading() { clear(); body.addView(Ui.empty(c, "در حال بارگذاری…")); }
        protected void offline(String what) { clear(); LinearLayout card = Ui.card(c, "رایانه در دسترس نیست"); card.addView(Ui.body(c, what + " به اتصال با رایانهٔ فروشگاه نیاز دارد. به همان شبکهٔ وای‌فای وصل شوید؛ برنامه خودش دوباره تلاش می‌کند.")); card.addView(Ui.ghost(c, "تلاش دوباره", this::load)); body.addView(card); }
        /** GET with cache/offline handling; runs cb on the main thread. */
        protected void get(String path, Consumer<Object> cb) { Api.get(path, cb::accept, e -> { if (e.offline()) offline(title()); else { clear(); body.addView(Ui.empty(c, e.getMessage())); } }); }
        protected void getQuiet(String path, Consumer<Object> cb) { Api.get(path, cb::accept, e -> {}); }
        protected void post(String path, JSONObject b, Consumer<Object> cb) { Api.post(path, b, cb::accept, e -> Ui.toast(e.getMessage())); }
        protected void patch(String path, JSONObject b, Consumer<Object> cb) { Api.patch(path, b, cb::accept, e -> Ui.toast(e.getMessage())); }
        protected void put(String path, JSONObject b, Consumer<Object> cb) { Api.put(path, b, cb::accept, e -> Ui.toast(e.getMessage())); }
        protected LinearLayout tabs(String[] labels, int active, Consumer<Integer> on) { LinearLayout r = Ui.row(c); for (int i = 0; i < labels.length; i++) { final int k = i; r.addView(Ui.chip(c, labels[i], i == active, () -> on.accept(k))); } return r; }
        protected static JSONArray arr(Object r) { return r instanceof JSONArray ? (JSONArray) r : r instanceof JSONObject ? (((JSONObject) r).optJSONArray("items") != null ? ((JSONObject) r).optJSONArray("items") : new JSONArray()) : new JSONArray(); }
        protected static String s(JSONObject o, String k) { return o == null || o.isNull(k) ? "" : o.optString(k); }
        protected static String s(JSONObject o, String k, String def) { String v = s(o, k); return v.isEmpty() ? def : v; }
        protected static double d(JSONObject o, String k) { return o == null ? 0 : o.optDouble(k, 0); }
        protected static JSONObject j(String... kv) { return Api.obj(kv); }
        protected static void putIf(JSONObject o, String k, String v) { try { if (v != null && !v.isEmpty()) o.put(k, v); } catch (Exception ignore) {} }
        protected static void putNum(JSONObject o, String k, double v) { try { o.put(k, v); } catch (Exception ignore) {} }
        protected static String dateIn(EditText e) { String v = Ui.str(e); if (v.isEmpty()) return null; String iso = Jalali.toIso(v); if (iso == null) { Ui.toast("تاریخ باید مانند ۱۴۰۴/۰۶/۱۸ باشد"); throw new IllegalArgumentException(); } return iso; }
        protected static String label(String code, String[][] map) { for (String[] m : map) if (m[0].equals(code)) return m[1]; return code; }
        protected static final String[][] PAY = {{"CASH", "نقدی"}, {"CARD", "کارت‌خوان"}, {"CREDIT", "نسیه"}, {"MIXED", "ترکیبی"}, {"TRANSFER", "کارت‌به‌کارت"}};
        protected static final String[][] INV_ST = {{"PAID", "پرداخت‌شده"}, {"PENDING", "در انتظار"}, {"VOID", "باطل"}, {"PARTIAL", "بخشی"}, {"UNPAID", "پرداخت‌نشده"}};
        protected int stColor(String st) { switch (st) { case "PAID": case "ACTIVE": case "SENT": case "COMPLETED": case "APPROVED": case "OK": case "CLEARED": case "POSTED": case "CONNECTED": return Ui.GREEN; case "VOID": case "FAILED": case "EXPIRED": case "BOUNCED": case "REJECTED": case "DISCONNECTED": case "CANCELLED": return Ui.RED; case "PENDING": case "DRAFT": case "NEW": case "IN_PROGRESS": case "WARN": case "PARTIAL": return Ui.AMBER; } return Ui.MUTED; }
    }

    /* ---------------- Home / dashboard (12 blocks) ---------------- */
    public static final class Home extends Screen {
        Home(AppActivity a) { super(a); }
        public String key() { return "home"; } public String title() { return "داشبورد"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            clear();
            LinearLayout hero = Ui.hero(c);
            LinearLayout hr = Ui.row(c); LinearLayout hcol = Ui.col(c); hcol.setLayoutParams(Ui.weight(1));
            hcol.addView(Ui.text(c, greeting() + "، " + userName(), 13, 0xDDFFFFFF, false)); hcol.addView(Ui.text(c, Prefs.get("store_name", "فروشگاه"), 21, 0xFFFFFFFF, true)); hcol.addView(Ui.text(c, "📅  " + Jalali.todayLong(), 12, 0xDDFFFFFF, false));
            hr.addView(hcol); TextView av = Ui.text(c, "🏪", 26, 0xFFFFFFFF, true); av.setGravity(android.view.Gravity.CENTER); av.setBackground(Ui.rounded(0x2EFFFFFF, 0, 16)); av.setLayoutParams(Ui.lp(Ui.dp(52), Ui.dp(52))); hr.addView(av); hero.addView(hr);
            LinearLayout quick = Ui.row(c); quick.setPadding(0, Ui.dp(14), 0, 0);
            quick.addView(qb("＋ فروش جدید", () -> a.route("pos"))); quick.addView(qb("▣ اسکن", () -> a.scan("اسکن بارکد", code -> a.open(new StockScreens.ProductDetail(a, code), true)))); quick.addView(qb("↓ ورود کالا", () -> a.route("receive")));
            hero.addView(quick); body.addView(hero);
            double[] loc = Db.todayStats();
            if (Api.standalone()) {
                double[] week = Db.weekSales();
                body.addView(Ui.grid2(c, Ui.tile(c, "↗", Ui.TEAL, "فروش امروز", Ui.money(loc[1]), Ui.spark(c, week, Ui.TEAL)), Ui.tile(c, "🏷", Ui.VIOLET, "کالاها", Ui.num(Db.count("products")), null)));
                body.addView(Ui.grid2(c, Ui.tile(c, "👤", Ui.AMBER, "مشتریان", Ui.num(Db.count("customers")), null), Ui.tile(c, "🧾", Ui.GREEN, "فاکتور امروز", Ui.num(loc[0]), null)));
                String[] tops = Db.topSellingToday(3); LinearLayout tp = Ui.card(c, "⭐ پرفروش‌ترین‌ها"); if (tops.length == 0) tp.addView(Ui.muted(c, "هنوز فروشی ثبت نشده")); else for (String t : tops) tp.addView(Ui.kv(c, t.substring(0, t.indexOf('|')), t.substring(t.indexOf('|') + 1), Ui.GOLD)); body.addView(tp);
                LinearLayout ex = Ui.card(c, "⏳ نزدیک انقضا"); int ne = Db.expiringCount(7), nx = Db.expiringCount(0); ex.addView(Ui.kv(c, "منقضی‌شده", Ui.num(nx), nx > 0 ? Ui.RED : 0)); ex.addView(Ui.kv(c, "تا ۷ روز آینده", Ui.num(ne), ne > 0 ? Ui.AMBER : 0)); ex.setOnClickListener(v -> a.route("inventory")); body.addView(ex);
                LinearLayout sa = Ui.card(c, "ℹ حالت مستقل"); sa.addView(Ui.muted(c, "این گوشی بدون رایانه کار می‌کند. هر زمان به رایانهٔ فروشگاه وصل شوید، همهٔ داده‌ها همگام می‌شود.")); body.addView(sa); return;
            }
            body.addView(Ui.empty(c, "در حال دریافت داشبورد…"));
            get("/reports/dashboard", r -> { JSONObject d = (JSONObject) r; body.removeViewAt(body.getChildCount() - 1); render(d, loc); });
        }
        static String greeting() { int h = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY); return h < 12 ? "صبح بخیر" : h < 17 ? "ظهر بخیر" : h < 20 ? "عصر بخیر" : "شب بخیر"; }
        private View qb(String s, Runnable r) { TextView t = Ui.text(c, s, 12, 0xFFFFFFFF, true); t.setGravity(android.view.Gravity.CENTER); t.setBackground(Ui.rounded(0x2EFFFFFF, 0, 14)); t.setPadding(0, Ui.dp(9), 0, Ui.dp(9)); LinearLayout.LayoutParams p = Ui.weight(1); p.setMargins(Ui.dp(3), 0, Ui.dp(3), 0); t.setLayoutParams(p); t.setOnClickListener(v -> r.run()); return t; }
        private void render(JSONObject d, double[] loc) {
            JSONObject sales = d.optJSONObject("sales"), inv = d.optJSONObject("inventory"), rec = d.optJSONObject("receivables"), sms = d.optJSONObject("sms"), sys = d.optJSONObject("system"), acc = d.optJSONObject("accounting"), exp = d.optJSONObject("expiry"), pr = d.optJSONObject("pricing"), profit = d.optJSONObject("profit");
            // 1-2 sales / invoices
            JSONArray tr0 = d.optJSONArray("trend"); double[] wk = new double[tr0 == null ? 0 : tr0.length()]; for (int i = 0; i < wk.length; i++) wk[i] = d(tr0.optJSONObject(i), "sales");
            body.addView(Ui.grid2(c, Ui.tile(c, "↗", Ui.TEAL, "فروش امروز", Ui.money(d(sales, "today")), wk.length > 0 ? Ui.spark(c, wk, Ui.TEAL) : null), Ui.tile(c, "🧾", Ui.GREEN, "فاکتورهای امروز", Ui.num(d(sales, "invoice_count_today")), null)));
            body.addView(Ui.grid2(c, Ui.tile(c, "🏷", Ui.VIOLET, "کالاها", Ui.num(d(inv, "product_count")), null), Ui.tile(c, "👤", Ui.AMBER, "مشتریان", Ui.num(Db.count("customers")), null)));
            // 3-4 month / profit
            body.addView(Ui.grid2(c, Ui.kpi(c, "فروش ماه", Ui.money(d(sales, "month")), null, Ui.TEAL), Ui.kpi(c, "سود امروز / ماه", Ui.money(d(profit, "today")), Ui.money(d(profit, "month")), Ui.VIOLET)));
            // 5-6 inventory / low stock
            int low = inv == null ? 0 : inv.optInt("low_stock_count"), none = inv == null ? 0 : inv.optInt("no_stock_count");
            body.addView(Ui.grid2(c, Ui.kpi(c, "ارزش موجودی", Ui.money(d(inv, "value")), Ui.num(d(inv, "product_count")) + " کالا", Ui.AMBER), Ui.kpi(c, "کمبود / بدون موجودی", Ui.fa(low + " / " + none), null, low + none > 0 ? Ui.RED : Ui.GREEN)));
            // 7 expiry
            LinearLayout ex = Ui.card(c, "انقضا"); int te = 0; String[][] EK = {{"EXPIRED", "منقضی"}, {"EXPIRING_TODAY", "امروز"}, {"EXPIRING_3_DAYS", "۳ روز"}, {"EXPIRING_7_DAYS", "۷ روز"}, {"EXPIRING_30_DAYS", "۳۰ روز"}};
            LinearLayout er = Ui.row(c); for (String[] k : EK) { int n = exp == null || exp.optJSONArray(k[0]) == null ? 0 : exp.optJSONArray(k[0]).length(); te += n; LinearLayout col = Ui.col(c); col.setGravity(android.view.Gravity.CENTER); col.setLayoutParams(Ui.weight(1)); col.addView(Ui.text(c, Ui.fa(String.valueOf(n)), 17, n > 0 ? ("EXPIRED".equals(k[0]) ? Ui.RED : Ui.AMBER) : Ui.TEXT, true)); col.addView(Ui.muted(c, k[1])); er.addView(col); }
            ex.addView(er); if (te == 0) ex.addView(Ui.muted(c, "هیچ کالایی نزدیک انقضا نیست")); ex.setOnClickListener(v -> a.open(new AdminScreens.Reports(a, 3), true)); body.addView(ex);
            // 8 receivables
            LinearLayout rc = Ui.card(c, "مطالبات و بدهکاران"); rc.addView(Ui.kv(c, "بدهی مشتریان", Ui.money(d(rec, "customer_debt")), Ui.AMBER)); rc.addView(Ui.kv(c, "تعداد بدهکار", Ui.num(d(rec, "debtor_count")), 0)); rc.addView(Ui.kv(c, "فاکتور در انتظار پرداخت", Ui.num(d(rec, "pending_count")) + " · " + Ui.money(d(rec, "pending_amount")), 0)); rc.setOnClickListener(v -> a.route("customers")); body.addView(rc);
            // 9 top products
            LinearLayout tp = Ui.card(c, "⭐ پرفروش‌ترین کالاها"); JSONArray top = d.optJSONArray("top_products"); if (top == null || top.length() == 0) tp.addView(Ui.muted(c, "هنوز فروشی ثبت نشده")); else for (int i = 0; i < Math.min(5, top.length()); i++) { JSONObject t = top.optJSONObject(i); tp.addView(Ui.kv(c, t.optString("name"), Ui.num(d(t, "qty")) + " · " + Ui.money(d(t, "revenue")), Ui.GOLD)); } body.addView(tp);
            // 10 trend (7 days, bar chart drawn with views)
            LinearLayout tr = Ui.card(c, "روند فروش ۷ روز"); JSONArray trend = d.optJSONArray("trend"); if (trend != null && trend.length() > 0) { double mx = 1; for (int i = 0; i < trend.length(); i++) mx = Math.max(mx, d(trend.optJSONObject(i), "sales")); LinearLayout bars = Ui.row(c); bars.setGravity(android.view.Gravity.BOTTOM); bars.setLayoutParams(Ui.lp(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(110))); for (int i = 0; i < trend.length(); i++) { JSONObject t = trend.optJSONObject(i); LinearLayout col = Ui.col(c); col.setGravity(android.view.Gravity.BOTTOM | android.view.Gravity.CENTER_HORIZONTAL); LinearLayout.LayoutParams lp = Ui.weight(1); lp.height = ViewGroup.LayoutParams.MATCH_PARENT; col.setLayoutParams(lp); View bar = new View(c); bar.setBackground(Ui.rounded(Ui.PRIMARY, 0, 4)); bar.setLayoutParams(Ui.lp(Ui.dp(14), Math.max(Ui.dp(3), (int) (Ui.dp(80) * d(t, "sales") / mx)))); col.addView(bar); TextView lb = Ui.muted(c, Ui.fa(t.optString("label").substring(3))); lb.setTextSize(10); col.addView(lb); bars.addView(col); } tr.addView(bars); } body.addView(tr);
            // 11 recent invoices
            LinearLayout ri = Ui.card(c, "آخرین فاکتورها"); JSONArray rinv = d.optJSONArray("recent_invoices"); if (rinv == null || rinv.length() == 0) ri.addView(Ui.muted(c, "—")); else for (int i = 0; i < Math.min(5, rinv.length()); i++) { JSONObject t = rinv.optJSONObject(i); ri.addView(Ui.kv(c, Ui.fa(t.optString("invoice_number")) + " · " + Ui.jdate(t.optString("created_at")).substring(11), Ui.money(d(t, "total")), stColor(t.optString("status")))); } ri.setOnClickListener(v -> a.route("invoices")); body.addView(ri);
            // 12 system + sms + accounting + pricing conflicts
            LinearLayout sy = Ui.card(c, "وضعیت سامانه"); sy.addView(Ui.kv(c, "نسخهٔ رایانه", Ui.fa(s(sys, "version")), 0)); sy.addView(Ui.kv(c, "وضعیت", s(sys, "status", "OK"), stColor(s(sys, "status", "OK")))); sy.addView(Ui.kv(c, "فضای آزاد دیسک", Ui.fa(String.valueOf(d(sys, "disk_free_gb"))) + " GB", 0)); sy.addView(Ui.kv(c, "صف همگام‌سازی رایانه", Ui.num(d(sys, "sync_queued")) + " · خطا " + Ui.num(d(sys, "sync_failed")), 0)); sy.addView(Ui.kv(c, "پیامک", (sms != null && sms.optBoolean("configured") ? "فعال" : "پیکربندی‌نشده") + " · در صف " + Ui.num(d(sms, "pending")), 0)); sy.addView(Ui.kv(c, "تعارض قیمت", Ui.num(d(pr, "price_conflict_count")), d(pr, "price_conflict_count") > 0 ? Ui.AMBER : 0)); sy.addView(Ui.kv(c, "صندوق / بانک", Ui.money(d(acc, "cash")) + " / " + Ui.money(d(acc, "bank")), 0)); sy.addView(Ui.kv(c, "بدهی به تأمین‌کننده", Ui.money(d(acc, "payables")), 0)); sy.addView(Ui.kv(c, "این گوشی امروز", Ui.num(loc[0]) + " فاکتور · " + (loc[2] > 0 ? Ui.num(loc[2]) + " در صف" : "همگام"), loc[2] > 0 ? Ui.AMBER : Ui.GREEN)); body.addView(sy);
        }
    }

    /* ---------------- Sync ---------------- */
    public static final class SyncScreen extends Screen {
        SyncScreen(AppActivity a) { super(a); }
        public String key() { return "sync"; } public String title() { return "همگام‌سازی"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            clear();
            LinearLayout st = Ui.card(c, "وضعیت");
            st.addView(Ui.kv(c, "رایانه", Api.standalone() ? "حالت مستقل" : Api.base, 0)); st.addView(Ui.kv(c, "اتصال", Api.online ? "متصل" : "قطع", Api.online ? Ui.GREEN : Ui.RED));
            st.addView(Ui.kv(c, "آخرین همگام‌سازی", Ui.jdate(Db.kv("last_sync")), 0)); st.addView(Ui.kv(c, "در صف ارسال", Ui.num(Db.opCount()), Db.opCount() > 0 ? Ui.AMBER : Ui.GREEN));
            st.addView(Ui.kv(c, "کالا / بچ / مشتری روی گوشی", Ui.fa(Db.count("products") + " / " + Db.count("batches") + " / " + Db.count("customers")), 0));
            st.addView(Ui.primary(c, "همگام‌سازی اکنون", () -> { Ui.toast("در حال همگام‌سازی…"); Sync.kick(); }));
            st.addView(Ui.ghost(c, "دریافت کامل دوبارهٔ کاتالوگ", () -> { Db.kv("cursor", null); Sync.kick(); }));
            body.addView(st);
            LinearLayout q = Ui.card(c, "صف عملیات این گوشی"); List<JSONObject> ops = Db.ops(); if (ops.isEmpty()) q.addView(Ui.muted(c, "صف خالی است — همه‌چیز روی رایانه ثبت شده")); else for (JSONObject o : ops) q.addView(Ui.item(c, s(o, "label", s(o, "type")), Ui.jdate(s(o, "created_at")) + (s(o, "last_error").isEmpty() ? "" : " · " + s(o, "last_error")), s(o, "type"), Ui.MUTED, null)); body.addView(q);
            LinearLayout cf = Ui.card(c, "موارد ردشده توسط رایانه"); List<JSONObject> cs = Db.conflicts(); if (cs.isEmpty()) cf.addView(Ui.muted(c, "موردی نیست")); else for (JSONObject o : cs) { LinearLayout it = Ui.item(c, s(o, "label"), s(o, "message") + " · " + Ui.jdate(s(o, "at")), "حذف", Ui.RED, () -> { Db.conflictDelete(o.optLong("id")); load(); }); cf.addView(it); } body.addView(cf);
            if (!Api.standalone()) { LinearLayout dv = Ui.card(c, "دستگاه‌های جفت‌شده با رایانه"); body.addView(dv); getQuiet("/mobile/devices", r -> { JSONArray ar = arr(r); for (int i = 0; i < ar.length(); i++) { JSONObject dd = ar.optJSONObject(i); boolean me = dd.optString("id").equals(Prefs.deviceIdStatic()); dv.addView(Ui.item(c, dd.optString("name") + (me ? " (این گوشی)" : ""), "کاربر " + dd.optString("user") + " · آخرین همگام " + Ui.jdate(s(dd, "last_sync_at")), dd.optBoolean("revoked") ? "لغو شده" : "فعال", dd.optBoolean("revoked") ? Ui.RED : Ui.GREEN, null)); } }); }
        }
    }

    /* ---------------- Device settings ---------------- */
    public static final class Device extends Screen {
        Device(AppActivity a) { super(a); }
        private View sw(String label, String key) { LinearLayout r = Ui.row(c); r.setPadding(0, Ui.dp(6), 0, Ui.dp(6)); TextView t = Ui.body(c, label); t.setLayoutParams(Ui.weight(1)); r.addView(t); android.widget.Switch s = new android.widget.Switch(c); s.setChecked("1".equals(Prefs.get(key, ""))); s.setOnCheckedChangeListener((b, on) -> { if (on) Biometric.prompt(a, "تأیید اثر انگشت", "برای فعال‌سازی", ok -> { if (ok) Prefs.set(key, "1"); else s.setChecked(false); }); else Prefs.set(key, ""); }); r.addView(s); return r; }
        public String key() { return "device"; } public String title() { return "تنظیمات دستگاه"; }
        public void load() {
            clear();
            LinearLayout cn = Ui.card(c, "اتصال به رایانه"); cn.addView(Ui.kv(c, "حالت", Api.standalone() ? "فقط گوشی (بدون رایانه)" : "متصل به رایانهٔ فروشگاه", 0)); cn.addView(Ui.kv(c, "آدرس فعلی", Api.standalone() ? "—" : Api.base, 0)); cn.addView(Ui.kv(c, "کلید اتصال", Prefs.get("link_key", "").isEmpty() ? "—" : Prefs.get("link_key", ""), 0)); cn.addView(Ui.kv(c, "شناسهٔ دستگاه", Prefs.deviceIdStatic() == null ? "—" : Prefs.deviceIdStatic(), 0));
            if (!Api.standalone()) cn.addView(Ui.muted(c, "اگر IP رایانه عوض شود، گوشی با «کلید اتصال» آن را در همان وای‌فای دوباره پیدا می‌کند و همگام‌سازی خودکار ادامه می‌یابد."));
            if (!Api.standalone()) cn.addView(Ui.ghost(c, "پیدا کردن رایانه در شبکه (اکنون)", () -> { Ui.toast("در حال جست‌وجو…"); Api.bg(() -> { String f = Discovery.find(Prefs.get("link_key", ""), 2500); Api.ui(() -> { if (f == null) Ui.toast("رایانه‌ای با این کلید در شبکه پیدا نشد"); else { Prefs.set("server_url", f); Api.base = f; Ui.toast("پیدا شد: " + f); Sync.kick(); load(); } }); }); }));
            cn.addView(Ui.primary(c, Api.standalone() ? "اتصال به رایانهٔ فروشگاه (QR / کد)" : "جفت‌سازی دوباره (QR / کد ۶ رقمی)", () -> { Intent i = new Intent(a, SetupActivity.class); i.putExtra("pair", true); a.startActivity(i); }));
            cn.addView(Ui.ghost(c, "تغییر آدرس رایانه", () -> Ui.prompt(c, "آدرس رایانه", "مثال: 192.168.1.10:8000", false, v -> { if (!v.isEmpty()) { String u = Prefs.normalise(v); Prefs.set("server_url", u); Api.base = u; Db.kv("cursor", null); Sync.kick(); load(); } })));
            body.addView(cn);
            // v2.3 — online relay (route 3) status/config on the phone
            if (!Api.standalone()) { LinearLayout rl = Ui.card(c, "اتصال از راه دور (رله)"); rl.addView(Ui.kv(c, "رله", Relay.available() ? Relay.label() : "تنظیم نشده (از رایانه: تنظیمات → همگام‌سازی آنلاین)", Relay.available() ? 0 : Ui.MUTED)); rl.addView(Ui.kv(c, "مسیر فعلی", Api.online ? (Relay.active ? "اینترنت / رله" : "وای‌فای فروشگاه") : (CloudSync.available() ? "آفلاین · Drive" : "آفلاین"), Api.online ? Ui.GREEN : Ui.AMBER)); rl.addView(Ui.muted(c, "ترتیب خودکار: وای‌فای فروشگاه ← رلهٔ آنلاین ← Google Drive. با تغییر IP یا شبکه، اتصال قطع نمی‌شود.")); if (Relay.available()) rl.addView(Ui.ghost(c, "آزمایش رله", () -> Api.bg(() -> { boolean ok = Relay.pcOnline(); Api.ui(() -> Ui.toast(ok ? "رایانه از طریق رله در دسترس است ✓" : "رایانه به رله وصل نیست")); }))); body.addView(rl); }
            // v2.3 — biometrics
            if (Biometric.available(a)) { LinearLayout bi = Ui.card(c, "اثر انگشت / قفل"); bi.addView(sw("باز کردن برنامه با اثر انگشت (پس از ۳۰ ثانیه دوری)", "bio_lock")); bi.addView(sw("ورود دوباره با اثر انگشت به‌جای رمز", "bio_login")); body.addView(bi); }
            LinearLayout ap = Ui.card(c, "ظاهر"); ap.addView(Ui.ghost(c, Ui.dark ? "پوستهٔ روشن" : "پوستهٔ تیره", () -> { Prefs.set("theme_resolved", Ui.dark ? "light" : "dark"); Prefs.set("theme_mode", Ui.dark ? "light" : "dark"); a.recreate(); })); ap.addView(Ui.ghost(c, "پوستهٔ خودکار (۷ صبح روشن / ۷ شب تیره)", () -> { Prefs.set("theme_mode", ""); int hr = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY); Prefs.set("theme_resolved", hr >= 7 && hr < 19 ? "light" : "dark"); a.recreate(); })); ap.addView(Ui.ghost(c, "پخش دوبارهٔ همهٔ راهنماها", () -> { Tour.resetAll(); Ui.toast("راهنماها دوباره نمایش داده می‌شوند"); })); body.addView(ap);
            LinearLayout sc = Ui.card(c, "اسکنر"); sc.addView(Ui.muted(c, "دوربین گوشی به‌صورت پیوسته بارکد را می‌خواند (EAN/UPC/Code128/QR). با هر خواندن لرزش کوتاه می‌دهد.")); sc.addView(Ui.ghost(c, "آزمایش اسکنر", () -> a.scan("آزمایش اسکنر", code -> Ui.toast("خوانده شد: " + code)))); body.addView(sc);
            LinearLayout dz = Ui.card(c, "داده‌های گوشی"); dz.addView(Ui.muted(c, "کاتالوگ و صف عملیات روی همین گوشی (SQLite) نگه داشته می‌شود تا بدون رایانه هم کار کند.")); dz.addView(Ui.danger(c, "حذف داده‌های محلی و لغو جفت‌سازی", () -> Ui.confirm(c, "همهٔ داده‌های محلی حذف می‌شود. عملیات همگام‌نشده (" + Db.opCount() + ") از بین می‌رود. ادامه؟", () -> { a.deleteDatabase("supermarket_native.db"); Prefs.clear(a); a.startActivity(new Intent(a, SetupActivity.class)); a.finish(); }))); body.addView(dz);
        }
    }

    /* ---------------- License ---------------- */
    public static final class License extends Screen {
        License(AppActivity a) { super(a); }
        public String key() { return "license"; } public String title() { return "لایسنس"; }
        public void load() {
            if (Api.standalone() || "own".equals(Lic.mode())) { clear(); LinearLayout cd = Ui.card(c, "لایسنس این گوشی"); cd.addView(Ui.kv(c, "وضعیت", Lic.allowed() ? "فعال" : Lic.reason(), Lic.allowed() ? Ui.GREEN : Ui.RED)); cd.addView(Ui.kv(c, "نوع", Prefs.get("lic_type", "—"), 0)); cd.addView(Ui.kv(c, "دارنده", Prefs.get("lic_owner", "—"), 0)); cd.addView(Ui.kv(c, "انقضا", Ui.jdate(Lic.expires()), 0)); cd.addView(Ui.kv(c, "کلید", Ui.fa(Lic.masked()), 0)); cd.addView(Ui.kv(c, "شناسهٔ دستگاه", Lic.hwid(), 0)); cd.addView(Ui.kv(c, "آخرین بررسی آنلاین", Ui.jdate(new java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).format(new java.util.Date(Long.parseLong(Prefs.get("lic_checked", "0"))))), 0)); cd.addView(Ui.ghost(c, "بررسی مجدد با سرور لایسنس", () -> { Ui.toast("در حال بررسی…"); Api.bg(() -> { String e = Lic.activate(Prefs.get("lic_key", "")); Api.ui(() -> { Ui.toast(e == null ? "لایسنس معتبر است" : e); load(); }); }); })); cd.addView(Ui.ghost(c, "وارد کردن کلید جدید", () -> Ui.prompt(c, "کلید لایسنس", "XXXX-XXXX-XXXX-XXXX", false, k -> Api.bg(() -> { String e = Lic.activate(k); Api.ui(() -> { Ui.toast(e == null ? "فعال شد" : e); load(); }); })))); body.addView(cd); return; }
            loading(); get("/setup/license", r -> { JSONObject l = (JSONObject) r; clear(); LinearLayout cd = Ui.card(c, "وضعیت لایسنس رایانه (اعتبار این گوشی)"); cd.addView(Ui.muted(c, "این گوشی با لایسنس رایانه کار می‌کند؛ با پایان اعتبار رایانه، گوشی هم قفل می‌شود.")); cd.addView(Ui.kv(c, "وضعیت", s(l, "status"), stColor(s(l, "status")))); cd.addView(Ui.kv(c, "نوع", s(l, "type"), 0)); cd.addView(Ui.kv(c, "دارنده", s(l, "owner"), 0)); cd.addView(Ui.kv(c, "انقضا", Ui.jdate(s(l, "expires")) + " (" + Ui.num(d(l, "days_left")) + " روز)", d(l, "days_left") < 15 ? Ui.AMBER : 0)); cd.addView(Ui.kv(c, "کلید", Ui.fa(s(l, "key_masked")), 0)); cd.addView(Ui.kv(c, "شناسهٔ سخت‌افزار", s(l, "hwid"), 0)); cd.addView(Ui.kv(c, "آخرین بررسی", Ui.jdate(s(l, "checked_at")), 0)); cd.addView(Ui.kv(c, "کار آفلاین تا", Ui.jdate(s(l, "offline_until")), 0)); if (!s(l, "last_error").isEmpty()) cd.addView(Ui.kv(c, "خطا", s(l, "last_error"), Ui.RED)); cd.addView(Ui.ghost(c, "بررسی مجدد با سرور لایسنس", () -> post("/setup/license/recheck", null, x -> { Ui.toast("بررسی شد"); load(); }))); body.addView(cd); }); }
    }

    /* ---------------- Cloud ---------------- */
    public static final class Cloud extends Screen {
        Cloud(AppActivity a) { super(a); }
        public String key() { return "cloud"; } public String title() { return "همگام‌سازی ابری"; }
        public void load() {
            LinearLayout ph = Ui.card(c, "این گوشی و اینترنت"); ph.addView(Ui.kv(c, "دسترسی ابری گوشی", CloudSync.available() ? "فعال (" + CloudSync.account() + ")" : "ندارد", CloudSync.available() ? Ui.GREEN : Ui.MUTED)); ph.addView(Ui.kv(c, "آخرین ارسال / دریافت", Ui.jdate(Prefs.get("cloud_last_push", "")) + " / " + Ui.jdate(Prefs.get("cloud_last_pull", "")), 0)); if (!Prefs.get("cloud_last_error", "").isEmpty()) ph.addView(Ui.kv(c, "خطا", Prefs.get("cloud_last_error", ""), Ui.RED));
            ph.addView(Ui.muted(c, CloudSync.available() ? "وقتی رایانه در این شبکه نیست، تغییرات گوشی از طریق پوشهٔ مخفی برنامه در Google Drive شما به رایانه می‌رسد و کاتالوگ به‌روز از همان‌جا دریافت می‌شود." : "پس از ورود به حساب Google در رایانه (تنظیمات → همگام‌سازی ابری)، با یک بار جفت‌سازی دوباره یا اولین همگام‌سازی، دسترسی ابری به این گوشی هم داده می‌شود."));
            if (CloudSync.available()) ph.addView(Ui.primary(c, "همگام‌سازی از طریق اینترنت اکنون", () -> { Ui.toast("در حال همگام‌سازی…"); Api.bg(() -> { int n = CloudSync.run(); Api.ui(() -> { Ui.toast(n < 0 ? "ناموفق: " + Prefs.get("cloud_last_error", "") : "انجام شد (" + Ui.num(n) + " عملیات ارسال شد)"); load(); }); }); }));
            if (Api.standalone()) { clear(); body.addView(ph); return; }
            loading(); body.addView(ph, 0); get("/cloud/status", r -> { JSONObject l = (JSONObject) r; clear(); body.addView(ph); LinearLayout cd = Ui.card(c, "رایانهٔ فروشگاه · " + s(l, "provider_label", "Google Drive")); cd.addView(Ui.kv(c, "پیکربندی", l.optBoolean("configured") ? "بله" : "خیر", 0)); cd.addView(Ui.kv(c, "اتصال", l.optBoolean("connected") ? "متصل" : "قطع", l.optBoolean("connected") ? Ui.GREEN : Ui.MUTED)); cd.addView(Ui.kv(c, "حساب", s(l, "account", "—"), 0)); cd.addView(Ui.kv(c, "آخرین ارسال / دریافت", Ui.jdate(s(l, "last_push_at")) + " / " + Ui.jdate(s(l, "last_pull_at")), 0)); cd.addView(Ui.kv(c, "اعمال‌شده", Ui.num(d(l, "applied_total")), 0)); if (!s(l, "last_error").isEmpty()) cd.addView(Ui.kv(c, "خطا", s(l, "last_error"), Ui.RED)); if (l.optBoolean("connected")) cd.addView(Ui.primary(c, "همگام‌سازی ابری اکنون", () -> post("/cloud/sync-now", null, x -> { Ui.toast("انجام شد"); load(); }))); else cd.addView(Ui.muted(c, "اتصال حساب ابری (اختیاری) از رایانه، بخش تنظیمات → همگام‌سازی ابری انجام می‌شود؛ گوشی از طریق شبکهٔ محلی با رایانه همگام است.")); body.addView(cd); }); }
    }

    /* ---------------- About ---------------- */
    /* ---------------- Notifications & sounds (v2.2) ---------------- */
    public static final class Notifications extends Screen {
        Notifications(AppActivity a) { super(a); }
        public String key() { return "notifications"; } public String title() { return "اعلان‌ها و صداها"; }
        public void load() {
            clear();
            LinearLayout n = Ui.card(c, "🔔 اعلان‌های نوار بالا");
            n.addView(Ui.muted(c, "اعلان‌ها حتی وقتی برنامه بسته است هر نیم ساعت بررسی می‌شوند (پاسخ پشتیبانی، انقضا، کمبود موجودی، همگام‌سازی)."));
            n.addView(toggle("پاسخ پشتیبانی", "notif_" + Notify.CH_SUPPORT)); n.addView(toggle("انقضا و کمبود موجودی", "notif_" + Notify.CH_STOCK)); n.addView(toggle("سامانه و همگام‌سازی", "notif_" + Notify.CH_SYSTEM));
            if (android.os.Build.VERSION.SDK_INT >= 33 && a.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != android.content.pm.PackageManager.PERMISSION_GRANTED)
                n.addView(Ui.primary(c, "اجازهٔ نمایش اعلان", () -> { Prefs.set("notif_asked", ""); Notify.askPermission(a); }));
            n.addView(Ui.ghost(c, "ارسال اعلان آزمایشی", () -> Notify.show(a, Notify.CH_SYSTEM, 199, "اعلان آزمایشی", "اعلان‌های سوپری من درست کار می‌کند ✓", "notifications", "note")));
            n.addView(Ui.ghost(c, "بررسی اکنون (انقضا / موجودی / پشتیبانی)", () -> { Prefs.set("notif_expiry_day", ""); Api.bg(() -> { Notify.checkLocal(a); if (Api.standalone()) { int k = SupportRelay.poll(); if (k > 0) Notify.supportReply(a, k); } else Notify.checkPcSupport(a); Api.ui(() -> Ui.toast("بررسی انجام شد")); }); }));
            body.addView(n);
            LinearLayout so = Ui.card(c, "🔈 صداها"); so.addView(Ui.muted(c, "صداها مانند نسخهٔ رایانه ملایم‌اند: ثبت فروش، افزودن کالا، خطا، ابطال، نگه‌داشتن و اعلان هرکدام صدای جداگانه دارند."));
            so.addView(toggle("پخش صداها", "sfx"));
            android.widget.SeekBar sb = new android.widget.SeekBar(c); sb.setMax(100); sb.setProgress(Math.round(Sfx.volume() * 100)); sb.setLayoutDirection(View.LAYOUT_DIRECTION_LTR); sb.setPadding(Ui.dp(8), Ui.dp(8), Ui.dp(8), Ui.dp(8));
            sb.setOnSeekBarChangeListener(new android.widget.SeekBar.OnSeekBarChangeListener() { public void onProgressChanged(android.widget.SeekBar b, int v, boolean u) { Prefs.set("sfx_vol", String.valueOf(v / 100f)); } public void onStartTrackingTouch(android.widget.SeekBar b) {} public void onStopTrackingTouch(android.widget.SeekBar b) { Sfx.play("note"); } });
            so.addView(Ui.label(c, "بلندی")); so.addView(sb);
            LinearLayout tr = Ui.row(c); for (String[] k : new String[][]{{"success", "فروش"}, {"add", "افزودن"}, {"alert", "هشدار"}, {"void", "ابطال"}, {"error", "خطا"}}) tr.addView(Ui.chip(c, k[1], false, () -> Sfx.play(k[0]))); so.addView(Ui.chips(c, tr));
            body.addView(so);
        }
        private View toggle(String label, String key) { LinearLayout r = Ui.row(c); r.setPadding(0, Ui.dp(6), 0, Ui.dp(6)); TextView t = Ui.body(c, label); t.setLayoutParams(Ui.weight(1)); r.addView(t); android.widget.Switch sw = new android.widget.Switch(c); sw.setChecked(!"0".equals(Prefs.get(key, "1"))); sw.setOnCheckedChangeListener((b, on) -> Prefs.set(key, on ? "1" : "0")); r.addView(sw); return r; }
    }

    public static final class About extends Screen {
        About(AppActivity a) { super(a); }
        public String key() { return "about"; } public String title() { return "دربارهٔ برنامه"; }
        public void load() {
            clear();
            LinearLayout hero = Ui.col(c); hero.setGravity(android.view.Gravity.CENTER); hero.setPadding(0, Ui.dp(18), 0, Ui.dp(10));
            android.widget.ImageView logo = new android.widget.ImageView(c); logo.setImageResource(R.mipmap.ic_launcher); logo.setLayoutParams(Ui.lp(Ui.dp(84), Ui.dp(84))); hero.addView(logo);
            TextView t = Ui.text(c, "سامانه جامع مدیریت سوپرمارکت", 18, Ui.TEXT, true); t.setGravity(android.view.Gravity.CENTER); t.setPadding(0, Ui.dp(10), 0, 0); hero.addView(t);
            TextView v = Ui.muted(c, "اپ اندروید بومی · نسخهٔ " + Ui.fa(Version.NAME)); v.setGravity(android.view.Gravity.CENTER); hero.addView(v); body.addView(hero);
            LinearLayout cd = Ui.card(c, null); cd.addView(Ui.body(c, "اپ بومی اندروید (بدون مرورگر و وب‌ویو) که به‌طور مستقل روی گوشی کار می‌کند و فقط داده را با رایانهٔ فروشگاه — از طریق شبکهٔ محلی، بدون اینترنت — رد و بدل می‌کند. همهٔ بخش‌های نسخهٔ ویندوز در همین اپ در دسترس است: صندوق، کالا و انبار، مشتری و دفتر حساب، جشنواره، گزارش، حسابداری، کاربران، تنظیمات، سخت‌افزار، پشتیبانی.")); body.addView(cd);
            LinearLayout dev = Ui.card(c, null); TextView d1 = Ui.text(c, "طراحی و توسعه توسط خواجوی", 15, Ui.TEXT, true); d1.setGravity(android.view.Gravity.CENTER); dev.addView(d1); body.addView(dev);
            if (!Api.standalone()) getQuiet("/settings/about", r -> { JSONObject ab = (JSONObject) r; LinearLayout pc = Ui.card(c, "رایانهٔ فروشگاه"); pc.addView(Ui.kv(c, "نسخهٔ نصب‌شده", Ui.fa(s(ab, "version")), 0)); pc.addView(Ui.kv(c, "فروشگاه", s(ab, "store_name"), 0)); body.addView(pc); });
            LinearLayout lic = Ui.card(c, "مجوزهای متن‌باز"); lic.addView(Ui.muted(c, "ZXing (Apache-2.0) برای خواندن بارکد · قلم Vazirmatn (OFL-1.1)")); body.addView(lic);
        }
    }
}
