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
            float x(int i, int n, float l, float r) { return l + (r - l) * i / (n - 1); }
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
        View v = new View(c) {
            final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG), t = new Paint(Paint.ANTI_ALIAS_FLAG);
            { t.setTextSize(Ui.dp(11)); t.setTypeface(Ui.FONT); }
            @Override protected void onDraw(Canvas cv) {
                float W = getWidth(); double max = 1; for (double d : values) max = Math.max(max, Math.abs(d));
                float lw = W * 0.42f;
                for (int i = 0; i < values.size(); i++) {
                    float y = i * rowH + Ui.dp(5); double val = values.get(i); float w = (float) ((W - lw - Ui.dp(70)) * Math.abs(val) / max);
                    t.setColor(Ui.TEXT); t.setTextAlign(Paint.Align.RIGHT); cv.drawText(ellipsize(labels.get(i), lw - Ui.dp(6)), W - Ui.dp(2), y + Ui.dp(14), t);
                    p.setStyle(Paint.Style.FILL); p.setColor(val >= 0 ? (colors != null && colors.get(i) != null ? colors.get(i) : Ui.TEAL) : Ui.RED);
                    android.graphics.RectF rc = new android.graphics.RectF(W - lw - Ui.dp(8) - w, y, W - lw - Ui.dp(8), y + Ui.dp(20)); cv.drawRoundRect(rc, Ui.dp(6), Ui.dp(6), p);
                    t.setColor(Ui.MUTED); cv.drawText(Ui.moneyShort(val), W - lw - Ui.dp(12) - w, y + Ui.dp(14), t);
                }
            }
            String ellipsize(String s, float maxW) { if (t.measureText(s) <= maxW) return s; while (s.length() > 3 && t.measureText(s + "…") > maxW) s = s.substring(0, s.length() - 1); return s + "…"; }
        };
        v.setLayoutParams(Ui.lp(android.view.ViewGroup.LayoutParams.MATCH_PARENT, rowH * Math.max(1, values.size()) + Ui.dp(10)));
        return v;
    }

    static double[] arr(List<Double> l) { double[] a = new double[l.size()]; for (int i = 0; i < a.length; i++) a[i] = l.get(i) == null ? Double.NaN : l.get(i); return a; }
    static List<Double> nulls(int n) { List<Double> l = new ArrayList<>(); for (int i = 0; i < n; i++) l.add(null); return l; }
}
