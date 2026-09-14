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
    static String prioLabel(int p) { return p <= 1 ? "فوری" : p == 2 ? "مهم" : "پیشنهاد"; }
    static String kindIcon(String k) { switch (k) { case "CROSS_SELL": case "BASKET_NUDGE": return "cart"; case "EXPIRY_LADDER": return "calendar"; case "DEAD_STOCK": return "box"; case "VELOCITY": return "trend"; case "CASHFLOW": return "bank"; case "VIP": return "star"; case "CHURN": return "users"; case "PRICE_GAP": return "tag"; case "LOSS_PREV": return "shield"; case "SEASON": return "chart"; } return "star"; }

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
        int tab = 0; JSONObject summary = new JSONObject();
        Feed(AppActivity a) { super(a); }
        public String key() { return "insights"; } public String title() { return "هوش فروشگاه"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            loading();
            get("/insights/summary", r -> { summary = (JSONObject) r; String st = tab == 0 ? "NEW" : tab == 1 ? "ACCEPTED,MEASURED" : "DISMISSED,SNOOZED,EXPIRED"; get("/insights?status=" + st + "&limit=80", rr -> render(arr(rr))); });
        }
        void render(JSONArray items) {
            clear();
            LinearLayout hero = Ui.hero(c); hero.addView(Ui.text(c, "هوش فروشگاه", 20, 0xFFFFFFFF, true)); hero.addView(Ui.text(c, "تحلیل محلی روی داده‌های خودتان — پیشنهادها را با یک لمس اجرا کنید؛ اثر واقعی هر اقدام اندازه‌گیری می‌شود.", 12, 0xDDFFFFFF, false));
            LinearLayout kp = Ui.row(c); kp.setPadding(0, Ui.dp(10), 0, 0);
            kp.addView(heroKpi("اثر کل", Ui.money(summary.optDouble("total_gain")))); kp.addView(heroKpi("۳۰ روز اخیر", Ui.money(summary.optDouble("month_gain")))); kp.addView(heroKpi("باز", Ui.num(summary.optInt("open")))); hero.addView(kp);
            LinearLayout br = Ui.row(c); br.setPadding(0, Ui.dp(10), 0, 0); android.widget.Button run = Ui.small(c, "تحلیل دوباره", () -> { Ui.toast("در حال تحلیل…"); post("/insights/run", new JSONObject(), r -> { JSONObject x = (JSONObject) r; Ui.done(Ui.ctx, "تحلیل انجام شد", Ui.num(x.optInt("created")) + " پیشنهاد تازه · " + Ui.num(x.optInt("refreshed")) + " به‌روزرسانی", null); load(); }); }); br.addView(run);
            br.addView(Ui.small(c, "پیش‌بینی سود", () -> a.route("insightsPlan")));
            android.widget.Button rep = Ui.small(c, "گزارش هفتگی", () -> get("/insights/report", r -> { JSONObject x = (JSONObject) r; LinearLayout l = Ui.col(c); TextView tv = Ui.body(c, x.optString("narrative")); tv.setLineSpacing(0, 1.35f); l.addView(tv); Ui.sheet(c, "گزارش هوش فروشگاه", l); })); br.addView(rep);
            android.widget.Button lst = Ui.small(c, "لیست سفارش", () -> get("/insights/tasks", r -> { JSONArray t = arr(r); LinearLayout l = Ui.col(c); if (t.length() == 0) l.addView(Ui.empty(c, "لیست سفارش خالی است")); for (int i = 0; i < t.length(); i++) { JSONObject x = t.optJSONObject(i); l.addView(Ui.kv(c, x.optString("name"), Ui.num(x.optDouble("qty")) + " عدد", Ui.AMBER)); } Ui.sheet(c, "لیست سفارش پیشنهادی", l); })); br.addView(lst); hero.addView(br); body.addView(hero);
            body.addView(tabs(new String[]{"پیشنهادها", "اجراشده و اثر", "بایگانی"}, tab, k -> { tab = k; load(); }));
            if (items.length() == 0) { body.addView(Ui.empty(c, tab == 0 ? "پیشنهاد بازی نیست — با فروش بیشتر، تحلیل دقیق‌تر می‌شود" : "موردی نیست")); return; }
            for (int i = 0; i < items.length(); i++) body.addView(card(items.optJSONObject(i)));
        }
        View heroKpi(String l, String v) { LinearLayout t = Ui.col(c); t.setLayoutParams(Ui.weight(1)); t.addView(Ui.text(c, v, 15, 0xFFFFFFFF, true)); t.addView(Ui.text(c, l, 11, 0xCCFFFFFF, false)); return t; }
        View card(JSONObject x) {
            LinearLayout card = Ui.card(c, null); card.setLayoutParams(Ui.margin(Ui.match(), 0, 0, 0, 10));
            LinearLayout hd = Ui.row(c); hd.setGravity(Gravity.CENTER_VERTICAL); hd.addView(Icons.view(c, kindIcon(x.optString("kind")), prioColor(x.optInt("priority")), 20)); LinearLayout tc = Ui.col(c); tc.setLayoutParams(Ui.weight(1)); tc.setPadding(Ui.dp(8), 0, 0, 0); tc.addView(Ui.text(c, x.optString("title"), 14.5f, Ui.TEXT, true)); tc.addView(Ui.muted(c, x.optString("label") + " · " + prioLabel(x.optInt("priority")))); hd.addView(tc);
            String st = x.optString("status"); if ("NEW".equals(st) && x.optDouble("expected_gain") > 0) hd.addView(Ui.badge(c, "~" + Ui.money(x.optDouble("expected_gain")) + "/ماه", Ui.GREEN)); else if (!x.isNull("measured_gain")) { double g = x.optDouble("measured_gain"); hd.addView(Ui.badge(c, (g >= 0 ? "+" : "") + Ui.money(g), g >= 0 ? Ui.GREEN : Ui.RED)); } else if ("ACCEPTED".equals(st)) hd.addView(Ui.badge(c, "در حال سنجش", Ui.AMBER)); card.addView(hd);
            TextView b = Ui.body(c, x.optString("body")); b.setLineSpacing(0, 1.3f); b.setPadding(0, Ui.dp(8), 0, 0); card.addView(b);
            JSONObject fc = x.optJSONObject("evidence") == null ? null : x.optJSONObject("evidence").optJSONObject("forecast");
            if ("NEW".equals(st) && fc != null && fc.optDouble("gain_month") > 0) card.addView(Ui.muted(c, "پیش‌بینی سود ماهانه: " + Ui.money(fc.optDouble("gain_month")) + " (" + Ui.moneyShort(fc.optDouble("low_month")) + " تا " + Ui.moneyShort(fc.optDouble("high_month")) + ") · اطمینان " + conf(fc.optString("confidence"))));
            JSONObject res = x.optJSONObject("result"), base = x.optJSONObject("baseline");
            if (res != null && base != null) { LinearLayout m = Ui.col(c); m.setBackground(Ui.rounded(0x14000000, 0, 12)); m.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8)); m.setLayoutParams(Ui.margin(Ui.match(), 0, 8, 0, 0)); m.addView(Ui.text(c, "قبل و بعد (" + res.optString("unit") + ")", 12, Ui.MUTED, true));
                m.addView(Ui.kv(c, "قبل (" + Ui.num(base.optDouble("window_days")) + " روز)", Ui.num(base.optDouble("value")), 0)); m.addView(Ui.kv(c, "بعد (" + Ui.num(res.optDouble("elapsed_days")) + " روز)", Ui.num(res.optDouble("value")) + (res.isNull("change_pct") ? "" : "  (" + (res.optDouble("change_pct") >= 0 ? "+" : "") + Ui.fa(String.valueOf(res.optDouble("change_pct"))) + "٪)"), res.isNull("change_pct") || res.optDouble("change_pct") >= 0 ? Ui.GREEN : Ui.RED));
                m.addView(Ui.kv(c, "اثر بر سود (تعدیل‌شده با روند فروشگاه)", Ui.money(res.optDouble("adjusted_gain")), res.optDouble("adjusted_gain") >= 0 ? Ui.GREEN : Ui.RED)); if (!res.isNull("projected_month")) m.addView(Ui.kv(c, "برآورد ماهانه", Ui.money(res.optDouble("projected_month")), 0)); if (!res.optBoolean("enough_data")) m.addView(Ui.muted(c, "برای سنجش دقیق حداقل یک روز فروش لازم است")); card.addView(m); }
            JSONArray acts = x.optJSONArray("actions");
            if ("NEW".equals(st) || "SNOOZED".equals(st)) { LinearLayout ar = Ui.col(c); ar.setPadding(0, Ui.dp(8), 0, 0);
                if (acts != null && acts.length() > 0) { StringBuilder sb = new StringBuilder(); for (int i = 0; i < acts.length(); i++) sb.append(i > 0 ? " · " : "").append(acts.optJSONObject(i).optString("label")); ar.addView(Ui.muted(c, "اقدام‌ها: " + sb)); }
                LinearLayout r = Ui.row(c); android.widget.Button ok = Ui.primary(c, "اجرا و سنجش اثر", () -> Ui.confirm(c, "این پیشنهاد اجرا شود؟ اقدام‌های آن هم‌اکنون انجام و اثرش از امروز اندازه‌گیری می‌شود.", () -> post("/insights/" + x.optLong("id") + "/accept", new JSONObject(), rr -> { JSONObject o = (JSONObject) rr; JSONArray ex = o.optJSONArray("executed"); StringBuilder sb = new StringBuilder(); for (int i = 0; ex != null && i < ex.length(); i++) { JSONObject e = ex.optJSONObject(i); sb.append(e.optBoolean("ok") ? "✓ " : "✗ ").append(e.optString("type")).append("\n"); } Sfx.play("ok"); Ui.done(Ui.ctx, "اجرا شد", sb.toString().trim(), null); load(); }))); ok.setLayoutParams(Ui.weight(1)); r.addView(ok);
                r.addView(Ui.small(c, "جزئیات", () -> card.performLongClick()));
                r.addView(Ui.small(c, "بعداً", () -> post("/insights/" + x.optLong("id") + "/snooze", j("days", "7"), rr -> load()))); r.addView(Ui.small(c, "رد", () -> post("/insights/" + x.optLong("id") + "/dismiss", new JSONObject(), rr -> load()))); ar.addView(r); card.addView(ar); }
            else if ("ACCEPTED".equals(st)) { card.addView(Ui.small(c, "سنجش دوباره", () -> post("/insights/" + x.optLong("id") + "/measure", new JSONObject(), rr -> load()))); }
            card.setOnLongClickListener(v -> { get("/insights/" + x.optLong("id") + "?narrate=1", rr -> { JSONObject o = (JSONObject) rr; LinearLayout l = Ui.col(c); TextView tv = Ui.body(c, o.optString("narrative").isEmpty() ? o.optString("body") : o.optString("narrative")); tv.setLineSpacing(0, 1.35f); l.addView(tv); if (o.optJSONObject("prediction") != null && o.optJSONObject("prediction").optDouble("gain_month") > 0) l.addView(predictBlock(c, o.optJSONObject("prediction"))); l.addView(Ui.muted(c, "شواهد: " + o.optJSONObject("evidence"))); Ui.sheet(c, x.optString("title"), l); }); return true; });
            return card;
        }
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
        void restore(java.util.function.Supplier<java.io.InputStream> src) { Ui.toast("در حال بازیابی…"); Api.bg(() -> { try (java.io.InputStream in = src.get()) { if (in == null) throw new Exception("فایل خوانده نشد"); org.json.JSONObject r = Local.restore(a, in); String msg = "windows".equals(r.optString("source")) ? "نسخهٔ ویندوز وارد شد: " + Ui.fa(String.valueOf(r.optInt("invoices"))) + " فاکتور، " + Ui.fa(String.valueOf(r.optInt("products"))) + " کالا، " + Ui.fa(String.valueOf(r.optInt("customers"))) + " مشتری." : "داده‌ها از فایل پشتیبان بارگذاری شدند."; Api.ui(() -> { Sfx.play("ok"); Screens.loadConfig(a); Ui.done(Ui.ctx, "بازیابی انجام شد", msg, () -> a.route("home")); }); } catch (Exception e) { Api.ui(() -> Ui.toast("بازیابی ناموفق: " + e.getMessage())); } }); }
    }
}
