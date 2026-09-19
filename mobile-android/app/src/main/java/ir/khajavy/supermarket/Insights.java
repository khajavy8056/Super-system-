package ir.khajavy.supermarket;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * v3.0 — «هوش فروشگاه» on the phone. Same contract as the Windows
 * {@code /api/insights} endpoints, computed from the phone's own SQLite so a
 * standalone shop gets the same suggestions, the same one-tap actions and the
 * same before/after measurement — fully offline.
 *
 * Analyzers (lightweight, run in < 1 s on a year of data):
 *  CROSS_SELL · EXPIRY_LADDER · DEAD_STOCK · VELOCITY · CASHFLOW · VIP · CHURN ·
 *  BASKET_NUDGE · PRICE_GAP · LOSS_PREV · SEASON
 * (SUPPLIER needs per-batch supplier ids which the phone does not track.)
 *
 * Measurement: accept() freezes a baseline (same metric, same window length,
 * ending now); measure() recomputes it after acceptance and credits the
 * difference in daily profit rate × elapsed days, adjusted by how the rest of
 * the store moved in the same period (difference-in-differences).
 */
public final class Insights {
    private Insights() {}

    static final String[][] LABELS = {{"CROSS_SELL", "هم‌خرید و چیدمان"}, {"EXPIRY_LADDER", "تخفیف پله‌ای انقضا"}, {"DEAD_STOCK", "سرمایهٔ راکد"}, {"VELOCITY", "هشدار اتمام موجودی"},
        {"SUPPLIER", "امتیاز تأمین‌کننده"}, {"CASHFLOW", "نقدینگی"}, {"VIP", "مشتریان VIP"}, {"CHURN", "بازگشت مشتری"}, {"BASKET_NUDGE", "پیشنهاد پای صندوق"},
        {"PRICE_GAP", "اصلاح قیمت"}, {"LOSS_PREV", "پیشگیری از ضرر"}, {"SEASON", "الگوی فصلی و هفتگی"}, {"VISIT_PATTERN", "پیش‌بینی خرید مشتری"}};
    static String label(String k) { for (String[] l : LABELS) if (l[0].equals(k)) return l[1]; for (String[] l : InsightsPro.LABELS) if (l[0].equals(k)) return l[1]; return k; }

    static final String DDL = "CREATE TABLE IF NOT EXISTS ai_insights(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, dedupe_key TEXT, title TEXT, body TEXT, priority INTEGER DEFAULT 2, evidence TEXT, actions TEXT, expected_gain REAL DEFAULT 0, metric TEXT, status TEXT DEFAULT 'NEW', accepted_at TEXT, snoozed_until TEXT, baseline TEXT, result TEXT, measured_at TEXT, measured_gain REAL, last_seen_at TEXT, narrative TEXT, created_at TEXT)";

    static void ensure() { try { Local.exec(DDL); } catch (Exception ignore) {} }

    /* ============================ dispatch (mirrors routers/insights.py) ============================ */
    public static Object handle(String method, String[] seg, JSONObject q, JSONObject b) throws Exception {
        ensure();
        if (seg.length == 1) { String st = q.optString("status", "NEW"); String where = "ALL".equals(st) ? "1=1" : "status IN ('" + st.replace(",", "','") + "')"; return arr(Local.rows("SELECT * FROM ai_insights WHERE " + where + " ORDER BY priority ASC, expected_gain DESC, id DESC LIMIT " + q.optInt("limit", 60))); }
        String w = seg[1];
        if ("summary".equals(w)) { JSONObject s = summary(); JSONArray ks = new JSONArray(); for (String[] l : LABELS) ks.put(Local.obj("kind", l[0], "label", l[1])); for (String[] l : InsightsPro.LABELS) ks.put(Local.obj("kind", l[0], "label", l[1])); s.put("kinds", ks); s.put("ai", Local.obj("provider", "local", "online", false, "model", "—")); return s; }
        if ("run".equals(w)) return run();
        if ("plan".equals(w)) { if (seg.length > 2 && "learn".equals(seg[2])) return Local.obj("ok", true, "calibration", Forecast.learn()); return Forecast.plan(Math.max(14, Math.min(365, q.optInt("horizon", 90)))); }
        if ("report".equals(w)) { JSONObject s = summary(); JSONArray open = arr(Local.rows("SELECT * FROM ai_insights WHERE status='NEW' ORDER BY priority, expected_gain DESC LIMIT 10")); return Local.obj("summary", s, "open", open, "narrative", weekly(s, open), "generated_at", Db.now()); }
        if ("nudges".equals(w)) return nudges(b.optJSONArray("product_ids"));
        if ("customers".equals(w)) { ensure(); return Local.obj("today", Jalali.todayIso().substring(0, 10), "horizon_days", q.optInt("days", 7), "rows", customerPatterns(new Frame(180), q.optInt("days", 7))); }
        if ("tasks".equals(w)) { JSONArray lst = new JSONArray(Local.setting("insights.reorder_list", "[]")); if ("DELETE".equals(method) && seg.length > 3) { JSONArray keep = new JSONArray(); for (int i = 0; i < lst.length(); i++) if (lst.optJSONObject(i).optLong("product_id") != Long.parseLong(seg[3])) keep.put(lst.optJSONObject(i)); Local.setSetting("insights.reorder_list", keep.toString()); return keep; } return lst; }
        long id = Long.parseLong(w); JSONObject row = Local.one("SELECT * FROM ai_insights WHERE id=?", id); if (row == null) throw new Api.ApiError(404, "INSIGHT_NOT_FOUND", "پیشنهاد یافت نشد");
        if (seg.length == 2) { if (q.optBoolean("narrate") && row.optString("narrative").isEmpty()) { String n = localNarrative(row); Local.exec("UPDATE ai_insights SET narrative=? WHERE id=?", n, id); row.put("narrative", n); } JSONObject o = out(row); if ("NEW".equals(row.optString("status")) || "SNOOZED".equals(row.optString("status"))) { try { o.put("prediction", Forecast.predictFor(row)); } catch (Exception ignore) {} } return o; }
        switch (seg[2]) {
            case "accept": { if (!"NEW".equals(row.optString("status")) && !"SNOOZED".equals(row.optString("status"))) throw new Api.ApiError(409, "INSIGHT_NOT_OPEN", "این پیشنهاد باز نیست"); JSONArray only = b.optJSONArray("actions"); JSONObject r = accept(row, only); r.put("ok", true); r.put("insight", out(Local.one("SELECT * FROM ai_insights WHERE id=?", id))); return r; }
            case "dismiss": Local.exec("UPDATE ai_insights SET status='DISMISSED' WHERE id=?", id); return Local.obj("ok", true);
            case "snooze": { String until = plusDays(Db.now(), Math.max(1, b.optInt("days", 7))); Local.exec("UPDATE ai_insights SET status='SNOOZED', snoozed_until=? WHERE id=?", until, id); return Local.obj("ok", true, "until", until); }
            case "measure": { JSONObject r = measure(row); if (r == null) throw new Api.ApiError(409, "INSIGHT_NOT_ACCEPTED", "هنوز اجرا نشده"); r.put("ok", true); r.put("insight", out(Local.one("SELECT * FROM ai_insights WHERE id=?", id))); return r; }
        }
        throw new Api.ApiError(404, "NOT_FOUND", "");
    }

    static JSONArray arr(List<JSONObject> rows) throws Exception { JSONArray a = new JSONArray(); for (JSONObject r : rows) a.put(out(r)); return a; }
    static JSONObject out(JSONObject r) throws Exception {
        JSONObject o = new JSONObject(r.toString());
        o.put("label", label(r.optString("kind")));
        o.put("evidence", jo(r.optString("evidence"))); o.put("actions", ja(r.optString("actions"))); o.put("metric", jo(r.optString("metric")));
        o.put("baseline", r.isNull("baseline") || r.optString("baseline").isEmpty() ? JSONObject.NULL : jo(r.optString("baseline")));
        o.put("result", r.isNull("result") || r.optString("result").isEmpty() ? JSONObject.NULL : jo(r.optString("result")));
        if (r.isNull("measured_gain")) o.put("measured_gain", JSONObject.NULL);
        return o;
    }
    static JSONObject jo(String s) { try { return s == null || s.isEmpty() ? new JSONObject() : new JSONObject(s); } catch (Exception e) { return new JSONObject(); } }
    static JSONArray ja(String s) { try { return s == null || s.isEmpty() ? new JSONArray() : new JSONArray(s); } catch (Exception e) { return new JSONArray(); } }

    /* ============================ time helpers ============================ */
    static final java.text.SimpleDateFormat ISO = new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US);
    static long ms(String iso) { try { return ISO.parse(iso.length() > 19 ? iso.substring(0, 19) : iso.replace(' ', 'T')).getTime(); } catch (Exception e) { return 0; } }
    static String plusDays(String iso, double days) { return ISO.format(new java.util.Date(ms(iso) + (long) (days * 86400000L))); }
    static String daysAgo(int d) { return plusDays(Db.now(), -d); }
    static double daysBetween(String a, String b) { return (ms(b) - ms(a)) / 86400000.0; }
    static String money(double v) { return Ui.fa(String.format(java.util.Locale.US, "%,d", Math.round(v))) + " " + Ui.currencyLabel; }
    static String fa(double v) { return Ui.num(v); }

    /* ============================ engine ============================ */
    static final class Draft { String kind, key, title, body; int prio = 2; JSONObject ev = new JSONObject(), metric = new JSONObject(); JSONArray actions = new JSONArray(); double gain;
        Draft(String kind, String key, String title, String body) { this.kind = kind; this.key = key; this.title = title; this.body = body; }
        Draft act(String type, String label, Object... kv) { try { actions.put(Local.obj("type", type, "label", label, "params", Local.obj(kv))); } catch (Exception ignore) {} return this; } }

    /** in-memory frame of the last N days of paid lines */
    static final class Frame {
        final List<JSONObject> lines = new ArrayList<>(); final Map<Long, JSONObject> inv = new HashMap<>(); final Map<Long, JSONObject> prod = new HashMap<>();
        final Map<Long, Set<Long>> basket = new HashMap<>();
        // v3.3: per-product aggregates computed once (velocity()/margin() used to rescan every line per call → O(batches × lines))
        private final Map<Long, double[]> agg = new HashMap<>();   // {qty28, profit90, qty90}
        private final String s28;
        Frame(int days) {
            String since = daysAgo(days); s28 = daysAgo(28);
            // only the columns the analyzers read — keeps a 180-day frame of a busy store well inside the phone's heap
            for (JSONObject i : Local.rows("SELECT rowid AS id, at, total, customer_id, user, status FROM invoices WHERE status<>'VOID' AND at>=?", since)) inv.put(i.optLong("id"), i);
            for (JSONObject l : Local.rows("SELECT ii.inv, ii.product_id, ii.qty, ii.unit_sell_price, ii.unit_buy_price, ii.discount, ii.subtotal, i.at, i.customer_id FROM invoices i JOIN invoice_items ii ON ii.inv=i.rowid WHERE i.status<>'VOID' AND i.at>=?", since)) {
                lines.add(l); basket.computeIfAbsent(l.optLong("inv"), k -> new HashSet<>()).add(l.optLong("product_id"));
                double[] a = agg.computeIfAbsent(l.optLong("product_id"), k -> new double[3]); double q = l.optDouble("qty"); if (l.optString("at").compareTo(s28) >= 0) a[0] += q; a[1] += profit(l); a[2] += q;
            }
            for (JSONObject p : Local.rows("SELECT id, name, barcode, min_stock_alert, category_id, image_url FROM products WHERE is_active<>0")) prod.put(p.optLong("id"), p);
        }
        String name(long pid) { JSONObject p = prod.get(pid); return p == null ? ("کالا #" + pid) : p.optString("name"); }
        double profit(JSONObject l) { return (l.optDouble("unit_sell_price") - l.optDouble("unit_buy_price")) * l.optDouble("qty") - l.optDouble("discount"); }
        double velocity(long pid, int days) { if (days == 28) { double[] a = agg.get(pid); return a == null ? 0 : a[0] / 28; } double q = 0; String since = daysAgo(days); for (JSONObject l : lines) if (l.optLong("product_id") == pid && l.optString("at").compareTo(since) >= 0) q += l.optDouble("qty"); return q / days; }
        double margin(long pid) { double[] a = agg.get(pid); return a == null || a[2] <= 0 ? 0 : a[1] / a[2]; }
    }

    public static JSONObject run() throws Exception {
        ensure(); Frame f = new Frame(90); List<Draft> drafts = new ArrayList<>(); JSONObject errors = new JSONObject();
        Object[][] an = {{"CROSS_SELL", (Analyzer) Insights::crossSell}, {"EXPIRY_LADDER", (Analyzer) Insights::expiry}, {"DEAD_STOCK", (Analyzer) Insights::deadStock}, {"VELOCITY", (Analyzer) Insights::velocity},
            {"CASHFLOW", (Analyzer) Insights::cashflow}, {"VIP", (Analyzer) Insights::vip}, {"CHURN", (Analyzer) Insights::churn}, {"BASKET_NUDGE", (Analyzer) Insights::basketNudge}, {"PRICE_GAP", (Analyzer) Insights::priceGap}, {"LOSS_PREV", (Analyzer) Insights::lossPrev}, {"SEASON", (Analyzer) Insights::season}, {"VISIT_PATTERN", (Analyzer) Insights::visitPattern}};
        for (Object[] a : an) { try { drafts.addAll(((Analyzer) a[1]).run(f)); } catch (Exception e) { errors.put((String) a[0], String.valueOf(e.getMessage())); } }
        for (Object[] a : InsightsPro.ANALYZERS) { try { drafts.addAll(((Analyzer) a[1]).run(f)); } catch (Throwable e) { errors.put((String) a[0], String.valueOf(e.getMessage())); } }   // v3.5 PRO pack
        int created = 0, refreshed = 0; Set<String> seen = new HashSet<>(); String now = Db.now(); JSONObject cal = Forecast.cal();
        for (Draft d : drafts) {
            seen.add(d.kind + "|" + d.key);
            // v3.1: keep the raw estimate for learning; expose the calibrated one with its band
            double raw = d.gain; JSONObject c = Forecast.calibrate(cal, d.kind, raw); d.ev.put("expected_gain_raw", Math.round(raw)); d.ev.put("forecast", Local.obj("gain_month", c.optLong("gain"), "low_month", c.optLong("low"), "high_month", c.optLong("high"), "confidence", c.optString("confidence"), "history_n", c.optInt("n"))); d.gain = c.optDouble("gain");
            JSONObject row = Local.one("SELECT * FROM ai_insights WHERE kind=? AND dedupe_key=? AND status IN ('NEW','SNOOZED','ACCEPTED')", d.kind, d.key);
            if (row != null) { if ("NEW".equals(row.optString("status"))) Local.exec("UPDATE ai_insights SET title=?,body=?,priority=?,evidence=?,actions=?,expected_gain=?,metric=?,last_seen_at=? WHERE id=?", d.title, d.body, d.prio, d.ev.toString(), d.actions.toString(), Math.round(d.gain), d.metric.toString(), now, row.optLong("id")); else Local.exec("UPDATE ai_insights SET last_seen_at=? WHERE id=?", now, row.optLong("id")); refreshed++; }
            else { Local.exec("INSERT INTO ai_insights(kind,dedupe_key,title,body,priority,evidence,actions,expected_gain,metric,status,last_seen_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,'NEW',?,?)", d.kind, d.key, d.title, d.body, d.prio, d.ev.toString(), d.actions.toString(), Math.round(d.gain), d.metric.toString(), now, now); created++; }
        }
        // stale NEW rows (situation no longer exists) → EXPIRED; snoozes wake up
        for (JSONObject r : Local.rows("SELECT id, kind, dedupe_key FROM ai_insights WHERE status='NEW'")) if (!seen.contains(r.optString("kind") + "|" + r.optString("dedupe_key"))) Local.exec("UPDATE ai_insights SET status='EXPIRED' WHERE id=?", r.optLong("id"));
        Local.exec("UPDATE ai_insights SET status='NEW' WHERE status='SNOOZED' AND snoozed_until<=?", now);
        measureAll(); applyMarkdownSteps();
        Local.setSetting("insights.last_run", now);
        return Local.obj("created", created, "refreshed", refreshed, "errors", errors, "invoices_analyzed", f.inv.size(), "window_days", 90);
    }
    interface Analyzer { List<Draft> run(Frame f) throws Exception; }

    /* ---- 1. cross-sell ---- */
    static List<Draft> crossSell(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); int n = f.basket.size(); if (n < 40) return out;
        Map<Long, Integer> cnt = new HashMap<>(); Map<String, Integer> pair = new HashMap<>();
        for (Set<Long> b : f.basket.values()) { List<Long> l = new ArrayList<>(b); java.util.Collections.sort(l); for (Long p : l) cnt.merge(p, 1, Integer::sum); for (int i = 0; i < l.size(); i++) for (int j = i + 1; j < l.size(); j++) pair.merge(l.get(i) + ":" + l.get(j), 1, Integer::sum); }
        List<Object[]> cands = new ArrayList<>();
        for (Map.Entry<String, Integer> e : pair.entrySet()) { int k = e.getValue(); if (k < Math.max(8, n * 0.01)) continue; String[] ab = e.getKey().split(":"); long a = Long.parseLong(ab[0]), c = Long.parseLong(ab[1]); double sup = k / (double) n, conf = k / (double) cnt.get(a), confB = k / (double) cnt.get(c), lift = conf / (cnt.get(c) / (double) n); if (lift < 1.6) continue; if (confB > conf) { long t = a; a = c; c = t; conf = confB; } cands.add(new Object[]{lift * k, a, c, k, sup, conf, lift}); }
        cands.sort((x, y) -> Double.compare((double) y[0], (double) x[0]));
        for (Object[] cd : cands.subList(0, Math.min(6, cands.size()))) { long a = (long) cd[1], c = (long) cd[2]; int k = (int) cd[3]; double conf = (double) cd[5], lift = (double) cd[6]; double gain = (cnt.get(a) - k) * 0.15 * f.margin(c) * (30.0 / 90);
            Draft d = new Draft("CROSS_SELL", "pair:" + a + ":" + c, "«" + f.name(a) + "» و «" + f.name(c) + "» با هم خریده می‌شوند", "در ۹۰ روز اخیر " + fa(k) + " بار با هم خریده شده‌اند؛ خریدارِ «" + f.name(a) + "» با احتمال " + fa(Math.round(conf * 100)) + "٪ «" + f.name(c) + "» را هم می‌خرد (" + fa(Math.round(lift * 10) / 10.0) + " برابر تصادف). پیشنهاد: کنار هم بچینید و پیشنهاد پای صندوق را روشن کنید.");
            d.prio = lift > 2.5 ? 2 : 3; d.gain = Math.max(0, gain); d.ev = Local.obj("pair_count", k, "invoices", n, "confidence", Math.round(conf * 100) / 100.0, "lift", Math.round(lift * 100) / 100.0, "products", new JSONArray().put(Local.obj("id", a, "name", f.name(a))).put(Local.obj("id", c, "name", f.name(c))));
            d.act("shelf_note", "یادداشت چیدمان", "products", new JSONArray().put(a).put(c)).act("pos_nudge", "پیشنهاد پای صندوق را فعال کن", "a", a, "b", c); d.metric = Local.obj("metric", "attach_rate", "a", a, "b", c, "window_days", 28); out.add(d); }
        return out;
    }

    /* ---- 2. expiry ladder ---- */
    static List<Draft> expiry(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); String today = Jalali.todayIso();
        for (JSONObject b : Local.rows("SELECT * FROM batches WHERE status='ACTIVE' AND current_qty>0 AND expiry_date IS NOT NULL AND expiry_date<>''")) {
            double left = daysBetween(today + "T00:00:00", b.optString("expiry_date").substring(0, 10) + "T00:00:00"); if (left < 0 || left > 45) continue;
            long pid = b.optLong("product_id"); double v = f.velocity(pid, 28), qty = b.optDouble("current_qty"); double will = v * left; if (will >= qty * 0.9) continue;
            double surplus = qty - will, buy = b.optDouble("buy_price"), sell = b.optDouble("sell_price"); double risk = surplus * buy; if (risk < 50000) continue;
            int maxPct = sell > 0 ? (int) Math.max(5, Math.min(40, Math.floor((1 - buy * 1.02 / sell) * 100))) : 10; int s1 = Math.max(1, (int) left / 3);
            JSONArray ladder = new JSONArray().put(Local.obj("from_day", 0, "percent", Math.max(5, maxPct / 3))).put(Local.obj("from_day", s1, "percent", Math.max(8, maxPct * 2 / 3))).put(Local.obj("from_day", s1 * 2, "percent", maxPct));
            Draft d = new Draft("EXPIRY_LADDER", "batch:" + b.optLong("id"), f.name(pid) + ": " + fa(Math.ceil(surplus)) + " عدد تا انقضا نمی‌فروشد", fa(Math.round(left)) + " روز تا انقضا مانده؛ سرعت فروش " + fa(Math.round(v * 70) / 10.0) + " عدد در هفته است و از " + fa(qty) + " عدد موجود حدود " + fa(Math.ceil(surplus)) + " عدد ضایعات می‌شود (" + money(risk) + " ضرر). پیشنهاد: تخفیف پله‌ای " + fa(ladder.optJSONObject(0).optInt("percent")) + "٪ ← " + fa(ladder.optJSONObject(1).optInt("percent")) + "٪ ← " + fa(maxPct) + "٪ (آخرین پله هنوز بالای قیمت خرید است).");
            d.prio = left <= 7 ? 1 : 2; d.gain = risk * 0.6; d.ev = Local.obj("batch_id", b.optLong("id"), "product_id", pid, "days_left", Math.round(left), "qty", qty, "velocity_per_day", Math.round(v * 1000) / 1000.0, "surplus", Math.round(surplus * 10) / 10.0, "at_risk", Math.round(risk), "buy", buy, "sell", sell, "ladder", ladder);
            d.act("markdown_ladder", "اعمال تخفیف پله‌ای", "batch_id", b.optLong("id"), "ladder", ladder).act("sms_buyers", "پیامک به خریداران قبلی", "product_id", pid, "percent", ladder.optJSONObject(0).optInt("percent")); d.metric = Local.obj("metric", "product_units", "product_id", pid, "window_days", Math.min(28, Math.max(7, (int) left))); out.add(d);
        }
        out.sort((x, y) -> Double.compare(y.gain, x.gain)); return out.subList(0, Math.min(8, out.size()));
    }

    /* ---- 3. dead stock ---- */
    static List<Draft> deadStock(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); Map<Long, Double> sold60 = new HashMap<>(); String s60 = daysAgo(60); for (JSONObject l : f.lines) if (l.optString("at").compareTo(s60) >= 0) sold60.merge(l.optLong("product_id"), l.optDouble("qty"), Double::sum);
        Map<Long, Double> qty90 = new HashMap<>(); for (JSONObject l : f.lines) qty90.merge(l.optLong("product_id"), l.optDouble("qty"), Double::sum); List<Long> movers = new ArrayList<>(qty90.keySet()); movers.sort((a, b) -> Double.compare(qty90.get(b), qty90.get(a)));
        List<Object[]> cands = new ArrayList<>();
        for (JSONObject r : Local.rows("SELECT product_id, SUM(current_qty) AS q, SUM(current_qty*buy_price) AS v, MIN(IFNULL(received_at, updated_at)) AS rx FROM batches WHERE status='ACTIVE' AND current_qty>0 GROUP BY product_id")) { long pid = r.optLong("product_id"); if (!f.prod.containsKey(pid)) continue; double age = r.optString("rx").isEmpty() ? 0 : daysBetween(r.optString("rx"), Db.now()); double v = r.optDouble("v"), q = r.optDouble("q"); if (age < 45 || v < 100000) continue; if (sold60.getOrDefault(pid, 0.0) > q * 0.15) continue; cands.add(new Object[]{v, pid, q, age, sold60.getOrDefault(pid, 0.0)}); }
        cands.sort((x, y) -> Double.compare((double) y[0], (double) x[0])); double total = 0; for (Object[] c : cands) total += (double) c[0];
        for (Object[] c : cands.subList(0, Math.min(6, cands.size()))) { double v = (double) c[0]; long pid = (long) c[1]; Long partner = null; for (Long m : movers) if (m != pid) { partner = m; break; }
            Draft d = new Draft("DEAD_STOCK", "product:" + pid, "سرمایهٔ راکد: " + f.name(pid) + " (" + money(v) + ")", fa((double) c[2]) + " عدد از این کالا " + fa(Math.round((double) c[3])) + " روز است در انبار مانده و در ۶۰ روز اخیر فقط " + fa((double) c[4]) + " عدد فروخته شده. پیشنهاد: باندل «" + f.name(pid) + " + " + (partner == null ? "کالای پرفروش" : f.name(partner)) + "» با ۱۵٪ تخفیف روی کالای راکد، یا جابه‌جایی به قفسهٔ کنار صندوق. کل سرمایهٔ قفل‌شده در کالاهای راکد: " + money(total) + ".");
            d.prio = v > 500000 ? 2 : 3; d.gain = v * 0.5 * (30.0 / 60); d.ev = Local.obj("product_id", pid, "qty", c[2], "locked_value", Math.round(v), "age_days", Math.round((double) c[3]), "sold_60d", c[4], "partner_id", partner, "partner_name", partner == null ? "" : f.name(partner), "total_locked", Math.round(total));
            d.act("bundle_campaign", "ساخت باندل با ۱۵٪ تخفیف", "product_id", pid, "partner_id", partner, "percent", 15).act("shelf_note", "انتقال به قفسهٔ کنار صندوق", "products", new JSONArray().put(pid)); d.metric = Local.obj("metric", "product_units", "product_id", pid, "window_days", 28); out.add(d); }
        return out;
    }

    /* ---- 4. velocity / stockout ---- */
    static List<Draft> velocity(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); Map<Long, Double> stock = new HashMap<>(); for (JSONObject r : Local.rows("SELECT product_id, SUM(current_qty) AS q FROM batches WHERE status='ACTIVE' GROUP BY product_id")) stock.put(r.optLong("product_id"), r.optDouble("q"));
        Map<Long, Set<String>> days = new HashMap<>(); Map<Long, Double> q28 = new HashMap<>(); String s28 = daysAgo(28); for (JSONObject l : f.lines) if (l.optString("at").compareTo(s28) >= 0) { q28.merge(l.optLong("product_id"), l.optDouble("qty"), Double::sum); days.computeIfAbsent(l.optLong("product_id"), k -> new HashSet<>()).add(l.optString("at").substring(0, 10)); }
        for (Map.Entry<Long, Double> e : q28.entrySet()) { long pid = e.getKey(); if (days.get(pid).size() < 6) continue; double v = e.getValue() / 28, st = stock.getOrDefault(pid, 0.0), cover = v > 0 ? st / v : 99; if (cover > 6) continue; double m = f.margin(pid), lost = v * 7 * m; if (lost < 30000) continue; int reorder = (int) Math.ceil(v * 14 - st);
            Draft d = new Draft("VELOCITY", "product:" + pid, f.name(pid) + " تا " + fa(Math.round(cover * 10) / 10.0) + " روز دیگر تمام می‌شود", "میانگین فروش " + fa(Math.round(v * 70) / 10.0) + " عدد در هفته (" + fa(days.get(pid).size()) + " روز فروش از ۲۸ روز)؛ موجودی فعلی " + fa(st) + " عدد. هر هفته بدون موجودی یعنی " + money(lost) + " سود ازدست‌رفته. پیشنهاد سفارش: " + fa(Math.max(reorder, 1)) + " عدد (پوشش ۲ هفته).");
            d.prio = cover <= 2 ? 1 : 2; d.gain = lost * 2; d.ev = Local.obj("product_id", pid, "velocity_per_day", Math.round(v * 1000) / 1000.0, "stock", st, "days_cover", Math.round(cover * 10) / 10.0, "sold_28d", e.getValue(), "sale_days", days.get(pid).size(), "reorder_qty", Math.max(reorder, 1), "margin_per_unit", Math.round(m));
            d.act("reorder_note", "افزودن به لیست سفارش", "product_id", pid, "qty", Math.max(reorder, 1)).act("set_min_stock", "تنظیم حداقل موجودی هوشمند", "product_id", pid, "min_stock", (int) Math.ceil(v * 5)); d.metric = Local.obj("metric", "availability", "product_id", pid, "window_days", 14, "margin_per_day", Math.round(v * m)); out.add(d); }
        out.sort((x, y) -> x.prio != y.prio ? x.prio - y.prio : Double.compare(y.gain, x.gain)); return out.subList(0, Math.min(10, out.size()));
    }

    /* ---- 5. cash-flow ---- */
    static List<Draft> cashflow(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); double sales30 = 0; String s30 = daysAgo(30); for (JSONObject i : f.inv.values()) if (i.optString("at").compareTo(s30) >= 0) sales30 += i.optDouble("total"); double daily = sales30 / 30; if (daily <= 0) return out;
        JSONObject ex = Local.one("SELECT IFNULL(SUM(amount),0) AS s FROM expenses WHERE expense_date>=?", Jalali.daysAgoIso(90)); double expDaily = ex.optDouble("s") / 90;
        JSONObject pu = Local.one("SELECT IFNULL(SUM(IFNULL(quantity_received,current_qty)*buy_price),0) AS s FROM batches WHERE IFNULL(received_at,updated_at)>=?", daysAgo(90)); double purDaily = pu.optDouble("s") / 90;
        String today = Jalali.todayIso(); List<JSONObject> chq = Local.rows("SELECT * FROM cheques WHERE direction='ISSUED' AND status='PENDING' AND due_date>=? AND due_date<=?", today, plusDays(today + "T00:00:00", 30).substring(0, 10));
        List<JSONObject> in = Local.rows("SELECT * FROM cheques WHERE direction='RECEIVED' AND status='PENDING' AND due_date>=? AND due_date<=?", today, plusDays(today + "T00:00:00", 30).substring(0, 10));
        if (chq.isEmpty()) return out;
        double cash = Local.acc("1010", null, null) + Local.acc("1020", null, null); double bal = cash, low = cash; String lowDay = today; JSONArray tl = new JSONArray(); double outTotal = 0;
        for (int d = 1; d <= 30; d++) { String day = plusDays(today + "T00:00:00", d).substring(0, 10); bal += daily - expDaily - purDaily; for (JSONObject c : chq) if (c.optString("due_date").startsWith(day)) { bal -= c.optDouble("amount"); } for (JSONObject c : in) if (c.optString("due_date").startsWith(day)) bal += c.optDouble("amount"); if (bal < low) { low = bal; lowDay = day; } tl.put(Local.obj("day", day, "balance", Math.round(bal))); }
        for (JSONObject c : chq) outTotal += c.optDouble("amount"); if (low >= 0) return out;
        JSONObject big = chq.get(0); for (JSONObject c : chq) if (c.optDouble("amount") > big.optDouble("amount")) big = c;
        Draft d = new Draft("CASHFLOW", "month:" + today.substring(0, 7), "هشدار نقدینگی: کسری " + money(-low) + " تا " + fa(Math.round(daysBetween(today + "T00:00:00", lowDay + "T00:00:00"))) + " روز دیگر", "با فروش میانگین " + money(daily) + " در روز و هزینه/خرید روزانهٔ حدود " + money(expDaily + purDaily) + "، سررسید " + fa(chq.size()) + " چک صادره (" + money(outTotal) + ") در ۳۰ روز آینده باعث کسری تقریبی " + money(-low) + " در " + Ui.jdate(lowDay) + " می‌شود. بزرگ‌ترین چک: " + money(big.optDouble("amount")) + " به «" + big.optString("party_name") + "» در " + Ui.jdate(big.optString("due_date")) + ". پیشنهاد: وصول بدهی مشتریان با پیامک یادآوری، جابه‌جایی سررسید بزرگ‌ترین چک یا فروش ویژهٔ ۳ روزهٔ کالاهای راکد.");
        d.prio = 1; d.ev = Local.obj("avg_daily_sales", Math.round(daily), "expense_daily", Math.round(expDaily), "purchase_daily", Math.round(purDaily), "lowest", Math.round(low), "lowest_day", lowDay, "timeline", tl, "cheques_out", chq.size());
        d.act("debt_reminders", "پیامک یادآوری به بدهکاران").act("flash_sale", "فروش ویژهٔ ۳ روزه", "percent", 10, "days", 3); d.metric = Local.obj("metric", "receivables_collected", "window_days", 14); out.add(d); return out;
    }

    /* ---- 6. VIP ---- */
    static List<Draft> vip(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); Map<Long, double[]> by = new HashMap<>(); double totalP = 0;
        for (JSONObject l : f.lines) { double p = f.profit(l); totalP += p; if (l.isNull("customer_id") || l.optLong("customer_id") == 0) continue; double[] a = by.computeIfAbsent(l.optLong("customer_id"), k -> new double[3]); a[0] += l.optDouble("subtotal"); a[1] += p; }
        for (JSONObject i : f.inv.values()) if (!i.isNull("customer_id") && by.containsKey(i.optLong("customer_id"))) by.get(i.optLong("customer_id"))[2]++;
        if (by.size() < 10 || totalP <= 0) return out; List<Map.Entry<Long, double[]>> rows = new ArrayList<>(by.entrySet()); rows.sort((a, b) -> Double.compare(b.getValue()[1], a.getValue()[1]));
        int top = Math.max(3, (int) Math.ceil(rows.size() * 0.1)); rows = rows.subList(0, Math.min(top, rows.size())); double sP = 0, sS = 0; JSONArray ev = new JSONArray(); JSONArray ids = new JSONArray();
        for (Map.Entry<Long, double[]> e : rows) { sP += e.getValue()[1]; sS += e.getValue()[0]; JSONObject c = Local.one("SELECT * FROM customers WHERE id=?", e.getKey()); ev.put(Local.obj("customer_id", e.getKey(), "name", c == null ? "" : (c.optString("name") + " " + c.optString("last_name")).trim(), "invoices", (int) e.getValue()[2], "sales", Math.round(e.getValue()[0]), "profit", Math.round(e.getValue()[1]))); ids.put(e.getKey()); }
        double share = sP / totalP; if (share < 0.2) return out;
        Draft d = new Draft("VIP", "quarter:" + Jalali.todayIso().substring(0, 7), fa(rows.size()) + " مشتری، " + fa(Math.round(share * 100)) + "٪ سود شما را می‌سازند", "این " + fa(rows.size()) + " نفر در ۹۰ روز اخیر " + money(sS) + " خرید و " + money(sP) + " سود آورده‌اند. پیشنهاد: باشگاه VIP — کوپن ۵٪ ماهانه با پیامک شخصی، اولویت در کالاهای کمیاب، و تبریک مناسبت‌ها. هزینهٔ حفظ این‌ها بسیار کمتر از جذب مشتری جدید است.");
        d.prio = 2; d.gain = sP / 3 * 0.10; d.ev = Local.obj("rows", ev, "share", Math.round(share * 1000) / 1000.0, "total_profit_90d", Math.round(totalP)); d.act("vip_coupons", "صدور کوپن VIP + پیامک", "customer_ids", ids, "percent", 5, "days", 30); d.metric = Local.obj("metric", "customer_sales", "customer_ids", ids, "window_days", 28); out.add(d); return out;
    }

    /* ---- 7. churn ---- */
    static List<Draft> churn(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); Map<Long, List<String>> visits = new HashMap<>(); Map<Long, Double> profit = new HashMap<>();
        for (JSONObject i : Local.rows("SELECT rowid AS id, customer_id, at FROM invoices WHERE status<>'VOID' AND customer_id IS NOT NULL AND at>=? ORDER BY at", daysAgo(180))) visits.computeIfAbsent(i.optLong("customer_id"), k -> new ArrayList<>()).add(i.optString("at"));
        for (JSONObject l : f.lines) if (!l.isNull("customer_id")) profit.merge(l.optLong("customer_id"), f.profit(l), Double::sum);
        JSONArray rows = new JSONArray(); JSONArray ids = new JSONArray(); double atRisk = 0;
        for (Map.Entry<Long, List<String>> e : visits.entrySet()) { List<String> v = e.getValue(); if (v.size() < 4) continue; List<Double> gaps = new ArrayList<>(); for (int i = 1; i < v.size(); i++) gaps.add(daysBetween(v.get(i - 1), v.get(i))); java.util.Collections.sort(gaps); double typical = gaps.get(gaps.size() / 2), silent = daysBetween(v.get(v.size() - 1), Db.now()); if (silent > Math.max(14, typical * 2.5)) { JSONObject c = Local.one("SELECT * FROM customers WHERE id=?", e.getKey()); if (c == null) continue; double mp = profit.getOrDefault(e.getKey(), 0.0) / 3; atRisk += mp; rows.put(Local.obj("customer_id", e.getKey(), "name", (c.optString("name") + " " + c.optString("last_name")).trim(), "silent_days", Math.round(silent), "typical_gap", Math.round(typical), "invoices", v.size(), "monthly_profit", Math.round(mp))); ids.put(e.getKey()); } }
        if (rows.length() == 0) return out;
        Draft d = new Draft("CHURN", "week:" + Jalali.todayIso().substring(0, 10), fa(rows.length()) + " مشتری ثابت مدتی است نیامده‌اند", "این مشتریان به‌طور معمول هر چند روز خرید می‌کردند اما مدتی است غایب‌اند؛ سود ماهانهٔ در خطر حدود " + money(atRisk) + ". پیشنهاد: پیامک بازگشت با کوپن ۱۰٪ یک‌بارمصرف ۱۴ روزه.");
        d.prio = 2; d.gain = atRisk * 0.4; d.ev = Local.obj("rows", rows, "monthly_profit_at_risk", Math.round(atRisk)); d.act("winback_sms", "پیامک بازگشت + کوپن ۱۰٪", "customer_ids", ids, "percent", 10, "days", 14); d.metric = Local.obj("metric", "customer_sales", "customer_ids", ids, "window_days", 21); out.add(d); return out;
    }

    /* ---- v3.2 per-customer purchase rhythm → who is due in the next N days ---- */
    static final String[] WD_FA = {"یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه"};   // Calendar.DAY_OF_WEEK − 1
    static JSONArray customerPatterns(Frame f, int horizon) throws Exception {
        Map<Long, List<String>> visits = new HashMap<>(); Map<Long, Double> totals = new HashMap<>(), profit = new HashMap<>(); Map<Long, Map<Long, Integer>> items = new HashMap<>();
        for (JSONObject i : f.inv.values()) if (!i.isNull("customer_id")) { visits.computeIfAbsent(i.optLong("customer_id"), k -> new ArrayList<>()).add(i.optString("at")); totals.merge(i.optLong("customer_id"), i.optDouble("total"), Double::sum); }
        for (JSONObject l : f.lines) if (!l.isNull("customer_id")) { profit.merge(l.optLong("customer_id"), f.profit(l), Double::sum); items.computeIfAbsent(l.optLong("customer_id"), k -> new HashMap<>()).merge(l.optLong("product_id"), 1, Integer::sum); }
        String today = Jalali.todayIso().substring(0, 10); java.util.Calendar cal = java.util.Calendar.getInstance(); List<JSONObject> out = new ArrayList<>();
        for (Map.Entry<Long, List<String>> e : visits.entrySet()) {
            java.util.TreeSet<String> days = new java.util.TreeSet<>(); for (String v : e.getValue()) days.add(v.substring(0, 10)); if (days.size() < 5) continue;
            List<String> dl = new ArrayList<>(days); List<Integer> gaps = new ArrayList<>(); for (int i = 1; i < dl.size(); i++) { int g = (int) Math.round(daysBetween(dl.get(i - 1) + "T00:00:00", dl.get(i) + "T00:00:00")); if (g > 0) gaps.add(g); } if (gaps.size() < 3) continue;
            List<Integer> gs = new ArrayList<>(gaps); java.util.Collections.sort(gs); int med = gs.get(gs.size() / 2); List<Integer> dev = new ArrayList<>(); for (int g : gaps) dev.add(Math.abs(g - med)); java.util.Collections.sort(dev); double mad = dev.get(dev.size() / 2), regularity = Math.max(0, 1 - mad / Math.max(1, med));
            String last = dl.get(dl.size() - 1); if (last.equals(today)) continue; String next = plusDays(last + "T12:00:00", med).substring(0, 10); int dueIn = (int) Math.round(daysBetween(today + "T00:00:00", next + "T00:00:00")); if (dueIn < -1 || dueIn > horizon) continue;
            int[] wd = new int[7], hr = new int[24]; for (String v : e.getValue()) { cal.setTimeInMillis(ms(v)); wd[cal.get(java.util.Calendar.DAY_OF_WEEK) - 1]++; hr[cal.get(java.util.Calendar.HOUR_OF_DAY)]++; } int bw = 0, bh = 0; for (int i = 0; i < 7; i++) if (wd[i] > wd[bw]) bw = i; for (int i = 0; i < 24; i++) if (hr[i] > hr[bh]) bh = i;
            List<Map.Entry<Long, Integer>> its = new ArrayList<>(items.getOrDefault(e.getKey(), new HashMap<>()).entrySet()); its.sort((x, y) -> y.getValue() - x.getValue()); JSONArray ui = new JSONArray(); for (int i = 0; i < Math.min(4, its.size()); i++) ui.put(Local.obj("product_id", its.get(i).getKey(), "name", f.name(its.get(i).getKey()), "times", its.get(i).getValue()));
            JSONObject c = Local.one("SELECT * FROM customers WHERE id=?", e.getKey()); if (c == null) continue;
            out.add(Local.obj("customer_id", e.getKey(), "name", (c.optString("name") + " " + c.optString("last_name")).trim(), "phone", c.isNull("phone") ? JSONObject.NULL : c.optString("phone"), "visits", days.size(), "typical_gap", med, "regularity", Math.round(regularity * 100) / 100.0, "last_visit", last, "predicted", next, "due_in", dueIn, "usual_weekday", WD_FA[bw], "usual_hour", bh, "avg_ticket", Math.round(totals.getOrDefault(e.getKey(), 0.0) / e.getValue().size()), "monthly_profit", Math.round(profit.getOrDefault(e.getKey(), 0.0) / 6.0), "usual_items", ui));
        }
        out.sort((x, y) -> Double.compare(y.optDouble("regularity") * y.optDouble("monthly_profit"), x.optDouble("regularity") * x.optDouble("monthly_profit")));
        JSONArray a = new JSONArray(); for (JSONObject o : out) a.put(o); return a;
    }
    static List<Draft> visitPattern(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); JSONArray all = customerPatterns(new Frame(180), 3); JSONArray rows = new JSONArray(); JSONArray cs = new JSONArray(); double mp = 0; int withPhone = 0;
        for (int i = 0; i < all.length() && rows.length() < 30; i++) { JSONObject r = all.optJSONObject(i); if (r.optDouble("regularity") < 0.35) continue; rows.put(r); mp += r.optDouble("monthly_profit"); if (!r.isNull("phone") && !r.optString("phone").isEmpty()) { withPhone++; JSONArray ui = r.optJSONArray("usual_items"); cs.put(Local.obj("customer_id", r.optLong("customer_id"), "item", ui != null && ui.length() > 0 ? ui.optJSONObject(0).optString("name") : "")); } }
        if (rows.length() < 3) return out; JSONObject ex = rows.optJSONObject(0); JSONArray exi = ex.optJSONArray("usual_items"); JSONArray ids = new JSONArray(); for (int i = 0; i < rows.length(); i++) ids.put(rows.optJSONObject(i).optLong("customer_id"));
        Draft d = new Draft("VISIT_PATTERN", "day:" + Jalali.todayIso().substring(0, 10), fa(rows.length()) + " مشتری ثابت طی ۳ روز آینده می‌آیند — پیامک شخصی بفرستید", "از روی فاصلهٔ خریدهای هر مشتری، " + fa(rows.length()) + " مشتری ثابت در ۳ روز آینده نوبت خریدشان است (مثلاً «" + ex.optString("name") + "» معمولاً هر " + fa(ex.optInt("typical_gap")) + " روز، " + ex.optString("usual_weekday") + "‌ها ساعت " + fa(ex.optInt("usual_hour")) + "، و بیشتر «" + (exi != null && exi.length() > 0 ? exi.optJSONObject(0).optString("name") : "—") + "» می‌خرد). یک پیامک کوتاه و شخصی درست قبل از نوبتشان — «فلان کالای همیشگی‌تان رسیده» — احتمال آمدن و اندازهٔ سبد را بالا می‌برد. سود ماهانهٔ این گروه: " + money(mp) + "؛ " + fa(withPhone) + " نفر شماره دارند.");
        d.prio = 2; d.gain = mp * 0.12; d.ev = Local.obj("rows", rows, "monthly_profit", Math.round(mp), "with_phone", withPhone); d.act("visit_sms", "پیامک شخصی «کالای همیشگی‌تان» به مشتریان در نوبت", "customers", cs); d.metric = Local.obj("metric", "customer_sales", "customer_ids", ids, "window_days", 14); out.add(d); return out;
    }

    /* ---- 8. basket nudge (rules for the POS) ---- */
    static List<Draft> basketNudge(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); int n = f.basket.size(); if (n < 40) return out;
        Map<Long, Integer> cnt = new HashMap<>(); Map<String, Integer> pair = new HashMap<>();
        for (Set<Long> b : f.basket.values()) { for (Long p : b) cnt.merge(p, 1, Integer::sum); for (Long x : b) for (Long y : b) if (!x.equals(y)) pair.merge(x + ":" + y, 1, Integer::sum); }
        JSONArray rules = new JSONArray(); List<Object[]> c = new ArrayList<>();
        for (Map.Entry<String, Integer> e : pair.entrySet()) { int k = e.getValue(); if (k < 6) continue; String[] xy = e.getKey().split(":"); long x = Long.parseLong(xy[0]), y = Long.parseLong(xy[1]); double conf = k / (double) cnt.get(x), lift = conf / (cnt.get(y) / (double) n); if (conf >= 0.25 && lift >= 1.5) c.add(new Object[]{conf * lift, x, y, conf, lift, k}); }
        c.sort((a, b) -> Double.compare((double) b[0], (double) a[0])); Set<Long> usedIf = new HashSet<>(); double gain = 0;
        for (Object[] r : c) { long x = (long) r[1], y = (long) r[2]; if (usedIf.contains(x)) continue; usedIf.add(x); rules.put(Local.obj("if", x, "then", y, "if_name", f.name(x), "then_name", f.name(y), "confidence", Math.round((double) r[3] * 100) / 100.0, "lift", Math.round((double) r[4] * 100) / 100.0, "support", r[5])); gain += (cnt.get(x) - (int) r[5]) * 0.08 * f.margin(y) * (30.0 / 90); if (rules.length() >= 24) break; }
        if (rules.length() < 3) return out; double avg = 0; for (JSONObject i : f.inv.values()) avg += i.optDouble("total"); avg /= Math.max(1, n);
        Draft d = new Draft("BASKET_NUDGE", "rules", fa(rules.length()) + " پیشنهاد لحظه‌ای برای صندوق‌دار آماده است", "با روشن‌کردن «پیشنهاد پای صندوق»، وقتی کالایی به سبد اضافه می‌شود صندوق‌دار یک خط کوچک می‌بیند: «مشتری " + rules.optJSONObject(0).optString("if_name") + " خرید — " + rules.optJSONObject(0).optString("then_name") + " هم پیشنهاد بده؟». میانگین سبد فعلی " + money(avg) + " است؛ حتی ۳٪ افزایش سبد یعنی سود قابل توجه در ماه.");
        d.prio = 2; d.gain = gain; d.ev = Local.obj("rules", rules, "avg_basket", Math.round(avg)); d.act("enable_nudges", "فعال‌سازی پیشنهاد پای صندوق"); d.metric = Local.obj("metric", "avg_basket_size", "window_days", 28); out.add(d); return out;
    }

    /* ---- 9. price gap ---- */
    static List<Draft> priceGap(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); Set<Long> seen = new HashSet<>();
        for (JSONObject b : Local.rows("SELECT * FROM batches WHERE status='ACTIVE' AND current_qty>0 ORDER BY id DESC")) { long pid = b.optLong("product_id"); if (seen.contains(pid) || !f.prod.containsKey(pid)) continue; seen.add(pid); double cost = b.optDouble("buy_price"), sell = b.optDouble("sell_price"), cons = b.optDouble("consumer_price"); if (cost <= 0 || sell <= 0) continue; double margin = (sell - cost) / sell, v = f.velocity(pid, 28);
            if (margin < 0.03 && v > 0.2) { double np = Math.round(Math.max(cost * 1.12, cons > 0 ? Math.min(cons, cost * 1.15) : cost * 1.15) / 100) * 100; Draft d = new Draft("PRICE_GAP", "product:" + pid, f.name(pid) + " تقریباً بدون سود فروخته می‌شود", "قیمت خرید " + money(cost) + " و فروش " + money(sell) + " → حاشیهٔ " + fa(Math.round(margin * 1000) / 10.0) + "٪ با " + fa(Math.round(v * 70) / 10.0) + " فروش در هفته. پیشنهاد: قیمت " + money(np) + (cons > 0 ? " (مصرف‌کننده " + money(cons) + ")" : "") + "."); d.prio = 2; d.gain = (np - sell) * v * 30; d.ev = Local.obj("product_id", pid, "batch_id", b.optLong("id"), "buy", cost, "sell", sell, "consumer", cons, "margin", Math.round(margin * 1000) / 1000.0, "velocity", Math.round(v * 100) / 100.0); d.act("set_price", "اصلاح قیمت به " + money(np), "batch_id", b.optLong("id"), "sell_price", np); d.metric = Local.obj("metric", "product_profit", "product_id", pid, "window_days", 28); out.add(d); }
            else if (cons > 0 && sell > cons * 1.02 && v > 0) { Draft d = new Draft("PRICE_GAP", "over:" + pid, f.name(pid) + " بالاتر از قیمت مصرف‌کننده است", "فروش " + money(sell) + " در حالی که قیمت درج‌شده " + money(cons) + " است؛ ریسک شکایت و از دست دادن اعتماد. پیشنهاد: اصلاح به قیمت مصرف‌کننده."); d.prio = 1; d.ev = Local.obj("product_id", pid, "batch_id", b.optLong("id"), "sell", sell, "consumer", cons); d.act("set_price", "اصلاح به قیمت مصرف‌کننده", "batch_id", b.optLong("id"), "sell_price", cons); d.metric = Local.obj("metric", "product_units", "product_id", pid, "window_days", 28); out.add(d); } }
        out.sort((x, y) -> x.prio != y.prio ? x.prio - y.prio : Double.compare(y.gain, x.gain)); return out.subList(0, Math.min(6, out.size()));
    }

    /* ---- 10. loss prevention ---- */
    static List<Draft> lossPrev(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); String s60 = daysAgo(60); Map<String, int[]> by = new HashMap<>();
        for (JSONObject i : Local.rows("SELECT IFNULL(user,'—') AS u, status FROM invoices WHERE at>=?", s60)) { int[] a = by.computeIfAbsent(i.optString("u"), k -> new int[2]); a[0]++; if ("VOID".equals(i.optString("status"))) a[1]++; }
        if (by.size() < 2) return out; List<double[]> rates = new ArrayList<>(); JSONArray peers = new JSONArray(); for (Map.Entry<String, int[]> e : by.entrySet()) { if (e.getValue()[0] < 30) continue; double r = e.getValue()[1] / (double) e.getValue()[0]; rates.add(new double[]{r}); peers.put(Local.obj("name", e.getKey(), "sales", e.getValue()[0], "void_rate", Math.round(r * 1000) / 1000.0)); }
        if (rates.size() < 2) return out; List<Double> rs = new ArrayList<>(); for (double[] r : rates) rs.add(r[0]); java.util.Collections.sort(rs); double med = rs.get(rs.size() / 2);
        for (Map.Entry<String, int[]> e : by.entrySet()) { if (e.getValue()[0] < 30) continue; double r = e.getValue()[1] / (double) e.getValue()[0]; if (r > Math.max(0.02, med * 3) && r > med + 0.015) { Draft d = new Draft("LOSS_PREV", "user:" + e.getKey(), "الگوی غیرعادی در صندوق «" + e.getKey() + "»", "در ۶۰ روز اخیر: نرخ ابطال " + fa(Math.round(r * 1000) / 10.0) + "٪ (میانه " + fa(Math.round(med * 1000) / 10.0) + "٪). این لزوماً تقلب نیست (ممکن است آموزش یا مشتری خاص باشد)، اما ارزش یک گفت‌وگوی دوستانه و بررسی چند فاکتور باطل‌شده را دارد."); d.prio = 1; d.ev = Local.obj("user", e.getKey(), "void_rate", Math.round(r * 1000) / 1000.0, "median", Math.round(med * 1000) / 1000.0, "peers", peers); d.act("note", "ثبت یادداشت بررسی"); d.metric = Local.obj("metric", "void_rate", "user", e.getKey(), "window_days", 30); out.add(d); } }
        return out;
    }

    /* ---- 11. season / weekday ---- */
    static List<Draft> season(Frame f) throws Exception {
        List<Draft> out = new ArrayList<>(); if (f.inv.size() < 100) return out; double[] sum = new double[7]; Set<String>[] days = new Set[7]; for (int i = 0; i < 7; i++) days[i] = new HashSet<>();
        java.util.Calendar cal = java.util.Calendar.getInstance(); for (JSONObject i : f.inv.values()) { cal.setTimeInMillis(ms(i.optString("at"))); int wd = cal.get(java.util.Calendar.DAY_OF_WEEK) - 1; sum[wd] += i.optDouble("total"); days[wd].add(i.optString("at").substring(0, 10)); }
        String[] N = {"یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه"}; double[] avg = new double[7]; double tot = 0; int cnt = 0; JSONObject wk = new JSONObject(); for (int i = 0; i < 7; i++) { if (days[i].isEmpty()) continue; avg[i] = sum[i] / days[i].size(); tot += avg[i]; cnt++; wk.put(N[i], Math.round(avg[i])); } if (cnt < 5) return out; double mean = tot / cnt; int peak = 0; for (int i = 1; i < 7; i++) if (avg[i] > avg[peak]) peak = i; double idx = avg[peak] / mean; if (idx < 1.15) return out;
        int todayWd = java.util.Calendar.getInstance().get(java.util.Calendar.DAY_OF_WEEK) - 1; int ahead = (peak - todayWd + 7) % 7;
        Draft d = new Draft("SEASON", "peak:" + peak, N[peak] + "‌ها " + fa(Math.round((idx - 1) * 100)) + "٪ بیشتر از میانگین می‌فروشید", "میانگین فروش " + N[peak] + " " + money(avg[peak]) + " در برابر میانگین هفته " + money(mean) + ". پیشنهاد: تا " + fa(ahead) + " روز دیگر قفسه‌ها و موجودی کالاهای پرفروش را برای اوج آماده کنید.");
        d.prio = 3; d.ev = Local.obj("weekday_avg", wk, "peak", N[peak], "index", Math.round(idx * 100) / 100.0); d.act("note", "یادآوری آماده‌سازی روز اوج"); d.metric = Local.obj("metric", "weekday_sales", "weekday", peak, "window_days", 28); out.add(d); return out;
    }

    /* ============================ actions ============================ */
    static JSONObject accept(JSONObject row, JSONArray only) throws Exception {
        JSONObject spec = jo(row.optString("metric")); int wd = spec.optInt("window_days", 28); String now = Db.now();
        JSONObject first = Local.one("SELECT MIN(at) AS a FROM invoices"); if (first != null && !first.optString("a").isEmpty() && daysBetween(first.optString("a"), now) < wd) wd = Math.max(3, (int) daysBetween(first.optString("a"), now));
        JSONObject base = metric(spec, plusDays(now, -wd), now); base.put("window_days", wd); base.put("from", plusDays(now, -wd)); base.put("to", now);
        JSONArray executed = new JSONArray(); JSONArray acts = ja(row.optString("actions")); Set<String> onlySet = null; if (only != null) { onlySet = new HashSet<>(); for (int i = 0; i < only.length(); i++) onlySet.add(only.optString(i)); }
        for (int i = 0; i < acts.length(); i++) { JSONObject a = acts.optJSONObject(i); if (onlySet != null && !onlySet.contains(a.optString("type"))) continue; try { executed.put(Local.obj("type", a.optString("type"), "ok", true, "result", execute(row, a.optString("type"), a.optJSONObject("params") == null ? new JSONObject() : a.optJSONObject("params")))); } catch (Exception e) { executed.put(Local.obj("type", a.optString("type"), "ok", false, "error", String.valueOf(e.getMessage()))); } }
        Local.exec("UPDATE ai_insights SET status='ACCEPTED', accepted_at=?, baseline=? WHERE id=?", now, base.toString(), row.optLong("id"));
        Local.audit("INSIGHT_ACCEPTED", "Insight", String.valueOf(row.optLong("id")), null, row.optString("kind"));
        return Local.obj("baseline", base, "executed", executed);
    }

    static Object execute(JSONObject ins, String type, JSONObject p) throws Exception {
        String store = Prefs.get("store_name", "فروشگاه"); String now = Db.now();
        Object pro = InsightsPro.execute(ins, type, p); if (pro != null) return pro;   // v3.5
        switch (type) {
            case "shelf_note": { StringBuilder sb = new StringBuilder(); JSONArray ids = p.optJSONArray("products"); for (int i = 0; ids != null && i < ids.length(); i++) { JSONObject pr = Db.productById(ids.optLong(i)); if (pr != null) sb.append(i > 0 ? "، " : "").append(pr.optString("name")); } notify("کار انبار: تغییر چیدمان", "این کالاها را کنار هم بچینید: " + sb); return Local.obj("note", sb.toString()); }
            case "reorder_note": { JSONArray lst = new JSONArray(Local.setting("insights.reorder_list", "[]")); long pid = p.optLong("product_id"); boolean has = false; for (int i = 0; i < lst.length(); i++) if (lst.optJSONObject(i).optLong("product_id") == pid) has = true; if (!has) { JSONObject pr = Db.productById(pid); lst.put(Local.obj("product_id", pid, "name", pr == null ? String.valueOf(pid) : pr.optString("name"), "qty", p.opt("qty"), "added", now, "insight_id", ins.optLong("id"))); } Local.setSetting("insights.reorder_list", lst.toString()); return Local.obj("reorder_list", lst.length()); }
            case "set_min_stock": { long pid = p.optLong("product_id"); JSONObject pr = Db.productById(pid); if (pr == null) return Local.obj("skipped", "product"); Local.exec("UPDATE products SET min_stock_alert=? WHERE id=?", p.optInt("min_stock"), pid); Local.audit("INSIGHT_ACTION", "Product", String.valueOf(pid), pr.opt("min_stock_alert"), p.optInt("min_stock")); return Local.obj("min_stock_alert", p.optInt("min_stock")); }
            case "set_price": { long bid = p.optLong("batch_id"); JSONObject b = Local.one("SELECT * FROM batches WHERE id=?", bid); if (b == null) return Local.obj("skipped", "batch"); Local.exec("UPDATE batches SET sell_price=?, updated_at=? WHERE id=?", p.optDouble("sell_price"), now, bid); Local.exec("INSERT INTO price_history(product_id,price_type,price,effective_from) VALUES(?,?,?,?)", b.optLong("product_id"), "SELL", p.optDouble("sell_price"), now); Local.audit("INSIGHT_ACTION", "Batch", String.valueOf(bid), b.optDouble("sell_price"), p.optDouble("sell_price")); return Local.obj("sell_price", p.optDouble("sell_price")); }
            case "markdown_ladder": { long bid = p.optLong("batch_id"); JSONObject b = Local.one("SELECT * FROM batches WHERE id=?", bid); if (b == null) return Local.obj("skipped", "batch"); JSONArray plans = new JSONArray(Local.setting("insights.markdown_plans", "[]")); JSONArray keep = new JSONArray(); for (int i = 0; i < plans.length(); i++) if (plans.optJSONObject(i).optLong("batch_id") != bid) keep.put(plans.optJSONObject(i)); keep.put(Local.obj("batch_id", bid, "base_price", b.optDouble("sell_price"), "start", Jalali.todayIso(), "ladder", p.optJSONArray("ladder"), "applied", new JSONArray(), "insight_id", ins.optLong("id"))); Local.setSetting("insights.markdown_plans", keep.toString()); applyMarkdownSteps(); return Local.obj("plan", "saved"); }
            case "vip_coupons": case "winback_sms": { boolean vip = "vip_coupons".equals(type); JSONArray ids = p.optJSONArray("customer_ids"); int pct = p.optInt("percent", vip ? 5 : 10), days = p.optInt("days", vip ? 30 : 14); Local.exec("INSERT INTO campaigns(name,discount_type,discount_value,min_purchase,valid_until,status,created_at) VALUES(?,?,?,?,?,'ACTIVE',?)", vip ? "باشگاه VIP" : "بازگشت مشتری", "PERCENT", pct, 0, plusDays(now, days), now); int issued = 0, sent = 0;
                for (int i = 0; ids != null && i < ids.length(); i++) { JSONObject c = Local.one("SELECT * FROM customers WHERE id=?", ids.optLong(i)); if (c == null) continue; String code = (vip ? "VIP-" : "BACK-") + Long.toString(System.currentTimeMillis() % 100000000L + i * 7919L, 36).toUpperCase(); Local.exec("INSERT INTO coupons(code,discount_type,discount_value,min_purchase,customer_phone,valid_until,usage_limit,used_count,status,created_at) VALUES(?,?,?,?,?,?,1,0,'ACTIVE',?)", code, "PERCENT", pct, 0, c.optString("phone", null), plusDays(now, days), now); issued++; String ph = c.optString("phone"); if (!ph.isEmpty() && SmsLocal.configured()) { SmsLocal.enqueueAndSend(ph, vip ? (c.optString("name") + " عزیز، شما مشتری ویژهٔ " + store + " هستید. کد " + code + " = " + pct + "٪ تخفیف تا " + days + " روز. با سپاس از همراهی‌تان.") : (c.optString("name") + " عزیز، دلمان برایتان تنگ شده! " + store + " با کد " + code + " " + pct + "٪ تخفیف تا " + days + " روز منتظر شماست."), "coupon"); sent++; } }
                return Local.obj("coupons", issued, "sms", sent); }
            case "visit_sms": { int sent = 0; JSONArray cs = p.optJSONArray("customers"); if (SmsLocal.configured()) for (int i = 0; cs != null && i < cs.length(); i++) { JSONObject row = cs.optJSONObject(i); JSONObject c = Local.one("SELECT * FROM customers WHERE id=?", row.optLong("customer_id")); if (c == null || c.optString("phone").isEmpty()) continue; String item = row.optString("item"); SmsLocal.enqueueAndSend(c.optString("phone"), c.optString("name") + " عزیز، " + store + ": " + (item.isEmpty() ? "" : "«" + item + "» تازه رسیده و برایتان کنار گذاشته‌ایم؛ ") + "منتظر دیدارتان هستیم.", "campaign"); sent++; } return Local.obj("sms", sent); }
            case "sms_buyers": { long pid = p.optLong("product_id"); JSONObject pr = Db.productById(pid); int sent = 0; if (SmsLocal.configured()) for (JSONObject c : Local.rows("SELECT DISTINCT c.* FROM customers c JOIN invoices i ON i.customer_id=c.id JOIN invoice_items ii ON ii.inv=i.rowid WHERE ii.product_id=? AND i.at>=? AND c.phone IS NOT NULL AND c.phone<>''", pid, daysAgo(120))) { SmsLocal.enqueueAndSend(c.optString("phone"), c.optString("name") + " عزیز، «" + (pr == null ? "کالای موردعلاقهٔ شما" : pr.optString("name")) + "» این هفته در " + store + " با " + p.optInt("percent") + "٪ تخفیف. تا اتمام موجودی.", "campaign"); sent++; } return Local.obj("sms", sent); }
            case "bundle_campaign": { long pid = p.optLong("product_id"); JSONObject pr = Db.productById(pid); JSONObject pa = p.isNull("partner_id") ? null : Db.productById(p.optLong("partner_id")); String name = "باندل " + (pr == null ? "" : pr.optString("name")) + (pa == null ? "" : " + " + pa.optString("name")); Local.exec("INSERT INTO campaigns(name,discount_type,discount_value,min_purchase,valid_until,status,created_at) VALUES(?,?,?,?,?,'ACTIVE',?)", name, "PERCENT", p.optInt("percent", 15), 0, plusDays(now, 21), now); for (JSONObject b : Local.rows("SELECT * FROM batches WHERE product_id=? AND status='ACTIVE' AND current_qty>0", pid)) { double np = Math.max(b.optDouble("buy_price") * 1.01, Math.round(b.optDouble("sell_price") * (1 - p.optInt("percent", 15) / 100.0) / 100) * 100); Local.exec("UPDATE batches SET sell_price=?, updated_at=? WHERE id=?", np, now, b.optLong("id")); } notify("باندل ساخته شد", name + " — " + p.optInt("percent", 15) + "٪ تخفیف روی کالای راکد؛ آن را کنار کالای پرفروش بچینید."); return Local.obj("campaign", name); }
            case "flash_sale": { Local.exec("INSERT INTO campaigns(name,discount_type,discount_value,min_purchase,valid_until,status,created_at) VALUES(?,?,?,?,?,'ACTIVE',?)", "فروش ویژهٔ نقدینگی", "PERCENT", p.optInt("percent", 10), 0, plusDays(now, p.optInt("days", 3)), now); return Local.obj("campaign", "flash"); }
            case "debt_reminders": { int sent = 0; if (SmsLocal.configured()) for (JSONObject c : Local.rows("SELECT customer_id, SUM(CASE WHEN entry_type IN ('CHARGE','ADJUSTMENT_DEBIT') THEN amount ELSE -amount END) AS b FROM ledger GROUP BY customer_id")) if (c.optDouble("b") > 0.5) { JSONObject cu = Local.one("SELECT * FROM customers WHERE id=?", c.optLong("customer_id")); if (cu != null && !cu.optString("phone").isEmpty()) { SmsLocal.enqueueAndSend(cu.optString("phone"), Local.setting("sms.template.debt_reminder", "{customer} عزیز، بدهی شما به {store} {amount} {currency} است. لطفاً تسویه بفرمایید.").replace("{customer}", cu.optString("name")).replace("{store}", store).replace("{amount}", Ui.num(c.optDouble("b"))).replace("{currency}", Ui.currencyLabel), "debt"); sent++; } } return Local.obj("sms", sent); }
            case "enable_nudges": Local.setSetting("insights.pos_nudges", "true"); return Local.obj("pos_nudges", true);
            case "pos_nudge": { Local.setSetting("insights.pos_nudges", "true"); JSONArray extra = new JSONArray(Local.setting("insights.manual_rules", "[]")); long a = p.optLong("a"), b = p.optLong("b"); JSONObject pa = Db.productById(a), pb = Db.productById(b); for (long[] xy : new long[][]{{a, b}, {b, a}}) { boolean has = false; for (int i = 0; i < extra.length(); i++) if (extra.optJSONObject(i).optLong("if") == xy[0] && extra.optJSONObject(i).optLong("then") == xy[1]) has = true; if (!has) extra.put(Local.obj("if", xy[0], "then", xy[1], "if_name", (xy[0] == a ? pa : pb) == null ? "" : (xy[0] == a ? pa : pb).optString("name"), "then_name", (xy[1] == b ? pb : pa) == null ? "" : (xy[1] == b ? pb : pa).optString("name"), "confidence", 1.0, "lift", 1.0)); } Local.setSetting("insights.manual_rules", extra.toString()); return Local.obj("rules", extra.length()); }
            case "note": notify(ins.optString("title"), ins.optString("body").length() > 300 ? ins.optString("body").substring(0, 300) : ins.optString("body")); return Local.obj("noted", true);
        }
        throw new IllegalArgumentException("unknown action " + type);
    }

    static int applyMarkdownSteps() throws Exception {
        JSONArray plans = new JSONArray(Local.setting("insights.markdown_plans", "[]")); JSONArray keep = new JSONArray(); int changed = 0; String today = Jalali.todayIso();
        for (int i = 0; i < plans.length(); i++) { JSONObject plan = plans.optJSONObject(i); JSONObject b = Local.one("SELECT * FROM batches WHERE id=?", plan.optLong("batch_id")); if (b == null || !"ACTIVE".equals(b.optString("status")) || b.optDouble("current_qty") <= 0) continue; int day = (int) daysBetween(plan.optString("start") + "T00:00:00", today + "T00:00:00"); JSONArray ladder = plan.optJSONArray("ladder"), applied = plan.optJSONArray("applied"); JSONObject step = null; for (int k = 0; ladder != null && k < ladder.length(); k++) if (ladder.optJSONObject(k).optInt("from_day") <= day) step = ladder.optJSONObject(k);
            if (step != null) { boolean done = false; for (int k = 0; k < applied.length(); k++) if (applied.optInt(k) == step.optInt("percent")) done = true; if (!done) { double np = Math.max(Math.round(plan.optDouble("base_price") * (1 - step.optInt("percent") / 100.0) / 100) * 100, b.optDouble("buy_price") * 1.01); Local.exec("UPDATE batches SET sell_price=?, updated_at=? WHERE id=?", Math.round(np), Db.now(), b.optLong("id")); applied.put(step.optInt("percent")); changed++; JSONObject pr = Db.productById(b.optLong("product_id")); notify("تخفیف پله‌ای " + step.optInt("percent") + "٪ اعمال شد", (pr == null ? "" : pr.optString("name")) + " — قیمت جدید " + money(np)); } }
            if (applied.length() < (ladder == null ? 0 : ladder.length())) keep.put(plan); }
        Local.setSetting("insights.markdown_plans", keep.toString()); return changed;
    }

    /* ============================ measurement ============================ */
    static JSONObject metric(JSONObject spec, String start, String end) throws Exception {
        String m = spec.optString("metric"); String P = " i.status<>'VOID' AND i.at>=? AND i.at<? ";
        String PROFIT = "IFNULL(SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount),0)";
        switch (m) {
            case "product_units": { JSONObject r = Local.one("SELECT IFNULL(SUM(ii.qty),0) AS q, " + PROFIT + " AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P + "AND ii.product_id=?", start, end, spec.optLong("product_id")); return Local.obj("value", r.optDouble("q"), "unit", "عدد", "profit", r.optDouble("p")); }
            case "product_profit": { JSONObject r = Local.one("SELECT " + PROFIT + " AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P + "AND ii.product_id=?", start, end, spec.optLong("product_id")); return Local.obj("value", r.optDouble("p"), "unit", "تومان", "profit", r.optDouble("p")); }
            case "customer_sales": { String ids = idList(spec.optJSONArray("customer_ids")); JSONObject s = Local.one("SELECT IFNULL(SUM(total),0) AS s, IFNULL(SUM(discount),0) AS d FROM invoices i WHERE" + P + "AND customer_id IN (" + ids + ")", start, end); JSONObject r = Local.one("SELECT " + PROFIT + " AS p, IFNULL(SUM(ii.discount),0) AS ld FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P + "AND i.customer_id IN (" + ids + ")", start, end); return Local.obj("value", s.optDouble("s"), "unit", "تومان", "profit", r.optDouble("p") - Math.max(0, s.optDouble("d") - r.optDouble("ld"))); }
            case "attach_rate": { long a = spec.optLong("a"), b = spec.optLong("b"); Set<Long> ia = new HashSet<>(), ib = new HashSet<>(); for (JSONObject r : Local.rows("SELECT DISTINCT ii.inv FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P + "AND ii.product_id=?", start, end, a)) ia.add(r.optLong("inv")); for (JSONObject r : Local.rows("SELECT DISTINCT ii.inv FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P + "AND ii.product_id=?", start, end, b)) ib.add(r.optLong("inv")); Set<Long> both = new HashSet<>(ia); both.retainAll(ib); Set<Long> uni = new HashSet<>(ia); uni.addAll(ib); JSONObject r = Local.one("SELECT " + PROFIT + " AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P + "AND ii.product_id IN (?,?)", start, end, a, b); return Local.obj("value", Math.round(both.size() / (double) Math.max(1, uni.size()) * 1000) / 1000.0, "unit", "نرخ هم‌خرید", "profit", r.optDouble("p"), "both", both.size()); }
            case "avg_basket_size": { JSONObject s = Local.one("SELECT COUNT(*) AS n, IFNULL(SUM(total),0) AS s, IFNULL(SUM(discount),0) AS d FROM invoices i WHERE" + P, start, end); JSONObject r = Local.one("SELECT " + PROFIT + " AS p, IFNULL(SUM(ii.discount),0) AS ld FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P, start, end); int n = s.optInt("n"); return Local.obj("value", n == 0 ? 0 : Math.round(s.optDouble("s") / n), "unit", "تومان/فاکتور", "profit", r.optDouble("p") - Math.max(0, s.optDouble("d") - r.optDouble("ld")), "invoices", n); }
            case "receivables_collected": { JSONObject r = Local.one("SELECT IFNULL(SUM(amount),0) AS v FROM ledger WHERE entry_type IN ('PAYMENT','SETTLE','SETTLEMENT') AND created_at>=? AND created_at<?", start, end); return Local.obj("value", r.optDouble("v"), "unit", "تومان", "profit", 0); }
            case "void_rate": { JSONObject r = Local.one("SELECT COUNT(*) AS n, SUM(status='VOID') AS v FROM invoices WHERE IFNULL(user,'—')=? AND at>=? AND at<?", spec.optString("user"), start, end); return Local.obj("value", r.optInt("n") == 0 ? 0 : Math.round(r.optDouble("v") / r.optInt("n") * 1000) / 1000.0, "unit", "نرخ ابطال", "profit", 0); }
            case "weekday_sales": { double s = 0; java.util.Calendar cal = java.util.Calendar.getInstance(); for (JSONObject i : Local.rows("SELECT at, total FROM invoices i WHERE" + P, start, end)) { cal.setTimeInMillis(ms(i.optString("at"))); if (cal.get(java.util.Calendar.DAY_OF_WEEK) - 1 == spec.optInt("weekday")) s += i.optDouble("total"); } return Local.obj("value", s, "unit", "تومان", "profit", 0); }
            case "stockout_days": { long pid = spec.optLong("product_id"); Set<String> sold = new HashSet<>(); for (JSONObject r : Local.rows("SELECT DISTINCT substr(i.at,1,10) AS d FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P + "AND ii.product_id=?", start, end, pid)) sold.add(r.optString("d")); List<JSONObject> mv = Local.rows("SELECT created_at, quantity FROM movements WHERE product_id=? AND created_at<? ORDER BY created_at", pid, end); double bal = 0; int idx = 0, days = Math.max(1, (int) daysBetween(start, end)), outDays = 0; for (int k = 0; k < days; k++) { String day = plusDays(start, k).substring(0, 10); while (idx < mv.size() && mv.get(idx).optString("created_at").compareTo(day + "T99") <= 0) { bal += mv.get(idx).optDouble("quantity"); idx++; } if (bal <= 0.5 && !sold.contains(day)) outDays++; } double lost = outDays * spec.optDouble("margin_per_day", 0); return Local.obj("value", outDays, "unit", "روز بدون موجودی", "profit", -lost, "days", days); }
            case "availability": { long pid = spec.optLong("product_id"); Set<String> sold = new HashSet<>(); for (JSONObject r : Local.rows("SELECT DISTINCT substr(i.at,1,10) AS d FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P + "AND ii.product_id=?", start, end, pid)) sold.add(r.optString("d")); List<JSONObject> mv = Local.rows("SELECT created_at, quantity FROM movements WHERE product_id=? AND created_at<? ORDER BY created_at", pid, end); double bal = 0; int idx = 0, days = Math.max(1, (int) Math.round(daysBetween(start, end))), outDays = 0; for (int k = 0; k < days; k++) { String day = plusDays(start, k).substring(0, 10); while (idx < mv.size() && mv.get(idx).optString("created_at").compareTo(day + "T99") <= 0) { bal += mv.get(idx).optDouble("quantity"); idx++; } if (bal <= 0.5 && !sold.contains(day)) outDays++; }
                JSONObject r = Local.one("SELECT IFNULL(SUM(ii.qty),0) AS q, " + PROFIT + " AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE" + P + "AND ii.product_id=?", start, end, pid); return Local.obj("value", Math.round((days - outDays) * 1000.0 / days) / 10.0, "unit", "٪ روزهای موجود", "profit", r.optDouble("p"), "units", r.optDouble("q"), "stockout_days", outDays, "days", days); }
        }
        return Local.obj("value", 0, "unit", "—", "profit", 0);
    }

    /** v3.2 — daily profit of the measured slice, 14 days before acceptance + days since (for the chart). */
    static JSONObject dailySeries(JSONObject spec, String start, String end, JSONObject base) {
        String m = spec.optString("metric"); JSONArray before = new JSONArray(), after = new JSONArray();
        try {
            String bFrom = base.optString("from", plusDays(start, -14)); if (daysBetween(bFrom, start) > 14) bFrom = plusDays(start, -14);
            String where; Object[] args;
            if (m.matches("product_units|product_profit|availability|stockout_days")) { where = "ii.product_id=?"; args = new Object[]{bFrom, end, spec.optLong("product_id")}; }
            else if ("attach_rate".equals(m)) { where = "ii.product_id IN (?,?)"; args = new Object[]{bFrom, end, spec.optLong("a"), spec.optLong("b")}; }
            else if ("customer_sales".equals(m)) { where = "i.customer_id IN (" + idList(spec.optJSONArray("customer_ids")) + ")"; args = new Object[]{bFrom, end}; }
            else if ("avg_basket_size".equals(m)) { where = "1=1"; args = new Object[]{bFrom, end}; }
            else return Local.obj("before", before, "after", after);
            Map<String, Double> byDay = new HashMap<>();
            for (JSONObject r : Local.rows("SELECT substr(i.at,1,10) AS d, IFNULL(SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount),0) AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE i.status<>'VOID' AND i.at>=? AND i.at<? AND " + where + " GROUP BY substr(i.at,1,10)", args)) byDay.put(r.optString("d"), r.optDouble("p"));
            String startDay = start.substring(0, 10); int n = 0;
            for (String d = bFrom.substring(0, 10); d.compareTo(end.substring(0, 10)) <= 0 && n < 60; d = plusDays(d + "T12:00:00", 1).substring(0, 10), n++) { double v = Math.round(byDay.containsKey(d) ? byDay.get(d) : 0); if (d.compareTo(startDay) < 0) before.put(v); else after.put(v); }
        } catch (Exception ignore) {}
        return Local.obj("before", before, "after", after);
    }
    static String idList(JSONArray a) { StringBuilder sb = new StringBuilder(); for (int i = 0; a != null && i < a.length(); i++) sb.append(i > 0 ? "," : "").append(a.optLong(i)); return sb.length() == 0 ? "-1" : sb.toString(); }
    static double storeProfitRate(String start, String end) { JSONObject r = Local.one("SELECT IFNULL(SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount),0) AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE i.status<>'VOID' AND i.at>=? AND i.at<?", start, end); return r.optDouble("p") / Math.max(1e-9, daysBetween(start, end)); }

    static JSONObject measure(JSONObject row) throws Exception {
        if (!"ACCEPTED".equals(row.optString("status")) && !"MEASURED".equals(row.optString("status"))) return null;
        JSONObject spec = jo(row.optString("metric")); JSONObject base = jo(row.optString("baseline")); int wd = spec.optInt("window_days", 28); String start = row.optString("accepted_at"), now = Db.now(); String end = daysBetween(start, now) > wd ? plusDays(start, wd) : now; double elapsed = Math.max(1e-9, daysBetween(start, end));
        JSONObject post = metric(spec, start, end); double baseDays = Math.max(1e-9, base.optDouble("window_days", wd)); String unit = post.optString("unit"); boolean enough = elapsed >= 1.0; String m = spec.optString("metric");
        double ctrl = 1.0; if (m.matches("product_units|product_profit|customer_sales|attach_rate|receivables_collected|weekday_sales|availability")) { double sb = storeProfitRate(base.optString("from", plusDays(start, -baseDays)), start), sp = storeProfitRate(start, end); if (sb > 0 && sp > 0) ctrl = Math.max(0.5, Math.min(2.0, sp / sb)); }
        double baseRate, postRate, raw, adj; Double change = null;
        if ("avg_basket_size".equals(m)) { int bi = Math.max(1, base.optInt("invoices", 1)), pi = Math.max(1, post.optInt("invoices", 1)); baseRate = base.optDouble("profit") / bi; postRate = post.optDouble("profit") / pi; raw = adj = (postRate - baseRate) * pi; if (baseRate != 0) change = Math.round((postRate - baseRate) / baseRate * 1000) / 10.0; }
        else { if ("تومان".equals(unit) && base.optDouble("profit") == 0 && post.optDouble("profit") == 0) { baseRate = base.optDouble("value") / baseDays; postRate = post.optDouble("value") / elapsed; } else { baseRate = base.optDouble("profit") / baseDays; postRate = post.optDouble("profit") / elapsed; } raw = (postRate - baseRate) * elapsed; adj = (postRate - baseRate * ctrl) * elapsed; double bv = base.optDouble("value"), pv = post.optDouble("value"); if (bv != 0) change = Math.round(((pv / elapsed) - (bv / baseDays)) / (bv / baseDays) * 1000) / 10.0; }
        JSONObject res = new JSONObject(post.toString()); res.put("window_days", wd); res.put("elapsed_days", Math.round(elapsed * 10) / 10.0); res.put("from", start); res.put("to", end); res.put("enough_data", enough); res.put("change_pct", change == null ? JSONObject.NULL : change); res.put("control_ratio", Math.round(ctrl * 1000) / 1000.0); res.put("raw_gain", Math.round(raw)); res.put("adjusted_gain", Math.round(adj)); res.put("projected_month", enough ? Math.round(adj / elapsed * 30) : JSONObject.NULL);
        res.put("profit_pct", baseRate != 0 ? Math.round((postRate - baseRate) / Math.abs(baseRate) * 1000) / 10.0 : JSONObject.NULL); res.put("profit_pct_adj", baseRate != 0 ? Math.round((postRate - baseRate * ctrl) / Math.abs(baseRate * ctrl) * 1000) / 10.0 : JSONObject.NULL);
        res.put("base_value", base.opt("value")); res.put("post_value", post.opt("value")); res.put("base_profit_per_day", Math.round(baseRate)); res.put("post_profit_per_day", Math.round(postRate)); res.put("daily", dailySeries(spec, start, end, base));
        String st = elapsed >= wd - 0.01 ? "MEASURED" : "ACCEPTED";
        if (enough) Local.exec("UPDATE ai_insights SET result=?, measured_gain=?, measured_at=?, status=? WHERE id=?", res.toString(), Math.round(adj), now, st, row.optLong("id")); else Local.exec("UPDATE ai_insights SET result=?, measured_gain=NULL, measured_at=?, status=? WHERE id=?", res.toString(), now, st, row.optLong("id"));
        if ("MEASURED".equals(st) && !"MEASURED".equals(row.optString("status"))) { try { Forecast.learn(); } catch (Exception ignore) {} }   // v3.1: the engine learns from every completed measurement
        return Local.obj("baseline", base, "post", post, "gain", enough ? Math.round(adj) : 0, "complete", "MEASURED".equals(st));
    }
    static int measureAll() { int n = 0; for (JSONObject r : Local.rows("SELECT * FROM ai_insights WHERE status='ACCEPTED'")) { try { if (measure(r) != null) n++; } catch (Exception ignore) {} } return n; }

    static JSONObject summary() throws Exception {
        ensure(); List<JSONObject> rows = Local.rows("SELECT * FROM ai_insights WHERE status IN ('ACCEPTED','MEASURED') ORDER BY accepted_at DESC"); double total = 0, month = 0; Map<String, Double> byKind = new HashMap<>(); String now = Db.now(), m0 = daysAgo(30);
        for (JSONObject r : rows) { double g = r.isNull("measured_gain") ? 0 : r.optDouble("measured_gain"); total += g; byKind.merge(r.optString("kind"), g, Double::sum); if (g == 0) continue; JSONObject res = jo(r.optString("result")); String acc = r.optString("accepted_at"), end = res.optString("to", now); if (end.isEmpty() || end.compareTo(now) > 0) end = now; double span = Math.max(1e-9, daysBetween(acc, end)), overlap = Math.max(0, daysBetween(acc.compareTo(m0) > 0 ? acc : m0, end)); month += g * Math.min(1.0, overlap / span); }
        List<JSONObject> top = new ArrayList<>(rows); top.sort((a, b) -> Double.compare(b.isNull("measured_gain") ? 0 : b.optDouble("measured_gain"), a.isNull("measured_gain") ? 0 : a.optDouble("measured_gain")));
        JSONArray topA = new JSONArray(); for (JSONObject r : top.subList(0, Math.min(5, top.size()))) topA.put(Local.obj("id", r.optLong("id"), "kind", r.optString("kind"), "label", label(r.optString("kind")), "title", r.optString("title"), "gain", r.isNull("measured_gain") ? 0 : Math.round(r.optDouble("measured_gain")), "status", r.optString("status"), "accepted_at", r.optString("accepted_at")));
        List<Map.Entry<String, Double>> bk = new ArrayList<>(byKind.entrySet()); bk.sort((a, b) -> Double.compare(b.getValue(), a.getValue())); JSONArray bkA = new JSONArray(); for (Map.Entry<String, Double> e : bk) bkA.put(Local.obj("kind", e.getKey(), "label", label(e.getKey()), "gain", Math.round(e.getValue())));
        JSONObject open = Local.one("SELECT COUNT(*) AS n, IFNULL(SUM(expected_gain),0) AS g FROM ai_insights WHERE status='NEW'"); JSONObject mp = Local.one("SELECT IFNULL(SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount),0) AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE i.status<>'VOID' AND i.at>=?", m0);
        int measured = 0; for (JSONObject r : rows) if ("MEASURED".equals(r.optString("status"))) measured++;
        return Local.obj("accepted", rows.size(), "measured", measured, "open", open.optInt("n"), "total_gain", Math.round(total), "month_gain", Math.round(month), "expected_open", Math.round(open.optDouble("g")), "month_profit", Math.round(mp.optDouble("p")), "share_of_month_profit", mp.optDouble("p") > 0 ? Math.round(month / mp.optDouble("p") * 1000) / 1000.0 : 0, "by_kind", bkA, "top", topA);
    }

    /* ============================ POS nudges ============================ */
    public static JSONArray nudges(JSONArray ids) throws Exception {
        JSONArray out = new JSONArray(); if (ids == null || ids.length() == 0 || !"true".equals(Local.setting("insights.pos_nudges", "false"))) return out; ensure();
        Set<Long> cart = new HashSet<>(); for (int i = 0; i < ids.length(); i++) cart.add(ids.optLong(i)); Set<Long> offered = new HashSet<>();
        JSONArray rules = new JSONArray(); JSONObject row = Local.one("SELECT evidence FROM ai_insights WHERE kind='BASKET_NUDGE' AND status IN ('ACCEPTED','MEASURED') ORDER BY id DESC LIMIT 1"); if (row != null) rules = jo(row.optString("evidence")).optJSONArray("rules"); if (rules == null) rules = new JSONArray(); JSONArray manual = new JSONArray(Local.setting("insights.manual_rules", "[]")); for (int i = 0; i < manual.length(); i++) rules.put(manual.optJSONObject(i));
        for (int i = 0; i < rules.length() && out.length() < 2; i++) { JSONObject r = rules.optJSONObject(i); if (cart.contains(r.optLong("if")) && !cart.contains(r.optLong("then")) && !offered.contains(r.optLong("then"))) { offered.add(r.optLong("then")); out.put(Local.obj("product_id", r.optLong("then"), "name", r.optString("then_name"), "because", r.optString("if_name"), "confidence", r.optDouble("confidence"))); } }
        return out;
    }

    /* ============================ narrative ============================ */
    static String localNarrative(JSONObject ins) { StringBuilder sb = new StringBuilder(ins.optString("body").trim()); JSONArray acts = ja(ins.optString("actions")); if (acts.length() > 0) { sb.append("\nاقدام‌های پیشنهادی:"); for (int i = 0; i < acts.length(); i++) sb.append("\n• ").append(acts.optJSONObject(i).optString("label")); } if (ins.optDouble("expected_gain") > 0) sb.append("\nبرآورد اثر: حدود ").append(money(ins.optDouble("expected_gain"))).append(" در ماه."); return sb.toString(); }
    static String weekly(JSONObject s, JSONArray open) { StringBuilder sb = new StringBuilder("این هفته " + fa(s.optInt("accepted")) + " پیشنهاد اجرا شده و اثر اندازه‌گیری‌شدهٔ آن‌ها " + money(s.optDouble("total_gain")) + " است" + (s.optDouble("share_of_month_profit") > 0 ? " (" + fa(Math.round(s.optDouble("share_of_month_profit") * 100)) + "٪ سود این ماه)." : ".")); if (open.length() > 0) { sb.append("\n").append(fa(open.length())).append(" پیشنهاد باز دارید؛ مهم‌ترین‌ها:"); double exp = 0; for (int i = 0; i < open.length(); i++) { if (i < 5) sb.append("\n• ").append(open.optJSONObject(i).optString("title")); exp += open.optJSONObject(i).optDouble("expected_gain"); } if (exp > 0) sb.append("\nاگر همه اجرا شوند، برآورد اثر حدود ").append(money(exp)).append(" در ماه است."); } sb.append("\nهر پیشنهاد را با یک لمس اجرا کنید؛ اثر واقعی آن به‌طور خودکار اندازه‌گیری می‌شود."); return sb.toString(); }

    static int nid = 3000;
    static void notify(String title, String text) { try { if (Ui.ctx != null) Notify.show(Ui.ctx, Notify.CH_SYSTEM, ++nid, title, text, "insights", null); } catch (Exception ignore) {} }

    /** background tick: called from the sync/alarm worker (every ~6 h) */
    public static void tick() { try { if (!"true".equals(Local.setting("insights.enabled", "true"))) return; String last = Local.setting("insights.last_run", ""); if (!last.isEmpty() && daysBetween(last, Db.now()) < 0.25) { applyMarkdownSteps(); return; } run(); for (JSONObject r : Local.rows("SELECT * FROM ai_insights WHERE status='NEW' AND priority=1 AND narrative IS NULL")) { notify("پیشنهاد فوری هوش فروشگاه", r.optString("title")); Local.exec("UPDATE ai_insights SET narrative='' WHERE id=?", r.optLong("id")); } } catch (Exception ignore) {} }
}
