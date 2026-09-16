package ir.khajavy.supermarket;

import android.app.Dialog;
import android.content.Intent;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * v3.0 — «هوش فروشگاه» screens: suggestion feed with one-tap execution,
 * per-action before/after measurement, the profit-impact card on the
 * dashboard, and the Backup screen (create / share / import).
 */
public final class InsightScreens {
    private InsightScreens() {}

    static int prioColor(int p) { return p <= 1 ? Ui.RED : p == 2 ? Ui.AMBER : Ui.TEAL; }
    static String prioLabel(int p) { return p <= 1 ? "فوری" : p == 2 ? "مهم" : p == 3 ? "پیشنهاد" : "نکته"; }
    static String kindIcon(String k) { switch (k) { case "CROSS_SELL": case "BASKET_NUDGE": return "cart"; case "EXPIRY_LADDER": return "calendar"; case "DEAD_STOCK": return "box"; case "VELOCITY": return "trend"; case "CASHFLOW": return "bank"; case "VIP": return "star"; case "CHURN": return "users"; case "PRICE_GAP": return "tag"; case "LOSS_PREV": return "shield"; case "SEASON": return "chart"; } return groupIcon(group(k)); }
    // v3.5 — kind groups (mirror of backend GROUPS); PRO kinds fall back to their group's icon
    static final String[][] GROUPS = {
        {"customer", "رفتار مشتری", "VIP,CHURN,VISIT_PATTERN,PAY_CYCLE,CUST_FAVORITE,CUST_ITEM_DUE,TICKET_DROP,FREQ_DROP,NEW_CUST_2ND,OFFER_SENSITIVE,CATEGORY_GAP,CREDIT_RISK,ANNIVERSARY,BULK_BUYER,THRESHOLD_UPSELL"},
        {"stock", "انبار و پیش‌بینی", "VELOCITY,EXPIRY_LADDER,DEAD_STOCK,SUPPLIER,REORDER_POINT,OVERSTOCK,STOCKOUT_HISTORY,TREND_UP,TREND_DOWN,EXPIRY_RISK_BUY,WASTE_PATTERN,SHRINKAGE,CATEGORY_TURNS,FIFO_BREAK,SUPPLIER_LEAD,SEASONAL_YOY"},
        {"price", "قیمت و سود", "PRICE_GAP,PROFIT_PARETO,NEGATIVE_MARGIN,DISCOUNT_LEAK,PRICE_ROUNDING,ELASTICITY,CATEGORY_MARGIN"},
        {"ops", "عملیات و مالی", "CASHFLOW,LOSS_PREV,PEAK_HOURS,QUEUE_STRESS,CASHIER_PERF,CASH_DIFF,RETURNS_PRODUCT,RECEIVABLES_AGING,EXPENSE_SPIKE,SMS_ROI"},
        {"growth", "رشد و بازاریابی", "CROSS_SELL,BASKET_NUDGE,SEASON,CAMPAIGN_FATIGUE,UNREGISTERED_SALES,HERO_PRODUCT,SLOW_DAY,BASKET_TREND,NEW_PRODUCT_WATCH,CATEGORY_DEPTH"},
        {"daily", "روزانه", "SURPRISE,AI_ADVISOR"}};
    static String group(String kind) { for (String[] g : GROUPS) if (("," + g[2] + ",").contains("," + kind + ",")) return g[0]; return "growth"; }
    static String groupIcon(String g) { switch (g) { case "customer": return "users"; case "stock": return "box"; case "price": return "tag"; case "ops": return "shield"; case "daily": return "star"; } return "trend"; }

    /* ---------------- dashboard card (called from Screens.Home) ---------------- */
    public static void dashboardCard(Screens.Screen sc, LinearLayout body, AppActivity a) {
        LinearLayout card = Ui.card(sc.c, null); LinearLayout hd = Ui.row(sc.c); hd.setGravity(Gravity.CENTER_VERTICAL); hd.addView(Icons.view(sc.c, "star", Ui.GOLD, 20)); TextView t = Ui.h2(sc.c, "هوش فروشگاه"); t.setPadding(Ui.dp(8), 0, 0, 0); t.setLayoutParams(Ui.weight(1)); hd.addView(t); card.addView(hd);
        TextView ph = Ui.muted(sc.c, "در حال تحلیل…"); card.addView(ph); card.setOnClickListener(v -> a.route("insights")); body.addView(card);
        Api.get("/insights/summary", r -> { JSONObject s = (JSONObject) r; card.removeView(ph);
            double tg = s.optDouble("total_gain"), mg = s.optDouble("month_gain"); int open = s.optInt("open");
            card.addView(Ui.grid2(sc.c, Ui.kpi(sc.c, "اثر اندازه‌گیری‌شده (کل)", Ui.money(tg), Ui.num(s.optInt("accepted")) + " اقدام اجراشده", tg >= 0 ? Ui.GREEN : Ui.RED), Ui.kpi(sc.c, "اثر ۳۰ روز اخیر", Ui.money(mg), s.optDouble("share_of_month_profit") > 0 ? Ui.fa(String.valueOf(Math.round(s.optDouble("share_of_month_profit") * 100))) + "٪ سود دوره" : null, Ui.VIOLET)));
            JSONArray top = s.optJSONArray("top"); if (top != null) for (int i = 0; i < Math.min(3, top.length()); i++) { JSONObject x = top.optJSONObject(i); card.addView(Ui.kv(sc.c, x.optString("title"), (x.optDouble("gain") >= 0 ? "+" : "") + Ui.money(x.optDouble("gain")), x.optDouble("gain") >= 0 ? Ui.GREEN : Ui.RED)); }
            LinearLayout bt = Ui.row(sc.c); android.widget.Button b1 = Ui.ghost(sc.c, open > 0 ? Ui.num(open) + " پیشنهاد باز — مشاهده" : "همهٔ پیشنهادها", () -> a.route("insights")); b1.setLayoutParams(Ui.weight(1)); bt.addView(b1); bt.addView(Ui.small(sc.c, "پیش‌بینی سود", () -> a.route("insightsPlan"))); card.addView(bt); }, e -> { ph.setText("هوش فروشگاه در دسترس نیست"); });
    }

    /* ---------------- suggestions feed ---------------- */
    public static final class Feed extends Screens.Screen {
        int tab = 0; String grp = ""; JSONObject summary = new JSONObject();
        Feed(AppActivity a) { super(a); }
        public String key() { return "insights"; } public String title() { return "هوش فروشگاه"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            loading();
            get("/insights/summary", r -> { summary = (JSONObject) r; String st = tab == 0 ? "NEW" : tab == 1 ? "ACCEPTED,MEASURED" : "DISMISSED,SNOOZED,EXPIRED"; get("/insights?status=" + st + "&limit=300", rr -> render(arr(rr))); });
        }
        void render(JSONArray all) {
            JSONArray items = all; clear();
            LinearLayout hero = Ui.hero(c); hero.addView(Ui.text(c, "هوش فروشگاه", 20, 0xFFFFFFFF, true)); hero.addView(Ui.text(c, "تحلیل محلی روی داده‌های خودتان — پیشنهادها را با یک لمس اجرا کنید؛ اثر واقعی هر اقدام اندازه‌گیری می‌شود.", 12, 0xDDFFFFFF, false));
            LinearLayout kp = Ui.row(c); kp.setPadding(0, Ui.dp(10), 0, 0);
            kp.addView(heroKpi("اثر کل", Ui.money(summary.optDouble("total_gain")))); kp.addView(heroKpi("۳۰ روز اخیر", Ui.money(summary.optDouble("month_gain")))); kp.addView(heroKpi("باز", Ui.num(summary.optInt("open")))); hero.addView(kp);
            LinearLayout br = Ui.row(c); br.setPadding(0, Ui.dp(10), 0, 0); android.widget.Button run = Ui.small(c, "تحلیل دوباره", () -> { Ui.toast("در حال تحلیل…"); post("/insights/run", new JSONObject(), r -> { JSONObject x = (JSONObject) r; Ui.done(Ui.ctx, "تحلیل انجام شد", Ui.num(x.optInt("created")) + " پیشنهاد تازه · " + Ui.num(x.optInt("refreshed")) + " به‌روزرسانی", null); load(); }); }); br.addView(run);
            if (!Api.standalone()) br.addView(Ui.small(c, "مشاور AI", this::advisor));   // v3.5 — free-model advisor lives on the PC engine
            br.addView(Ui.small(c, "پیش‌بینی سود", () -> a.route("insightsPlan"))); br.addView(Ui.small(c, "مشتریان در نوبت", () -> a.route("insightsCustomers")));
            android.widget.Button rep = Ui.small(c, "گزارش هفتگی", () -> get("/insights/report", r -> { JSONObject x = (JSONObject) r; LinearLayout l = Ui.col(c); TextView tv = Ui.body(c, x.optString("narrative")); tv.setLineSpacing(0, 1.35f); l.addView(tv); Ui.sheet(c, "گزارش هوش فروشگاه", l); })); br.addView(rep);
            android.widget.Button lst = Ui.small(c, "لیست سفارش", () -> get("/insights/tasks", r -> { JSONArray t = arr(r); LinearLayout l = Ui.col(c); if (t.length() == 0) l.addView(Ui.empty(c, "لیست سفارش خالی است")); for (int i = 0; i < t.length(); i++) { JSONObject x = t.optJSONObject(i); l.addView(Ui.kv(c, x.optString("name"), Ui.num(x.optDouble("qty")) + " عدد", Ui.AMBER)); } Ui.sheet(c, "لیست سفارش پیشنهادی", l); })); br.addView(lst); hero.addView(br); body.addView(hero);
            body.addView(tabs(new String[]{"پیشنهادها", "اجراشده و اثر", "بایگانی"}, tab, k -> { tab = k; load(); }));
            // v3.5 — group strip; filtering is local so switching is instant
            java.util.Map<String, Integer> cnt = new java.util.HashMap<>(); for (int i = 0; i < items.length(); i++) cnt.merge(group(items.optJSONObject(i).optString("kind")), 1, Integer::sum);
            LinearLayout gl = Ui.row(c); gl.addView(Ui.chip(c, "همه (" + Ui.num(items.length()) + ")", grp.isEmpty(), () -> { grp = ""; render(all); }));
            for (String[] g : GROUPS) { int n = cnt.getOrDefault(g[0], 0); if (n == 0) continue; gl.addView(Ui.chip(c, g[1] + " (" + Ui.num(n) + ")", g[0].equals(grp), () -> { grp = g[0]; render(all); })); }
            body.addView(Ui.chips(c, gl));
            if (!grp.isEmpty()) { JSONArray fl = new JSONArray(); for (int i = 0; i < items.length(); i++) if (grp.equals(group(items.optJSONObject(i).optString("kind")))) fl.put(items.optJSONObject(i)); items = fl; }
            if (items.length() == 0) { body.addView(Ui.empty(c, tab == 0 ? "پیشنهاد بازی نیست — با فروش بیشتر، تحلیل دقیق‌تر می‌شود" : "موردی نیست")); return; }
            LinearLayout list = Ui.col(c); body.addView(list); Ui.paged(list, items, 12, this::card);   // v3.5 staged (cards carry charts)
        }
        void advisor() {
            Ui.toast("در حال ارسال گزارش به مدل…");
            post("/insights/ai/advise", new JSONObject(), r -> { JSONObject x = (JSONObject) r; Ui.toast(Ui.num(x.optInt("created")) + " راهکار از مشاور دریافت شد"); grp = "daily"; tab = 0; load(); });
        }
        void accept(JSONObject x) { Ui.confirm(c, "این پیشنهاد اجرا شود؟ اقدام‌های آن هم‌اکنون انجام و اثرش از امروز اندازه‌گیری می‌شود.", () -> post("/insights/" + x.optLong("id") + "/accept", new JSONObject(), rr -> { JSONObject o = (JSONObject) rr; JSONArray ex = o.optJSONArray("executed"); StringBuilder sb = new StringBuilder(); for (int i = 0; ex != null && i < ex.length(); i++) { JSONObject e = ex.optJSONObject(i); sb.append(e.optBoolean("ok") ? "✓ " : "✗ ").append(e.optString("type")).append("\n"); } Sfx.play("ok"); Ui.done(Ui.ctx, "اجرا شد", sb.toString().trim(), null); load(); })); }
        void openDetail(long id) { a.open(new Detail(a, id), true); }
        static android.widget.Button wbtn(android.widget.Button b) { LinearLayout.LayoutParams lp = Ui.weight(1); lp.setMargins(Ui.dp(3), Ui.dp(2), Ui.dp(3), Ui.dp(2)); b.setLayoutParams(lp); b.setPadding(Ui.dp(4), 0, Ui.dp(4), 0); b.setSingleLine(true); b.setEllipsize(android.text.TextUtils.TruncateAt.END); return b; }
        View heroKpi(String l, String v) { LinearLayout t = Ui.col(c); t.setLayoutParams(Ui.weight(1)); t.addView(Ui.text(c, v, 15, 0xFFFFFFFF, true)); t.addView(Ui.text(c, l, 11, 0xCCFFFFFF, false)); return t; }
        View card(JSONObject x) {
            LinearLayout card = Ui.card(c, null); card.setLayoutParams(Ui.margin(Ui.match(), 0, 0, 0, 10));
            LinearLayout hd = Ui.row(c); hd.setGravity(Gravity.CENTER_VERTICAL); hd.addView(Icons.view(c, kindIcon(x.optString("kind")), prioColor(x.optInt("priority")), 20)); LinearLayout tc = Ui.col(c); tc.setLayoutParams(Ui.weight(1)); tc.setPadding(Ui.dp(8), 0, 0, 0); tc.addView(Ui.text(c, x.optString("title"), 14.5f, Ui.TEXT, true)); tc.addView(Ui.muted(c, x.optString("label") + " · " + prioLabel(x.optInt("priority")))); hd.addView(tc);
            String st = x.optString("status"); if ("NEW".equals(st) && x.optDouble("expected_gain") > 0) hd.addView(Ui.badge(c, "~" + Ui.money(x.optDouble("expected_gain")) + "/ماه", Ui.GREEN)); else if (!x.isNull("measured_gain")) { double g = x.optDouble("measured_gain"); hd.addView(Ui.badge(c, (g >= 0 ? "+" : "") + Ui.money(g), g >= 0 ? Ui.GREEN : Ui.RED)); } else if ("ACCEPTED".equals(st)) hd.addView(Ui.badge(c, "در حال سنجش", Ui.AMBER)); card.addView(hd);
            TextView b = Ui.body(c, x.optString("body")); b.setLineSpacing(0, 1.3f); b.setPadding(0, Ui.dp(8), 0, 0); card.addView(b);
            JSONObject fc = x.optJSONObject("evidence") == null ? null : x.optJSONObject("evidence").optJSONObject("forecast");
            if ("NEW".equals(st) && fc != null && fc.optDouble("gain_month") > 0) card.addView(Ui.muted(c, "پیش‌بینی سود ماهانه: " + Ui.money(fc.optDouble("gain_month")) + " (" + Ui.moneyShort(fc.optDouble("low_month")) + " تا " + Ui.moneyShort(fc.optDouble("high_month")) + ") · اطمینان " + conf(fc.optString("confidence"))));
            JSONObject res = x.optJSONObject("result"), base = x.optJSONObject("baseline");
            if (res != null && base != null) card.addView(measuredBlock(c, x, false));
            JSONArray acts = x.optJSONArray("actions");
            if ("NEW".equals(st) || "SNOOZED".equals(st)) { LinearLayout ar = Ui.col(c); ar.setPadding(0, Ui.dp(8), 0, 0);
                if (acts != null && acts.length() > 0) { StringBuilder sb = new StringBuilder(); for (int i = 0; i < acts.length(); i++) sb.append(i > 0 ? " · " : "").append(acts.optJSONObject(i).optString("label")); ar.addView(Ui.muted(c, "اقدام‌ها: " + sb)); }
                // v3.2 — the primary button gets its own full-width row; the three secondary actions share
                // the row below with equal weights, so nothing overflows on narrow screens.
                android.widget.Button ok = Ui.primary(c, "اجرا و سنجش اثر", () -> accept(x)); ok.setLayoutParams(Ui.margin(Ui.match(), 0, 6, 0, 4)); ar.addView(ok);
                LinearLayout r = Ui.row(c);
                r.addView(wbtn(Ui.small(c, "جزئیات و نمودار", () -> openDetail(x.optLong("id"))))); r.addView(wbtn(Ui.small(c, "بعداً", () -> post("/insights/" + x.optLong("id") + "/snooze", j("days", "7"), rr -> load())))); r.addView(wbtn(Ui.small(c, "رد", () -> post("/insights/" + x.optLong("id") + "/dismiss", new JSONObject(), rr -> load()))));
                ar.addView(r); card.addView(ar); }
            else { LinearLayout r = Ui.row(c); r.setPadding(0, Ui.dp(6), 0, 0); r.addView(wbtn(Ui.small(c, "جزئیات و نمودار", () -> openDetail(x.optLong("id"))))); if ("ACCEPTED".equals(st)) r.addView(wbtn(Ui.small(c, "سنجش دوباره", () -> post("/insights/" + x.optLong("id") + "/measure", new JSONObject(), rr -> load())))); card.addView(r); }
            card.setOnClickListener(v -> openDetail(x.optLong("id")));
            return card;
        }
    }


    /* ---------------- v3.2 measured effect (percent first) + evidence charts ---------------- */
    static final int[] PALETTE = {0xFF1F8C78, 0xFF7B6ED0, 0xFFD8952E, 0xFFD3505B, 0xFF2FA872, 0xFF3B82F6, 0xFFC2479B, 0xFF0EA5E9};
    static String metricLabel(String m) { switch (m) { case "product_units": return "تعداد فروش"; case "product_profit": return "سود کالا"; case "customer_sales": return "فروش این مشتریان"; case "attach_rate": return "نرخ هم‌خرید"; case "avg_basket_size": return "میانگین فاکتور"; case "receivables_collected": return "وصولی"; case "void_rate": return "نرخ ابطال"; case "weekday_sales": return "فروش روز اوج"; case "availability": return "روزهای موجود بودن"; case "stockout_days": return "روزهای بدون موجودی"; default: return "شاخص"; } }
    static String pctTxt(double v) { return (v >= 0 ? "+" : "−") + Ui.fa(String.format(java.util.Locale.US, "%.1f", Math.abs(v))) + "٪"; }
    static String fmtVal(String m, double v) { if (m.contains("rate")) return Ui.fa(String.valueOf(Math.round(v * 100))) + "٪"; if (m.equals("availability")) return Ui.fa(String.valueOf(v)) + "٪"; if (m.contains("units") || m.contains("stockout")) return Ui.num(v); return Ui.moneyShort(v); }
    static LinearLayout tile(android.content.Context c, String label, String value, String sub, int color) { LinearLayout t = Ui.col(c); t.setBackground(Ui.rounded(Ui.CARD2, Ui.BORDER, 12)); t.setPadding(Ui.dp(10), Ui.dp(8), Ui.dp(10), Ui.dp(8)); LinearLayout.LayoutParams lp = Ui.weight(1); lp.setMargins(Ui.dp(3), Ui.dp(3), Ui.dp(3), Ui.dp(3)); t.setLayoutParams(lp); t.addView(Ui.text(c, label, 11, Ui.MUTED, false)); TextView v = Ui.text(c, value, 16, color == 0 ? Ui.TEXT : color, true); v.setSingleLine(true); v.setEllipsize(android.text.TextUtils.TruncateAt.END); t.addView(v); if (sub != null && !sub.isEmpty()) t.addView(Ui.text(c, sub, 10.5f, Ui.MUTED, false)); return t; }
    static LinearLayout tiles2(android.content.Context c, View a, View b) { LinearLayout r = Ui.row(c); r.addView(a); r.addView(b); return r; }

    /** Before/after block: growth % first, toman second, then a daily before/after chart. */
    static View measuredBlock(android.content.Context c, JSONObject x, boolean full) {
        JSONObject res = x.optJSONObject("result"), base = x.optJSONObject("baseline"); if (res == null || base == null) return new View(c);
        String m = x.optJSONObject("metric") == null ? "" : x.optJSONObject("metric").optString("metric");
        boolean pending = x.isNull("measured_gain"); double g = x.optDouble("measured_gain", 0); Double gr = res.isNull("profit_pct_adj") ? (res.isNull("profit_pct") ? null : res.optDouble("profit_pct")) : res.optDouble("profit_pct_adj");
        int col = pending ? Ui.AMBER : g >= 0 ? Ui.GREEN : Ui.RED;
        LinearLayout box = Ui.col(c); box.setBackground(Ui.rounded((col & 0x00FFFFFF) | 0x14000000, (col & 0x00FFFFFF) | 0x55000000, 14)); box.setPadding(Ui.dp(8), Ui.dp(8), Ui.dp(8), Ui.dp(8)); box.setLayoutParams(Ui.margin(Ui.match(), 0, 8, 0, 0));
        LinearLayout hd = Ui.row(c); hd.addView(Icons.view(c, "trend", col, 16)); TextView ht = Ui.text(c, pending ? "در حال سنجش اثر" : "اثر اندازه‌گیری‌شده (واقعی)", 12.5f, col, true); ht.setPadding(Ui.dp(6), 0, 0, 0); hd.addView(ht); hd.setPadding(Ui.dp(4), 0, Ui.dp(4), Ui.dp(4)); box.addView(hd);
        box.addView(tiles2(c, tile(c, "رشد سود", pending ? "…" : gr == null ? "—" : pctTxt(gr), res.optDouble("control_ratio", 1) != 1 ? "پس از حذف روند فروشگاه" : "نسبت به قبل از اجرا", gr == null ? 0 : gr >= 0 ? Ui.GREEN : Ui.RED),
                tile(c, "اثر بر سود", pending ? "…" : (g >= 0 ? "+" : "−") + Ui.moneyShort(Math.abs(g)), res.isNull("projected_month") ? "" : "ماهانه ≈ " + Ui.moneyShort(res.optDouble("projected_month")), pending ? 0 : g >= 0 ? Ui.GREEN : Ui.RED)));
        box.addView(tiles2(c, tile(c, metricLabel(m) + " — قبل", fmtVal(m, base.optDouble("value")), Ui.num(base.optDouble("window_days", 28)) + " روز · " + Ui.moneyShort(res.optDouble("base_profit_per_day")) + "/روز", 0),
                tile(c, metricLabel(m) + " — بعد", fmtVal(m, res.optDouble("value")), Ui.num(res.optDouble("elapsed_days")) + " روز · " + Ui.moneyShort(res.optDouble("post_profit_per_day")) + "/روز" + (res.isNull("change_pct") ? "" : " · " + pctTxt(res.optDouble("change_pct"))), 0)));
        JSONObject daily = res.optJSONObject("daily"); JSONArray bef = daily == null ? null : daily.optJSONArray("before"), aft = daily == null ? null : daily.optJSONArray("after");
        if (bef != null && aft != null && bef.length() + aft.length() >= 4) {
            java.util.List<Double> b = new java.util.ArrayList<>(), af = new java.util.ArrayList<>(); String[] lb = new String[bef.length() + aft.length()];
            for (int i = 0; i < bef.length(); i++) { b.add(bef.optDouble(i)); af.add(null); lb[i] = i == 0 ? "قبل" : null; }
            for (int i = 0; i < aft.length(); i++) { b.add(null); af.add(aft.optDouble(i)); lb[bef.length() + i] = i == 0 ? "اجرا ▶" : i == aft.length() - 1 ? "امروز" : null; }
            java.util.List<Chart.Series> ss = new java.util.ArrayList<>(); ss.add(new Chart.Series("سود روزانه — قبل", Ui.MUTED, Chart.arr(b), false, true)); ss.add(new Chart.Series("سود روزانه — بعد از اجرا", g >= 0 ? Ui.GREEN : Ui.RED, Chart.arr(af), false, true));
            box.addView(Chart.line(c, ss, lb, null, null, full ? 150 : 110));
        }
        if (pending) box.addView(Ui.muted(c, "برای سنجش دقیق حداقل یک روز فروش پس از اجرا لازم است."));
        return box;
    }

    static java.util.List<String> L(String... a) { return java.util.Arrays.asList(a); }
    static java.util.List<Double> D(double... a) { java.util.List<Double> l = new java.util.ArrayList<>(); for (double d : a) l.add(d); return l; }
    static java.util.List<Integer> C(int... a) { java.util.List<Integer> l = new java.util.ArrayList<>(); for (int d : a) l.add(d); return l; }

    /** Evidence rendered per kind (tiles + charts) — never a raw JSON dump. */
    static void evidenceViews(android.content.Context c, JSONObject x, LinearLayout out) {
        JSONObject ev = x.optJSONObject("evidence"); if (ev == null) ev = new JSONObject(); String k = x.optString("kind");
        switch (k) {
            case "VELOCITY": { double cover = ev.optDouble("days_cover"); out.addView(tiles2(c, tile(c, "سرعت فروش", Ui.num(Math.round(ev.optDouble("velocity_per_day") * 70) / 10.0), "عدد در هفته", 0), tile(c, "موجودی", Ui.num(ev.optDouble("stock")), Ui.num(ev.optInt("sale_days")) + " روز فروش از ۲۸", 0))); out.addView(tiles2(c, tile(c, "پوشش", Ui.num(cover) + " روز", "", cover <= 2 ? Ui.RED : Ui.AMBER), tile(c, "سفارش پیشنهادی", Ui.num(ev.optDouble("reorder_qty")), "عدد (۲ هفته)", Ui.GREEN)));
                out.addView(Chart.bars(c, L("موجودی فعلی", "فروش ۲ هفته", "بعد از سفارش"), D(ev.optDouble("stock"), ev.optDouble("velocity_per_day") * 14, ev.optDouble("stock") + ev.optDouble("reorder_qty")), C(Ui.RED, Ui.MUTED, Ui.GREEN), "عدد")); break; }
            case "DEAD_STOCK": { out.addView(tiles2(c, tile(c, "تعداد راکد", Ui.num(ev.optDouble("qty")), "", 0), tile(c, "سرمایهٔ قفل‌شده", Ui.moneyShort(ev.optDouble("locked_value")), "", Ui.RED))); out.addView(tiles2(c, tile(c, "عمر در انبار", Ui.num(ev.optInt("age_days")) + " روز", "", 0), tile(c, "فروش ۶۰ روز", Ui.num(ev.optDouble("sold_60d")), "", 0)));
                out.addView(Chart.bars(c, L("قفل در این کالا", "کل کالاهای راکد"), D(ev.optDouble("locked_value"), ev.optDouble("total_locked")), C(Ui.RED, Ui.AMBER))); break; }
            case "EXPIRY_LADDER": { out.addView(tiles2(c, tile(c, "تا انقضا", Ui.num(ev.optInt("days_left")) + " روز", "", Ui.RED), tile(c, "موجودی", Ui.num(ev.optDouble("qty")), "", 0))); out.addView(tiles2(c, tile(c, "مازاد (ضایعات)", Ui.num(ev.optDouble("surplus")), "", Ui.RED), tile(c, "در خطر", Ui.moneyShort(ev.optDouble("at_risk")), "", Ui.RED)));
                JSONArray lad = ev.optJSONArray("ladder"); if (lad != null && lad.length() > 0) { java.util.List<String> l = new java.util.ArrayList<>(); java.util.List<Double> v = new java.util.ArrayList<>(); java.util.List<Integer> cc = new java.util.ArrayList<>(); for (int i = 0; i < lad.length(); i++) { JSONObject st = lad.optJSONObject(i); l.add("از روز " + Ui.num(st.optInt("from_day")) + " — " + Ui.num(st.optInt("percent")) + "٪"); v.add(st.optDouble("price")); cc.add(PALETTE[i % PALETTE.length]); } out.addView(Chart.bars(c, l, v, cc)); } break; }
            case "CROSS_SELL": { out.addView(tiles2(c, tile(c, "هم‌خرید", Ui.num(ev.optInt("pair_count")), "از " + Ui.num(ev.optInt("invoices")) + " فاکتور", 0), tile(c, "اطمینان", Ui.fa(String.valueOf(Math.round(ev.optDouble("confidence") * 100))) + "٪", "", 0))); out.addView(tiles2(c, tile(c, "ضریب هم‌خرید", Ui.fa(String.valueOf(ev.optDouble("lift"))) + "×", "", Ui.GREEN), tile(c, "پشتیبانی", Ui.fa(String.valueOf(Math.round(ev.optDouble("support") * 1000) / 10.0)) + "٪", "", 0)));
                int pc = ev.optInt("pair_count"), n = Math.max(1, ev.optInt("invoices")); out.addView(Chart.donut(c, L("با هم", "جدا"), D(pc, Math.max(0, n - pc)), C(Ui.TEAL, Ui.BORDER), Ui.fa(String.valueOf(Math.round(pc * 100.0 / n))) + "٪")); break; }
            case "CASHFLOW": { out.addView(tiles2(c, tile(c, "فروش روزانه", Ui.moneyShort(ev.optDouble("avg_daily_sales")), "", 0), tile(c, "هزینه + خرید روزانه", Ui.moneyShort(ev.optDouble("expense_daily") + ev.optDouble("purchase_daily")), "", 0))); out.addView(tiles2(c, tile(c, "کمترین مانده", Ui.moneyShort(ev.optDouble("lowest")), ev.optString("lowest_day"), Ui.RED), tile(c, "چک‌های صادره", Ui.num(ev.optJSONArray("cheques_out") != null ? ev.optJSONArray("cheques_out").length() : ev.optInt("cheques_out")), "", 0)));
                JSONArray tl = ev.optJSONArray("timeline"); if (tl != null && tl.length() > 1) { java.util.List<Double> v = new java.util.ArrayList<>(); String[] lb = new String[tl.length()]; for (int i = 0; i < tl.length(); i++) { v.add(tl.optJSONObject(i).optDouble("balance")); lb[i] = i % 6 == 0 ? md(tl.optJSONObject(i).optString("day")) : null; } java.util.List<Chart.Series> ss = new java.util.ArrayList<>(); ss.add(new Chart.Series("ماندهٔ نقد پیش‌بینی‌شده", Ui.AMBER, Chart.arr(v), false, true)); out.addView(Chart.line(c, ss, lb, null, null, 140)); } break; }
            case "VIP": { JSONArray rows = ev.optJSONArray("rows"); double sh = ev.optDouble("profit_share"); out.addView(Chart.donut(c, L(Ui.num(rows == null ? 0 : rows.length()) + " مشتری برتر", "بقیهٔ مشتریان"), D(sh, 1 - sh), C(Ui.GOLD, Ui.BORDER), Ui.fa(String.valueOf(Math.round(sh * 100))) + "٪ سود"));
                if (rows != null) { java.util.List<String> l = new java.util.ArrayList<>(); java.util.List<Double> v = new java.util.ArrayList<>(); java.util.List<Integer> cc = new java.util.ArrayList<>(); for (int i = 0; i < Math.min(8, rows.length()); i++) { l.add(rows.optJSONObject(i).optString("name")); v.add(rows.optJSONObject(i).optDouble("profit")); cc.add(PALETTE[i % PALETTE.length]); } out.addView(Chart.bars(c, l, v, cc)); } break; }
            case "CHURN": { JSONArray rows = ev.optJSONArray("rows"); if (rows != null) { java.util.List<String> l = new java.util.ArrayList<>(); java.util.List<Double> v = new java.util.ArrayList<>(); java.util.List<Integer> cc = new java.util.ArrayList<>(); for (int i = 0; i < Math.min(8, rows.length()); i++) { JSONObject r = rows.optJSONObject(i); l.add(r.optString("name") + " — " + Ui.num(r.optInt("silent_days")) + " روز غایب"); v.add(r.optDouble("monthly_profit")); cc.add(Ui.RED); } out.addView(Chart.bars(c, l, v, cc)); } break; }
            case "VISIT_PATTERN": { JSONArray rows = ev.optJSONArray("rows"); out.addView(tiles2(c, tile(c, "در نوبت خرید", Ui.num(rows == null ? 0 : rows.length()), "مشتری", 0), tile(c, "سود ماهانهٔ گروه", Ui.moneyShort(ev.optDouble("monthly_profit")), Ui.num(ev.optInt("with_phone")) + " نفر شماره دارند", Ui.GREEN))); if (rows != null) for (int i = 0; i < Math.min(12, rows.length()); i++) out.addView(visitRow(c, rows.optJSONObject(i))); break; }
            case "BASKET_NUDGE": { JSONArray rules = ev.optJSONArray("rules"); if (rules != null) { java.util.List<String> l = new java.util.ArrayList<>(); java.util.List<Double> v = new java.util.ArrayList<>(); java.util.List<Integer> cc = new java.util.ArrayList<>(); for (int i = 0; i < Math.min(8, rules.length()); i++) { JSONObject r = rules.optJSONObject(i); l.add(r.optString("if_name") + " ← " + r.optString("then_name")); v.add(r.optDouble("confidence") * 100); cc.add(PALETTE[i % PALETTE.length]); } out.addView(Chart.bars(c, l, v, cc, "٪")); } break; }
            case "SEASON": { JSONObject wa = ev.optJSONObject("weekday_avg"); if (wa != null) { java.util.List<String> l = new java.util.ArrayList<>(); java.util.List<Double> v = new java.util.ArrayList<>(); java.util.List<Integer> cc = new java.util.ArrayList<>(); java.util.Iterator<String> it = wa.keys(); while (it.hasNext()) { String d = it.next(); l.add(d); v.add(wa.optDouble(d)); cc.add(d.equals(ev.optString("peak")) ? Ui.AMBER : 0xFF3B82F6); } out.addView(Chart.bars(c, l, v, cc)); } break; }
            case "SUPPLIER": { JSONArray t = ev.optJSONArray("table"); if (t != null) { java.util.List<String> l = new java.util.ArrayList<>(); java.util.List<Double> v = new java.util.ArrayList<>(); java.util.List<Integer> cc = new java.util.ArrayList<>(); for (int i = 0; i < t.length(); i++) { JSONObject r = t.optJSONObject(i); l.add(r.optString("name")); v.add(r.optDouble("score")); cc.add(r.optDouble("score") >= 70 ? Ui.GREEN : r.optDouble("score") >= 50 ? Ui.AMBER : Ui.RED); } out.addView(Chart.bars(c, l, v, cc, "امتیاز")); } break; }
            case "PRICE_GAP": { out.addView(tiles2(c, tile(c, "قیمت خرید", Ui.moneyShort(ev.optDouble("buy")), "", 0), tile(c, "قیمت فروش فعلی", Ui.moneyShort(ev.has("sell") ? ev.optDouble("sell") : ev.optDouble("sell_price")), "", Ui.RED))); break; }
            case "LOSS_PREV": { JSONArray peers = ev.optJSONArray("peers"); long uid = ev.optJSONObject("row") == null ? -1 : ev.optJSONObject("row").optLong("user_id"); if (peers != null) { java.util.List<String> l = new java.util.ArrayList<>(); java.util.List<Double> v = new java.util.ArrayList<>(); java.util.List<Integer> cc = new java.util.ArrayList<>(); for (int i = 0; i < peers.length(); i++) { JSONObject r = peers.optJSONObject(i); l.add(r.optString("name")); v.add(r.optDouble("void_rate") * 100); cc.add(r.optLong("user_id") == uid ? Ui.RED : Ui.MUTED); } out.addView(Chart.bars(c, l, v, cc, "٪ ابطال")); } break; }
            default: break;
        }
        // generic readable key/values for whatever is left (numbers & short strings only)
        java.util.Iterator<String> it = ev.keys(); int shown = 0;
        while (it.hasNext() && shown < 8) { String key = it.next(); Object v = ev.opt(key); if (v instanceof JSONObject || v instanceof JSONArray || key.endsWith("_id") || key.equals("forecast") || key.equals("expected_gain_raw")) continue; String lab = evLabel(key); if (lab == null) continue; out.addView(Ui.kv(c, lab, v instanceof Number ? Ui.num(((Number) v).doubleValue()) : String.valueOf(v), 0)); shown++; }
    }
    static String evLabel(String k) { switch (k) { case "invoices": return "فاکتورها"; case "customers": return "مشتریان"; case "window_days": return "بازه (روز)"; case "sold_28d": return "فروش ۲۸ روز"; case "margin_per_unit": return "سود هر عدد"; case "partner_name": return "کالای همراه"; case "peak": return "روز اوج"; case "consumer": return "قیمت مصرف‌کننده"; case "margin": return "حاشیه"; default: return null; } }

    static View visitRow(android.content.Context c, JSONObject r) {
        LinearLayout row = Ui.row(c); row.setBackground(Ui.rounded(Ui.CARD2, Ui.BORDER, 12)); row.setPadding(Ui.dp(10), Ui.dp(8), Ui.dp(10), Ui.dp(8)); row.setLayoutParams(Ui.margin(Ui.match(), 0, 6, 0, 0));
        LinearLayout tc = Ui.col(c); tc.setLayoutParams(Ui.weight(1)); tc.addView(Ui.text(c, r.optString("name"), 13.5f, Ui.TEXT, true));
        StringBuilder items = new StringBuilder(); JSONArray ui = r.optJSONArray("usual_items"); for (int i = 0; ui != null && i < Math.min(3, ui.length()); i++) items.append(i > 0 ? "، " : "").append(ui.optJSONObject(i).optString("name"));
        tc.addView(Ui.muted(c, "هر " + Ui.num(r.optInt("typical_gap")) + " روز · " + r.optString("usual_weekday") + "‌ها ساعت " + Ui.num(r.optInt("usual_hour")) + " · نظم " + Ui.fa(String.valueOf(Math.round(r.optDouble("regularity") * 100))) + "٪"));
        if (items.length() > 0) tc.addView(Ui.muted(c, "خرید همیشگی: " + items));
        row.addView(tc); int due = r.optInt("due_in"); row.addView(Ui.badge(c, due <= 0 ? "امروز" : Ui.num(due) + " روز دیگر", due <= 0 ? Ui.GREEN : Ui.TEAL));
        if (!r.isNull("phone") && !r.optString("phone").isEmpty()) { row.setOnClickListener(v -> { try { android.content.Intent in = new android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse("smsto:" + r.optString("phone"))); in.putExtra("sms_body", r.optString("name") + " عزیز، " + (items.length() > 0 ? "«" + ui.optJSONObject(0).optString("name") + "» تازه رسیده؛ " : "") + "منتظر دیدارتان هستیم."); c.startActivity(in); } catch (Exception e) { Ui.toast("برنامهٔ پیامک در دسترس نیست"); } }); }
        return row;
    }

    /* ---------------- v3.2 detail screen (readable body, effect, what-if, charts, actions) ---------------- */
    public static final class Detail extends Screens.Screen {
        final long id;
        Detail(AppActivity a, long id) { super(a); this.id = id; }
        public String key() { return "insightDetail"; } public String title() { return "جزئیات پیشنهاد"; }
        public void load() { loading(); get("/insights/" + id + "?narrate=1", r -> render((JSONObject) r)); }
        void render(JSONObject x) {
            clear(); String st = x.optString("status"); int pc = prioColor(x.optInt("priority"));
            LinearLayout hero = Ui.hero(c); LinearLayout hd = Ui.row(c); hd.addView(Icons.view(c, kindIcon(x.optString("kind")), 0xFFFFFFFF, 26)); LinearLayout tc = Ui.col(c); tc.setLayoutParams(Ui.weight(1)); tc.setPadding(Ui.dp(10), 0, 0, 0); tc.addView(Ui.text(c, x.optString("title"), 17, 0xFFFFFFFF, true)); tc.addView(Ui.text(c, x.optString("label") + " · " + prioLabel(x.optInt("priority")) + " · " + statusLabel(st), 12, 0xDDFFFFFF, false)); hd.addView(tc); hero.addView(hd);
            if (!x.isNull("measured_gain")) { double g = x.optDouble("measured_gain"); JSONObject res = x.optJSONObject("result"); Double gr = res == null || res.isNull("profit_pct_adj") ? null : res.optDouble("profit_pct_adj"); hero.addView(Ui.text(c, (gr == null ? "" : "رشد سود " + pctTxt(gr) + " · ") + "اثر واقعی " + (g >= 0 ? "+" : "−") + Ui.money(Math.abs(g)), 14, g >= 0 ? 0xFFB9F5D8 : 0xFFFFC2C6, true)); }
            else if (x.optDouble("expected_gain") > 0) hero.addView(Ui.text(c, "برآورد سود ماهانه: " + Ui.money(x.optDouble("expected_gain")), 13.5f, 0xFFEFE3B8, true));
            body.addView(hero);
            LinearLayout card = Ui.card(c, "چه اتفاقی افتاده؟"); String narr = x.optString("narrative"); TextView tv = Ui.body(c, narr.isEmpty() || "null".equals(narr) ? x.optString("body") : narr); tv.setLineSpacing(0, 1.4f); card.addView(tv); body.addView(card);
            if (x.optJSONObject("result") != null && x.optJSONObject("baseline") != null) { LinearLayout mc = Ui.card(c, "اثر اجرا — قبل و بعد"); mc.addView(measuredBlock(c, x, true)); body.addView(mc); }
            JSONObject p = x.optJSONObject("prediction"); if (p != null && p.optDouble("gain_month") > 0) { LinearLayout pcard = Ui.card(c, "پیش‌بینی اگر اجرا شود"); pcard.addView(predictBlock(c, p)); body.addView(pcard); }
            LinearLayout evc = Ui.card(c, "شواهد از داده‌های خود فروشگاه"); evidenceViews(c, x, evc); body.addView(evc);
            JSONArray acts = x.optJSONArray("actions"); LinearLayout ac = Ui.card(c, "اقدام‌ها"); if (acts == null || acts.length() == 0) ac.addView(Ui.muted(c, "—")); else for (int i = 0; i < acts.length(); i++) { LinearLayout r = Ui.row(c); r.addView(Icons.view(c, "check", Ui.TEAL, 16)); TextView t = Ui.body(c, acts.optJSONObject(i).optString("label")); t.setPadding(Ui.dp(8), Ui.dp(4), 0, Ui.dp(4)); r.addView(t); ac.addView(r); }
            if ("NEW".equals(st) || "SNOOZED".equals(st)) { android.widget.Button ok = Ui.primary(c, "اجرا و سنجش اثر", () -> Ui.confirm(c, "این پیشنهاد اجرا شود؟ اقدام‌های آن هم‌اکنون انجام و اثرش از امروز اندازه‌گیری می‌شود.", () -> post("/insights/" + id + "/accept", new JSONObject(), rr -> { Sfx.play("ok"); Ui.done(Ui.ctx, "اجرا شد", "اثر این اقدام از امروز اندازه‌گیری می‌شود.", null); load(); }))); ok.setLayoutParams(Ui.margin(Ui.match(), 0, 10, 0, 4)); ac.addView(ok);
                LinearLayout r = Ui.row(c); r.addView(Feed.wbtn(Ui.small(c, "بعداً (۷ روز)", () -> post("/insights/" + id + "/snooze", j("days", "7"), rr -> { Ui.toast("به تعویق افتاد"); a.onBackPressed(); })))); r.addView(Feed.wbtn(Ui.small(c, "رد", () -> post("/insights/" + id + "/dismiss", new JSONObject(), rr -> a.onBackPressed())))); ac.addView(r); }
            else if ("ACCEPTED".equals(st)) { android.widget.Button m = Ui.ghost(c, "سنجش دوباره", () -> post("/insights/" + id + "/measure", new JSONObject(), rr -> load())); ac.addView(m); }
            body.addView(ac);
        }
        static String statusLabel(String s) { switch (s) { case "NEW": return "باز"; case "ACCEPTED": return "اجراشده — در حال سنجش"; case "MEASURED": return "سنجیده‌شده"; case "SNOOZED": return "به تعویق"; case "DISMISSED": return "ردشده"; case "EXPIRED": return "منقضی"; default: return s; } }
    }

    /* ---------------- v3.2 customer purchase-pattern prediction ---------------- */
    public static final class Customers extends Screens.Screen {
        Customers(AppActivity a) { super(a); }
        public String key() { return "insightsCustomers"; } public String title() { return "پیش‌بینی خرید مشتریان"; }
        public void load() { loading(); get("/insights/customers/patterns?days=7", r -> render((JSONObject) r)); }
        void render(JSONObject d) {
            clear(); JSONArray rows = d.optJSONArray("rows"); if (rows == null) rows = new JSONArray(); int today = 0, phone = 0; double mp = 0; int[] byDay = new int[8];
            for (int i = 0; i < rows.length(); i++) { JSONObject r = rows.optJSONObject(i); if (r.optInt("due_in") <= 0) today++; if (!r.isNull("phone") && !r.optString("phone").isEmpty()) phone++; mp += r.optDouble("monthly_profit"); byDay[Math.max(0, Math.min(7, r.optInt("due_in")))]++; }
            LinearLayout hero = Ui.hero(c); hero.addView(Ui.text(c, "چه کسی این هفته می‌آید؟", 20, 0xFFFFFFFF, true)); hero.addView(Ui.text(c, "از فاصلهٔ خریدهای هر مشتری ثابت، نوبت بعدی‌اش پیش‌بینی می‌شود. درست قبل از نوبت، با یک پیامک شخصی («کالای همیشگی‌تان رسیده») صدایش کنید — لمس هر ردیف، پیامک را آماده می‌کند.", 12.5f, 0xDDFFFFFF, false));
            LinearLayout kp = Ui.row(c); kp.setPadding(0, Ui.dp(10), 0, 0); kp.addView(hk("امروز", Ui.num(today))); kp.addView(hk("۷ روز آینده", Ui.num(rows.length()))); kp.addView(hk("قابل پیامک", Ui.num(phone))); kp.addView(hk("سود ماهانه", Ui.moneyShort(mp))); hero.addView(kp); body.addView(hero);
            LinearLayout ch = Ui.card(c, "چند مشتری در هر روز نوبتشان است؟"); java.util.List<String> l = new java.util.ArrayList<>(); java.util.List<Double> v = new java.util.ArrayList<>(); java.util.List<Integer> cc = new java.util.ArrayList<>(); for (int k = 0; k <= 7; k++) { l.add(k == 0 ? "امروز" : Ui.num(k) + " روز دیگر"); v.add((double) byDay[k]); cc.add(PALETTE[k % PALETTE.length]); } ch.addView(Chart.bars(c, l, v, cc, "نفر")); body.addView(ch);
            LinearLayout lc = Ui.card(c, "مشتریان در نوبت"); if (rows.length() == 0) lc.addView(Ui.empty(c, "هنوز الگوی منظمی پیدا نشده — با ثبت مشتری روی فاکتورها، این صفحه پر می‌شود.")); for (int i = 0; i < rows.length(); i++) lc.addView(visitRow(c, rows.optJSONObject(i))); body.addView(lc);
        }
        View hk(String l, String v) { LinearLayout t = Ui.col(c); t.setLayoutParams(Ui.weight(1)); t.addView(Ui.text(c, v, 15, 0xFFFFFFFF, true)); t.addView(Ui.text(c, l, 11, 0xCCFFFFFF, false)); return t; }
    }

    /* ---------------- v3.1 planning & profit forecast ---------------- */
    static String conf(String c) { switch (c) { case "high": return "بالا"; case "medium": return "متوسط"; case "low": return "پایین (اولین تجربه)"; default: return "—"; } }
    static String md(String iso) { try { String[] p = iso.substring(0, 10).split("-"); int[] j = Jalali.toJalali(Integer.parseInt(p[0]), Integer.parseInt(p[1]), Integer.parseInt(p[2])); return Ui.fa(j[1] + "/" + j[2]); } catch (Exception e) { return iso; } }

    /** «اگر این پیشنهاد اجرا شود…» block (calibrated gain, band, growth %, 90-day path). */
    static View predictBlock(android.content.Context c, JSONObject p) {
        LinearLayout m = Ui.col(c); m.setBackground(Ui.rounded(0x14000000, 0, 12)); m.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8)); m.setLayoutParams(Ui.margin(Ui.match(), 0, 8, 0, 0));
        m.addView(Ui.text(c, "اگر این پیشنهاد اجرا شود…", 12.5f, Ui.MUTED, true));
        m.addView(Ui.kv(c, "سود اضافه در ماه", "+" + Ui.money(p.optDouble("gain_month")), Ui.GREEN));
        m.addView(Ui.kv(c, "بازهٔ پیش‌بینی", Ui.money(p.optDouble("low_month")) + " تا " + Ui.money(p.optDouble("high_month")), 0));
        m.addView(Ui.kv(c, "رشد سود ماهانهٔ فروشگاه", p.isNull("growth_pct") ? "—" : Ui.fa(String.valueOf(p.optDouble("growth_pct"))) + "٪", 0));
        m.addView(Ui.kv(c, "جمع ۹۰ روز", "+" + Ui.money(p.optDouble("gain_90d")), Ui.GREEN));
        m.addView(Ui.kv(c, "اطمینان", conf(p.optString("confidence")) + (p.optInt("history_n") > 0 ? " (" + Ui.num(p.optInt("history_n")) + " اقدام مشابه سنجیده‌شده)" : ""), 0));
        JSONArray path = p.optJSONArray("path");
        if (path != null && path.length() > 0) {
            java.util.List<Double> g = new java.util.ArrayList<>(), lo = new java.util.ArrayList<>(), hi = new java.util.ArrayList<>(); g.add(0.0); lo.add(0.0); hi.add(0.0); String[] lb = new String[path.length() + 1]; lb[0] = "امروز";
            for (int i = 0; i < path.length(); i++) { JSONObject x = path.optJSONObject(i); g.add(x.optDouble("cum_gain")); lo.add(x.optDouble("cum_low")); hi.add(x.optDouble("cum_high")); lb[i + 1] = i % 2 == 1 ? "روز " + Ui.num(x.optInt("day")) : null; }
            java.util.List<Chart.Series> ss = new java.util.ArrayList<>(); ss.add(new Chart.Series("سود تجمعی اضافه", Ui.VIOLET, Chart.arr(g), false, true));
            m.addView(Chart.line(c, ss, lb, Chart.arr(lo), Chart.arr(hi), 130));
        }
        m.addView(Ui.muted(c, "با هر اقدام اجراشده، اثر واقعی سنجیده و ضریب همین نوع پیشنهاد اصلاح می‌شود؛ پیش‌بینی‌ها به مرور دقیق‌تر می‌شوند."));
        return m;
    }

    public static final class Plan extends Screens.Screen {
        Plan(AppActivity a) { super(a); }
        public String key() { return "insightsPlan"; } public String title() { return "برنامه‌ریزی و پیش‌بینی سود"; }
        public void load() { loading(); get("/insights/plan?horizon=90", r -> render((JSONObject) r)); }
        void render(JSONObject p) {
            clear(); JSONObject m = p.optJSONObject("model"), b = p.optJSONObject("baseline"), pl = p.optJSONObject("plan");
            LinearLayout hero = Ui.hero(c); hero.addView(Ui.text(c, "پیش‌بینی سود فروشگاه", 20, 0xFFFFFFFF, true));
            hero.addView(Ui.text(c, "روند فعلی در برابر برنامهٔ اجرای پیشنهادهای باز — با بازهٔ اطمینان و دقت مدل تا امروز.", 12.5f, 0xCCFFFFFF, false));
            LinearLayout kp = Ui.row(c); kp.setPadding(0, Ui.dp(10), 0, 0);
            kp.addView(heroKpi("پایه / ماه", Ui.moneyShort(b.optDouble("profit_month")))); kp.addView(heroKpi("با برنامه / ماه", Ui.moneyShort(pl.optDouble("profit_month")))); kp.addView(heroKpi("رشد", pl.isNull("growth_pct") ? "—" : "+" + Ui.fa(String.valueOf(pl.optDouble("growth_pct"))) + "٪")); hero.addView(kp);
            LinearLayout br = Ui.row(c); br.setPadding(0, Ui.dp(10), 0, 0);
            br.addView(Ui.small(c, "پیشنهادها", () -> a.route("insights"))); br.addView(Ui.small(c, "بازآموزی مدل", () -> post("/insights/plan/learn", new JSONObject(), r -> { Ui.toast("ضرایب از اندازه‌گیری‌های واقعی به‌روز شد"); load(); }))); hero.addView(br); body.addView(hero);
            body.addView(Ui.grid2(c, Ui.kpi(c, "سود اضافهٔ برنامه / ماه", "+" + Ui.money(pl.optDouble("gain_month")), "بازه " + Ui.moneyShort(pl.optDouble("low_month")) + " تا " + Ui.moneyShort(pl.optDouble("high_month")), Ui.GREEN),
                    Ui.kpi(c, "دقت مدل تا امروز", m.isNull("direction_accuracy") ? "—" : Ui.fa(String.valueOf(Math.round(m.optDouble("direction_accuracy") * 100))) + "٪ جهت درست", m.optInt("measured_count") > 0 ? Ui.num(m.optInt("measured_count")) + " اقدام سنجیده · خطا " + (m.isNull("mean_abs_pct_error") ? "—" : Ui.fa(String.valueOf(m.optInt("mean_abs_pct_error"))) + "٪") : "هنوز اقدامی سنجیده نشده", Ui.VIOLET)));
            body.addView(Ui.grid2(c, Ui.kpi(c, "روند هفتگی", (m.optDouble("trend_pct_per_week") >= 0 ? "+" : "") + Ui.fa(String.valueOf(m.optDouble("trend_pct_per_week"))) + "٪", Ui.num(m.optInt("weeks_of_history")) + " هفته سابقه", Ui.TEAL),
                    Ui.kpi(c, "۹۰ روز آینده", "+" + Ui.moneyShort(pl.optDouble("gain_horizon")), "سود اضافه با اجرای " + Ui.num(pl.optInt("open")) + " پیشنهاد", Ui.GOLD)));
            // weekly chart
            JSONArray hw = p.optJSONArray("history_weeks"), fc = p.optJSONArray("forecast"); int hn = Math.min(14, hw.length()), off = hw.length() - hn;
            java.util.List<Double> hist = new java.util.ArrayList<>(), base = new java.util.ArrayList<>(), plan = new java.util.ArrayList<>(); String[] lb = new String[hn + fc.length()];
            for (int i = 0; i < hn; i++) { JSONObject w = hw.optJSONObject(off + i); hist.add(w.optDouble("profit")); base.add(i == hn - 1 ? w.optDouble("profit") : null); plan.add(i == hn - 1 ? w.optDouble("profit") : null); lb[i] = i % 3 == 0 ? md(w.optString("week_start")) : null; }
            for (int i = 0; i < fc.length(); i++) { JSONObject f = fc.optJSONObject(i); hist.add(null); base.add(f.optDouble("week_baseline")); plan.add(f.optDouble("week_plan")); lb[hn + i] = i % 3 == 0 ? md(f.optString("day")) : null; }
            LinearLayout c1 = Ui.card(c, "سود هفتگی: گذشته، روند پایه و برنامه");
            java.util.List<Chart.Series> s1 = new java.util.ArrayList<>(); s1.add(new Chart.Series("سود واقعی", Ui.TEAL, Chart.arr(hist), false, true)); s1.add(new Chart.Series("ادامهٔ روند", Ui.MUTED, Chart.arr(base), true, false)); s1.add(new Chart.Series("با اجرای پیشنهادها", Ui.VIOLET, Chart.arr(plan), false, false));
            c1.addView(Chart.line(c, s1, lb, null, null, 190)); c1.addView(Chart.legend(c, s1)); body.addView(c1);
            // cumulative
            java.util.List<Double> cb = new java.util.ArrayList<>(), cp = new java.util.ArrayList<>(), cl = new java.util.ArrayList<>(), ch = new java.util.ArrayList<>(); String[] lb2 = new String[fc.length()];
            for (int i = 0; i < fc.length(); i++) { JSONObject f = fc.optJSONObject(i); cb.add(f.optDouble("cum_baseline")); cp.add(f.optDouble("cum_plan")); cl.add(f.optDouble("cum_low")); ch.add(f.optDouble("cum_high")); lb2[i] = i % 2 == 0 ? md(f.optString("day")) : null; }
            LinearLayout c2 = Ui.card(c, "سود تجمعی ۹۰ روز آینده (با بازهٔ اطمینان)");
            java.util.List<Chart.Series> s2 = new java.util.ArrayList<>(); s2.add(new Chart.Series("پایه", Ui.MUTED, Chart.arr(cb), true, false)); s2.add(new Chart.Series("برنامه", Ui.VIOLET, Chart.arr(cp), false, true));
            c2.addView(Chart.line(c, s2, lb2, Chart.arr(cl), Chart.arr(ch), 180)); c2.addView(Chart.legend(c, s2)); body.addView(c2);
            // by kind
            JSONArray bk = p.optJSONArray("by_kind");
            if (bk != null && bk.length() > 0) { LinearLayout c3 = Ui.card(c, "سهم هر نوع پیشنهاد در سود ماهانهٔ برنامه"); java.util.List<String> ls = new java.util.ArrayList<>(); java.util.List<Double> vs = new java.util.ArrayList<>(); for (int i = 0; i < bk.length(); i++) { JSONObject k = bk.optJSONObject(i); ls.add(k.optString("label") + " (" + Ui.num(k.optInt("count")) + ")"); vs.add(k.optDouble("gain_month")); } c3.addView(Chart.bars(c, ls, vs, null)); body.addView(c3); }
            // action plan
            LinearLayout c4 = Ui.card(c, "برنامهٔ اقدام — به ترتیب اثر"); JSONArray items = p.optJSONArray("items");
            if (items == null || items.length() == 0) c4.addView(Ui.empty(c, "پیشنهاد بازی نیست"));
            for (int i = 0; items != null && i < items.length(); i++) { JSONObject it = items.optJSONObject(i); final long id = it.optLong("id");
                LinearLayout row = Ui.col(c); row.setPadding(0, Ui.dp(8), 0, Ui.dp(8)); row.addView(Ui.text(c, it.optString("title"), 13.5f, Ui.TEXT, true));
                row.addView(Ui.kv(c, it.optString("label") + " · اطمینان " + conf(it.optString("confidence")), "+" + Ui.money(it.optDouble("gain_month")) + " / ماه", Ui.GREEN));
                row.addView(Ui.muted(c, "بازه " + Ui.moneyShort(it.optDouble("low_month")) + " تا " + Ui.moneyShort(it.optDouble("high_month")) + " · ۹۰ روز +" + Ui.moneyShort(it.optDouble("gain_horizon"))));
                row.setOnClickListener(v -> a.route("insights")); c4.addView(row); if (i < items.length() - 1) c4.addView(Ui.divider(c)); }
            body.addView(c4);
            // learning
            LinearLayout c5 = Ui.card(c, "یادگیری مدل — پیش‌بینی در برابر اثر واقعی"); JSONArray cal = m.optJSONArray("calibration");
            if (cal == null || cal.length() == 0) c5.addView(Ui.muted(c, "هنوز اقدامی به پایان اندازه‌گیری نرسیده؛ پس از اولین اقدام سنجیده‌شده، ضریب هر نوع پیشنهاد به‌طور خودکار یاد گرفته می‌شود."));
            for (int i = 0; cal != null && i < cal.length(); i++) { JSONObject k = cal.optJSONObject(i); c5.addView(Ui.kv(c, k.optString("label") + " · " + Ui.num(k.optInt("n")) + " اقدام", "ضریب " + Ui.fa(String.valueOf(k.optDouble("ratio"))) + (k.isNull("direction_accuracy") ? "" : " · جهت " + Ui.fa(String.valueOf(Math.round(k.optDouble("direction_accuracy") * 100))) + "٪"), 0)); }
            JSONArray acc = p.optJSONArray("accuracy");
            if (acc != null && acc.length() > 0) { java.util.List<String> ls = new java.util.ArrayList<>(); java.util.List<Double> vs = new java.util.ArrayList<>(); java.util.List<Integer> cs = new java.util.ArrayList<>(); for (int i = 0; i < Math.min(8, acc.length()); i++) { JSONObject x = acc.optJSONObject(i); ls.add(x.optString("title") + " — پیش‌بینی"); vs.add(x.optDouble("calibrated")); cs.add(Ui.MUTED); ls.add("اثر واقعی"); vs.add(x.optDouble("measured")); cs.add(Ui.VIOLET); } c5.addView(Chart.bars(c, ls, vs, cs)); }
            body.addView(c5);
        }
        View heroKpi(String l, String v) { LinearLayout t = Ui.col(c); t.setLayoutParams(Ui.weight(1)); t.addView(Ui.text(c, v, 15, 0xFFFFFFFF, true)); t.addView(Ui.text(c, l, 11, 0xCCFFFFFF, false)); return t; }
    }


    /* ---------------- v3.4 — بانک محصولات (catalog.pack from the PC / a file) ---------------- */
    public static final class CatalogScreen extends Screens.Screen {
        CatalogScreen(AppActivity a) { super(a); }
        public String key() { return "catalog"; } public String title() { return "بانک محصولات"; }
        public void load() {
            clear();
            JSONObject inf = Catalog.info(a);
            LinearLayout info = Ui.card(c, "بانک محصولات فروشگاه (نام + دسته + تصویر، آفلاین)");
            info.addView(Ui.body(c, "بانک محصولات روی رایانهٔ ویندوز از پوشهٔ اکسل و تصاویر شما ساخته می‌شود و به‌صورت یک فایل (catalog.pack) به گوشی می‌آید. بعد از دریافت، اسکن هر بارکد نام و تصویر کالا را بدون اینترنت نشان می‌دهد. تصاویر در حافظهٔ خصوصی برنامه می‌مانند و در گالری دیده نمی‌شوند."));
            if (inf.optBoolean("exists")) info.addView(Ui.kv(c, "وضعیت", Ui.fa(String.valueOf(inf.optInt("items"))) + " کالا · " + Ui.fa(String.valueOf(inf.optInt("images"))) + " تصویر · " + Ui.fa(String.format(java.util.Locale.US, "%.1f", inf.optLong("bytes") / 1048576.0)) + " MB · " + Ui.jdate(new java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).format(new java.util.Date(inf.optLong("at")))), 0));
            else info.addView(Ui.kv(c, "وضعیت", "هنوز دریافت نشده", 0xFFB45309));
            body.addView(info);
            LinearLayout act = Ui.card(c, "دریافت");
            if (!Api.standalone()) act.addView(Ui.primary(c, "دریافت از رایانه (شبکهٔ داخلی)", () -> run(pr -> Catalog.fetchFromPc(a, pr))));
            act.addView(Ui.ghost(c, "انتخاب فایل catalog.pack از گوشی…", this::pick));
            act.addView(Ui.muted(c, Api.standalone() ? "روی رایانه: تنظیمات → بانک محصولات → «دانلود برای کپی روی گوشی»؛ فایل را با کابل/بلوتوث/تلگرام به گوشی بفرستید و اینجا انتخاب کنید." : "رایانه باید روشن و روی همان وای‌فای باشد. اگر روی رایانه هنوز «وارد کردن از پوشه» انجام نشده، اول همان را انجام دهید."));
            body.addView(act);
        }
        void pick() { Intent i = new Intent(Intent.ACTION_GET_CONTENT); i.setType("*/*"); i.addCategory(Intent.CATEGORY_OPENABLE); a.pickCb = uri -> run(pr -> { java.io.InputStream in = a.getContentResolver().openInputStream(uri); long len = -1; try (android.database.Cursor cu = a.getContentResolver().query(uri, null, null, null, null)) { if (cu != null && cu.moveToFirst()) { int ix = cu.getColumnIndex(android.provider.OpenableColumns.SIZE); if (ix >= 0) len = cu.getLong(ix); } } catch (Exception ignore) {} return Catalog.importFrom(a, in, len, pr); }); Biometric.markInternal(); a.startActivityForResult(Intent.createChooser(i, "انتخاب فایل بانک محصولات"), AppActivity.REQ_PICK); }
        interface Job { JSONObject run(Catalog.Progress pr) throws Exception; }
        void run(Job job) {
            final android.app.Dialog[] dlg = new android.app.Dialog[1]; final android.widget.ProgressBar bar = new android.widget.ProgressBar(c, null, android.R.attr.progressBarStyleHorizontal); bar.setMax(100); bar.setIndeterminate(true);
            final TextView st = Ui.body(c, "در حال شروع…"); LinearLayout l = Ui.col(c); l.addView(st); l.addView(bar); l.addView(Ui.muted(c, "بسته به حجم تصاویر ممکن است چند دقیقه طول بکشد. برنامه را نبندید."));
            dlg[0] = Ui.sheet(c, "دریافت بانک محصولات", l); dlg[0].setCancelable(false);
            Thread t = new Thread(() -> {
                try {
                    JSONObject rep = job.run((phase, done, total) -> Api.ui(() -> { if ("download".equals(phase)) { st.setText("دریافت فایل… " + Ui.fa(String.valueOf(done / 1024)) + (total > 0 ? " از " + Ui.fa(String.valueOf(total / 1024)) + " MB" : " MB")); if (total > 0) { bar.setIndeterminate(false); bar.setProgress((int) (done * 100L / total)); } } else { st.setText("ثبت کالاها… " + Ui.fa(String.valueOf(done)) + (total > 0 ? " از " + Ui.fa(String.valueOf(total)) : "")); if (total > 0) { bar.setIndeterminate(false); bar.setProgress((int) (done * 100L / total)); } } }));
                    Api.ui(() -> { try { dlg[0].dismiss(); } catch (Exception ignore) {} Sfx.play("ok"); Ui.done(Ui.ctx, "بانک محصولات دریافت شد", Ui.fa(String.valueOf(rep.optInt("items"))) + " کالا و " + Ui.fa(String.valueOf(rep.optInt("images"))) + " تصویر" + (rep.optInt("created") > 0 ? " · " + Ui.fa(String.valueOf(rep.optInt("created"))) + " کالای جدید به فهرست اضافه شد" : ""), null); load(); });
                } catch (Throwable e) {
                    Api.ui(() -> { try { dlg[0].dismiss(); } catch (Exception ignore) {} new android.app.AlertDialog.Builder(c).setTitle("دریافت انجام نشد").setMessage(e.getMessage() == null ? String.valueOf(e) : e.getMessage()).setPositiveButton("باشه", null).show(); });
                }
            }, "catalog-import"); t.setDaemon(true); t.start();
        }
    }

    /* ---------------- Backup (create / share / import) ---------------- */
    public static final class Backup extends Screens.Screen {
        Backup(AppActivity a) { super(a); }
        public String key() { return "backup"; } public String title() { return "پشتیبان‌گیری"; }
        public void load() {
            clear();
            LinearLayout info = Ui.card(c, "پشتیبان‌گیری و بازیابی"); info.addView(Ui.body(c, "پشتیبان یک فایل کامل از همهٔ داده‌های گوشی است (کالاها، فاکتورها، مشتریان، تنظیمات، هوش فروشگاه). آن را در جای امنی (فضای ابری، رایانه) نگه دارید.")); info.addView(Ui.kv(c, "آخرین پشتیبان", Db.kv("last_backup") == null ? "—" : Ui.jdate(Db.kv("last_backup")), 0)); info.addView(Ui.kv(c, "آخرین بازیابی", Db.kv("last_restore") == null ? "—" : Ui.jdate(Db.kv("last_restore")), 0)); info.addView(Ui.kv(c, "پشتیبان خودکار روزانه", "true".equals(Local.setting("backup.auto_daily", "true")) ? "روشن" : "خاموش", 0)); body.addView(info);
            LinearLayout act = Ui.card(c, "اقدام‌ها");
            act.addView(Ui.primary(c, "تهیهٔ پشتیبان اکنون", () -> Api.bg(() -> { try { java.io.File f = Local.backup(a); Api.ui(() -> { Sfx.play("ok"); Ui.done(Ui.ctx, "پشتیبان ساخته شد", f.getName() + " (" + Ui.num(f.length() / 1024) + " KB)", null); load(); }); } catch (Exception e) { Ui.toast("خطا: " + e.getMessage()); } })));
            act.addView(Ui.ghost(c, "تهیه و ارسال (اشتراک‌گذاری فایل)", () -> Api.bg(() -> { try { java.io.File f = Local.backup(a); Api.ui(() -> share(f)); } catch (Exception e) { Ui.toast("خطا: " + e.getMessage()); } })));
            act.addView(Ui.ghost(c, "بازیابی از فایل پشتیبان…", () -> Ui.confirm(c, "با بازیابی، داده‌های فعلی گوشی با فایل پشتیبان جایگزین می‌شود (یک نسخهٔ امن از داده‌های فعلی هم گرفته می‌شود). ادامه می‌دهید؟", this::pick)));
            act.addView(Ui.muted(c, "فایل پشتیبان گوشی، فایل پشتیبان نسخهٔ ویندوز و فایل فشردهٔ .gz (مثل فروشگاه نمونه) هر سه قابل بازیابی‌اند."));
            body.addView(act);
            LinearLayout list = Ui.card(c, "پشتیبان‌های روی گوشی"); java.io.File dir = new java.io.File(a.getExternalFilesDir(null), "backups"); java.io.File[] fs = dir.listFiles(); int n = 0;
            if (fs != null) { java.util.Arrays.sort(fs, (x, y) -> Long.compare(y.lastModified(), x.lastModified())); for (java.io.File f : fs) { if (!f.getName().endsWith(".db")) continue; n++; final java.io.File ff = f; list.addView(Ui.item(c, f.getName(), Ui.num(f.length() / 1024) + " KB", "بازیابی", Ui.PRIMARY, () -> { LinearLayout l = Ui.col(c); l.addView(Ui.ghost(c, "اشتراک‌گذاری این فایل", () -> share(ff))); l.addView(Ui.primary(c, "بازیابی از این نسخه", () -> Ui.confirm(c, "داده‌های فعلی با «" + ff.getName() + "» جایگزین شود؟", () -> restore(() -> { try { return new java.io.FileInputStream(ff); } catch (Exception e) { return null; } })))); Ui.sheet(c, ff.getName(), l); })); } }
            if (n == 0) list.addView(Ui.empty(c, "هنوز پشتیبانی ساخته نشده")); body.addView(list);
        }
        void share(java.io.File f) { try { android.net.Uri u = BackupProvider.uri(a, f); Intent i = new Intent(Intent.ACTION_SEND); i.setType("application/octet-stream"); i.putExtra(Intent.EXTRA_STREAM, u); i.putExtra(Intent.EXTRA_SUBJECT, "پشتیبان سوپری من — " + f.getName()); i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION); Biometric.markInternal(); a.startActivity(Intent.createChooser(i, "ارسال فایل پشتیبان")); } catch (Exception e) { Ui.toast("اشتراک‌گذاری ممکن نشد: " + e.getMessage()); } }
        void pick() { Intent i = new Intent(Intent.ACTION_GET_CONTENT); i.setType("*/*"); i.addCategory(Intent.CATEGORY_OPENABLE); a.pickCb = uri -> restore(() -> { try { return a.getContentResolver().openInputStream(uri); } catch (Exception e) { return null; } }); Biometric.markInternal(); a.startActivityForResult(Intent.createChooser(i, "انتخاب فایل پشتیبان"), AppActivity.REQ_PICK); }
        void restore(java.util.function.Supplier<java.io.InputStream> src) {
            // v3.3: dedicated thread (never one of the 4 API workers the screens depend on), a modal progress sheet
            // with the current step, a system notification while it runs, and a clear error instead of a crash.
            final android.app.Dialog[] dlg = new android.app.Dialog[1]; final android.widget.ProgressBar bar = new android.widget.ProgressBar(c, null, android.R.attr.progressBarStyleHorizontal); bar.setMax(100); bar.setIndeterminate(false);
            final TextView step = Ui.body(c, "آماده‌سازی…"); final TextView pct = Ui.muted(c, "۰٪");
            LinearLayout box = Ui.col(c); box.setPadding(Ui.dp(4), Ui.dp(6), Ui.dp(4), Ui.dp(6)); box.addView(step); box.addView(bar); box.addView(pct); box.addView(Ui.muted(c, "برنامه را نبندید؛ داده‌های فعلی تا پایان موفقیت‌آمیز دست‌نخورده می‌مانند."));
            try { dlg[0] = Ui.sheet(c, "در حال بازیابی", box); dlg[0].setCancelable(false); dlg[0].setCanceledOnTouchOutside(false); } catch (Exception ignore) {}
            final long[] lastN = {0};
            Thread t = new Thread(() -> {
                try (java.io.InputStream in = src.get()) {
                    if (in == null) throw new Exception("فایل خوانده نشد");
                    org.json.JSONObject r = Local.restore(a, in, (p, m) -> { Api.ui(() -> { bar.setProgress(p); step.setText(m); pct.setText(Ui.fa(String.valueOf(p)) + "٪"); }); if (System.currentTimeMillis() - lastN[0] > 1500) { lastN[0] = System.currentTimeMillis(); Notify.progress(a, "بازیابی پشتیبان", m, p); } });
                    Notify.progressDone(a, "بازیابی انجام شد", "windows".equals(r.optString("source")) ? Ui.fa(String.valueOf(r.optInt("invoices"))) + " فاکتور وارد شد" : "داده‌ها بارگذاری شدند");
                    String msg = "windows".equals(r.optString("source")) ? "نسخهٔ ویندوز وارد شد: " + Ui.fa(String.valueOf(r.optInt("invoices"))) + " فاکتور، " + Ui.fa(String.valueOf(r.optInt("products"))) + " کالا، " + Ui.fa(String.valueOf(r.optInt("customers"))) + " مشتری." : "داده‌ها از فایل پشتیبان بارگذاری شدند.";
                    Api.ui(() -> { try { if (dlg[0] != null) dlg[0].dismiss(); } catch (Exception ignore) {} Sfx.play("ok"); Screens.loadConfig(a); Ui.done(Ui.ctx, "بازیابی انجام شد", msg, () -> a.route("home")); });
                } catch (Throwable e) {
                    Notify.progressDone(a, "بازیابی ناموفق", String.valueOf(e.getMessage()));
                    Api.ui(() -> { try { if (dlg[0] != null) dlg[0].dismiss(); } catch (Exception ignore) {} Ui.toast("بازیابی ناموفق: " + e.getMessage()); load(); });
                }
            }, "restore"); t.setPriority(Thread.NORM_PRIORITY + 1); t.start();
        }
    }
}
