package ir.khajavy.supermarket;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.view.View;

import java.util.ArrayList;
import java.util.List;

/**
 * v3.1 — tiny dependency-free charts for the planning screens (line with optional confidence
 * band + horizontal bars). Calm palette, Vazirmatn labels, Persian digits.
 */
final class Chart {
    private Chart() {}

    /**
     * v3.5.9 — hard limits. A bars view is {@code 30dp} tall per row, so an unbounded row count
     * produces a view taller than the Android canvas limit (it renders blank or throws) and makes
     * every {@code onDraw} walk the whole list — that is what hung «هوش فروشگاه» on a store with
     * many suppliers/cashiers. Callers may still pass a long list; it is trimmed here.
     */
    static final int MAX_BARS = 40;
    static final int[] FALLBACK = {0xFF1F8C78, 0xFF7B6ED0, 0xFFD8952E, 0xFFD3505B, 0xFF2FA872, 0xFF3B82F6, 0xFFC2479B, 0xFF0EA5E9};

    /** Null- and size-safe colour lookup: a short or null colour list must not crash the draw. */
    static int colorAt(List<Integer> colors, int i) {
        return colors != null && i >= 0 && i < colors.size() && colors.get(i) != null ? colors.get(i) : FALLBACK[Math.abs(i) % FALLBACK.length];
    }
    static String labelAt(List<String> labels, int i) {
        return labels != null && i >= 0 && i < labels.size() && labels.get(i) != null ? labels.get(i) : "";
    }

    static final class Series { final String name; final int color; final double[] pts; final boolean dashed, area; Series(String n, int c, double[] p, boolean d, boolean a) { name = n; color = c; pts = p; dashed = d; area = a; } }

    /** Line chart. {@code labels} may contain nulls to skip; {@code lo/hi} draw a translucent band. */
    static View line(Context c, List<Series> series, String[] labels, double[] lo, double[] hi, int heightDp) {
        View v = new View(c) {
            final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG), t = new Paint(Paint.ANTI_ALIAS_FLAG);
            { t.setTextSize(Ui.dp(10)); t.setTypeface(Ui.FONT); t.setColor(Ui.MUTED); }
            @Override protected void onDraw(Canvas cv) {
                float W = getWidth(), H = getHeight(), L = Ui.dp(6), R = Ui.dp(6), T = Ui.dp(10), B = Ui.dp(22);
                double max = 1, min = 0; int n = 2;
                for (Series s : series) { for (double d : s.pts) if (!Double.isNaN(d)) { max = Math.max(max, d); min = Math.min(min, d); } n = Math.max(n, s.pts.length); }
                if (hi != null) for (double d : hi) if (!Double.isNaN(d)) max = Math.max(max, d);
                final double fmax = max, fmin = min; final int fn = n;
                // grid
                p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(1); p.setColor(Ui.BORDER); p.setPathEffect(null);
                for (int g = 0; g <= 4; g++) { double val = fmin + (fmax - fmin) * g / 4; float y = y(val, fmin, fmax, T, H - B); cv.drawLine(L, y, W - R, y, p); t.setTextAlign(Paint.Align.RIGHT); cv.drawText(Ui.moneyShort(val), W - R, y - Ui.dp(2), t); }
                // band
                if (lo != null && hi != null && lo.length == hi.length && lo.length > 1) {
                    Path b = new Path(); boolean started = false;
                    for (int i = 0; i < hi.length; i++) { if (Double.isNaN(hi[i])) continue; float x = x(i, fn, L, W - R), y = y(hi[i], fmin, fmax, T, H - B); if (!started) { b.moveTo(x, y); started = true; } else b.lineTo(x, y); }
                    for (int i = lo.length - 1; i >= 0; i--) { if (Double.isNaN(lo[i])) continue; b.lineTo(x(i, fn, L, W - R), y(lo[i], fmin, fmax, T, H - B)); }
                    b.close(); p.setStyle(Paint.Style.FILL); p.setColor((Ui.VIOLET & 0x00FFFFFF) | 0x22000000); cv.drawPath(b, p);
                }
                // series
                for (Series s : series) {
                    Path path = new Path(); boolean started = false; int first = -1, last = -1;
                    for (int i = 0; i < s.pts.length; i++) { if (Double.isNaN(s.pts[i])) continue; float x = x(i, fn, L, W - R), y = y(s.pts[i], fmin, fmax, T, H - B); if (!started) { path.moveTo(x, y); started = true; first = i; } else path.lineTo(x, y); last = i; }
                    if (!started) continue;
                    if (s.area && last > first) { Path a = new Path(path); a.lineTo(x(last, fn, L, W - R), y(fmin, fmin, fmax, T, H - B)); a.lineTo(x(first, fn, L, W - R), y(fmin, fmin, fmax, T, H - B)); a.close(); p.setStyle(Paint.Style.FILL); p.setPathEffect(null); p.setColor((s.color & 0x00FFFFFF) | 0x16000000); cv.drawPath(a, p); }
                    p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(Ui.dp(s.dashed ? 1.6f : 2.4f)); p.setStrokeCap(Paint.Cap.ROUND); p.setStrokeJoin(Paint.Join.ROUND); p.setColor(s.color);
                    p.setPathEffect(s.dashed ? new android.graphics.DashPathEffect(new float[]{Ui.dp(6), Ui.dp(5)}, 0) : null); cv.drawPath(path, p);
                }
                p.setPathEffect(null);
                // x labels
                t.setTextAlign(Paint.Align.CENTER);
                if (labels != null) for (int i = 0; i < labels.length; i++) if (labels[i] != null) cv.drawText(labels[i], x(i, fn, L, W - R), H - Ui.dp(6), t);
            }
            float x(int i, int n, float l, float r) { return n <= 1 ? l : l + (r - l) * i / (n - 1); }
            float y(double v, double min, double max, float top, float bottom) { return (float) (top + (bottom - top) * (1 - (v - min) / (max - min == 0 ? 1 : max - min))); }
        };
        v.setLayoutParams(Ui.lp(android.view.ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(heightDp)));
        return v;
    }

    /** Legend row for a line chart. */
    static View legend(Context c, List<Series> series) {
        android.widget.LinearLayout r = Ui.row(c); r.setPadding(0, Ui.dp(6), 0, 0);
        for (Series s : series) { android.widget.LinearLayout it = Ui.row(c); it.setGravity(android.view.Gravity.CENTER_VERTICAL); it.setPadding(0, 0, Ui.dp(14), 0); View sw = new View(c); sw.setBackground(Ui.rounded(s.color, 0, 2)); sw.setLayoutParams(Ui.lp(Ui.dp(14), Ui.dp(4))); it.addView(sw); android.widget.TextView tv = Ui.muted(c, " " + s.name); tv.setTextSize(11); it.addView(tv); r.addView(it); }
        return r;
    }

    /** Horizontal bars: label on the right, value text on the left of the bar. */
    static View bars(Context c, List<String> labels, List<Double> values, List<Integer> colors) {
        final int rowH = Ui.dp(30);
        final int n = Math.min(values.size(), MAX_BARS);   // v3.5.9 — bounded view height + bounded draw
        View v = new View(c) {
            final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG), t = new Paint(Paint.ANTI_ALIAS_FLAG);
            { t.setTextSize(Ui.dp(11)); t.setTypeface(Ui.FONT); }
            @Override protected void onDraw(Canvas cv) {
                float W = getWidth(); double max = 1; for (int i = 0; i < n; i++) max = Math.max(max, Math.abs(values.get(i)));
                float lw = W * 0.42f;
                for (int i = 0; i < n; i++) {
                    float y = i * rowH + Ui.dp(5); double val = values.get(i); float w = (float) ((W - lw - Ui.dp(70)) * Math.abs(val) / max);
                    t.setColor(Ui.TEXT); t.setTextAlign(Paint.Align.RIGHT); cv.drawText(ellipsize(labelAt(labels, i), lw - Ui.dp(6)), W - Ui.dp(2), y + Ui.dp(14), t);
                    p.setStyle(Paint.Style.FILL); p.setColor(val >= 0 ? colorAt(colors, i) : Ui.RED);
                    android.graphics.RectF rc = new android.graphics.RectF(W - lw - Ui.dp(8) - w, y, W - lw - Ui.dp(8), y + Ui.dp(20)); cv.drawRoundRect(rc, Ui.dp(6), Ui.dp(6), p);
                    t.setColor(Ui.MUTED); cv.drawText(Ui.moneyShort(val), W - lw - Ui.dp(12) - w, y + Ui.dp(14), t);
                }
                if (values.size() > n) { t.setColor(Ui.MUTED); t.setTextAlign(Paint.Align.RIGHT); cv.drawText("… " + Ui.fa(String.valueOf(values.size() - n)) + " مورد دیگر", W - Ui.dp(2), n * rowH + Ui.dp(16), t); }
            }
            String ellipsize(String s, float maxW) { if (s == null || s.isEmpty() || maxW <= 0) return s == null ? "" : s; if (t.measureText(s) <= maxW) return s; while (s.length() > 3 && t.measureText(s + "…") > maxW) s = s.substring(0, s.length() - 1); return s + "…"; }
        };
        v.setLayoutParams(Ui.lp(android.view.ViewGroup.LayoutParams.MATCH_PARENT, rowH * Math.max(1, n) + Ui.dp(values.size() > n ? 26 : 10)));
        return v;
    }

    /** v3.2 — horizontal bars with a custom unit label (counts, percents) instead of money. */
    static View bars(Context c, List<String> labels, List<Double> values, List<Integer> colors, String unit) {
        final int rowH = Ui.dp(30);
        final int n = Math.min(values.size(), MAX_BARS);   // v3.5.9 — bounded view height + bounded draw
        View v = new View(c) {
            final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG), t = new Paint(Paint.ANTI_ALIAS_FLAG);
            { t.setTextSize(Ui.dp(11)); t.setTypeface(Ui.FONT); }
            @Override protected void onDraw(Canvas cv) {
                float W = getWidth(); double max = 1; for (int i = 0; i < n; i++) max = Math.max(max, Math.abs(values.get(i)));
                float lw = W * 0.42f;
                for (int i = 0; i < n; i++) {
                    float y = i * rowH + Ui.dp(5); double val = values.get(i); float w = (float) ((W - lw - Ui.dp(70)) * Math.abs(val) / max);
                    t.setColor(Ui.TEXT); t.setTextAlign(Paint.Align.RIGHT); String lb = labelAt(labels, i); while (lb.length() > 3 && t.measureText(lb + "…") > lw - Ui.dp(6)) lb = lb.substring(0, lb.length() - 1); if (!lb.equals(labelAt(labels, i))) lb += "…"; cv.drawText(lb, W - Ui.dp(2), y + Ui.dp(14), t);
                    p.setStyle(Paint.Style.FILL); p.setColor(val >= 0 ? colorAt(colors, i) : Ui.RED);
                    android.graphics.RectF rc = new android.graphics.RectF(W - lw - Ui.dp(8) - w, y, W - lw - Ui.dp(8), y + Ui.dp(20)); cv.drawRoundRect(rc, Ui.dp(6), Ui.dp(6), p);
                    t.setColor(Ui.MUTED); cv.drawText(Ui.num(Math.round(val * 10) / 10.0) + " " + unit, W - lw - Ui.dp(12) - w, y + Ui.dp(14), t);
                }
                if (values.size() > n) { t.setColor(Ui.MUTED); t.setTextAlign(Paint.Align.RIGHT); cv.drawText("… " + Ui.fa(String.valueOf(values.size() - n)) + " مورد دیگر", W - Ui.dp(2), n * rowH + Ui.dp(16), t); }
            }
        };
        v.setLayoutParams(Ui.lp(android.view.ViewGroup.LayoutParams.MATCH_PARENT, rowH * Math.max(1, n) + Ui.dp(values.size() > n ? 26 : 10)));
        return v;
    }

    /** v3.2 — donut (share) chart with a centre label and a legend row. */
    static View donut(Context c, List<String> labels, List<Double> values, List<Integer> colors, String centre) {
        android.widget.LinearLayout row = Ui.row(c); row.setPadding(0, Ui.dp(8), 0, 0);
        View v = new View(c) {
            final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG), t = new Paint(Paint.ANTI_ALIAS_FLAG);
            { t.setTextSize(Ui.dp(12)); t.setTypeface(Ui.FONT_BOLD); t.setColor(Ui.TEXT); t.setTextAlign(Paint.Align.CENTER); p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(Ui.dp(14)); p.setStrokeCap(Paint.Cap.BUTT); }
            @Override protected void onDraw(Canvas cv) {
                float S = Math.min(getWidth(), getHeight()), r = S / 2 - Ui.dp(10); float cx = getWidth() / 2f, cy = getHeight() / 2f;
                android.graphics.RectF rc = new android.graphics.RectF(cx - r, cy - r, cx + r, cy + r);
                double total = 0; for (Double d : values) total += d == null ? 0 : Math.max(0, d); if (total <= 0 || Double.isNaN(total)) total = 1; float start = -90;
                for (int i = 0; i < values.size(); i++) { double raw = values.get(i) == null ? 0 : values.get(i); if (Double.isNaN(raw)) raw = 0; float sweep = (float) (Math.max(0, raw) / total * 360); p.setColor(colorAt(colors, i)); cv.drawArc(rc, start, Math.max(0, sweep - 1.5f), false, p); start += sweep; }
                cv.drawText(centre == null ? "" : centre, cx, cy + Ui.dp(4), t);
            }
        };
        v.setLayoutParams(Ui.lp(Ui.dp(120), Ui.dp(120)));
        android.widget.LinearLayout lg = Ui.col(c); lg.setLayoutParams(Ui.weight(1)); lg.setPadding(Ui.dp(12), 0, 0, 0);
        for (int i = 0; i < labels.size(); i++) { android.widget.LinearLayout li = Ui.row(c); View dot = new View(c); dot.setBackground(Ui.rounded(colorAt(colors, i), 0, 5)); dot.setLayoutParams(Ui.margin(Ui.lp(Ui.dp(10), Ui.dp(10)), 0, 0, 6, 0)); li.addView(dot); li.addView(Ui.muted(c, labelAt(labels, i))); lg.addView(li); }
        row.addView(v); row.addView(lg); return row;
    }

    static double[] arr(List<Double> l) { double[] a = new double[l.size()]; for (int i = 0; i < a.length; i++) a[i] = l.get(i) == null ? Double.NaN : l.get(i); return a; }
    static List<Double> nulls(int n) { List<Double> l = new ArrayList<>(); for (int i = 0; i < n; i++) l.add(null); return l; }
}
