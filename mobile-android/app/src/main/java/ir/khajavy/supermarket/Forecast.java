package ir.khajavy.supermarket;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * v3.1 — forecasting, planning and self-calibration on the phone (mirror of the Windows
 * {@code services/forecast.py}; same maths, same JSON contract, so {@link InsightScreens.Plan}
 * renders identical figures whether the data comes from the PC or from the phone's own SQLite).
 *
 *  • calibration: measured ÷ predicted per suggestion kind (EWMA + dispersion) — the engine
 *    learns from every executed action and tightens the band as evidence accumulates;
 *  • forecast: weekly linear trend × weekday index over the last 26 weeks of net profit;
 *  • plan: baseline vs. plan cumulative paths for the horizon, per-item calibrated gain,
 *    accuracy history.
 */
final class Forecast {
    private Forecast() {}
    static final String CAL_KEY = "insights.calibration";
    static final int RAMP = 7; static final double DECAY = 0.7, RMIN = 0.15, RMAX = 2.5;

    /* ---------------- calibration ---------------- */
    static JSONObject cal() { return Insights.jo(Local.setting(CAL_KEY, "{}")); }

    static JSONObject learn() throws Exception {
        JSONObject cal = new JSONObject();
        Map<String, double[]> st = new HashMap<>();   // kind → {ratio, n, var, abs_err, hits}
        for (JSONObject r : Local.rows("SELECT * FROM ai_insights WHERE status='MEASURED' AND measured_gain IS NOT NULL ORDER BY measured_at, id")) {
            JSONObject ev = Insights.jo(r.optString("evidence")); double raw = ev.optDouble("expected_gain_raw", r.optDouble("expected_gain")); if (raw <= 0) continue;
            double m = r.optDouble("measured_gain"), ratio = Math.max(RMIN, Math.min(RMAX, m / raw));
            double[] c = st.get(r.optString("kind")); if (c == null) { c = new double[]{ratio, 0, 0.25, Math.abs(m - raw), 0}; st.put(r.optString("kind"), c); }
            else { double err = ratio - c[0]; c[0] = DECAY * c[0] + (1 - DECAY) * ratio; c[2] = DECAY * c[2] + (1 - DECAY) * err * err; c[3] = DECAY * c[3] + (1 - DECAY) * Math.abs(m - raw); }
            c[1]++; if ((m > 0) == (raw > 0)) c[4]++;
        }
        for (Map.Entry<String, double[]> e : st.entrySet()) { double[] c = e.getValue(); cal.put(e.getKey(), Local.obj("ratio", Math.round(c[0] * 1000) / 1000.0, "n", (int) c[1], "sd", Math.round(Math.sqrt(Math.max(0, c[2])) * 1000) / 1000.0, "abs_err", Math.round(c[3]), "hits", (int) c[4], "direction_accuracy", Math.round(c[4] / c[1] * 100) / 100.0)); }
        Local.setSetting(CAL_KEY, cal.toString());
        return cal;
    }

    /** {gain, low, high, confidence, n, ratio} for a raw analyzer estimate of this kind. */
    static JSONObject calibrate(JSONObject cal, String kind, double raw) throws Exception {
        JSONObject c = cal.optJSONObject(kind);
        if (raw <= 0) return Local.obj("gain", 0, "low", 0, "high", 0, "confidence", "n/a", "n", c == null ? 0 : c.optInt("n"), "ratio", 1.0);
        if (c == null || c.optInt("n") == 0) return Local.obj("gain", Math.round(raw), "low", Math.round(raw * 0.4), "high", Math.round(raw * 1.4), "confidence", "low", "n", 0, "ratio", 1.0);
        int n = c.optInt("n"); double ratio = c.optDouble("ratio"), sd = c.optDouble("sd", 0.5), band = sd / Math.sqrt(n), lo = Math.max(0, ratio - band), hi = ratio + band;
        String conf = n >= 5 && band < 0.25 ? "high" : n >= 2 && band < 0.6 ? "medium" : "low";
        return Local.obj("gain", Math.round(raw * ratio), "low", Math.round(raw * lo), "high", Math.round(raw * hi), "confidence", conf, "n", n, "ratio", ratio);
    }

    /* ---------------- time series ---------------- */
    static final String PROFIT = "IFNULL(SUM((ii.unit_sell_price-ii.unit_buy_price)*ii.qty-ii.discount),0)";

    /** Daily net profit for the last {@code days} days (zero-filled), oldest first: [{day, profit}]. */
    static List<double[]> daily(int days) {
        TreeMap<String, Double> by = new TreeMap<>();
        for (JSONObject r : Local.rows("SELECT substr(i.at,1,10) AS d, " + PROFIT + " AS p FROM invoice_items ii JOIN invoices i ON i.rowid=ii.inv WHERE i.status<>'VOID' AND i.at>=? GROUP BY substr(i.at,1,10)", Insights.daysAgo(days))) by.put(r.optString("d"), r.optDouble("p"));
        List<double[]> out = new ArrayList<>(); String d0 = Insights.plusDays(Insights.daysAgo(days), 1).substring(0, 10);
        for (int i = 0; i < days; i++) { String d = Insights.plusDays(d0 + "T00:00:00", i).substring(0, 10); Double v = by.get(d); out.add(new double[]{weekday(d), v == null ? 0 : v}); }
        return out;
    }
    static int weekday(String isoDate) { try { java.util.Calendar c = java.util.Calendar.getInstance(); c.setTime(Insights.ISO.parse(isoDate + "T00:00:00")); int w = c.get(java.util.Calendar.DAY_OF_WEEK); return (w + 5) % 7; } catch (Exception e) { return 0; } }   // Monday = 0 like Python

    static final class Fit { double level, slopePerDay, r2; double[] weekday = {1, 1, 1, 1, 1, 1, 1}; int weeks; }

    static Fit fit(List<double[]> series) {
        Fit f = new Fit(); int n = series.size(); int pos = 0; double sum = 0; for (double[] p : series) { sum += p[1]; if (p[1] > 0) pos++; }
        if (n < 14 || pos < 7) { f.level = n == 0 ? 0 : sum / n; f.weeks = n / 7; return f; }
        List<Double> weeks = new ArrayList<>(); for (int i = 0; i + 7 <= n - n % 7; i += 7) { double s = 0; for (int k = i; k < i + 7; k++) s += series.get(k)[1]; weeks.add(s); }
        double slopeW, levelW, r2 = 0;
        if (weeks.size() >= 3) {
            int m = weeks.size(); double mx = (m - 1) / 2.0, my = 0; for (double w : weeks) my += w; my /= m; double sxx = 0, sxy = 0; for (int i = 0; i < m; i++) { sxx += (i - mx) * (i - mx); sxy += (i - mx) * (weeks.get(i) - my); }
            slopeW = sxy / (sxx == 0 ? 1 : sxx); slopeW = Math.max(-0.015 * my, Math.min(0.015 * my, slopeW));
            double ssRes = 0, ssTot = 0; for (int i = 0; i < m; i++) { double fit = my + slopeW * (i - mx); ssRes += (weeks.get(i) - fit) * (weeks.get(i) - fit); ssTot += (weeks.get(i) - my) * (weeks.get(i) - my); }
            r2 = Math.max(0, 1 - ssRes / (ssTot == 0 ? 1 : ssTot)); levelW = my + slopeW * (m - 1 - mx);
        } else { slopeW = 0; double s = 0; for (double w : weeks) s += w; levelW = s / weeks.size(); }
        // weekday index from the last 8 weeks
        int from = Math.max(0, n - 56); double[] ws = new double[7]; int[] wc = new int[7]; double all = 0; int cnt = 0;
        for (int i = from; i < n; i++) { double[] p = series.get(i); ws[(int) p[0]] += p[1]; wc[(int) p[0]]++; all += p[1]; cnt++; }
        double mean = cnt == 0 ? 0 : all / cnt; double s7 = 0; for (int w = 0; w < 7; w++) { f.weekday[w] = wc[w] > 0 && mean > 0 ? (ws[w] / wc[w]) / mean : 1.0; s7 += f.weekday[w]; } for (int w = 0; w < 7; w++) f.weekday[w] /= (s7 / 7 == 0 ? 1 : s7 / 7);
        f.level = levelW / 7; f.slopePerDay = slopeW / 49; f.r2 = Math.round(r2 * 1000) / 1000.0; f.weeks = weeks.size(); return f;
    }

    /* ---------------- plan ---------------- */
    static JSONObject plan(int horizon) throws Exception {
        JSONObject cal = cal(); List<double[]> hist = daily(182); Fit f = fit(hist); String today = Db.now().substring(0, 10);
        JSONArray items = new JSONArray(); double planDay = 0, lowDay = 0, highDay = 0; Map<String, double[]> byKind = new HashMap<>();
        for (JSONObject r : Local.rows("SELECT * FROM ai_insights WHERE status='NEW' ORDER BY priority, expected_gain DESC")) {
            JSONObject ev = Insights.jo(r.optString("evidence")); double raw = ev.optDouble("expected_gain_raw", r.optDouble("expected_gain")); JSONObject c = calibrate(cal, r.optString("kind"), raw);
            items.put(Local.obj("id", r.optLong("id"), "kind", r.optString("kind"), "label", Insights.label(r.optString("kind")), "title", r.optString("title"), "priority", r.optInt("priority"), "raw_gain", Math.round(raw),
                    "gain_month", c.optLong("gain"), "low_month", c.optLong("low"), "high_month", c.optLong("high"), "confidence", c.optString("confidence"), "history_n", c.optInt("n"), "gain_horizon", Math.round(c.optDouble("gain") / 30 * Math.max(0, horizon - RAMP / 2.0))));
            planDay += c.optDouble("gain") / 30; lowDay += c.optDouble("low") / 30; highDay += c.optDouble("high") / 30;
            double[] k = byKind.get(r.optString("kind")); if (k == null) { k = new double[4]; byKind.put(r.optString("kind"), k); } k[0]++; k[1] += c.optDouble("gain"); k[2] += c.optDouble("low"); k[3] += c.optDouble("high");
        }
        JSONArray histWeeks = new JSONArray(); int n = hist.size(); String d0 = Insights.plusDays(Insights.daysAgo(182), 1).substring(0, 10);
        for (int i = 0; i + 7 <= n - n % 7; i += 7) { double s = 0; for (int k = i; k < i + 7; k++) s += hist.get(k)[1]; histWeeks.put(Local.obj("week_start", Insights.plusDays(d0 + "T00:00:00", i).substring(0, 10), "profit", Math.round(s))); }
        JSONArray fc = new JSONArray(); double cb = 0, cp = 0, cl = 0, ch = 0;
        for (int d = 1; d <= horizon; d++) {
            String day = Insights.plusDays(today + "T00:00:00", d).substring(0, 10); double base = Math.max(0, (f.level + f.slopePerDay * d) * f.weekday[weekday(day)]); double ramp = Math.min(1.0, d / (double) RAMP);
            cb += base; cp += base + planDay * ramp; cl += base + lowDay * ramp; ch += base + highDay * ramp;
            if (d % 7 == 0 || d == horizon) fc.put(Local.obj("day", day, "cum_baseline", Math.round(cb), "cum_plan", Math.round(cp), "cum_low", Math.round(cl), "cum_high", Math.round(ch), "week_baseline", Math.round(base * 7), "week_plan", Math.round((base + planDay * ramp) * 7)));
        }
        List<Map.Entry<String, double[]>> bk = new ArrayList<>(byKind.entrySet()); bk.sort((a, b) -> Double.compare(b.getValue()[1], a.getValue()[1])); JSONArray bkA = new JSONArray();
        for (Map.Entry<String, double[]> e : bk) bkA.put(Local.obj("kind", e.getKey(), "label", Insights.label(e.getKey()), "count", (int) e.getValue()[0], "gain_month", Math.round(e.getValue()[1]), "low_month", Math.round(e.getValue()[2]), "high_month", Math.round(e.getValue()[3])));
        long monthBase = Math.round(f.level * 30), planMonth = Math.round(planDay * 30);
        JSONArray acc = new JSONArray(); int hits = 0; double mapeSum = 0; int mapeN = 0;
        for (JSONObject r : Local.rows("SELECT * FROM ai_insights WHERE status='MEASURED' AND measured_gain IS NOT NULL ORDER BY measured_at DESC LIMIT 40")) {
            JSONObject ev = Insights.jo(r.optString("evidence")); long pred = Math.round(ev.optDouble("expected_gain_raw", r.optDouble("expected_gain"))), calb = Math.round(r.optDouble("expected_gain")), meas = Math.round(r.optDouble("measured_gain"));
            acc.put(Local.obj("id", r.optLong("id"), "kind", r.optString("kind"), "label", Insights.label(r.optString("kind")), "title", r.optString("title"), "predicted", pred, "calibrated", calb, "measured", meas, "measured_at", r.optString("measured_at")));
            if ((meas > 0) == (pred > 0)) hits++; if (calb != 0) { mapeSum += Math.abs(meas - calb) / (double) Math.abs(calb); mapeN++; }
        }
        JSONArray calA = new JSONArray(); java.util.Iterator<String> it = cal.keys(); List<String> ks = new ArrayList<>(); while (it.hasNext()) ks.add(it.next()); java.util.Collections.sort(ks);
        for (String k : ks) { JSONObject c = new JSONObject(cal.optJSONObject(k).toString()); c.put("kind", k); c.put("label", Insights.label(k)); calA.put(c); }
        JSONArray wd = new JSONArray(); for (double w : f.weekday) wd.put(Math.round(w * 100) / 100.0);
        JSONObject model = Local.obj("weeks_of_history", f.weeks, "trend_pct_per_week", f.level > 0 ? Math.round(f.slopePerDay * 7 / f.level * 10000) / 100.0 : 0, "fit_r2", f.r2, "weekday_index", wd, "calibration", calA,
                "measured_count", acc.length(), "direction_accuracy", acc.length() == 0 ? JSONObject.NULL : Math.round(hits * 100.0 / acc.length()) / 100.0, "mean_abs_pct_error", mapeN == 0 ? JSONObject.NULL : Math.round(mapeSum / mapeN * 100));
        return Local.obj("generated_at", Db.now(), "horizon_days", horizon, "model", model,
                "baseline", Local.obj("profit_per_day", Math.round(f.level), "profit_month", monthBase, "profit_horizon", Math.round(cb)),
                "plan", Local.obj("open", items.length(), "gain_month", planMonth, "low_month", Math.round(lowDay * 30), "high_month", Math.round(highDay * 30), "gain_horizon", Math.round(cp - cb), "profit_month", monthBase + planMonth, "profit_horizon", Math.round(cp), "growth_pct", monthBase == 0 ? JSONObject.NULL : Math.round(planMonth * 1000.0 / monthBase) / 10.0),
                "items", items, "by_kind", bkA, "history_weeks", histWeeks, "forecast", fc, "accuracy", acc);
    }

    /** Detail block for one open suggestion: what happens to profit if it is executed. */
    static JSONObject predictFor(JSONObject row) throws Exception {
        JSONObject cal = cal(); JSONObject ev = Insights.jo(row.optString("evidence")); double raw = ev.optDouble("expected_gain_raw", row.optDouble("expected_gain")); JSONObject c = calibrate(cal, row.optString("kind"), raw);
        Fit f = fit(daily(91)); double monthBase = f.level * 30, gain = c.optDouble("gain"); JSONArray path = new JSONArray(); double cum = 0;
        for (int d = 1; d < 91; d++) { cum += gain / 30 * Math.min(1.0, d / (double) RAMP); if (d % 15 == 0) path.put(Local.obj("day", d, "cum_gain", Math.round(cum), "cum_low", Math.round(gain == 0 ? 0 : cum * c.optDouble("low") / gain), "cum_high", Math.round(gain == 0 ? 0 : cum * c.optDouble("high") / gain))); }
        return Local.obj("raw_gain_month", Math.round(raw), "gain_month", Math.round(gain), "low_month", c.optLong("low"), "high_month", c.optLong("high"), "confidence", c.optString("confidence"), "history_n", c.optInt("n"), "ratio", c.optDouble("ratio"),
                "store_profit_month", Math.round(monthBase), "growth_pct", monthBase == 0 ? JSONObject.NULL : Math.round(gain / monthBase * 1000) / 10.0, "gain_90d", Math.round(cum), "path", path);
    }
}
