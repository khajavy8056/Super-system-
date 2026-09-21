package ir.khajavy.supermarket;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * v3.5 — PRO pack of the on-phone Store-Intelligence engine (standalone mode).
 * 20 analyzers that need only the phone's local tables (invoices, items, customers, batches, products).
 * Same Draft contract as {@link Insights}; the PC engine carries the full 59 when the phone is connected.
 */
final class InsightsPro {
    private InsightsPro() {}

    static final String[][] LABELS = {
        {"CUST_FAVORITE", "کالای موردعلاقهٔ مشتری"}, {"CUST_ITEM_DUE", "چرخهٔ خرید کالا"}, {"TICKET_DROP", "کوچک‌شدن سبد"}, {"FREQ_DROP", "کاهش دفعات خرید"},
        {"NEW_CUST_2ND", "خرید دوم مشتری جدید"}, {"ANNIVERSARY", "سالگرد مشتری"}, {"BULK_BUYER", "خریدار عمده"}, {"THRESHOLD_UPSELL", "آستانهٔ سبد"},
        {"REORDER_POINT", "نقطهٔ سفارش"}, {"OVERSTOCK", "موجودی مازاد"}, {"TREND_UP", "روند صعودی"}, {"TREND_DOWN", "روند نزولی"}, {"EXPIRY_RISK_BUY", "پیش‌بینی انقضا"},
        {"PROFIT_PARETO", "قلب فروشگاه (۸۰/۲۰)"}, {"NEGATIVE_MARGIN", "فروش زیر قیمت"}, {"PRICE_ROUNDING", "گردکردن قیمت"},
        {"PEAK_HOURS", "ساعات اوج"}, {"SLOW_DAY", "روز کم‌فروش"}, {"UNREGISTERED_SALES", "فروش بی‌نام"}, {"HERO_PRODUCT", "کالای قلاب"}, {"SURPRISE", "امروز می‌دانستید؟"},
        {"AI_ADVISOR", "مشاور هوش مصنوعی"}};

    static final Object[][] ANALYZERS = {
        {"CUST_FAVORITE", (Insights.Analyzer) InsightsPro::custFavorite}, {"CUST_ITEM_DUE", (Insights.Analyzer) InsightsPro::custItemDue}, {"TICKET_DROP", (Insights.Analyzer) InsightsPro::ticketDrop},
        {"FREQ_DROP", (Insights.Analyzer) InsightsPro::freqDrop}, {"NEW_CUST_2ND", (Insights.Analyzer) InsightsPro::newCust2nd}, {"ANNIVERSARY", (Insights.Analyzer) InsightsPro::anniversary},
        {"BULK_BUYER", (Insights.Analyzer) InsightsPro::bulkBuyer}, {"THRESHOLD_UPSELL", (Insights.Analyzer) InsightsPro::thresholdUpsell},
        {"REORDER_POINT", (Insights.Analyzer) InsightsPro::reorderPoint}, {"OVERSTOCK", (Insights.Analyzer) InsightsPro::overstock}, {"TREND_UP", (Insights.Analyzer) f -> trend(f, true)},
        {"TREND_DOWN", (Insights.Analyzer) f -> trend(f, false)}, {"EXPIRY_RISK_BUY", (Insights.Analyzer) InsightsPro::expiryRiskBuy},
        {"PROFIT_PARETO", (Insights.Analyzer) InsightsPro::profitPareto}, {"NEGATIVE_MARGIN", (Insights.Analyzer) InsightsPro::negativeMargin}, {"PRICE_ROUNDING", (Insights.Analyzer) InsightsPro::priceRounding},
        {"PEAK_HOURS", (Insights.Analyzer) InsightsPro::peakHours}, {"SLOW_DAY", (Insights.Analyzer) InsightsPro::slowDay}, {"UNREGISTERED_SALES", (Insights.Analyzer) InsightsPro::unregistered},
        {"HERO_PRODUCT", (Insights.Analyzer) InsightsPro::heroProduct}, {"SURPRISE", (Insights.Analyzer) InsightsPro::surprise}};

    static final String[] WD = {"دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"};

    /* ------------------------------------------------------------ helpers */
    static String fa(double v) { return Ui.num(v); }
    static String money(double v) { return Ui.num(Math.round(v)) + " تومان"; }
    static String today() { return Jalali.todayIso().substring(0, 10); }
    static String day(JSONObject l) { String a = l.optString("at"); return a.length() >= 10 ? a.substring(0, 10) : a; }
    static double median(List<? extends Number> xs) { if (xs.isEmpty()) return 0; List<Double> s = new ArrayList<>(); for (Number n : xs) s.add(n.doubleValue()); Collections.sort(s); return s.get(s.size() / 2); }
    static double slope(double[] ys) { int n = ys.length; if (n < 3) return 0; double xm = (n - 1) / 2.0, ym = 0; for (double y : ys) ym += y; ym /= n; double den = 0, num = 0; for (int i = 0; i < n; i++) { den += (i - xm) * (i - xm); num += (i - xm) * (ys[i] - ym); } return ym > 0 ? (num / den) / ym : 0; }
    static int weekday(String iso) { long d = Insights.ms(iso + "T12:00:00") / 86400000L; return (int) (((d + 3) % 7 + 7) % 7); } // 1970-01-01 = Thursday(3)
    static String jdate(String iso) { try { int[] j = Jalali.toJalali(Integer.parseInt(iso.substring(0, 4)), Integer.parseInt(iso.substring(5, 7)), Integer.parseInt(iso.substring(8, 10))); return fa(j[2]) + " " + JM[j[1] - 1]; } catch (Exception e) { return iso; } }
    static final String[] JM = {"فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"};
    static int hour(String at) { try { return Integer.parseInt(at.substring(11, 13)); } catch (Exception e) { return 12; } }

    static Map<Long, JSONObject> customers() { Map<Long, JSONObject> m = new HashMap<>(); for (JSONObject c : Local.rows("SELECT id, name, last_name, phone FROM customers")) m.put(c.optLong("id"), c); return m; }
    static String cname(Map<Long, JSONObject> cs, long id) { JSONObject c = cs.get(id); return c == null ? ("#" + id) : (c.optString("name") + " " + c.optString("last_name")).trim(); }
    static String phone(Map<Long, JSONObject> cs, long id) { JSONObject c = cs.get(id); return c == null || c.isNull("phone") ? "" : c.optString("phone"); }
    static Map<Long, List<JSONObject>> byCust(Insights.Frame f) { Map<Long, List<JSONObject>> m = new HashMap<>(); for (JSONObject i : f.inv.values()) { long c = i.optLong("customer_id"); if (c > 0) m.computeIfAbsent(c, k -> new ArrayList<>()).add(i); } for (List<JSONObject> l : m.values()) l.sort((a, b) -> a.optString("at").compareTo(b.optString("at"))); return m; }
    static Map<Long, Double> stock() { Map<Long, Double> s = new HashMap<>(); for (JSONObject r : Local.rows("SELECT product_id, SUM(current_qty) AS q FROM batches WHERE status='ACTIVE' GROUP BY product_id")) s.put(r.optLong("product_id"), r.optDouble("q")); return s; }
    static Map<Long, Double> velocity28(Insights.Frame f) { Map<Long, Double> v = new HashMap<>(); String s28 = Insights.daysAgo(28); for (JSONObject l : f.lines) if (l.optString("at").compareTo(s28) >= 0) v.merge(l.optLong("product_id"), l.optDouble("qty") / 28, Double::sum); return v; }
    static double[] weekly(Insights.Frame f, long pid, int n) { double[] w = new double[n]; long now = Insights.ms(Db.now()); for (JSONObject l : f.lines) if (l.optLong("product_id") == pid) { int k = (int) ((now - Insights.ms(l.optString("at"))) / (7 * 86400000L)); if (k >= 0 && k < n) w[n - 1 - k] += l.optDouble("qty"); } return w; }
    static JSONObject crow(Map<Long, JSONObject> cs, long id, Object... kv) throws Exception { JSONObject o = Local.obj(kv); o.put("customer_id", id); o.put("name", cname(cs, id)); o.put("phone", phone(cs, id)); return o; }
    static JSONObject sms(long cid, String text) throws Exception { return Local.obj("customer_id", cid, "text", text); }
    static double profitRate(Insights.Frame f) { double s = 0, p = 0; for (JSONObject l : f.lines) { s += l.optDouble("subtotal"); p += f.profit(l); } return s > 0 ? p / s : 0.15; }

    /* ------------------------------------------------------------ customers */
    static List<Insights.Draft> custFavorite(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, JSONObject> cs = customers(); Map<Long, List<JSONObject>> bc = byCust(f); if (bc.size() < 10) return out;
        Map<Long, Double> store = new HashMap<>(); double tot = 0; Map<Long, Map<Long, Double>> mine = new HashMap<>(); Map<Long, Double> spent = new HashMap<>();
        for (JSONObject l : f.lines) { double s = l.optDouble("subtotal"); store.merge(l.optLong("product_id"), s, Double::sum); tot += s; long c = l.optLong("customer_id"); if (c > 0) { mine.computeIfAbsent(c, k -> new HashMap<>()).merge(l.optLong("product_id"), s, Double::sum); spent.merge(c, s, Double::sum); } }
        if (tot <= 0) return out; JSONArray rows = new JSONArray(); JSONArray texts = new JSONArray(); JSONArray cps = new JSONArray(); JSONArray ids = new JSONArray(); double sp = 0;
        List<Map.Entry<Long, Double>> order = new ArrayList<>(spent.entrySet()); order.sort((a, b) -> Double.compare(b.getValue(), a.getValue()));
        for (Map.Entry<Long, Double> e : order) { long c = e.getKey(); if (bc.getOrDefault(c, Collections.emptyList()).size() < 4) continue; long pid = -1; double best = 0; for (Map.Entry<Long, Double> m : mine.get(c).entrySet()) if (m.getValue() > best) { best = m.getValue(); pid = m.getKey(); }
            double my = best / e.getValue(), base = store.getOrDefault(pid, 0.0) / tot, lift = base > 0 ? my / base : 0; if (my < 0.15 || lift < 3) continue;
            rows.put(crow(cs, c, "product_id", pid, "product", f.name(pid), "share", Math.round(my * 100), "lift", Math.round(lift * 10) / 10.0, "spent", Math.round(e.getValue()))); ids.put(c); sp += e.getValue();
            if (!phone(cs, c).isEmpty()) { texts.put(sms(c, cname(cs, c) + " عزیز، «" + f.name(pid) + "» که همیشه می‌برید این هفته با هدیهٔ ویژه برای شماست. منتظرتان هستیم.")); cps.put(Local.obj("customer_id", c, "percent", 5, "days", 10)); }
            if (rows.length() >= 40) break; }
        if (rows.length() < 3) return out; JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("CUST_FAVORITE", "week:" + today().substring(0, 7), "چیزی که هر مشتری را جذب می‌کند: " + fa(rows.length()) + " مشتری با «کالای عشق»",
            "هر یک از این مشتریان یک کالا دارد که سهمش در سبد او " + fa(r0.optDouble("lift")) + "× بیشتر از میانگین فروشگاه است (مثلاً «" + r0.optString("name") + "» ← «" + r0.optString("product") + "»، " + fa(r0.optInt("share")) + "٪ خریدش). پیام شخصی دربارهٔ همان کالا — نه تخفیف عمومی — چیزی است که او را برمی‌گرداند.");
        d.prio = 3; d.gain = sp * (30.0 / 90) * 0.08; d.ev = Local.obj("rows", rows); d.act("personal_sms", "پیامک شخصی دربارهٔ کالای موردعلاقهٔ هر مشتری", "customers", texts).act("personal_coupons", "کوپن ۵٪ شخصی (۱۰ روز)", "customers", cps);
        d.metric = Local.obj("metric", "customer_sales", "customer_ids", ids, "window_days", 21); out.add(d); return out;
    }

    static List<Insights.Draft> custItemDue(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, JSONObject> cs = customers(); Map<String, TreeSet<String>> per = new HashMap<>();
        for (JSONObject l : f.lines) { long c = l.optLong("customer_id"); if (c > 0) per.computeIfAbsent(c + ":" + l.optLong("product_id"), k -> new TreeSet<>()).add(day(l)); }
        JSONArray rows = new JSONArray(); JSONArray texts = new JSONArray(); Set<Long> ids = new HashSet<>(); double gain = 0; String tod = today();
        for (Map.Entry<String, TreeSet<String>> e : per.entrySet()) { if (e.getValue().size() < 4) continue; List<String> ds = new ArrayList<>(e.getValue()); List<Integer> gaps = new ArrayList<>(); for (int i = 1; i < ds.size(); i++) { int g = (int) Math.round(Insights.daysBetween(ds.get(i - 1) + "T00:00:00", ds.get(i) + "T00:00:00")); if (g > 0) gaps.add(g); }
            if (gaps.size() < 3) continue; double med = median(gaps); List<Double> dev = new ArrayList<>(); for (int g : gaps) dev.add(Math.abs(g - med)); if (med < 3 || median(dev) > med * 0.4) continue;
            String due = Insights.plusDays(ds.get(ds.size() - 1) + "T00:00:00", med).substring(0, 10); int in = (int) Math.round(Insights.daysBetween(tod + "T00:00:00", due + "T00:00:00")); if (in < -1 || in > 3) continue;
            long c = Long.parseLong(e.getKey().split(":")[0]), pid = Long.parseLong(e.getKey().split(":")[1]); double m = f.margin(pid); gain += m * 2;
            rows.put(crow(cs, c, "product_id", pid, "product", f.name(pid), "cycle_days", (int) med, "buys", ds.size(), "due", due, "due_in", in, "margin", Math.round(m))); ids.add(c);
            if (!phone(cs, c).isEmpty()) texts.put(sms(c, cname(cs, c) + " عزیز، «" + f.name(pid) + "» شما احتمالاً رو به اتمام است؛ تازه‌اش رسیده و برایتان کنار گذاشته‌ایم."));
            if (rows.length() >= 40) break; }
        if (rows.length() < 2) return out; JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("CUST_ITEM_DUE", "day:" + tod, fa(rows.length()) + " کالای همیشگی مشتریان همین روزها تمام می‌شود",
            "چرخهٔ خرید هر مشتری برای هر کالا محاسبه شد؛ مثلاً «" + r0.optString("name") + "» هر " + fa(r0.optInt("cycle_days")) + " روز «" + r0.optString("product") + "» می‌برد و نوبت بعدی " + fa(Math.abs(r0.optInt("due_in"))) + " روز " + (r0.optInt("due_in") >= 0 ? "دیگر" : "پیش") + " است. پیام «کالای شما دارد تمام می‌شود» دقیقاً همان لحظه‌ای می‌رسد که به فکرش می‌افتد.");
        d.prio = 2; d.gain = gain; d.ev = Local.obj("rows", rows); d.act("personal_sms", "پیامک «کالای همیشگی‌تان رو به اتمام است»", "customers", texts); d.metric = Local.obj("metric", "customer_sales", "customer_ids", new JSONArray(ids), "window_days", 14); out.add(d); return out;
    }

    static List<Insights.Draft> ticketDrop(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, JSONObject> cs = customers(); String cut = Insights.daysAgo(28); JSONArray rows = new JSONArray(); JSONArray texts = new JSONArray(); JSONArray cps = new JSONArray(); JSONArray ids = new JSONArray(); double loss = 0;
        List<Object[]> cand = new ArrayList<>();
        for (Map.Entry<Long, List<JSONObject>> e : byCust(f).entrySet()) { double so = 0, sn = 0; int no = 0, nn = 0; for (JSONObject i : e.getValue()) { if (i.optString("at").compareTo(cut) < 0) { so += i.optDouble("total"); no++; } else { sn += i.optDouble("total"); nn++; } }
            if (no < 5 || nn < 2) continue; double ao = so / no, an = sn / nn; if (ao > 0 && an < ao * 0.7) cand.add(new Object[]{e.getKey(), ao, an, nn, (ao - an) * nn * (30.0 / 28)}); }
        cand.sort((a, b) -> Double.compare((double) b[4], (double) a[4]));
        for (Object[] c : cand) { long id = (long) c[0]; if (rows.length() >= 30) break; rows.put(crow(cs, id, "avg_before", Math.round((double) c[1]), "avg_now", Math.round((double) c[2]), "drop_pct", Math.round((1 - (double) c[2] / (double) c[1]) * 100), "visits_now", c[3], "monthly_loss", Math.round((double) c[4]))); ids.put(id); loss += (double) c[4];
            if (!phone(cs, id).isEmpty()) { texts.put(sms(id, cname(cs, id) + " عزیز، نظرتان برای ما مهم است؛ اگر چیزی کم داریم یا قیمتی مناسب نبود همین‌جا پاسخ دهید. این هفته ۵٪ تخفیف شخصی دارید.")); cps.put(Local.obj("customer_id", id, "percent", 5, "days", 7)); } }
        if (rows.length() < 3) return out;
        Insights.Draft d = new Insights.Draft("TICKET_DROP", "week:" + today().substring(0, 7), "سبد " + fa(rows.length()) + " مشتری ثابت کوچک شده — بخشی از خریدشان جای دیگر می‌رود",
            "این مشتریان هنوز می‌آیند اما میانگین فاکتورشان " + fa(rows.optJSONObject(0).optInt("drop_pct")) + "٪ (و بیشتر) افت کرده؛ نشانهٔ کلاسیک «تقسیم سبد» با رقیب، قبل از ریزش کامل. فروش ماهانهٔ ازدست‌رفته: " + money(loss) + ". یک پیام نظرخواهی + کوپن کوچک معمولاً دلیل را رو می‌کند.");
        d.prio = 2; d.gain = loss * 0.3; d.ev = Local.obj("rows", rows, "monthly_loss", Math.round(loss)); d.act("personal_sms", "پیامک نظرخواهی + ۵٪ تخفیف", "customers", texts).act("personal_coupons", "کوپن ۵٪ شخصی (۷ روز)", "customers", cps); d.metric = Local.obj("metric", "customer_sales", "customer_ids", ids, "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> freqDrop(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, JSONObject> cs = customers(); JSONArray rows = new JSONArray(); JSONArray texts = new JSONArray(); JSONArray cps = new JSONArray(); JSONArray ids = new JSONArray(); double risk = 0; String tod = today(); List<Object[]> cand = new ArrayList<>();
        for (Map.Entry<Long, List<JSONObject>> e : byCust(f).entrySet()) { TreeSet<String> ds = new TreeSet<>(); double spent = 0; for (JSONObject i : e.getValue()) { ds.add(day(i)); spent += i.optDouble("total"); } List<String> dl = new ArrayList<>(ds); List<Integer> gaps = new ArrayList<>(); for (int i = 1; i < dl.size(); i++) gaps.add((int) Math.round(Insights.daysBetween(dl.get(i - 1) + "T00:00:00", dl.get(i) + "T00:00:00")));
            if (gaps.size() < 6) continue; double base = median(gaps.subList(0, gaps.size() - 3)), recent = (gaps.get(gaps.size() - 1) + gaps.get(gaps.size() - 2) + gaps.get(gaps.size() - 3)) / 3.0; double silent = Insights.daysBetween(dl.get(dl.size() - 1) + "T00:00:00", tod + "T00:00:00");
            if (base >= 1 && recent >= base * 1.8 && silent <= base * 2.5) cand.add(new Object[]{e.getKey(), base, recent, silent, spent * (30.0 / 90)}); }
        cand.sort((a, b) -> Double.compare((double) b[4], (double) a[4]));
        for (Object[] c : cand) { long id = (long) c[0]; if (rows.length() >= 30) break; rows.put(crow(cs, id, "gap_before", (int) (double) c[1], "gap_now", Math.round((double) c[2] * 10) / 10.0, "silent_days", (int) (double) c[3], "monthly_sales", Math.round((double) c[4]))); ids.put(id); risk += (double) c[4];
            if (!phone(cs, id).isEmpty()) { texts.put(sms(id, cname(cs, id) + " عزیز، مدتی است کمتر می‌بینیمتان؛ کالاهای تازه رسیده و این هفته ۱۰٪ تخفیف شخصی دارید.")); cps.put(Local.obj("customer_id", id, "percent", 10, "days", 7)); } }
        if (rows.length() < 3) return out; JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("FREQ_DROP", "week:" + tod.substring(0, 7), fa(rows.length()) + " مشتری دارند کم‌کم فاصله می‌گیرند (قبل از ریزش)",
            "فاصلهٔ خریدهای اخیر این مشتریان تقریباً دو برابر روال خودشان شده (مثلاً «" + r0.optString("name") + "»: هر " + fa(r0.optInt("gap_before")) + " روز → هر " + fa(r0.optDouble("gap_now")) + " روز). در این مرحله برگرداندنشان بسیار ارزان‌تر از بعد از قطع کامل است. فروش ماهانهٔ در خطر: " + money(risk) + ".");
        d.prio = 3; d.gain = risk * 0.15; d.ev = Local.obj("rows", rows); d.act("personal_sms", "پیامک «دلتنگ شدیم» + ۱۰٪", "customers", texts).act("personal_coupons", "کوپن ۱۰٪ شخصی (۷ روز)", "customers", cps); d.metric = Local.obj("metric", "customer_sales", "customer_ids", ids, "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> newCust2nd(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, JSONObject> cs = customers(); JSONArray rows = new JSONArray(); JSONArray cps = new JSONArray(); JSONArray ids = new JSONArray(); double sum = 0; String now = Db.now();
        for (JSONObject r : Local.rows("SELECT customer_id, MIN(at) AS first, COUNT(*) AS n, MAX(total) AS t FROM invoices WHERE status<>'VOID' AND customer_id>0 GROUP BY customer_id HAVING n=1")) { double age = Insights.daysBetween(r.optString("first"), now); long c = r.optLong("customer_id"); if (age < 5 || age > 30 || phone(cs, c).isEmpty()) continue;
            rows.put(crow(cs, c, "first_visit", r.optString("first").substring(0, 10), "days_ago", (int) age, "ticket", Math.round(r.optDouble("t")))); ids.put(c); sum += r.optDouble("t");
            cps.put(Local.obj("customer_id", c, "percent", 10, "days", 7, "text", cname(cs, c) + " عزیز، از اولین خریدتان سپاسگزاریم! برای دومین خرید ۱۰٪ تخفیف با کد {code} تا ۷ روز آینده مهمان ما باشید.")); if (rows.length() >= 40) break; }
        if (rows.length() < 3) return out; double avg = sum / rows.length();
        Insights.Draft d = new Insights.Draft("NEW_CUST_2ND", "week:" + today().substring(0, 7), fa(rows.length()) + " مشتری جدید فقط یک بار آمده‌اند — خرید دوم را بسازید",
            "مشتری‌ای که بار دوم برگردد، با احتمال چند برابر مشتری ثابت می‌شود. این " + fa(rows.length()) + " نفر در ۳۰ روز اخیر اولین خریدشان را کرده‌اند (میانگین فاکتور " + money(avg) + ") و هنوز برنگشته‌اند؛ همه شماره داده‌اند.");
        d.prio = 2; d.gain = avg * rows.length() * 0.06; d.ev = Local.obj("rows", rows); d.act("personal_coupons", "کوپن خوش‌آمد ۱۰٪ (۷ روز) + پیامک", "customers", cps); d.metric = Local.obj("metric", "customer_sales", "customer_ids", ids, "window_days", 14); out.add(d); return out;
    }

    static List<Insights.Draft> anniversary(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, JSONObject> cs = customers(); JSONArray rows = new JSONArray(); JSONArray texts = new JSONArray(); JSONArray ids = new JSONArray(); String tod = today(); int y = Integer.parseInt(tod.substring(0, 4));
        for (JSONObject r : Local.rows("SELECT customer_id, MIN(at) AS first, COUNT(*) AS n FROM invoices WHERE status<>'VOID' AND customer_id>0 GROUP BY customer_id HAVING n>=3")) { String first = r.optString("first"); int fy = Integer.parseInt(first.substring(0, 4)); int yrs = y - fy; if (yrs < 1) continue; long c = r.optLong("customer_id"); if (phone(cs, c).isEmpty()) continue;
            String ann = y + first.substring(4, 10); double in = Insights.daysBetween(tod + "T00:00:00", ann + "T00:00:00"); if (in < 0 || in > 6) continue;
            rows.put(crow(cs, c, "years", yrs, "date", ann, "in_days", (int) in)); ids.put(c); texts.put(sms(c, cname(cs, c) + " عزیز، " + fa(yrs) + " سال از اولین خریدتان از ما می‌گذرد. سپاس که هستید؛ این هفته یک هدیهٔ کوچک پای صندوق منتظرتان است.")); }
        if (rows.length() < 2) return out; JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("ANNIVERSARY", "week:" + tod.substring(0, 7), "سالگرد اولین خرید " + fa(rows.length()) + " مشتری در این هفته است",
            "کاری که هیچ رقیبی نمی‌کند: «" + r0.optString("name") + "» " + fa(r0.optInt("years")) + " سال پیش در همین هفته اولین بار از شما خرید کرد. یک پیام تشکر و یک هدیهٔ کوچک، وفاداری می‌سازد و هزینه‌اش تقریباً صفر است.");
        d.prio = 4; d.gain = rows.length() * 40000; d.ev = Local.obj("rows", rows); d.act("personal_sms", "پیامک تبریک سالگرد + هدیهٔ کوچک", "customers", texts); d.metric = Local.obj("metric", "customer_sales", "customer_ids", ids, "window_days", 21); out.add(d); return out;
    }

    static List<Insights.Draft> bulkBuyer(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, JSONObject> cs = customers(); Map<Long, List<Double>> typ = new HashMap<>(); for (JSONObject l : f.lines) typ.computeIfAbsent(l.optLong("product_id"), k -> new ArrayList<>()).add(l.optDouble("qty"));
        Map<Long, Double> med = new HashMap<>(); for (Map.Entry<Long, List<Double>> e : typ.entrySet()) if (e.getValue().size() >= 10) med.put(e.getKey(), median(e.getValue()));
        Map<String, List<Double>> hits = new HashMap<>(); for (JSONObject l : f.lines) { Double m = med.get(l.optLong("product_id")); long c = l.optLong("customer_id"); if (c > 0 && m != null && l.optDouble("qty") >= Math.max(6, m * 5)) hits.computeIfAbsent(c + ":" + l.optLong("product_id"), k -> new ArrayList<>()).add(l.optDouble("qty")); }
        JSONArray rows = new JSONArray(); JSONArray texts = new JSONArray(); Set<Long> ids = new HashSet<>(); double gain = 0;
        for (Map.Entry<String, List<Double>> e : hits.entrySet()) { if (e.getValue().size() < 3 || rows.length() >= 25) continue; long c = Long.parseLong(e.getKey().split(":")[0]), pid = Long.parseLong(e.getKey().split(":")[1]); double avg = 0; for (double q : e.getValue()) avg += q; avg /= e.getValue().size(); double m = f.margin(pid); gain += avg * m * e.getValue().size() * (30.0 / 90) * 0.3;
            rows.put(crow(cs, c, "product_id", pid, "product", f.name(pid), "times", e.getValue().size(), "avg_qty", Math.round(avg * 10) / 10.0, "typical_qty", med.get(pid))); ids.add(c); if (!phone(cs, c).isEmpty()) texts.put(sms(c, cname(cs, c) + " عزیز، برای خرید عمدهٔ «" + f.name(pid) + "» قیمت ویژه برایتان در نظر گرفته‌ایم؛ قبل از خرید بعدی به ما خبر دهید تا آماده باشد.")); }
        if (rows.length() < 2) return out; JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("BULK_BUYER", "month:" + today().substring(0, 7), fa(rows.length()) + " خریدار عمده در میان مشتریان شما پنهان است",
            "«" + r0.optString("name") + "» " + fa(r0.optInt("times")) + " بار «" + r0.optString("product") + "» را به‌طور میانگین " + fa(r0.optDouble("avg_qty")) + " عدد برده (معمول: " + fa(r0.optDouble("typical_qty")) + "). این‌ها احتمالاً مغازه‌دار یا خانوادهٔ پرجمعیت‌اند؛ یک قرار «قیمت عمده + رزرو» آن‌ها را از بنکدار جدا می‌کند.");
        d.prio = 3; d.gain = gain; d.ev = Local.obj("rows", rows); d.act("personal_sms", "پیشنهاد قیمت عمده + رزرو کالا", "customers", texts); d.metric = Local.obj("metric", "customer_sales", "customer_ids", new JSONArray(ids), "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> thresholdUpsell(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); List<Double> totals = new ArrayList<>(); for (JSONObject i : f.inv.values()) if (i.optDouble("total") > 0) totals.add(i.optDouble("total")); if (totals.size() < 80) return out;
        double med = median(totals); double step = med < 300000 ? 50000 : med < 1000000 ? 100000 : 500000; double thr = Math.ceil(med / step) * step; int near = 0; double gap = 0; for (double t : totals) if (t >= thr * 0.8 && t < thr) { near++; gap += thr - t; }
        double share = (double) near / totals.size(); if (share < 0.15) return out;
        Insights.Draft d = new Insights.Draft("THRESHOLD_UPSELL", "thr:" + (long) thr, fa(Math.round(share * 100)) + "٪ فاکتورها کمی زیر " + money(thr) + " می‌مانند",
            "میانهٔ فاکتور " + money(med) + " است و " + fa(near) + " فاکتور بین ۸۰٪ تا ۱۰۰٪ آستانهٔ " + money(thr) + " بسته شده‌اند. یک پیشنهاد سادهٔ «خرید بالای " + money(thr) + " = ۳٪ تخفیف» معمولاً یک‌سوم این فاکتورها را از خط رد می‌کند؛ جمع فاصله تا آستانه " + money(gap) + " است.");
        d.prio = 3; d.gain = gap * profitRate(f) * 0.35 * (30.0 / 90); d.ev = Local.obj("threshold", (long) thr, "median_ticket", Math.round(med), "near_count", near, "invoices", totals.size(), "gap_sum", Math.round(gap));
        d.act("threshold_campaign", "کمپین «بالای " + money(thr) + " = ۳٪ تخفیف» (۳۰ روز)", "percent", 3, "min_purchase", (long) thr, "days", 30); d.metric = Local.obj("metric", "avg_basket_size", "window_days", 28); out.add(d); return out;
    }

    /* ------------------------------------------------------------ stock */
    static List<Insights.Draft> reorderPoint(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, Double> v28 = velocity28(f); List<Object[]> cand = new ArrayList<>();
        for (Map.Entry<Long, Double> e : v28.entrySet()) { long pid = e.getKey(); double v = e.getValue(); JSONObject p = f.prod.get(pid); if (p == null || v * 28 < 8) continue; int opt = (int) Math.ceil(v * 5), cur = (int) p.optDouble("min_stock_alert"); if (cur == 0 || cur < opt * 0.5 || cur > opt * 3) cand.add(new Object[]{pid, v, cur, opt, f.margin(pid)}); }
        if (cand.size() < 3) return out; cand.sort((a, b) -> Double.compare((double) b[1] * (double) b[4], (double) a[1] * (double) a[4])); JSONArray rows = new JSONArray(); JSONArray items = new JSONArray(); int ups = 0; double gain = 0;
        for (Object[] c : cand) { if (rows.length() >= 40) break; boolean up = (int) c[2] < (int) c[3]; if (up) { ups++; gain += (double) c[1] * (double) c[4] * 3; } rows.put(Local.obj("product_id", c[0], "name", f.name((long) c[0]), "velocity_per_day", Math.round((double) c[1] * 100) / 100.0, "current_min", c[2], "suggested_min", c[3], "direction", up ? "up" : "down")); items.put(Local.obj("product_id", c[0], "min_stock", c[3])); }
        JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("REORDER_POINT", "month:" + today().substring(0, 7), "نقطهٔ سفارش " + fa(rows.length()) + " کالا با سرعت فروش واقعی‌شان نمی‌خواند",
            "حداقل موجودی باید ≈ ۵ روز فروش باشد (۳ روز تا رسیدن جنس + ۲ روز ایمنی). " + fa(ups) + " کالا هشدارشان خیلی دیر می‌آید و " + fa(rows.length() - ups) + " کالا سرمایه را بی‌دلیل قفل کرده‌اند. مثلاً «" + r0.optString("name") + "» روزی " + fa(r0.optDouble("velocity_per_day")) + " عدد می‌فروشد؛ حداقل فعلی " + fa(r0.optInt("current_min")) + " ← پیشنهادی " + fa(r0.optInt("suggested_min")) + ".");
        d.prio = 2; d.gain = gain; d.ev = Local.obj("rows", rows); d.act("set_min_stock_bulk", "به‌روزرسانی هوشمند حداقل موجودی همهٔ این کالاها", "items", items); d.metric = Local.obj("metric", "availability", "product_id", r0.optLong("product_id"), "window_days", 28, "margin_per_day", Math.round(r0.optDouble("velocity_per_day") * (double) cand.get(0)[4])); out.add(d); return out;
    }

    static List<Insights.Draft> overstock(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, Double> v28 = velocity28(f); JSONArray rows = new JSONArray(); double excess = 0; List<Object[]> cand = new ArrayList<>();
        for (JSONObject r : Local.rows("SELECT product_id, SUM(current_qty) AS q, SUM(current_qty*buy_price) AS cap FROM batches WHERE status='ACTIVE' GROUP BY product_id")) { double v = v28.getOrDefault(r.optLong("product_id"), 0.0); if (v <= 0) continue; double cover = r.optDouble("q") / v, cap = r.optDouble("cap"); if (cover > 90 && cap > 300000) cand.add(new Object[]{r.optLong("product_id"), r.optDouble("q"), v, cover, cap, cap * (1 - 45 / cover)}); }
        if (cand.isEmpty()) return out; cand.sort((a, b) -> Double.compare((double) b[5], (double) a[5]));
        for (Object[] c : cand) { if (rows.length() >= 30) break; rows.put(Local.obj("product_id", c[0], "name", f.name((long) c[0]), "stock", c[1], "velocity_per_day", Math.round((double) c[2] * 100) / 100.0, "days_cover", Math.round((double) c[3]), "capital", Math.round((double) c[4]), "excess_capital", Math.round((double) c[5]))); excess += (double) c[5]; }
        JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("OVERSTOCK", "month:" + today().substring(0, 7), money(excess) + " سرمایهٔ اضافی در " + fa(rows.length()) + " کالای پرموجودی",
            "این کالاها می‌فروشند، اما موجودی‌شان بیش از ۹۰ روز فروش است (مثلاً «" + r0.optString("name") + "»: " + fa(r0.optLong("days_cover")) + " روز). نیازی به حراج نیست؛ فقط سفارش بعدی را نگیرید. با پوشش ۴۵ روزه، " + money(excess) + " نقد آزاد می‌شود.");
        d.prio = 3; d.gain = excess * 0.03; d.ev = Local.obj("rows", rows, "excess_capital", Math.round(excess)); d.act("note", "ثبت در فهرست «سفارش نگیر» برای خرید بعدی"); d.metric = Local.obj("metric", "product_profit", "product_id", r0.optLong("product_id"), "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> trend(Insights.Frame f, boolean up) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, Double> v28 = velocity28(f), st = stock(); List<Object[]> cand = new ArrayList<>();
        for (long pid : v28.keySet()) { double[] w = weekly(f, pid, 6); double sum = 0; for (double x : w) sum += x; if (sum < 12) continue; double s = slope(w); if ((up && s >= 0.12) || (!up && s <= -0.12)) cand.add(new Object[]{pid, w, s, f.margin(pid), sum}); }
        if (cand.size() < 2) return out; cand.sort((a, b) -> Double.compare(Math.abs((double) b[2]) * (double) b[3] * (double) b[4], Math.abs((double) a[2]) * (double) a[3] * (double) a[4]));
        JSONArray rows = new JSONArray(); JSONArray prods = new JSONArray(); double gain = 0; int flag = 0;
        for (Object[] c : cand) { if (rows.length() >= 20) break; long pid = (long) c[0]; double[] w = (double[]) c[1]; double s = (double) c[2], next = Math.max(0, w[5] * (1 + s)), stock = st.getOrDefault(pid, 0.0); JSONArray wk = new JSONArray(); for (double x : w) wk.put(Math.round(x * 10) / 10.0);
            boolean mark = up ? stock < next * 1.5 : stock > Math.max(1, next) * 6; if (mark) { flag++; prods.put(pid); if (up) gain += next * (double) c[3] * 2; else gain += stock * (double) c[3] * 0.2; }
            rows.put(Local.obj("product_id", pid, "name", f.name(pid), "weekly", wk, "trend_pct_per_week", Math.round(s * 100), "stock", stock, "next_week", Math.round(next * 10) / 10.0, "margin", Math.round((double) c[3]))); }
        JSONObject r0 = rows.optJSONObject(0); StringBuilder wl = new StringBuilder(); JSONArray wk = r0.optJSONArray("weekly"); for (int i = 0; i < wk.length(); i++) wl.append(i > 0 ? "، " : "").append(fa(wk.optDouble(i)));
        Insights.Draft d = up ? new Insights.Draft("TREND_UP", "week:" + today().substring(0, 7), fa(rows.length()) + " کالا در حال اوج‌گرفتن‌اند — " + fa(flag) + " تا موجودی کافی ندارند",
                "فروش هفتگی «" + r0.optString("name") + "» شش هفته است هر هفته ≈" + fa(r0.optInt("trend_pct_per_week")) + "٪ رشد می‌کند (" + wl + "). پیش‌بینی هفتهٔ بعد: " + fa(r0.optDouble("next_week")) + " عدد؛ موجودی " + fa(r0.optDouble("stock")) + ". سفارش را بر اساس روند بگیرید، نه میانگین.")
            : new Insights.Draft("TREND_DOWN", "week:" + today().substring(0, 7), fa(rows.length()) + " کالا دارند افت می‌کنند — سفارش بعدی را کوچک کنید",
                "فروش «" + r0.optString("name") + "» هر هفته ≈" + fa(Math.abs(r0.optInt("trend_pct_per_week"))) + "٪ کم می‌شود (" + wl + "). " + fa(flag) + " کالا با این روند بیش از ۶ هفته موجودی دارند. قبل از راکدشدن، سفارش را نصف کنید یا با کالای پرفروش باندل کنید.");
        d.prio = up && flag > 0 ? 2 : 3; d.gain = gain; d.ev = Local.obj("rows", rows); if (up) d.act("reorder_note", "سفارش کالاهای رو به رشد", "products", prods.length() > 0 ? prods : new JSONArray().put(r0.optLong("product_id"))); else d.act("note", "یادداشت «سفارش نصف» برای خرید بعدی");
        d.metric = Local.obj("metric", up ? "product_units" : "product_profit", "product_id", r0.optLong("product_id"), "window_days", up ? 14 : 28); out.add(d); return out;
    }

    static List<Insights.Draft> expiryRiskBuy(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, Double> v28 = velocity28(f); String tod = today(); List<Object[]> cand = new ArrayList<>();
        for (JSONObject b : Local.rows("SELECT id, product_id, current_qty, buy_price, expiry_date FROM batches WHERE status='ACTIVE' AND current_qty>0 AND expiry_date IS NOT NULL AND expiry_date<>''")) { double left = Insights.daysBetween(tod + "T00:00:00", b.optString("expiry_date").substring(0, 10) + "T00:00:00"); if (left <= 14 || left > 120) continue; double v = v28.getOrDefault(b.optLong("product_id"), 0.0), qty = b.optDouble("current_qty"), sell = v * left; if (v <= 0 || qty > sell * 1.3) { double waste = Math.max(0, qty - sell), loss = waste * b.optDouble("buy_price"); if (loss > 50000) cand.add(new Object[]{b, left, v, sell, waste, loss}); } }
        if (cand.isEmpty()) return out; cand.sort((a, b) -> Double.compare((double) b[5], (double) a[5])); JSONArray rows = new JSONArray(); double loss = 0;
        for (Object[] c : cand) { if (rows.length() >= 25) break; JSONObject b = (JSONObject) c[0]; rows.put(Local.obj("batch_id", b.optLong("id"), "product_id", b.optLong("product_id"), "name", f.name(b.optLong("product_id")), "qty", b.optDouble("current_qty"), "days_left", (int) (double) c[1], "velocity_per_day", Math.round((double) c[2] * 100) / 100.0, "will_sell", Math.round((double) c[3]), "will_expire", Math.round((double) c[4]), "loss", Math.round((double) c[5]))); loss += (double) c[5]; }
        JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("EXPIRY_RISK_BUY", "week:" + tod.substring(0, 7), money(loss) + " کالا با این سرعت فروش قبل از فروش منقضی می‌شود",
            "«" + r0.optString("name") + "»: " + fa(r0.optDouble("qty")) + " عدد، " + fa(r0.optInt("days_left")) + " روز تا انقضا، روزی " + fa(r0.optDouble("velocity_per_day")) + " عدد فروش → فقط " + fa(r0.optLong("will_sell")) + " عدد می‌فروشد و " + fa(r0.optLong("will_expire")) + " عدد دور می‌رود. هنوز زود است و می‌شود با تخفیف ملایم یا برگرداندن به تأمین‌کننده جلویش را گرفت.");
        d.prio = 2; d.gain = loss * 0.5; d.ev = Local.obj("rows", rows, "loss", Math.round(loss)); JSONArray ladder = new JSONArray().put(Local.obj("from_day", 0, "percent", 10)).put(Local.obj("from_day", 14, "percent", 20));
        d.act("markdown_ladder", "تخفیف ملایم ۱۰٪ اکنون، ۲۰٪ در دو هفته", "batch_id", r0.optLong("batch_id"), "ladder", ladder).act("note", "یادداشت «برگشت به تأمین‌کننده» برای انباردار"); d.metric = Local.obj("metric", "product_units", "product_id", r0.optLong("product_id"), "window_days", 21); out.add(d); return out;
    }

    /* ------------------------------------------------------------ pricing */
    static List<Insights.Draft> profitPareto(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, Double> pr = new HashMap<>(); for (JSONObject l : f.lines) pr.merge(l.optLong("product_id"), f.profit(l), Double::sum); if (pr.size() < 30) return out;
        double tot = 0; for (double v : pr.values()) if (v > 0) tot += v; if (tot <= 0) return out; List<Map.Entry<Long, Double>> order = new ArrayList<>(pr.entrySet()); order.sort((a, b) -> Double.compare(b.getValue(), a.getValue()));
        Map<Long, Double> v28 = velocity28(f), st = stock(); double acc = 0; List<Long> core = new ArrayList<>(); for (Map.Entry<Long, Double> e : order) { if (e.getValue() <= 0 || acc >= tot * 0.8) break; acc += e.getValue(); core.add(e.getKey()); }
        if ((double) core.size() / pr.size() > 0.5) return out; JSONArray rows = new JSONArray(); JSONArray items = new JSONArray(); int weak = 0; double wgain = 0;
        for (long pid : core) { double cover = st.getOrDefault(pid, 0.0) / Math.max(1e-9, v28.getOrDefault(pid, 0.0)); if (cover < 5) { weak++; wgain += pr.get(pid); } if (rows.length() < 40) rows.put(Local.obj("product_id", pid, "name", f.name(pid), "profit", Math.round(pr.get(pid)), "share_pct", Math.round(pr.get(pid) / tot * 1000) / 10.0, "stock", st.getOrDefault(pid, 0.0), "days_cover", Math.round(Math.min(999, cover) * 10) / 10.0)); if (v28.getOrDefault(pid, 0.0) > 0) items.put(Local.obj("product_id", pid, "min_stock", Math.max(1, (int) Math.ceil(v28.get(pid) * 7)))); }
        JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("PROFIT_PARETO", "month:" + today().substring(0, 7), fa(core.size()) + " کالا (" + fa(Math.round(100.0 * core.size() / pr.size())) + "٪ اقلام) ۸۰٪ سود شما را می‌سازند — " + fa(weak) + " تا کم‌موجودی‌اند",
            "این فهرست «قلب فروشگاه» است: «" + r0.optString("name") + "» به‌تنهایی " + fa(r0.optDouble("share_pct")) + "٪ سود دوره را آورده. برای این‌ها قاعده فرق می‌کند: هرگز خالی نمانند (حداقل ۷ روز پوشش)، همیشه در دید باشند و قیمتشان هر هفته بازبینی شود.");
        d.prio = weak > 0 ? 2 : 3; d.gain = wgain * (30.0 / 90) * 0.1; d.ev = Local.obj("rows", rows, "core_count", core.size(), "all_products_sold", pr.size()); d.act("set_min_stock_bulk", "حداقل موجودی ۷ روزه برای کالاهای قلب فروشگاه", "items", items); d.metric = Local.obj("metric", "avg_basket_size", "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> negativeMargin(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, Double> loss = new HashMap<>(); Map<Long, Integer> n = new HashMap<>(); for (JSONObject l : f.lines) { double p = f.profit(l); if (p < 0 && l.optDouble("qty") > 0) { loss.merge(l.optLong("product_id"), -p, Double::sum); n.merge(l.optLong("product_id"), 1, Integer::sum); } }
        List<Map.Entry<Long, Double>> cand = new ArrayList<>(); for (Map.Entry<Long, Double> e : loss.entrySet()) if (n.get(e.getKey()) >= 3 && e.getValue() > 30000) cand.add(e); if (cand.isEmpty()) return out; cand.sort((a, b) -> Double.compare(b.getValue(), a.getValue()));
        JSONArray rows = new JSONArray(); double tot = 0; for (Map.Entry<Long, Double> e : cand) { if (rows.length() >= 25) break; rows.put(Local.obj("product_id", e.getKey(), "name", f.name(e.getKey()), "lines", n.get(e.getKey()), "loss", Math.round(e.getValue()))); tot += e.getValue(); } tot *= 30.0 / 90; JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("NEGATIVE_MARGIN", "month:" + today().substring(0, 7), fa(rows.length()) + " کالا عملاً زیر قیمت خرید فروخته شده‌اند — " + money(tot) + " زیان ماهانه",
            "بعد از احتساب تخفیف‌های پای صندوق، «" + r0.optString("name") + "» در " + fa(r0.optInt("lines")) + " فاکتور با زیان فروخته شده (" + money(r0.optLong("loss")) + "). یا قیمت خرید جدید ثبت نشده، یا قیمت فروش قدیمی است، یا تخفیف دستی زیاد است.");
        d.prio = 1; d.gain = tot * 0.8; d.ev = Local.obj("rows", rows, "monthly_loss", Math.round(tot)); JSONObject b = Local.one("SELECT id, buy_price FROM batches WHERE product_id=? AND status='ACTIVE' AND current_qty>0 ORDER BY id DESC LIMIT 1", r0.optLong("product_id"));
        if (b != null) d.act("set_price", "اصلاح قیمت «" + r0.optString("name") + "» به قیمت خرید + ۱۲٪", "batch_id", b.optLong("id"), "sell_price", Math.round(b.optDouble("buy_price") * 1.12 / 100) * 100); d.act("note", "بررسی قیمت و تخفیف این کالاها"); d.metric = Local.obj("metric", "product_profit", "product_id", r0.optLong("product_id"), "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> priceRounding(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, Double> v28 = velocity28(f); List<Object[]> cand = new ArrayList<>();
        for (JSONObject b : Local.rows("SELECT id, product_id, sell_price FROM batches WHERE status='ACTIVE' AND current_qty>0")) { double p = b.optDouble("sell_price"); if (p < 5000) continue; double step = p < 50000 ? 500 : 1000, r = p % step; if (r > 0 && step - r <= step * 0.3) { double v = v28.getOrDefault(b.optLong("product_id"), 0.0); if (v * 28 >= 4) cand.add(new Object[]{b, p + (step - r), step - r, v * 30, (step - r) * v * 30}); } }
        if (cand.size() < 3) return out; cand.sort((a, b) -> Double.compare((double) b[4], (double) a[4])); JSONArray rows = new JSONArray(); JSONArray items = new JSONArray(); double gain = 0;
        for (Object[] c : cand) { if (rows.length() >= 40) break; JSONObject b = (JSONObject) c[0]; rows.put(Local.obj("batch_id", b.optLong("id"), "product_id", b.optLong("product_id"), "name", f.name(b.optLong("product_id")), "price", b.optDouble("sell_price"), "new_price", c[1], "monthly_units", Math.round((double) c[3]), "gain", Math.round((double) c[4]))); items.put(Local.obj("batch_id", b.optLong("id"), "sell_price", c[1])); gain += (double) c[4]; }
        JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("PRICE_ROUNDING", "month:" + today().substring(0, 7), "گردکردن قیمت " + fa(rows.length()) + " کالا: " + money(gain) + " سود ماهانهٔ بی‌دردسر",
            "«" + r0.optString("name") + "» " + money(r0.optDouble("price")) + " است؛ " + money(r0.optDouble("new_price")) + " برای مشتری فرقی ندارد ولی با " + fa(r0.optLong("monthly_units")) + " عدد فروش ماهانه " + money(r0.optLong("gain")) + " اضافه می‌آورد و خرده‌پول صندوق را هم کم می‌کند.");
        d.prio = 4; d.gain = gain * 0.9; d.ev = Local.obj("rows", rows, "monthly_gain", Math.round(gain)); d.act("set_prices_bulk", "گردکردن قیمت همهٔ این کالاها", "items", items); d.metric = Local.obj("metric", "product_profit", "product_id", r0.optLong("product_id"), "window_days", 28); out.add(d); return out;
    }

    /* ------------------------------------------------------------ operations / growth */
    static List<Insights.Draft> peakHours(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); if (f.inv.size() < 200) return out; double[] s = new double[24]; int[] n = new int[24]; double tot = 0; for (JSONObject i : f.inv.values()) { int h = hour(i.optString("at")); s[h] += i.optDouble("total"); n[h]++; tot += i.optDouble("total"); }
        Integer[] hs = new Integer[24]; for (int i = 0; i < 24; i++) hs[i] = i; java.util.Arrays.sort(hs, (a, b) -> Double.compare(s[b], s[a])); JSONArray rows = new JSONArray(); for (int h = 0; h < 24; h++) if (n[h] > 0) rows.put(Local.obj("hour", h, "invoices_per_day", Math.round(n[h] / 90.0 * 10) / 10.0, "sales_per_day", Math.round(s[h] / 90)));
        double share = (s[hs[0]] + s[hs[1]] + s[hs[2]]) / tot; int[] top = {hs[0], hs[1], hs[2]}; java.util.Arrays.sort(top);
        Insights.Draft d = new Insights.Draft("PEAK_HOURS", "month:" + today().substring(0, 7), "ساعت‌های " + fa(top[0]) + "، " + fa(top[1]) + "، " + fa(top[2]) + " → " + fa(Math.round(share * 100)) + "٪ فروش روزانه",
            "در این سه ساعت روزانه " + fa(Math.round((n[hs[0]] + n[hs[1]] + n[hs[2]]) / 90.0 * 10) / 10.0) + " فاکتور بسته می‌شود؛ صف و کمبود کالای تازه بیشترین ضرر را همین‌جا می‌زند. ساعات خلوت بهترین زمان چیدمان، شمارش و تماس با تأمین‌کننده است.");
        d.prio = 3; d.gain = tot / 90 * 30 * 0.005; d.ev = Local.obj("rows", rows); d.act("note", "برنامهٔ نیرو و تحویل کالا بر اساس ساعات اوج"); d.metric = Local.obj("metric", "avg_basket_size", "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> slowDay(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); if (f.inv.size() < 200) return out; double[] s = new double[7]; int[] n = new int[7]; for (JSONObject i : f.inv.values()) { int w = weekday(day(i)); s[w] += i.optDouble("total"); n[w]++; } double tot = 0; int seen = 0; for (int w = 0; w < 7; w++) { tot += s[w]; if (n[w] > 0) seen++; } if (seen < 6) return out;
        double avg = tot / 7; int worst = 0; for (int w = 1; w < 7; w++) if (s[w] < s[worst]) worst = w; if (s[worst] > avg * 0.65) return out; JSONArray rows = new JSONArray(); for (int w = 0; w < 7; w++) rows.put(Local.obj("weekday", WD[w], "wd", w, "sales", Math.round(s[w]), "invoices", n[w], "vs_avg_pct", Math.round((s[w] / avg - 1) * 100)));
        Insights.Draft d = new Insights.Draft("SLOW_DAY", "wd:" + worst + ":" + today().substring(0, 7), WD[worst] + "‌ها " + fa(Math.round((1 - s[worst] / avg) * 100)) + "٪ زیر میانگین هفته می‌فروشید",
            "فروش " + WD[worst] + " در این دوره " + money(s[worst]) + " بوده در برابر میانگین روزانهٔ " + money(avg) + ". تخفیف در روز اوج فقط سود را کم می‌کند؛ همان تخفیف در " + WD[worst] + " مشتری تازه می‌آورد. پیشنهاد: «" + WD[worst] + "‌های ۵٪» فقط با ثبت شماره.");
        d.prio = 3; d.gain = (avg - s[worst]) * (30.0 / 90) * 0.2 * profitRate(f); d.ev = Local.obj("rows", rows, "avg_day_sales", Math.round(avg)); d.act("flash_sale", "کمپین «" + WD[worst] + "‌های ۵٪» (۴ هفته)", "percent", 5, "days", 28); d.metric = Local.obj("metric", "weekday_sales", "weekday", worst, "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> unregistered(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); int n = f.inv.size(); if (n < 100) return out; int anon = 0, big = 0; double as = 0; for (JSONObject i : f.inv.values()) if (i.optLong("customer_id") <= 0) { anon++; as += i.optDouble("total"); if (i.optDouble("total") > 500000) big++; } double share = (double) anon / n; if (share < 0.6) return out;
        Insights.Draft d = new Insights.Draft("UNREGISTERED_SALES", "month:" + today().substring(0, 7), fa(Math.round(share * 100)) + "٪ فاکتورها بدون مشتری ثبت می‌شوند — هوش فروشگاه نیمه‌کور است",
            money(as) + " فروش این دوره به هیچ مشتری‌ای وصل نیست، از جمله " + fa(big) + " فاکتور بالای ۵۰۰ هزار تومان. تحلیل رفتار، پیامک شخصی و بازگشت مشتری فقط برای مشتریان ثبت‌شده کار می‌کند. یک جمله پای صندوق («شماره‌تان را بدهید تا امتیاز جمع شود») روی فاکتورهای بزرگ، در دو هفته این عدد را نصف می‌کند.");
        d.prio = 3; d.gain = as * (30.0 / 90) * profitRate(f) * 0.02; d.ev = Local.obj("invoices", n, "anonymous", anon, "anonymous_sales", Math.round(as), "big_anonymous", big); d.act("set_setting", "یادآوری ثبت شماره برای فاکتورهای بالای ۵۰۰ هزار تومان", "key", "pos.ask_phone_above", "value", "500000"); d.metric = Local.obj("metric", "avg_basket_size", "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> heroProduct(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); Map<Long, List<JSONObject>> bc = byCust(f); String since = Insights.daysAgo(90); List<Set<Long>> firsts = new ArrayList<>();
        for (JSONObject r : Local.rows("SELECT customer_id, MIN(at) AS first FROM invoices WHERE status<>'VOID' AND customer_id>0 GROUP BY customer_id")) { if (r.optString("first").compareTo(since) < 0) continue; List<JSONObject> invs = bc.get(r.optLong("customer_id")); if (invs == null || invs.isEmpty()) continue; Set<Long> pids = f.basket.get(invs.get(0).optLong("id")); if (pids != null) firsts.add(pids); }
        if (firsts.size() < 20) return out; Map<Long, Integer> fc = new HashMap<>(), all = new HashMap<>(); for (Set<Long> s : firsts) for (long p : s) fc.merge(p, 1, Integer::sum); for (Set<Long> s : f.basket.values()) for (long p : s) all.merge(p, 1, Integer::sum); int nAll = f.inv.size(); List<Object[]> cand = new ArrayList<>();
        for (Map.Entry<Long, Integer> e : fc.entrySet()) { if (e.getValue() < 5) continue; double lift = ((double) e.getValue() / firsts.size()) / Math.max(1e-9, (double) all.getOrDefault(e.getKey(), 1) / nAll); if (lift >= 1.5) cand.add(new Object[]{e.getKey(), e.getValue(), lift}); }
        if (cand.isEmpty()) return out; cand.sort((a, b) -> Double.compare((double) b[2] * (int) b[1], (double) a[2] * (int) a[1])); JSONArray rows = new JSONArray(); for (Object[] c : cand) { if (rows.length() >= 10) break; rows.put(Local.obj("product_id", c[0], "name", f.name((long) c[0]), "first_baskets", c[1], "first_share_pct", Math.round(100.0 * (int) c[1] / firsts.size()), "lift", Math.round((double) c[2] * 10) / 10.0)); }
        JSONObject r0 = rows.optJSONObject(0);
        Insights.Draft d = new Insights.Draft("HERO_PRODUCT", "month:" + today().substring(0, 7), "«" + r0.optString("name") + "» مشتری جدید می‌آورد (" + fa(r0.optLong("first_share_pct")) + "٪ اولین خریدها)",
            "در " + fa(firsts.size()) + " «اولین خرید» این دوره، این کالا " + fa(r0.optDouble("lift")) + "× بیشتر از سبدهای عادی دیده می‌شود؛ یعنی مردم به‌خاطر آن وارد می‌شوند. همین را روی بنر بیرون، استوری و پیامک جذب بگذارید — نه پرفروش‌ترین کالا را.");
        d.prio = 3; d.gain = firsts.size() * (30.0 / 90) * 0.15 * 80000; d.ev = Local.obj("rows", rows, "first_baskets", firsts.size()); d.act("note", "استفاده از کالای قلاب در تبلیغ بیرونی"); d.metric = Local.obj("metric", "product_units", "product_id", r0.optLong("product_id"), "window_days", 28); out.add(d); return out;
    }

    static List<Insights.Draft> surprise(Insights.Frame f) throws Exception {
        List<Insights.Draft> out = new ArrayList<>(); if (f.inv.isEmpty()) return out; List<String[]> facts = new ArrayList<>(); int n = f.inv.size();
        Map<String, Double> byDay = new HashMap<>(); int[] hrs = new int[24]; int[] wd = new int[7]; int reg = 0; double pr = 0; Map<Long, Double> pp = new HashMap<>();
        for (JSONObject i : f.inv.values()) { byDay.merge(day(i), i.optDouble("total"), Double::sum); hrs[hour(i.optString("at"))]++; wd[weekday(day(i))]++; if (i.optLong("customer_id") > 0) reg++; }
        for (JSONObject l : f.lines) { double p = f.profit(l); pr += p; pp.merge(l.optLong("product_id"), p, Double::sum); }
        String bd = null; double bv = 0; for (Map.Entry<String, Double> e : byDay.entrySet()) if (e.getValue() > bv) { bv = e.getValue(); bd = e.getKey(); } if (bd != null) facts.add(new String[]{"record_day", "پرفروش‌ترین روز ۹۰ روز اخیر: " + jdate(bd), money(bv) + " فروش در یک روز (" + WD[weekday(bd)] + "). چه چیزی آن روز فرق داشت؟ همان را تکرار کنید."});
        int bh = 0; for (int h = 1; h < 24; h++) if (hrs[h] > hrs[bh]) bh = h; facts.add(new String[]{"busiest_hour", "ساعت " + fa(bh) + " شلوغ‌ترین ساعت شماست", fa(hrs[bh]) + " فاکتور در این دوره (" + fa(Math.round(100.0 * hrs[bh] / n)) + "٪ کل). بهترین جا برای کالای تازه و پیشنهاد پای صندوق."});
        int bw = 0; for (int w = 1; w < 7; w++) if (wd[w] > wd[bw]) bw = w; facts.add(new String[]{"weekday", WD[bw] + " پرمشتری‌ترین روز هفته است", fa(wd[bw]) + " فاکتور در این دوره؛ چیدمان و موجودی را از شب قبل آماده کنید."});
        facts.add(new String[]{"registered", fa(Math.round(100.0 * reg / n)) + "٪ فاکتورها به یک مشتری وصل‌اند", "هر ۱۰٪ بیشتر یعنی پیش‌بینی دقیق‌تر خرید بعدی و پیامک‌های شخصی‌تر."});
        facts.add(new String[]{"profit_per_invoice", "هر فاکتور به‌طور میانگین " + money(pr / n) + " سود دارد", fa((int) Math.ceil(1000000 / Math.max(1, pr / n))) + " فاکتور اضافه = یک میلیون تومان سود."});
        long tp = -1; double tv = 0; for (Map.Entry<Long, Double> e : pp.entrySet()) if (e.getValue() > tv) { tv = e.getValue(); tp = e.getKey(); } if (tp > 0) facts.add(new String[]{"top_profit", "«" + f.name(tp) + "» سودآورترین کالای شماست", money(tv) + " سود در دوره. هرگز نباید خالی بماند — حداقل موجودی‌اش را چک کنید."});
        String tod = today(); int idx = (int) ((Insights.ms(tod + "T00:00:00") / 86400000L) % facts.size()); String[] fct = facts.get(Math.abs(idx));
        Insights.Draft d = new Insights.Draft("SURPRISE", "day:" + tod, "امروز می‌دانستید؟ " + fct[1], fct[2]); d.prio = 4; d.gain = 0; d.ev = Local.obj("fact", fct[0], "pool", facts.size()); d.metric = new JSONObject(); out.add(d); return out;
    }

    /* ------------------------------------------------------------ actions */
    static String coupon(String prefix, long cid, String phone, int pct, int days, String now) throws Exception {
        String code = prefix + "-" + Long.toString((System.currentTimeMillis() + cid * 7919L) % 100000000L, 36).toUpperCase();
        Local.exec("INSERT INTO coupons(code,discount_type,discount_value,min_purchase,customer_phone,valid_until,usage_limit,used_count,status,created_at) VALUES(?,?,?,?,?,?,1,0,'ACTIVE',?)", code, "PERCENT", pct, 0, phone, Insights.plusDays(now, days), now);
        return code;
    }

    /** returns null when the action type is not one of the PRO ones */
    static Object execute(JSONObject ins, String type, JSONObject p) throws Exception {
        String now = Db.now(); String store = Prefs.get("store_name", "فروشگاه");
        switch (type) {
            case "personal_sms": { int sent = 0; JSONArray cs = p.optJSONArray("customers"); if (SmsLocal.configured()) for (int i = 0; cs != null && i < cs.length(); i++) { JSONObject r = cs.optJSONObject(i); JSONObject c = Local.one("SELECT phone FROM customers WHERE id=?", r.optLong("customer_id")); if (c == null || c.optString("phone").isEmpty() || r.optString("text").isEmpty()) continue; SmsLocal.enqueueAndSend(c.optString("phone"), r.optString("text"), "insight:" + ins.optLong("id")); sent++; } return Local.obj("sms", sent, "skipped", SmsLocal.configured() ? JSONObject.NULL : "sms_disabled"); }
            case "personal_coupons": { int issued = 0, sent = 0; JSONArray cs = p.optJSONArray("customers"); for (int i = 0; cs != null && i < cs.length(); i++) { JSONObject r = cs.optJSONObject(i); JSONObject c = Local.one("SELECT id, name, phone FROM customers WHERE id=?", r.optLong("customer_id")); if (c == null) continue; int pct = r.optInt("percent", 5), days = r.optInt("days", 7); String code = coupon("ME", c.optLong("id"), c.optString("phone"), pct, days, now); issued++;
                if (!c.optString("phone").isEmpty() && SmsLocal.configured()) { String t = r.optString("text").isEmpty() ? c.optString("name") + " عزیز، کد " + code + " = " + fa(pct) + "٪ تخفیف شخصی شما در " + store + " تا " + fa(days) + " روز آینده." : r.optString("text").replace("{code}", code); SmsLocal.enqueueAndSend(c.optString("phone"), t, "insight:" + ins.optLong("id")); sent++; } } return Local.obj("coupons", issued, "sms", sent); }
            case "set_min_stock_bulk": { int n = 0; JSONArray items = p.optJSONArray("items"); for (int i = 0; items != null && i < items.length(); i++) { JSONObject it = items.optJSONObject(i); JSONObject pr = Db.productById(it.optLong("product_id")); if (pr == null) continue; Local.exec("UPDATE products SET min_stock_alert=? WHERE id=?", it.optInt("min_stock"), it.optLong("product_id")); n++; } Local.audit("INSIGHT_ACTION", "Product", "bulk", null, n); return Local.obj("updated", n); }
            case "set_prices_bulk": { int n = 0; JSONArray items = p.optJSONArray("items"); for (int i = 0; items != null && i < items.length(); i++) { JSONObject it = items.optJSONObject(i); JSONObject b = Local.one("SELECT product_id FROM batches WHERE id=?", it.optLong("batch_id")); if (b == null) continue; Local.exec("UPDATE batches SET sell_price=?, updated_at=? WHERE id=?", it.optDouble("sell_price"), now, it.optLong("batch_id")); try { Local.exec("INSERT INTO price_history(product_id,price_type,price,effective_from) VALUES(?,?,?,?)", b.optLong("product_id"), "SELL", it.optDouble("sell_price"), now); } catch (Exception ignore) {} n++; } return Local.obj("updated", n); }
            case "threshold_campaign": { Local.exec("INSERT INTO campaigns(name,discount_type,discount_value,min_purchase,valid_until,status,created_at) VALUES(?,?,?,?,?,'ACTIVE',?)", "خرید بالای " + fa(p.optLong("min_purchase")) + " = " + fa(p.optInt("percent", 3)) + "٪", "PERCENT", p.optInt("percent", 3), p.optLong("min_purchase"), Insights.plusDays(now, p.optInt("days", 30)), now); return Local.obj("campaign", "threshold"); }
            case "set_setting": { String k = p.optString("key"); if (!k.startsWith("pos.") && !k.startsWith("insights.") && !k.startsWith("sms.")) return Local.obj("skipped", "unsafe"); Local.setSetting(k, p.optString("value")); return Local.obj(k, p.optString("value")); }
            case "set_credit_limit": { int n = 0; JSONArray cs = p.optJSONArray("customers"); for (int i = 0; cs != null && i < cs.length(); i++) { JSONObject r = cs.optJSONObject(i); Local.exec("UPDATE customers SET credit_limit=? WHERE id=?", r.optDouble("limit"), r.optLong("customer_id")); n++; } return Local.obj("updated", n); }
            case "tag_customers": return Local.obj("tagged", 0);
        }
        return null;
    }
}
