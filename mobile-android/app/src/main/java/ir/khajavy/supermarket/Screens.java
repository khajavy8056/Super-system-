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
            case "insights": return new InsightScreens.Feed(a);
            case "insightsPlan": return new InsightScreens.Plan(a);
            case "insightsCustomers": return new InsightScreens.Customers(a);
            case "backup": return new InsightScreens.Backup(a);
            case "catalog": return new InsightScreens.CatalogScreen(a);
            case "my-shifts": return new ShiftScreens.Mine(a);
            case "shifts": return new ShiftScreens.Roster(a);
            case "attendance": return new ShiftScreens.Attendance(a);
            case "announcements": return new HrScreens.Announcements(a);
            case "payroll": return new HrScreens.Payroll(a);
            case "performance": return new HrScreens.Performance(a);
        }
        return null;
    }
    static final String[][] PERMS = {{"pos", "pos.sell"}, {"held", "pos.sell"}, {"invoices", "reports.view"}, {"customers", "customers.manage"}, {"marketing", "marketing.view"}, {"products", "products.view"}, {"receive", "batches.manage"}, {"inventory", "inventory.view"}, {"stocktake", "inventory.stocktake"}, {"stockops", "inventory.adjust"}, {"warehouses", "inventory.adjust"}, {"movements", "inventory.adjust"}, {"reports", "reports.view"}, {"shifts", "shifts.view"}, {"attendance", "shifts.view"}, {"accounting", "accounting.view"}, {"users", "users.manage"}, {"audit", "audit.view"}, {"settings", "settings.manage"}, {"store", "settings.manage"}, {"sms", "settings.manage"}, {"hardware", "settings.manage"}, {"diagnostics", "settings.manage"}, {"license", "settings.manage"}, {"cloud", "settings.manage"}, {"insights", "reports.view"}, {"insightsPlan", "reports.view_all"}, {"backup", "settings.manage"}, {"insightsCustomers", "reports.view_all"}};
    public static boolean allowed(String key) {
        if ("my-shifts".equals(key) || "announcements".equals(key) || "performance".equals(key)) return user != null && user.optLong("id", 0) > 0;
        if ("payroll".equals(key)) return can("payroll.view") || can("payroll.manage");
        if ("shifts".equals(key) || "attendance".equals(key)) return can("shifts.view") || can("shifts.manage");
        if ("customers".equals(key)) return can("customers.manage") || can("customers.settle") || can("pos.sell");
        if ("invoices".equals(key)) return can("reports.view");
        String need = null; for (String[] p : PERMS) if (p[0].equals(key)) need = p[1];
        if (need == null) return true;
        return can(need);
    }
    public static boolean can(String perm) {
        JSONArray ps = user == null ? null : user.optJSONArray("permissions"); if (ps == null) return false;
        for (int i = 0; i < ps.length(); i++) if (perm.equals(ps.optString(i))) return true;
        return "reports.view".equals(perm) && contains(ps, "reports.view_all")
                || "shifts.view".equals(perm) && contains(ps, "shifts.manage");
    }
    private static boolean contains(JSONArray values, String target) { for (int i = 0; i < values.length(); i++) if (target.equals(values.optString(i))) return true; return false; }
    private static boolean hasPerm(JSONArray values, String target) { return values != null && contains(values, target); }
    /** Dashboard presentation follows the same effective permission profile returned by Backend.
     * Offline SQLite falls back to the user's cached permission set; it never widens data scope. */
    public static String dashboardProfile(JSONObject payload) {
        String server = payload == null ? "" : payload.optString("dashboard_profile", "");
        if ("administrator".equals(server) || "supervisor".equals(server) || "accountant".equals(server)
                || "seller".equals(server) || "manager".equals(server) || "operations".equals(server) || "staff".equals(server)) return server;
        return dashboardProfileFromPermissions(user == null ? null : user.optJSONArray("permissions"));
    }
    public static String dashboardProfileFromPermissions(JSONArray ps) {
        boolean admin = hasPerm(ps, "users.manage") && hasPerm(ps, "settings.manage");
        if (admin) return "administrator";
        boolean supervisor = hasPerm(ps, "reports.view_all") && hasPerm(ps, "shifts.manage")
                && hasPerm(ps, "inventory.adjust") && !hasPerm(ps, "users.manage") && !hasPerm(ps, "settings.manage");
        if (supervisor) return "supervisor";
        boolean accountant = hasPerm(ps, "accounting.view") && !hasPerm(ps, "pos.sell")
                && !hasPerm(ps, "shifts.manage") && !hasPerm(ps, "users.manage") && !hasPerm(ps, "settings.manage");
        if (accountant) return "accountant";
        boolean seller = hasPerm(ps, "pos.sell") && !hasPerm(ps, "reports.view_all")
                && !hasPerm(ps, "accounting.view") && !hasPerm(ps, "shifts.manage")
                && !hasPerm(ps, "users.manage") && !hasPerm(ps, "settings.manage");
        if (seller) return "seller";
        if (hasPerm(ps, "users.manage") || hasPerm(ps, "settings.manage")) return "manager";
        if (hasPerm(ps, "reports.view_all")) return "operations";
        return "staff";
    }
    public static String dashboardLabel(String profile) {
        switch (profile) {
            case "seller": return "فروشنده";
            case "accountant": return "حسابدار";
            case "supervisor": return "سوپروایزر";
            case "administrator": return "مدیر کل";
            case "manager": return "مدیر فروشگاه";
            case "operations": return "عملیات فروشگاه";
            default: return "کاربر";
        }
    }
    public static String dashboardTitle(String profile) {
        switch (profile) {
            case "seller": return "پنل فروش و صندوق";
            case "accountant": return "پنل حسابداری";
            case "supervisor": return "پنل سوپروایزر";
            case "administrator": return "پنل مدیر کل";
            case "manager": return "پنل مدیریت فروشگاه";
            case "operations": return "پنل عملیات فروشگاه";
            default: return "داشبورد";
        }
    }
    public static String userName() { String n = user.optString("full_name", ""); return n.isEmpty() ? user.optString("username", "") : n; }
    public static void loadConfig(AppActivity a) {
        try { user = new JSONObject(Prefs.get("user_json", "{}")); } catch (Exception ignore) {}
        Api.get("/auth/me", r -> {
            user = (JSONObject) r;
            Prefs.set("user_json", user.toString());
            if (a != null) a.refreshCurrent();
        }, e -> {});
        Api.get("/settings/currency", r -> { JSONObject c = (JSONObject) r; String code = c.optString("code", "IRR"); Ui.currencyLabel = "IRT".equals(code) ? "تومان" : "ریال"; Prefs.set("currency_label", Ui.currencyLabel); }, e -> {});
        if (Prefs.get("theme_mode", "").isEmpty()) Api.get("/settings/theme", r -> { String res = ((JSONObject) r).optString("resolved", "dark"); if (!res.equals(Prefs.get("theme_resolved", "dark"))) { Prefs.set("theme_resolved", res); a.recreate(); } }, e -> {});
        Api.get("/settings/store-profile", r -> Prefs.set("store_name", ((JSONObject) r).optString("name", "")), e -> {});
    }

    /* ---------------- base ---------------- */
    public abstract static class Screen {
        protected final AppActivity a; protected final LinearLayout body; protected final Context c;
        /** v4.8.1 — the screen's scroller, kept so a background refresh can restore the position. */
        public android.widget.ScrollView scroll;
        protected Screen(AppActivity a) { this.a = a; this.c = a; body = Ui.col(a); body.setPadding(Ui.dp(14), Ui.dp(14), Ui.dp(14), Ui.dp(24)); }
        public abstract String key();
        public abstract String title();
        public View view() { scroll = Ui.scroll(a, body); return scroll; }
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
        protected ViewGroup tabs(String[] labels, int active, Consumer<Integer> on) { Ui.Flow r = Ui.wrap(c); for (int i = 0; i < labels.length; i++) { final int k = i; r.addView(Ui.chip(c, labels[i], i == active, () -> on.accept(k))); } return r; }
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
        public String key() { return "home"; } public String title() { return Screens.dashboardTitle(Screens.dashboardProfile(null)); }
        public boolean autoRefresh() { return true; }
        private long loadGen = 0;
        public void load() {
            // build-484 — «استقلال کامل»: داشبورد همیشه بالا می‌آید؛ اول دادهٔ در دسترس (رایانه/محلی)،
            // بدون وابستگی به اتصال. هیچ مسیری نباید صفحهٔ خالی بگذارد (باگ مالک: «داشبورد لود نمی‌شه»).
            try { loadSafe(); } catch (Throwable t) {
                try { clear(); body.addView(Ui.empty(c, "خطای داشبورد: " + t)); } catch (Throwable ignore) {}
            }
        }
        void loadSafe() {
            clear();
            LinearLayout hero = Ui.hero(c);
            LinearLayout hr = Ui.row(c); LinearLayout hcol = Ui.col(c); hcol.setLayoutParams(Ui.weight(1));
            String profile = Screens.dashboardProfile(null);
            hcol.addView(Ui.text(c, greeting() + "، " + userName(), 13, 0xDDFFFFFF, false)); hcol.addView(Ui.text(c, Screens.dashboardTitle(profile) + " · نمای متناسب با دسترسی‌های شما", 13, 0xFFFFFFFF, true)); hcol.addView(Ui.text(c, Prefs.get("store_name", "فروشگاه") + " · " + Jalali.todayLong(), 12, 0xDDFFFFFF, false));
            hr.addView(hcol); android.widget.ImageView av = Icons.view(c, "store", 0xFFFFFFFF, 54); int pd = Ui.dp(13); av.setPadding(pd, pd, pd, pd); av.setBackground(Ui.rounded(0x2EFFFFFF, 0x557383EF, 18)); hr.addView(av); hero.addView(hr);
            LinearLayout quick = Ui.row(c); quick.setPadding(0, Ui.dp(14), 0, 0);
            if (allowed("pos")) quick.addView(qb("cart", "فروش جدید", Ui.GREEN, () -> a.route("pos")));
            if (allowed("receive")) quick.addView(qb("truck", "دریافت کالا", Ui.VIOLET, () -> a.route("receive")));
            if (allowed("inventory")) quick.addView(qb("box", "موجودی کالا", 0xFF4F8CFF, () -> a.route("inventory")));
            LinearLayout quick2 = Ui.row(c);
            if (allowed("customers")) quick2.addView(qb("user", "ثبت مشتری", 0xFFF4657A, () -> a.route("customers")));
            if (allowed("marketing")) quick2.addView(qb("gift", "کمپین جدید", Ui.AMBER, () -> a.route("marketing")));
            if ("seller".equals(profile) && allowed("held")) quick2.addView(qb("pause", "فاکتورهای نگه‌داشته", Ui.VIOLET, () -> a.route("held")));
            if (allowed("reports")) quick2.addView(qb("chart", "seller".equals(profile) ? "گزارش فروش من" : "گزارش فروش", Ui.TEAL, () -> a.route("reports")));
            if (quick.getChildCount() > 0) hero.addView(quick);
            if (quick2.getChildCount() > 0) hero.addView(quick2);
            body.addView(hero);
            // build-493 — presence/shift stays immediately below the existing welcome hero, not at the page tail.
            addShiftCard();
            if (can("shifts.view") || can("shifts.manage")) addTeamAttendanceCard();
            final double[] loc = Db.todayStats();
            final View ph = Ui.empty(c, "در حال دریافت داشبورد…"); body.addView(ph);
            final long gen = ++loadGen;
            final View[] pend = {ph};
            // اگر ساخت داده طول بکشد، کارت «صبر کنید» می‌آید ولی تلاش ادامه می‌یابد و هر نتیجه‌ای
            // (شبکه یا محلی) جای آن را می‌گیرد — هیچ‌وقت صفحهٔ خالی یا ارور بی‌دلیل نمی‌ماند.
            Api.ui(() -> {
                if (gen == loadGen && pend[0] != null && pend[0].getParent() == body) {
                    body.removeView(pend[0]);
                    // پین تست v33: هرگز اسپینر بی‌پایان — کارت شکست/تلاش دوباره باید وجود داشته باشد
                    LinearLayout cd = Ui.card(c, "داشبورد آماده نشد");
                    cd.addView(Ui.body(c, "آماده‌سازی داشبورد طول کشید — داده‌های در دسترس به‌محض آماده شدن نمایش داده می‌شود."));
                    cd.addView(Ui.primary(c, "تلاش دوباره", this::load));
                    body.addView(cd); pend[0] = cd;
                }
            }, 12000);
            Api.bg(() -> {
                Object r = null;
                try { r = Api.call("GET", "/reports/dashboard", null, null); } catch (Throwable ignore) {}
                if (!(r instanceof JSONObject)) {
                    try { r = Local.handle("GET", "/reports/dashboard", null); } catch (Throwable ignore) {}
                }
                final JSONObject j = (r instanceof JSONObject) ? (JSONObject) r : new JSONObject();
                Api.ui(() -> {
                    if (gen != loadGen) return;
                    if (pend[0] != null && pend[0].getParent() == body) body.removeView(pend[0]);
                    try { render(j, loc); }
                    catch (Throwable e) { body.addView(Ui.empty(c, "خطا در نمایش داشبورد: " + e)); }
                });
            });
        }
        private void addShiftCard() {
            final long uid = user == null ? 0 : user.optLong("id", 0);
            final LinearLayout card = Ui.card(c, "شیفت و حضور امروز");
            card.addView(Ui.muted(c, "در حال بررسی وضعیت حضور…"));
            body.addView(card);
            JSONObject cachedStatus = null, cachedSummary = null;
            try { String raw = uid > 0 ? Db.kv("shift_status_" + uid) : null; if (raw != null) cachedStatus = new JSONObject(raw); } catch (Exception e) { android.util.Log.w("Home", "invalid cached shift status", e); }
            try { String raw = uid > 0 ? Db.kv("attendance_summary_" + uid) : null; if (raw != null) cachedSummary = new JSONObject(raw); } catch (Exception e) { android.util.Log.w("Home", "invalid cached attendance summary", e); }
            final JSONObject cachedStatusForDisplay = cachedStatus, cachedSummaryForDisplay = cachedSummary;
            if (cachedStatusForDisplay != null) renderShiftCard(card, cachedStatusForDisplay, cachedSummaryForDisplay, true);
            if (uid <= 0) { card.removeAllViews(); card.addView(Ui.muted(c, "برای نمایش شیفت وارد حساب کاربری شوید.")); return; }
            Api.get("/hr/attendance/status?auto=1", result -> {
                if (!(result instanceof JSONObject) || card.getParent() != body) return;
                JSONObject status = (JSONObject) result;
                Db.kv("shift_status_" + uid, status.toString());
                renderShiftCard(card, status, cachedSummaryForDisplay, false);
            }, error -> {
                if (card.getParent() == body && cachedStatusForDisplay == null) {
                    card.removeAllViews(); card.addView(Ui.muted(c, "وضعیت حضور هنوز همگام نشده است؛ برنامهٔ محلی همچنان در دسترس است."));
                }
            });
            Api.get("/hr/attendance/my-summary", result -> {
                if (!(result instanceof JSONObject) || card.getParent() != body) return;
                JSONObject summary = (JSONObject) result;
                Db.kv("attendance_summary_" + uid, summary.toString());
                JSONObject status = null;
                try { String raw = Db.kv("shift_status_" + uid); if (raw != null) status = new JSONObject(raw); } catch (Exception e) { android.util.Log.w("Home", "invalid cached shift status", e); }
                renderShiftCard(card, status, summary, false);
            }, error -> { /* The last user-scoped summary stays visible when offline. */ });
        }
        private void addTeamAttendanceCard() {
            final LinearLayout card = Ui.card(c, "حضور امروز تیم");
            card.addView(Ui.muted(c, "در حال دریافت خلاصهٔ حضور…")); body.addView(card);
            Api.get("/hr/attendance/today", value -> {
                if (card.getParent() != body) return;
                JSONArray staff = value instanceof JSONArray ? (JSONArray) value : new JSONArray();
                int present = 0;
                for (int i = 0; i < staff.length(); i++) { JSONObject item = staff.optJSONObject(i); if (item != null && item.optBoolean("present")) present++; }
                card.removeAllViews();
                card.addView(Ui.kv(c, "حاضر / برنامه‌ریزی‌شده", Ui.num(present) + " / " + Ui.num(staff.length()), present > 0 ? Ui.GREEN : Ui.MUTED));
                for (int i = 0; i < Math.min(3, staff.length()); i++) {
                    JSONObject item = staff.optJSONObject(i); if (item == null) continue;
                    String shift = item.optString("shift_name", "بدون شیفت") + " · " + item.optString("start_time", "—") + " تا " + item.optString("end_time", "—");
                    String state = item.optBoolean("present") ? "حاضر · " + minutesLabel(item.optInt("minutes", 0)) : "ورود ثبت نشده";
                    card.addView(Ui.kv(c, item.optString("name", "کارمند") + " · " + shift, state, item.optBoolean("present") ? Ui.GREEN : Ui.AMBER));
                }
                if (staff.length() == 0) card.addView(Ui.muted(c, "برای امروز شیفتی ثبت نشده است."));
                if (allowed("attendance")) card.addView(Ui.small(c, "مشاهدهٔ فهرست کامل", () -> a.route("attendance")));
            }, error -> {
                if (card.getParent() == body) { card.removeAllViews(); card.addView(Ui.muted(c, "خلاصهٔ تیم هنگام قطع اتصال در دسترس نیست؛ اطلاعات شخصی حضور محفوظ است.")); }
            });
        }
        private void renderShiftCard(LinearLayout card, JSONObject status, JSONObject summary, boolean cached) {
            card.removeAllViews();
            if (status == null) {
                card.addView(Ui.muted(c, "برای امروز وضعیت شیفت در دسترس نیست."));
            } else {
                String state = status.optString("shift_state", "NO_SHIFT");
                String stateLabel = "IN_SHIFT".equals(state) ? "در حال شیفت" : "OUT_OF_SHIFT".equals(state) ? "خارج از بازهٔ شیفت" : "COMPLETED".equals(state) ? "حضور امروز پایان یافته" : "شیفتی برای امروز تعیین نشده";
                int accent = "IN_SHIFT".equals(state) ? Ui.GREEN : "COMPLETED".equals(state) ? Ui.TEAL : "OUT_OF_SHIFT".equals(state) ? Ui.AMBER : Ui.MUTED;
                card.addView(Ui.kv(c, "وضعیت", stateLabel, accent));
                String shift = status.optString("shift_name", "");
                String start = status.optString("start_time", ""), end = status.optString("end_time", "");
                if (shift.isEmpty()) shift = "بدون نام";
                card.addView(Ui.kv(c, "شیفت", shift, 0));
                if (!start.isEmpty() || !end.isEmpty()) card.addView(Ui.kv(c, "زمان برنامه‌ریزی‌شده", (start.isEmpty() ? "—" : start) + " تا " + (end.isEmpty() ? "—" : end), 0));
                if (status.optBoolean("present")) card.addView(Ui.kv(c, "حضور", "ثبت‌شده · " + minutesLabel(status.optInt("minutes", 0)) + " کارکرد فعلی", Ui.GREEN));
                else if (status.has("ended_at") && !status.isNull("ended_at")) card.addView(Ui.kv(c, "حضور", "پایان‌یافته در " + status.optString("ended_at"), Ui.TEAL));
                int late = status.optInt("late_minutes", 0);
                if (late > 0) card.addView(Ui.kv(c, "تأخیر", minutesLabel(late), Ui.AMBER));
                if (cached) card.addView(Ui.muted(c, "آخرین وضعیت ذخیره‌شده روی این گوشی · به‌روزرسانی در پس‌زمینه"));
                if (!cached && Api.online && !Api.standalone()) {
                    if (status.optBoolean("present")) card.addView(Ui.ghost(c, "ثبت پایان حضور", () -> Api.post("/hr/attendance/clock-out", new JSONObject(), result -> addShiftCard(), error -> Ui.toast(error.getMessage()))));
                    else if (status.optBoolean("in_shift_window") && !"COMPLETED".equals(state)) card.addView(Ui.primary(c, "ثبت حضور اکنون", () -> Api.post("/hr/attendance/enter", new JSONObject(), result -> addShiftCard(), error -> Ui.toast(error.getMessage()))));
                }
            }
            if (summary != null) {
                card.addView(Ui.kv(c, "کارکرد ۳۰ روز", minutesLabel(summary.optInt("worked_minutes", 0)) + " از " + minutesLabel(summary.optInt("planned_minutes", 0)), 0));
                card.addView(Ui.kv(c, "اضافه‌کاری / کسری", minutesLabel(summary.optInt("overtime_minutes", 0)) + " / " + minutesLabel(summary.optInt("deficit_minutes", 0)), Ui.VIOLET));
            }
        }
        private String minutesLabel(int minutes) { int h = Math.max(0, minutes) / 60, m = Math.max(0, minutes) % 60; return Ui.fa(h + " ساعت " + m + " دقیقه"); }
        private void renderCashierDashboard(JSONObject data, double[] local) {
            JSONObject sales = data.optJSONObject("sales");
            double today = d(sales, "today"), month = d(sales, "month");
            int count = (int) d(sales, "invoice_count_today");
            body.addView(Ui.grid2(c,
                    Ui.kpi(c, "فروش امروز من", Ui.money(today), "فروش ماه " + Ui.money(month), Ui.GREEN),
                    Ui.kpi(c, "فاکتورهای امروز", Ui.num(count), "مقایسه با روز قبل: " + Ui.num(d(sales, "invoice_count_yesterday")), Ui.VIOLET)));
            JSONArray payments = data.optJSONArray("today_by_payment");
            if (payments != null && payments.length() > 0) {
                LinearLayout card = Ui.card(c, "ترکیب فروش امروز");
                for (int i = 0; i < payments.length(); i++) {
                    JSONObject p = payments.optJSONObject(i); if (p == null) continue;
                    card.addView(Ui.kv(c, p.optString("name", "پرداخت"), Ui.num(p.optInt("invoice_count")) + " فاکتور · " + Ui.money(p.optDouble("sales")), 0));
                }
                body.addView(card);
            }
            if (Screens.can("inventory.view")) {
                JSONObject inventory = data.optJSONObject("inventory");
                if (inventory != null) {
                    LinearLayout stock = Ui.card(c, "موجودی فروشگاه");
                    stock.addView(Ui.kv(c, "کالاهای فعال", Ui.num(inventory.optInt("product_count")), Ui.PRIMARY));
                    stock.addView(Ui.kv(c, "کمبود / بدون موجودی", Ui.fa(inventory.optInt("low_stock_count") + " / " + inventory.optInt("no_stock_count")),
                            inventory.optInt("low_stock_count") + inventory.optInt("no_stock_count") > 0 ? Ui.AMBER : Ui.GREEN));
                    JSONArray none = inventory.optJSONArray("no_stock"), low = inventory.optJSONArray("low_stock");
                    int shown = 0;
                    for (int i = 0; none != null && shown < 3 && i < none.length(); i++) {
                        JSONObject item = none.optJSONObject(i);
                        if (item != null) { stock.addView(Ui.kv(c, "اتمام · " + item.optString("name"), "۰ / حد " + Ui.num(item.optDouble("min_stock_alert")), Ui.RED)); shown++; }
                    }
                    for (int i = 0; low != null && shown < 3 && i < low.length(); i++) {
                        JSONObject item = low.optJSONObject(i);
                        if (item != null) { stock.addView(Ui.kv(c, "کمبود · " + item.optString("name"), Ui.num(item.optDouble("total_stock")) + " / حد " + Ui.num(item.optDouble("min_stock_alert")), Ui.AMBER)); shown++; }
                    }
                    stock.addView(Ui.small(c, "جزئیات موجودی", () -> a.route("inventory")));
                    body.addView(stock);
                }
            }
            addTrendChart("روند فروش من · ۷ روز", data.optJSONArray("trend"), "sales");
            addRecentInvoiceCard(data.optJSONArray("recent_invoices"));
            if (local != null && local.length > 2 && local[2] > 0) {
                LinearLayout queue = Ui.card(c, "فروش‌های این گوشی");
                queue.addView(Ui.kv(c, "در انتظار همگام‌سازی", Ui.num(local[2]) + " فاکتور · " + Ui.money(local[1]), Ui.AMBER));
                queue.addView(Ui.muted(c, "فروش‌های محلی امن می‌مانند و پس از اتصال ارسال می‌شوند.")); body.addView(queue);
            }
            addAnnouncementsAndUpdates();
        }
        private void renderAccountantDashboard(JSONObject data, double[] local) {
            JSONObject accounts = data.optJSONObject("accounting"), sales = data.optJSONObject("sales"), profit = data.optJSONObject("profit");
            boolean storeScope = "store".equals(data.optString("scope"));
            body.addView(Ui.grid2(c,
                    Ui.kpi(c, "صندوق نقدی", moneyOrDash(accounts, "cash"), "ماندهٔ دفتر مالی", Ui.GREEN),
                    Ui.kpi(c, "حساب‌های بانکی", moneyOrDash(accounts, "bank"), "ماندهٔ بانک", Ui.VIOLET)));
            body.addView(Ui.grid2(c,
                    Ui.kpi(c, "مطالبات مشتریان", moneyOrDash(accounts, "receivables"), "بدهی فروشگاه به دیگران: " + moneyOrDash(accounts, "payables"), Ui.AMBER),
                    Ui.kpi(c, "سود خالص ماه", moneyOrDash(accounts, "month_net_profit"), "هزینهٔ ماه: " + moneyOrDash(accounts, "month_expenses"), Ui.TEAL)));
            if (storeScope) {
                body.addView(Ui.grid2(c,
                        Ui.kpi(c, "فروش امروز", Ui.money(d(sales, "today")), Ui.num(d(sales, "invoice_count_today")) + " فاکتور", Ui.GREEN),
                        Ui.kpi(c, "فروش ماه", Ui.money(d(sales, "month")), "سود امروز " + moneyOrDash(profit, "today"), Ui.GOLD)));
            } else {
                LinearLayout scope = Ui.card(c, "دامنهٔ گزارش فروش");
                scope.addView(Ui.muted(c, "دفتر مالی با مجوز حسابداری در دسترس است؛ آمار فروش سراسری به مجوز گزارش فروشگاه نیاز دارد.")); body.addView(scope);
            }
            LinearLayout actions = Ui.card(c, "دسترسی‌های مالی"); LinearLayout row = Ui.row(c);
            if (allowed("accounting")) row.addView(qb("wallet", "دفتر مالی", Ui.GREEN, () -> a.route("accounting")));
            if (allowed("payroll")) row.addView(qb("users", "حقوق", Ui.VIOLET, () -> a.route("payroll")));
            if (allowed("reports")) row.addView(qb("chart", "گزارش‌ها", Ui.TEAL, () -> a.route("reports")));
            actions.addView(row); body.addView(actions);
            if (storeScope) {
                addTrendChart("روند فروش فروشگاه · ۷ روز", data.optJSONArray("trend"), "sales");
                addRecentInvoiceCard(data.optJSONArray("recent_invoices"));
            }
            if (local != null && local.length > 2 && local[2] > 0) {
                LinearLayout queue = Ui.card(c, "همگام‌سازی این گوشی");
                queue.addView(Ui.kv(c, "فروش‌های صف‌شده", Ui.num(local[2]), Ui.AMBER)); body.addView(queue);
            }
            addAnnouncementsAndUpdates();
        }
        private String moneyOrDash(JSONObject source, String key) {
            return source == null || source.isNull(key) ? "—" : Ui.money(source.optDouble(key));
        }
        private void addTrendChart(String title, JSONArray trend, String metric) {
            if (trend == null || trend.length() == 0) return;
            LinearLayout card = Ui.card(c, title); double max = 1;
            for (int i = 0; i < trend.length(); i++) { JSONObject item = trend.optJSONObject(i); if (item != null) max = Math.max(max, item.optDouble(metric)); }
            LinearLayout bars = Ui.row(c); bars.setGravity(android.view.Gravity.BOTTOM);
            bars.setLayoutParams(Ui.lp(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(112)));
            for (int i = 0; i < trend.length(); i++) {
                JSONObject item = trend.optJSONObject(i); if (item == null) continue;
                LinearLayout col = Ui.col(c); col.setGravity(android.view.Gravity.BOTTOM | android.view.Gravity.CENTER_HORIZONTAL);
                LinearLayout.LayoutParams cp = Ui.weight(1); cp.height = ViewGroup.LayoutParams.MATCH_PARENT; col.setLayoutParams(cp);
                View bar = new View(c); bar.setBackground(Ui.rounded(Ui.PRIMARY, 0, 4));
                bar.setLayoutParams(Ui.lp(Ui.dp(13), Math.max(Ui.dp(3), (int) (Ui.dp(76) * item.optDouble(metric) / max)))); col.addView(bar);
                String label = item.optString("label", item.optString("date")); if (label.length() > 5) label = label.substring(label.length() - 5);
                TextView day = Ui.muted(c, Ui.fa(label)); day.setTextSize(9); col.addView(day); bars.addView(col);
            }
            card.addView(bars); body.addView(card);
        }
        private void addRecentInvoiceCard(JSONArray invoices) {
            LinearLayout card = Ui.card(c, "آخرین فاکتورها");
            if (invoices == null || invoices.length() == 0) card.addView(Ui.muted(c, "هنوز فاکتوری برای نمایش وجود ندارد."));
            else for (int i = 0; i < Math.min(5, invoices.length()); i++) {
                JSONObject item = invoices.optJSONObject(i); if (item == null) continue;
                String date = item.optString("created_at", ""); String time = date.length() >= 16 ? date.substring(11, 16) : "";
                card.addView(Ui.kv(c, Ui.fa(item.optString("invoice_number", "فاکتور")) + (time.isEmpty() ? "" : " · " + time), Ui.money(item.optDouble("total")), stColor(item.optString("status", "PAID"))));
            }
            if (allowed("invoices")) card.addView(Ui.small(c, "مشاهدهٔ همهٔ فاکتورها", () -> a.route("invoices")));
            body.addView(card);
        }
        private void addAnnouncementsAndUpdates() {
            final LinearLayout notices = Ui.card(c, "اطلاعیه‌های فروشگاه"); notices.addView(Ui.muted(c, "در حال دریافت…")); body.addView(notices);
            Api.get("/hr/announcements", value -> {
                if (notices.getParent() != body) return;
                notices.removeAllViews(); JSONArray items = value instanceof JSONArray ? (JSONArray) value : new JSONArray();
                if (items.length() == 0) notices.addView(Ui.muted(c, "اطلاعیه‌ای نیست"));
                for (int i = 0; i < Math.min(3, items.length()); i++) {
                    JSONObject item = items.optJSONObject(i); if (item != null) notices.addView(SugRow("bell", Ui.VIOLET, item.optString("title"), item.optString("body"), () -> {}));
                }
                if (allowed("announcements")) notices.addView(Ui.small(c, "همهٔ اطلاعیه‌ها", () -> a.route("announcements")));
            }, error -> { if (notices.getParent() == body) { notices.removeAllViews(); notices.addView(Ui.muted(c, "اطلاعیهٔ تازه همگام نشده است؛ نسخهٔ محلی همچنان قابل‌استفاده است.")); } });
            final LinearLayout update = Ui.card(c, "به‌روزرسانی برنامه"); update.addView(Ui.muted(c, "در حال بررسی…")); body.addView(update);
            Api.get("/system/update/check?platform=android", value -> {
                if (update.getParent() != body) return;
                update.removeAllViews(); JSONObject result = value instanceof JSONObject ? (JSONObject) value : new JSONObject();
                JSONObject latest = result.optJSONObject("latest"); String version = latest == null ? "" : latest.optString("version");
                if (result.optBoolean("update_available")) {
                    String link = latest.optString("html_url", "https://github.com/khajavy8056/Rasasys/releases");
                    update.addView(SugRow("star", Ui.AMBER, "نسخهٔ جدید " + Ui.fa(version) + " آماده است", "دریافت از صفحهٔ انتشار", () -> {
                        try { a.startActivity(new Intent(Intent.ACTION_VIEW, android.net.Uri.parse(link))); }
                        catch (Exception e) { Ui.toast("مرورگر در دسترس نیست"); }
                    }));
                } else update.addView(Ui.kv(c, "وضعیت", result.optBoolean("available", true) ? "برنامه به‌روز است" : "بررسی آنلاین انجام نشد", Ui.GREEN));
            }, error -> { if (update.getParent() == body) { update.removeAllViews(); update.addView(Ui.muted(c, "برای بررسی نسخه به اینترنت نیاز است؛ برنامه آفلاین فعال می‌ماند.")); } });
        }
        static String greeting() { int h = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY); return h < 12 ? "صبح بخیر" : h < 17 ? "ظهر بخیر" : h < 20 ? "عصر بخیر" : "شب بخیر"; }
        /** build-484 — کاشی‌های پاستلی «عملیات سریع» (الهام از تصویر مرجع): رنگ روشن + آیکون رنگی. */
        private View qb(String icon, String s, int accent, Runnable r) {
            LinearLayout t = Ui.col(c); t.setGravity(android.view.Gravity.CENTER);
            int tint = (accent & 0x00FFFFFF) | (Ui.dark ? 0x36000000 : 0x24000000);
            t.setBackground(Ui.rounded(tint, Ui.dark ? 0x33FFFFFF : 0x14000000, 16));
            t.setPadding(0, Ui.dp(12), 0, Ui.dp(10));
            LinearLayout.LayoutParams p = Ui.weight(1); p.setMargins(Ui.dp(4), Ui.dp(4), Ui.dp(4), Ui.dp(4)); t.setLayoutParams(p);
            t.addView(Icons.view(c, icon, accent, 22));
            TextView l = Ui.text(c, s, 11.5f, Ui.TEXT, true); l.setPadding(0, Ui.dp(6), 0, 0); t.addView(l);
            t.setClickable(true); t.setOnClickListener(v -> r.run()); return t;
        }
        /** build-486 — ردیف پیشنهاد/هشدار (زبان طراحی کارت‌های ریل مرجع). */
        private View SugRow(String icon, int accent, String title, String sub, Runnable r) {
            LinearLayout row = Ui.row(c); row.setGravity(android.view.Gravity.CENTER_VERTICAL);
            row.setPadding(0, Ui.dp(6), 0, Ui.dp(6));
            android.widget.ImageView ib = Icons.view(c, icon, accent, 16); int pd = Ui.dp(8);
            ib.setPadding(pd, pd, pd, pd);
            ib.setBackground(Ui.rounded((accent & 0x00FFFFFF) | (Ui.dark ? 0x33000000 : 0x22000000), 0, 10));
            ib.setLayoutParams(Ui.lp(Ui.dp(32), Ui.dp(32))); row.addView(ib);
            LinearLayout tx = Ui.col(c); tx.setPadding(Ui.dp(8), 0, 0, 0); tx.setLayoutParams(Ui.weight(1));
            tx.addView(Ui.text(c, title, 12f, Ui.TEXT, true)); tx.addView(Ui.muted(c, sub)); row.addView(tx);
            row.setClickable(true); row.setOnClickListener(v -> r.run()); return row;
        }
        /** build-486 — ستون شاخص «وضعیت فروشگاه». */
        private View StatCol(String label, String value, int color) {
            LinearLayout col = Ui.col(c); col.setGravity(android.view.Gravity.CENTER); col.setLayoutParams(Ui.weight(1));
            col.addView(Ui.text(c, value, 17, color, true)); col.addView(Ui.muted(c, label)); return col;
        }
        private void renderManagementActions(String profile) {
            LinearLayout panel = Ui.card(c, "مرکز " + ("administrator".equals(profile) ? "مدیریت کل" : "نظارت عملیاتی"));
            panel.addView(Ui.muted(c, "نمای مدیریتی فروشگاه · میان‌برها فقط برای دسترسی‌های فعال این حساب نمایش داده می‌شوند."));
            LinearLayout operations = Ui.row(c), governance = Ui.row(c);
            if (allowed("reports")) operations.addView(qb("chart", "گزارش فروش", Ui.TEAL, () -> a.route("reports")));
            if (allowed("inventory")) operations.addView(qb("box", "موجودی", 0xFF4F8CFF, () -> a.route("inventory")));
            if (allowed("receive")) operations.addView(qb("truck", "دریافت کالا", Ui.VIOLET, () -> a.route("receive")));
            if (allowed("accounting")) operations.addView(qb("wallet", "دفتر مالی", Ui.GREEN, () -> a.route("accounting")));
            if (allowed("shifts")) governance.addView(qb("clock", "شیفت‌ها", Ui.AMBER, () -> a.route("shifts")));
            if (allowed("users")) governance.addView(qb("users", "کاربران", Ui.VIOLET, () -> a.route("users")));
            if (allowed("settings")) governance.addView(qb("gear", "تنظیمات", 0xFF4F8CFF, () -> a.route("settings")));
            if (operations.getChildCount() > 0) panel.addView(operations);
            if (governance.getChildCount() > 0) panel.addView(governance);
            body.addView(panel);
        }
        private void render(JSONObject d, double[] loc) {
            JSONObject sales = d.optJSONObject("sales"), inv = d.optJSONObject("inventory"), rec = d.optJSONObject("receivables"), sms = d.optJSONObject("sms"), sys = d.optJSONObject("system"), acc = d.optJSONObject("accounting"), exp = d.optJSONObject("expiry"), pr = d.optJSONObject("pricing"), profit = d.optJSONObject("profit");
            String profile = Screens.dashboardProfile(d);
            boolean showSales = can("reports.view") && !"none".equals(d.optString("scope", "none"));
            boolean storeScope = can("reports.view_all") && "store".equals(d.optString("scope"));
            if ("accountant".equals(profile)) { renderAccountantDashboard(d, loc); return; }
            if ("seller".equals(profile)) { renderCashierDashboard(d, loc); return; }
            if ("administrator".equals(profile) || "supervisor".equals(profile)) renderManagementActions(profile);
            // 1-2 sales / invoices
            JSONArray tr0 = d.optJSONArray("trend"); double[] wk = new double[tr0 == null ? 0 : tr0.length()]; for (int i = 0; i < wk.length; i++) wk[i] = d(tr0.optJSONObject(i), "sales");
            double sToday = d(sales, "today"), sYest = d(sales, "yesterday"); int iToday = (int) d(sales, "invoice_count_today"), iYest = (int) d(sales, "invoice_count_yesterday");
            TextView sTr = Ui.muted(c, sYest > 0 ? (sToday >= sYest ? "▲ " : "▼ ") + Ui.fa(String.valueOf(Math.round(Math.abs(sToday - sYest) * 100 / sYest))) + "٪ نسبت به دیروز" : "ثبت امروز");
            TextView iTr = Ui.muted(c, iYest > 0 ? (iToday >= iYest ? "▲ " : "▼ ") + Ui.fa(String.valueOf(Math.round(Math.abs(iToday - iYest) * 100.0 / iYest))) + "٪ نسبت به دیروز" : "ثبت امروز");
            if (showSales) body.addView(Ui.grid2(c, Ui.tile(c, "trend", Ui.GREEN, "فروش امروز", Ui.money(sToday), sTr), Ui.tile(c, "receipt", Ui.VIOLET, "فاکتورهای من", Ui.num(iToday), iTr)));
            if (storeScope) body.addView(Ui.grid2(c, Ui.tile(c, "users", Ui.AMBER, "مشتریان", Ui.num(Db.count("customers")), null), Ui.tile(c, "box", 0xFF4F8CFF, "موجودی کل محصولات", Ui.num(d(inv, "product_count")), null)));
            // build-486 — «پیشنهادات هوشمند» (همان ردیف‌های ریل تصویر مرجع، دادهٔ واقعی محلی)
            if (storeScope) {
                LinearLayout sg = Ui.card(c, null);
                LinearLayout sh = Ui.row(c); sh.setGravity(android.view.Gravity.CENTER_VERTICAL);
                sh.addView(Icons.view(c, "star", Ui.VIOLET, 20));
                TextView stx = Ui.h2(c, "پیشنهادات هوشمند"); stx.setPadding(Ui.dp(8), 0, 0, 0); stx.setLayoutParams(Ui.weight(1)); sh.addView(stx);
                sh.addView(Ui.small(c, "همه", () -> a.route("insights"))); sg.addView(sh);
                int added = 0;
                int lowAll = (inv == null ? 0 : inv.optInt("low_stock_count")) + (inv == null ? 0 : inv.optInt("no_stock_count"));
                if (lowAll > 0) {
                    JSONArray lows = inv == null ? null : inv.optJSONArray("low_stock");
                    StringBuilder names = new StringBuilder();
                    if (lows != null) for (int i = 0; i < Math.min(3, lows.length()); i++) { if (i > 0) names.append("، "); names.append(lows.optJSONObject(i).optString("name")); }
                    sg.addView(SugRow("box", Ui.AMBER, "موجودی " + Ui.fa(String.valueOf(lowAll)) + " محصول در حال اتمام است", names.length() > 0 ? names.toString() : "بررسی قفسه‌ها", () -> a.route("inventory"))); added++;
                }
                int expAll = 0; if (exp != null) for (String ek : new String[]{"EXPIRED", "EXPIRING_TODAY", "EXPIRING_3_DAYS", "EXPIRING_7_DAYS", "EXPIRING_30_DAYS"}) expAll += exp.optJSONArray(ek) == null ? 0 : Math.max(exp.optInt("total_" + ek), exp.optJSONArray(ek).length());
                if (expAll > 0) { sg.addView(SugRow("clock", Ui.RED, expAll + " بچ نزدیک انقضا یا منقضی", "پیش از ضرر بررسی کنید", () -> a.open(new AdminScreens.Reports(a, 3), true))); added++; }
                if (d(pr, "price_conflict_count") > 0) { sg.addView(SugRow("tag", Ui.VIOLET, "پیشنهاد قیمت‌گذاری: " + Ui.fa(String.valueOf((int) d(pr, "price_conflict_count"))) + " کالا با چند قیمت فعال", "یکسان‌سازی قیمت پیش از فروش", () -> a.route("products"))); added++; }
                if (d(rec, "debtor_count") > 0) { sg.addView(SugRow("user", 0xFF4F8CFF, "مطالبات مشتریان: " + Ui.num(d(rec, "debtor_count")) + " بدهکار", "پیگیری وصول از مشتریان", () -> a.route("customers"))); added++; }
                if (added == 0) sg.addView(Ui.muted(c, "هشدار فعالی نیست؛ همه‌چیز مرتب است."));
                body.addView(sg);
            }
            // build-488 — اطلاعیه‌های داخلی (§۱۴–۱۷): آخرین اطلاعیه‌های مجاز کاربر؛ آفلاین بی‌صدا مخفی
            {
                final LinearLayout an = Ui.card(c, "اطلاعیه‌های فروشگاه");
                an.addView(Ui.muted(c, "در حال دریافت…"));
                Api.get("/hr/announcements", o -> {
                    an.removeAllViews();
                    JSONArray arr = (JSONArray) o;
                    if (arr == null || arr.length() == 0) { an.addView(Ui.muted(c, "اطلاعیه‌ای نیست")); return; }
                    int n = Math.min(3, arr.length());
                    for (int i = 0; i < n; i++) {
                        JSONObject r = arr.optJSONObject(i);
                        an.addView(SugRow("bell", Ui.VIOLET, r.optString("title"), r.optString("body"), () -> {}));
                    }
                }, e -> { an.removeAllViews(); an.addView(Ui.muted(c, "در دسترس نیست (آفلاین)")); });
                body.addView(an);
            }
            // build-488 — به‌روزرسانی (§۴۳–۴۴): فقط نسخهٔ اندروید، بدون وابستگی به لایسنس؛ اعلان هر نسخه یک بار
            {
                final LinearLayout up = Ui.card(c, "به‌روزرسانی");
                up.addView(Ui.muted(c, "در حال بررسی نسخه…"));
                Api.get("/system/update/check?platform=android", o -> {
                    up.removeAllViews();
                    JSONObject r = (JSONObject) o;
                    JSONObject latestObj = r == null ? null : r.optJSONObject("latest");
                    String latest = latestObj == null ? "" : latestObj.optString("version");
                    final String link = latestObj == null ? "" : latestObj.optString("html_url", "");
                    if (r != null && r.optBoolean("update_available")) {
                        up.addView(SugRow("star", Ui.AMBER, "نسخهٔ جدید در دسترس است", latest.length() > 0 ? "نسخهٔ " + Ui.fa(latest) : "دریافت از مخزن انتشار", () -> { try { a.startActivity(new android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(link.length() > 0 ? link : "https://github.com/khajavy8056/Rasasys/releases"))); } catch (Exception ex) { Ui.toast("مرورگر در دسترس نیست"); } }));
                        up.addView(Ui.muted(c, "نسخهٔ فعلی: " + Ui.fa(r.optString("current_version", ""))));
                    } else {
                        up.addView(Ui.kv(c, "وضعیت", "برنامه به‌روز است", Ui.GREEN));
                    }
                }, e -> { up.removeAllViews(); up.addView(Ui.muted(c, "بررسی به‌روزرسانی ممکن نشد (آفلاین)")); });
                body.addView(up);
            }
            if (storeScope) {
                // v3.0 — store intelligence: measured profit impact of executed suggestions
                InsightScreens.dashboardCard(this, body, a);
            // 3-4 month / profit
            body.addView(Ui.grid2(c, Ui.kpi(c, "فروش ماه", Ui.money(d(sales, "month")), null, Ui.TEAL), Ui.kpi(c, "سود امروز / ماه", moneyOrDash(profit, "today"), moneyOrDash(profit, "month"), Ui.VIOLET)));
            // 5-6 inventory / low stock
            int low = inv == null ? 0 : inv.optInt("low_stock_count"), none = inv == null ? 0 : inv.optInt("no_stock_count");
            body.addView(Ui.grid2(c, Ui.kpi(c, "ارزش موجودی", moneyOrDash(inv, "value"), Ui.num(d(inv, "product_count")) + " کالا", Ui.AMBER), Ui.kpi(c, "کمبود / بدون موجودی", Ui.fa(low + " / " + none), null, low + none > 0 ? Ui.RED : Ui.GREEN)));
            // 7 expiry
            LinearLayout ex = Ui.card(c, "انقضا"); int te = 0; String[][] EK = {{"EXPIRED", "منقضی"}, {"EXPIRING_TODAY", "امروز"}, {"EXPIRING_3_DAYS", "۳ روز"}, {"EXPIRING_7_DAYS", "۷ روز"}, {"EXPIRING_30_DAYS", "۳۰ روز"}};
            LinearLayout er = Ui.row(c); for (String[] k : EK) { int n = exp == null || exp.optJSONArray(k[0]) == null ? 0 : Math.max(exp.optInt("total_" + k[0]), exp.optJSONArray(k[0]).length()); te += n; LinearLayout col = Ui.col(c); col.setGravity(android.view.Gravity.CENTER); col.setLayoutParams(Ui.weight(1)); col.addView(Ui.text(c, Ui.fa(String.valueOf(n)), 17, n > 0 ? ("EXPIRED".equals(k[0]) ? Ui.RED : Ui.AMBER) : Ui.TEXT, true)); col.addView(Ui.muted(c, k[1])); er.addView(col); }
            ex.addView(er); if (te == 0) ex.addView(Ui.muted(c, "هیچ کالایی نزدیک انقضا نیست")); ex.setOnClickListener(v -> a.open(new AdminScreens.Reports(a, 3), true)); body.addView(ex);
            // 8 receivables
            LinearLayout rc = Ui.card(c, "مطالبات و بدهکاران"); rc.addView(Ui.kv(c, "بدهی مشتریان", Ui.money(d(rec, "customer_debt")), Ui.AMBER)); rc.addView(Ui.kv(c, "تعداد بدهکار", Ui.num(d(rec, "debtor_count")), 0)); rc.addView(Ui.kv(c, "فاکتور در انتظار پرداخت", Ui.num(d(rec, "pending_count")) + " · " + Ui.money(d(rec, "pending_amount")), 0)); rc.setOnClickListener(v -> a.route("customers")); body.addView(rc);
            // 9 top products
            LinearLayout tp = Ui.card(c, "پرفروش‌ترین کالاها"); JSONArray top = d.optJSONArray("top_products"); if (top == null || top.length() == 0) tp.addView(Ui.muted(c, "هنوز فروشی ثبت نشده")); else for (int i = 0; i < Math.min(5, top.length()); i++) { JSONObject t = top.optJSONObject(i); tp.addView(Ui.kv(c, t.optString("name"), Ui.num(d(t, "qty")) + " · " + Ui.money(d(t, "revenue")), Ui.GOLD)); } body.addView(tp);
            // build-484 — «توزیع فروش بر اساس دسته‌بندی» (هم‌ارز دونات مرجع؛ روی موبیل نوارهای پاستلی)
            JSONArray cats = d.optJSONArray("sales_by_category");
            if (cats != null && cats.length() > 0) {
                LinearLayout cc = Ui.card(c, "توزیع فروش بر اساس دسته‌بندی");
                double mx = 1; for (int i = 0; i < cats.length(); i++) mx = Math.max(mx, cats.optJSONObject(i).optDouble("sales"));
                int[] PAL = {Ui.GREEN, Ui.VIOLET, Ui.AMBER, 0xFF4F8CFF, 0xFFF4657A, Ui.TEAL};
                for (int i = 0; i < cats.length(); i++) {
                    JSONObject t = cats.optJSONObject(i);
                    LinearLayout crow = Ui.col(c); crow.setPadding(0, Ui.dp(4), 0, Ui.dp(4));
                    crow.addView(Ui.kv(c, s(t, "name", "سایر"), Ui.fa(String.valueOf(t.optDouble("share_pct"))) + "٪ · " + Ui.money(t.optDouble("sales")), PAL[i % PAL.length]));
                    View track = new View(c); track.setBackground(Ui.rounded(Ui.dark ? 0x22FFFFFF : 0x14000000, 0, 5));
                    LinearLayout.LayoutParams tl = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(6)); track.setLayoutParams(tl); crow.addView(track);
                    View fill = new View(c); fill.setBackground(Ui.rounded(PAL[i % PAL.length], 0, 5));
                    LinearLayout.LayoutParams fl = new LinearLayout.LayoutParams(Math.max(Ui.dp(6), (int) (Ui.dp(220) * t.optDouble("sales") / mx)), Ui.dp(6));
                    fill.setLayoutParams(fl); crow.addView(fill);
                    cc.addView(crow);
                }
                body.addView(cc);
            }
            }
            if (showSales) {
            // 10 trend (7 days, bar chart drawn with views)
            LinearLayout tr = Ui.card(c, "روند فروش ۷ روز"); JSONArray trend = d.optJSONArray("trend"); if (trend != null && trend.length() > 0) { double mx = 1; for (int i = 0; i < trend.length(); i++) mx = Math.max(mx, d(trend.optJSONObject(i), "sales")); LinearLayout bars = Ui.row(c); bars.setGravity(android.view.Gravity.BOTTOM); bars.setLayoutParams(Ui.lp(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(110))); for (int i = 0; i < trend.length(); i++) { JSONObject t = trend.optJSONObject(i); LinearLayout col = Ui.col(c); col.setGravity(android.view.Gravity.BOTTOM | android.view.Gravity.CENTER_HORIZONTAL); LinearLayout.LayoutParams lp = Ui.weight(1); lp.height = ViewGroup.LayoutParams.MATCH_PARENT; col.setLayoutParams(lp); View bar = new View(c); bar.setBackground(Ui.rounded(Ui.PRIMARY, 0, 4)); bar.setLayoutParams(Ui.lp(Ui.dp(14), Math.max(Ui.dp(3), (int) (Ui.dp(80) * d(t, "sales") / mx)))); col.addView(bar); TextView lb = Ui.muted(c, Ui.fa(t.optString("label").substring(3))); lb.setTextSize(10); col.addView(lb); bars.addView(col); } tr.addView(bars); } body.addView(tr);
            // 11 recent invoices
            LinearLayout ri = Ui.card(c, "آخرین فاکتورها"); JSONArray rinv = d.optJSONArray("recent_invoices"); if (rinv == null || rinv.length() == 0) ri.addView(Ui.muted(c, "—")); else for (int i = 0; i < Math.min(5, rinv.length()); i++) { JSONObject t = rinv.optJSONObject(i); ri.addView(Ui.kv(c, Ui.fa(t.optString("invoice_number")) + " · " + Ui.jdate(t.optString("created_at")).substring(11), Ui.money(d(t, "total")), stColor(t.optString("status")))); } ri.setOnClickListener(v -> a.route("invoices")); body.addView(ri);
            // build-485 — «گزارش فروش روزانه» (همان جدول تصویر مرجع؛ روی گوشی از دادهٔ محلی)
            JSONArray byPay = d.optJSONArray("today_by_payment");
            if (byPay != null && byPay.length() > 0) {
                LinearLayout dp = Ui.card(c, "گزارش فروش روزانه");
                double tot = 0;
                for (int i = 0; i < byPay.length(); i++) {
                    JSONObject t = byPay.optJSONObject(i); tot += t.optDouble("sales");
                    dp.addView(Ui.kv(c, s(t, "name", "نقدی"), Ui.num(t.optInt("invoice_count")) + " فاکتور · " + Ui.money(t.optDouble("sales")), 0));
                }
                dp.addView(Ui.kv(c, "جمع کل", Ui.money(tot), Ui.GOLD));
                body.addView(dp);
            }
            }
            if (storeScope) {
            // build-486 — «وضعیت فروشگاه» (همان کارت حلقه‌های مرجع؛ سه شاخص واقعی)
            {
                LinearLayout sc2 = Ui.card(c, "وضعیت فروشگاه");
                double targetDay = d(sales, "month") / 30.0; int goal = targetDay > 0 ? (int) Math.min(100, Math.round(d(sales, "today") * 100 / targetDay)) : 0;
                int stockPct = d(inv, "product_count") > 0 ? (int) Math.round((d(inv, "product_count") - d(inv, "no_stock_count")) * 100 / d(inv, "product_count")) : 100;
                String sysS = s(sys, "status", "OK");
                LinearLayout gr = Ui.row(c);
                gr.addView(StatCol("فروش امروز", Ui.fa(String.valueOf(goal)) + "٪", goal >= 50 ? Ui.GREEN : Ui.AMBER));
                gr.addView(StatCol("موجودی در قفسه", Ui.fa(String.valueOf(stockPct)) + "٪", stockPct >= 70 ? Ui.GREEN : Ui.RED));
                gr.addView(StatCol("سلامت سامانه", sysS, stColor(sysS)));
                sc2.addView(gr);
                sc2.addView(Ui.kv(c, "این گوشی امروز", Ui.num(loc[0]) + " فاکتور", loc[2] > 0 ? Ui.AMBER : Ui.GREEN));
                body.addView(sc2);
            }
            }
            // 12 system + sms + accounting + pricing conflicts — privileged diagnostics only
            if (can("settings.manage")) {
                LinearLayout sy = Ui.card(c, "وضعیت سامانه"); sy.addView(Ui.kv(c, "نسخهٔ رایانه", Ui.fa(s(sys, "version")), 0)); sy.addView(Ui.kv(c, "وضعیت", s(sys, "status", "OK"), stColor(s(sys, "status", "OK")))); sy.addView(Ui.kv(c, "فضای آزاد دیسک", Ui.fa(String.valueOf(d(sys, "disk_free_gb"))) + " GB", 0)); sy.addView(Ui.kv(c, "صف همگام‌سازی رایانه", Ui.num(d(sys, "sync_queued")) + " · خطا " + Ui.num(d(sys, "sync_failed")), 0)); sy.addView(Ui.kv(c, "پیامک", (sms != null && sms.optBoolean("configured") ? "فعال" : "پیکربندی‌نشده") + " · در صف " + Ui.num(d(sms, "pending")), 0)); sy.addView(Ui.kv(c, "تعارض قیمت", Ui.num(d(pr, "price_conflict_count")), d(pr, "price_conflict_count") > 0 ? Ui.AMBER : 0)); sy.addView(Ui.kv(c, "صندوق / بانک", Ui.money(d(acc, "cash")) + " / " + Ui.money(d(acc, "bank")), 0)); sy.addView(Ui.kv(c, "بدهی به تأمین‌کننده", Ui.money(d(acc, "payables")), 0)); sy.addView(Ui.kv(c, "این گوشی امروز", Ui.num(loc[0]) + " فاکتور · " + (loc[2] > 0 ? Ui.num(loc[2]) + " در صف" : "همگام"), loc[2] > 0 ? Ui.AMBER : Ui.GREEN)); body.addView(sy);
            }
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
            long uid = user == null ? 0 : user.optLong("id", 0); boolean seeAllQueue = can("users.manage");
            List<JSONObject> visibleOps = seeAllQueue ? Db.ops() : Db.opsForUser(uid);
            List<JSONObject> visibleConflicts = seeAllQueue ? Db.conflicts() : Db.conflictsForUser(uid);
            int pending = seeAllQueue ? Db.opCount() : Db.opCountForUser(uid);
            st.addView(Ui.kv(c, "آخرین همگام‌سازی", Ui.jdate(Db.kv("last_sync")), 0)); st.addView(Ui.kv(c, "در صف ارسال", Ui.num(pending), pending > 0 ? Ui.AMBER : Ui.GREEN));
            st.addView(Ui.kv(c, "کالا / بچ / مشتری روی گوشی", Ui.fa(Db.count("products") + " / " + Db.count("batches") + " / " + Db.count("customers")), 0));
            st.addView(Ui.primary(c, "همگام‌سازی اکنون", () -> { Ui.toast("در حال همگام‌سازی…"); Sync.kick(); }));
            st.addView(Ui.ghost(c, "دریافت کامل دوبارهٔ کاتالوگ", () -> { Db.kv("cursor_user_" + uid, null); Sync.kick(); }));
            body.addView(st);
            LinearLayout q = Ui.card(c, "صف عملیات این گوشی"); if (visibleOps.isEmpty()) q.addView(Ui.muted(c, "صف خالی است — همه‌چیز روی رایانه ثبت شده")); else for (JSONObject o : visibleOps) q.addView(Ui.item(c, s(o, "label", s(o, "type")), Ui.jdate(s(o, "created_at")) + (s(o, "last_error").isEmpty() ? "" : " · " + s(o, "last_error")), s(o, "type"), Ui.MUTED, null)); body.addView(q);
            LinearLayout cf = Ui.card(c, "موارد ردشده توسط رایانه"); if (visibleConflicts.isEmpty()) cf.addView(Ui.muted(c, "موردی نیست")); else for (JSONObject o : visibleConflicts) { LinearLayout it = Ui.item(c, s(o, "label"), s(o, "message") + " · " + Ui.jdate(s(o, "at")), "حذف", Ui.RED, () -> { Db.conflictDelete(o.optLong("id")); load(); }); cf.addView(it); } body.addView(cf);
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
            LinearLayout n = Ui.card(c, "اعلان‌های نوار بالا");
            n.addView(Ui.muted(c, "اعلان‌ها حتی وقتی برنامه بسته است هر نیم ساعت بررسی می‌شوند (پاسخ پشتیبانی، انقضا، کمبود موجودی، همگام‌سازی)."));
            n.addView(toggle("پاسخ پشتیبانی", "notif_" + Notify.CH_SUPPORT)); n.addView(toggle("انقضا و کمبود موجودی", "notif_" + Notify.CH_STOCK)); n.addView(toggle("سامانه و همگام‌سازی", "notif_" + Notify.CH_SYSTEM));
            if (android.os.Build.VERSION.SDK_INT >= 33 && a.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != android.content.pm.PackageManager.PERMISSION_GRANTED)
                n.addView(Ui.primary(c, "اجازهٔ نمایش اعلان", () -> { Prefs.set("notif_asked", ""); Notify.askPermission(a); }));
            n.addView(Ui.ghost(c, "ارسال اعلان آزمایشی", () -> Notify.show(a, Notify.CH_SYSTEM, 199, "اعلان آزمایشی", "اعلان‌های رسا سیستم درست کار می‌کند ✓", "notifications", "note")));
            n.addView(Ui.ghost(c, "بررسی اکنون (انقضا / موجودی / پشتیبانی)", () -> { Prefs.set("notif_expiry_day", ""); Api.bg(() -> { Notify.checkLocal(a); if (Api.standalone()) { int k = SupportRelay.poll(); if (k > 0) Notify.supportReply(a, k); } else Notify.checkPcSupport(a); Api.ui(() -> Ui.toast("بررسی انجام شد")); }); }));
            body.addView(n);
            LinearLayout so = Ui.card(c, "صداها"); so.addView(Ui.muted(c, "صداها مانند نسخهٔ رایانه ملایم‌اند: ثبت فروش، افزودن کالا، خطا، ابطال، نگه‌داشتن و اعلان هرکدام صدای جداگانه دارند."));
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
            TextView t = Ui.text(c, "مدیریت سوپرمارکت رسا سیستم", 18, Ui.TEXT, true); t.setGravity(android.view.Gravity.CENTER); t.setPadding(0, Ui.dp(10), 0, 0); hero.addView(t);
            TextView v = Ui.muted(c, "اپ اندروید بومی · نسخهٔ " + Ui.fa(Version.NAME)); v.setGravity(android.view.Gravity.CENTER); hero.addView(v); body.addView(hero);
            LinearLayout cd = Ui.card(c, null); cd.addView(Ui.body(c, "اپ بومی اندروید (بدون مرورگر و وب‌ویو) با پایگاه‌دادهٔ محلی، ورود مستقل و همگام‌سازی پس‌زمینه. دسترسی هر بخش بر اساس مجوز همان حساب کنترل می‌شود؛ هنگام قطع شبکه، داده‌های ذخیره‌شده روی این گوشی نمایش داده می‌شود.")); body.addView(cd);
            LinearLayout crash = Ui.card(c, "گزارش آخرین بسته‌شدن غیرمنتظره");
            String report = Diagnostics.last(c);
            if (report.isEmpty()) crash.addView(Ui.muted(c, "گزارش خرابی ذخیره‌شده‌ای وجود ندارد."));
            else {
                TextView crashText = Ui.body(c, report); crashText.setTextIsSelectable(true); crash.addView(crashText);
                crash.addView(Ui.primary(c, "اشتراک گزارش برای پشتیبانی", () -> {
                    Intent share = new Intent(Intent.ACTION_SEND); share.setType("text/plain"); share.putExtra(Intent.EXTRA_SUBJECT, "گزارش بسته‌شدن برنامهٔ اندروید"); share.putExtra(Intent.EXTRA_TEXT, report);
                    a.startActivity(Intent.createChooser(share, "ارسال گزارش خرابی"));
                }));
            }
            body.addView(crash);
            LinearLayout dev = Ui.card(c, null); TextView d1 = Ui.text(c, "طراحی و توسعه توسط خواجوی", 15, Ui.TEXT, true); d1.setGravity(android.view.Gravity.CENTER); dev.addView(d1); body.addView(dev);
            if (!Api.standalone()) getQuiet("/settings/about", r -> { JSONObject ab = (JSONObject) r; LinearLayout pc = Ui.card(c, "رایانهٔ فروشگاه"); pc.addView(Ui.kv(c, "نسخهٔ نصب‌شده", Ui.fa(s(ab, "version")), 0)); pc.addView(Ui.kv(c, "فروشگاه", s(ab, "store_name"), 0)); body.addView(pc); });
            LinearLayout lic = Ui.card(c, "مجوزهای متن‌باز"); lic.addView(Ui.muted(c, "ZXing (Apache-2.0) برای خواندن بارکد · قلم Vazirmatn (OFL-1.1)")); body.addView(lic);
        }
    }
}
