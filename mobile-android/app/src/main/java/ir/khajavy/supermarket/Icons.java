package ir.khajavy.supermarket;

import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.drawable.Drawable;
import android.view.View;
import android.widget.ImageView;

/**
 * v2.9 — in-house vector icon set (no emoji, no drawable resources, no dependencies).
 *
 * Every icon is a stroked outline drawn on a 24×24 grid with round caps/joins — the same
 * language as premium POS apps. Emoji looked different on every phone and cheapened the
 * shell; these are crisp at any size and take the theme colour.
 *
 * Usage:  Icons.view(ctx, "cart", Ui.PRIMARY, 22)   → ImageView
 *         Icons.badge(ctx, "cart", accent, 40)     → icon inside a tinted rounded square
 */
public final class Icons {
    private Icons() {}

    /** tiny path language: M x y | L x y | C (circle) cx cy r | R (rect) x y w h rad | A (arc) l t r b start sweep | Z */
    private static final java.util.Map<String, String> P = new java.util.HashMap<>();
    static {
        P.put("home",      "M 3 11 L 12 4 L 21 11 M 5 10 L 5 20 L 19 20 L 19 10 M 10 20 L 10 14 L 14 14 L 14 20");
        P.put("cart",      "M 3 4 L 6 4 L 8.5 16 L 19 16 L 21 8 L 7 8 C 9.5 19.5 1.2 C 17.5 19.5 1.2");
        P.put("tag",       "M 12 3 L 20 3 L 20 11 L 11 20 L 3 12 Z C 16 7 1.2");
        P.put("box",       "M 3 8 L 12 3 L 21 8 L 21 16 L 12 21 L 3 16 Z M 3 8 L 12 13 L 21 8 M 12 13 L 12 21");
        P.put("menu",      "M 4 7 L 20 7 M 4 12 L 20 12 M 4 17 L 14 17");
        P.put("grid",      "R 4 4 6.5 6.5 1.5 R 13.5 4 6.5 6.5 1.5 R 4 13.5 6.5 6.5 1.5 R 13.5 13.5 6.5 6.5 1.5");
        P.put("receipt",   "M 6 3 L 18 3 L 18 21 L 15.5 19.2 L 13 21 L 10.5 19.2 L 8 21 L 6 19.2 Z M 9 8 L 15 8 M 9 12 L 15 12 M 9 16 L 13 16");
        P.put("users",     "C 9 8 3.2 M 3 20 L 3 18.5 A 3 12 15 20 180 180 L 15 20 C 17 9 2.5 M 17 14 A 17 14 21 20 270 180 L 21 20");
        P.put("user",      "C 12 8 3.6 M 5 20 L 5 19 A 5 13.5 19 20 180 180 L 19 20");
        P.put("chart",     "M 4 20 L 20 20 M 7 16 L 7 11 M 12 16 L 12 6 M 17 16 L 17 9");
        P.put("trend",     "M 4 17 L 10 11 L 14 14 L 20 7 M 15 7 L 20 7 L 20 12");
        P.put("wallet",    "R 3 6 18 14 3 M 3 10 L 21 10 M 16 15 L 18 15");
        P.put("calc",      "R 5 3 14 18 2.5 M 8 7 L 16 7 M 8.5 12 L 8.5 12 M 12 12 L 12 12 M 15.5 12 L 15.5 12 M 8.5 16 L 8.5 16 M 12 16 L 12 16 M 15.5 16 L 15.5 16");
        P.put("settings",  "C 12 12 3 M 12 2.5 L 12 5.5 M 12 18.5 L 12 21.5 M 2.5 12 L 5.5 12 M 18.5 12 L 21.5 12 M 5.3 5.3 L 7.4 7.4 M 16.6 16.6 L 18.7 18.7 M 5.3 18.7 L 7.4 16.6 M 16.6 7.4 L 18.7 5.3");
        P.put("store",     "M 4 9 L 5.5 4 L 18.5 4 L 20 9 M 4 9 L 4 20 L 20 20 L 20 9 M 4 9 L 20 9 M 9.5 20 L 9.5 14 L 14.5 14 L 14.5 20");
        P.put("warehouse", "M 3 20 L 3 9 L 12 4 L 21 9 L 21 20 M 7 20 L 7 13 L 17 13 L 17 20 M 7 16.5 L 17 16.5");
        P.put("truck",     "R 2 6 12 10 1.5 M 14 10 L 18.5 10 L 21 13.5 L 21 16 L 14 16 C 6 18 1.8 C 17 18 1.8");
        P.put("gift",      "R 3 8 18 4 1 M 5 12 L 5 20 L 19 20 L 19 12 M 12 8 L 12 20 M 12 8 C 9 5.5 2.2 C 15 5.5 2.2");
        P.put("sms",       "M 4 5 L 20 5 L 20 16 L 9 16 L 5 19.5 L 5 16 L 4 16 Z M 8 9 L 16 9 M 8 12 L 13 12");
        P.put("bell", "M 6 16 L 6 11 A 6 4 18 16 180 180 L 18 16 L 19.5 18 L 4.5 18 Z M 10.5 20.5 L 13.5 20.5 M 12 3 L 12 5");
        P.put("lock",      "R 5 10 14 11 2.5 M 8 10 L 8 7.5 A 8 3.5 16 11 180 180 L 16 10 M 12 15 L 12 17");
        P.put("key",       "C 8 14 4 M 11 11 L 20 3 M 16 7 L 18.5 9.5 M 13.5 9.5 L 16 12");
        P.put("support", "C 12 12 8.5 M 4 12 L 4 15 L 7 15 L 7 12 Z M 17 12 L 17 15 L 20 15 L 20 12 Z M 15 19.5 L 13 19.5");
        P.put("sync", "A 4 4 20 20 200 250 M 17 3 L 20.5 5 L 18.5 8.5 A 4 4 20 20 20 250 M 7 21 L 3.5 19 L 5.5 15.5");
        P.put("cloud", "M 7 18 L 17 18 A 11 6 21 18 90 -180 A 5 5 16 16 -20 -130 A 3 10 11 18 -50 -130 Z");
        P.put("shield", "M 12 3 L 20 6 L 20 12 A 4 6 20 21 0 90 A 4 12 20 21 90 90 L 4 6 Z M 9 12 L 11 14 L 15 10");
        P.put("scan",      "M 3 8 L 3 4 L 7 4 M 17 4 L 21 4 L 21 8 M 21 16 L 21 20 L 17 20 M 7 20 L 3 20 L 3 16 M 7 9 L 7 15 M 10 9 L 10 15 M 13 9 L 13 15 M 17 9 L 17 15");
        P.put("search",    "C 10.5 10.5 6 M 15 15 L 21 21");
        P.put("plus",      "M 12 5 L 12 19 M 5 12 L 19 12");
        P.put("check",     "M 4 12.5 L 9.5 18 L 20 6.5");
        P.put("close",     "M 6 6 L 18 18 M 18 6 L 6 18");
        P.put("back",      "M 9 5 L 16 12 L 9 19");
        P.put("chev",      "M 15 5 L 8 12 L 15 19");
        P.put("down",      "M 6 9 L 12 15 L 18 9");
        P.put("up",        "M 6 15 L 12 9 L 18 15");
        P.put("help",      "C 12 12 9 M 9.5 9.5 A 9 6.5 15 12.5 180 180 L 12 14 L 12 15 M 12 18 L 12 18");
        P.put("sun",       "C 12 12 4 M 12 2.5 L 12 4.5 M 12 19.5 L 12 21.5 M 2.5 12 L 4.5 12 M 19.5 12 L 21.5 12 M 5.3 5.3 L 6.7 6.7 M 17.3 17.3 L 18.7 18.7 M 5.3 18.7 L 6.7 17.3 M 17.3 6.7 L 18.7 5.3");
        P.put("moon", "M 19 15.5 A 3.5 3.5 20.5 20.5 20 235 A 8 2 21 15 260 -120 Z");
        P.put("logout",    "M 10 4 L 5 4 L 5 20 L 10 20 M 14 8 L 18.5 12 L 14 16 M 9 12 L 18 12");
        P.put("printer",   "M 7 8 L 7 3 L 17 3 L 17 8 R 3 8 18 9 2 M 7 14 L 7 21 L 17 21 L 17 14 Z M 17.5 11.5 L 17.5 11.5");
        P.put("list",      "M 8 6 L 20 6 M 8 12 L 20 12 M 8 18 L 20 18 M 4 6 L 4 6 M 4 12 L 4 12 M 4 18 L 4 18");
        P.put("clipboard", "R 5 5 14 16 2.5 M 9 5 L 9 3 L 15 3 L 15 5 M 9 11 L 15 11 M 9 15 L 13 15");
        P.put("history", "A 3.5 3.5 20.5 20.5 -60 300 M 3 6 L 3.5 10.5 L 8 10 M 12 8 L 12 12.5 L 15 14.5");
        P.put("pause",     "R 6 4 4 16 1.5 R 14 4 4 16 1.5");
        P.put("undo", "M 9 7 L 4 12 L 9 17 M 4 12 L 14 12 A 8 12 20 20 270 180 L 14 20 L 10 20");
        P.put("trash",     "M 4 7 L 20 7 M 9 7 L 9 4 L 15 4 L 15 7 M 6 7 L 7 20 L 17 20 L 18 7 M 10 11 L 10 17 M 14 11 L 14 17");
        P.put("camera",    "M 3 8 L 8 8 L 9.5 5 L 14.5 5 L 16 8 L 21 8 L 21 19 L 3 19 Z C 12 13 3.5");
        P.put("image",     "R 3 4 18 16 2.5 C 8.5 9 1.6 M 3 17 L 9 12 L 13 15 L 16 12.5 L 21 17");
        P.put("phone",     "R 7 2.5 10 19 2.5 M 11 18.5 L 13 18.5");
        P.put("pc",        "R 3 4 18 12 2 M 8 20 L 16 20 M 12 16 L 12 20");
        P.put("link", "M 9.5 14.5 L 14.5 9.5 M 8 16 L 6.5 17.5 A 3 12.5 9 19 -45 225 L 8.5 16.5 M 16 8 L 17.5 6.5 A 15 5 21 11 135 225 L 15.5 7.5");
        P.put("star",      "M 12 3.5 L 14.6 9 L 20.5 9.7 L 16.1 13.8 L 17.3 19.7 L 12 16.8 L 6.7 19.7 L 7.9 13.8 L 3.5 9.7 L 9.4 9 Z");
        P.put("percent",   "M 6 18 L 18 6 C 7.5 7.5 2 C 16.5 16.5 2");
        P.put("coin",      "C 12 12 8.5 M 12 7 L 12 17 M 15 9.5 A 9 7.5 15 12 270 -180 M 9 14.5 A 9 12 15 16.5 90 -180");
        P.put("exit",      "M 15 4 L 20 4 L 20 20 L 15 20 M 4 12 L 13 12 M 9 8 L 4.5 12 L 9 16");
        P.put("pulse",     "M 3 12 L 7 12 L 9.5 6 L 13.5 18 L 16 12 L 21 12");
        P.put("wand",      "M 4 20 L 15 9 M 13 7 L 17 11 M 18 3 L 18 3 M 21 7 L 21 7 M 15 3 L 15 3");
        P.put("archive",   "R 3 4 18 4.5 1 M 4.5 8.5 L 4.5 20 L 19.5 20 L 19.5 8.5 M 10 13 L 14 13");
        P.put("bank",      "M 3 9 L 12 4 L 21 9 Z M 5 9 L 5 18 M 9.5 9 L 9.5 18 M 14.5 9 L 14.5 18 M 19 9 L 19 18 M 3 20 L 21 20");
        P.put("dashboard", "A 3 5 21 21 180 180 M 12 15 L 16.5 9.5 M 12 4 L 12 6.5 M 5 12 L 7 12 M 17 12 L 19 12");
        P.put("map",       "M 4 6 L 9 4 L 15 6 L 20 4 L 20 18 L 15 20 L 9 18 L 4 20 Z M 9 4 L 9 18 M 15 6 L 15 20");
        P.put("bag",       "M 5 8 L 19 8 L 20 21 L 4 21 Z M 9 8 L 9 6.5 A 9 3 15 10 180 180 L 15 8");
        P.put("calendar",  "R 3 5 18 16 2.5 M 3 10 L 21 10 M 8 3 L 8 7 M 16 3 L 16 7 M 7.5 14 L 7.5 14 M 12 14 L 12 14 M 16.5 14 L 16.5 14 M 7.5 17.5 L 7.5 17.5 M 12 17.5 L 12 17.5");
        P.put("basket",    "M 3 10 L 21 10 L 19 20 L 5 20 Z M 8 10 L 11 4 M 16 10 L 13 4 M 9.5 14 L 9.5 17 M 12 14 L 12 17 M 14.5 14 L 14.5 17");
    }

    public static boolean has(String name) { return P.containsKey(name); }

    /** Drawable that paints a named icon in a colour. */
    public static final class Icon extends Drawable {
        private final Path path = new Path();
        private final java.util.List<float[]> dots = new java.util.ArrayList<>();
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final float strokeUnits;
        public Icon(String name, int color, float strokeWidthUnits) {
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeCap(Paint.Cap.ROUND); paint.setStrokeJoin(Paint.Join.ROUND); paint.setColor(color);
            strokeUnits = strokeWidthUnits;
            build(P.containsKey(name) ? P.get(name) : P.get("help"));
        }
        private void build(String d) {
            String[] t = d.trim().split("\\s+"); int i = 0; float lx = 0, ly = 0;
            while (i < t.length) {
                String op = t[i++];
                switch (op) {
                    case "M": { float x = f(t[i++]), y = f(t[i++]); lx = x; ly = y; path.moveTo(x, y);
                        // «M x y L x y» with identical coordinates → a dot
                        if (i + 2 < t.length && t[i].equals("L") && f(t[i + 1]) == x && f(t[i + 2]) == y) { dots.add(new float[]{x, y}); i += 3; } break; }
                    case "L": { float x = f(t[i++]), y = f(t[i++]); path.lineTo(x, y); lx = x; ly = y; break; }
                    case "C": { float cx = f(t[i++]), cy = f(t[i++]), r = f(t[i++]); path.addCircle(cx, cy, r, Path.Direction.CW); break; }
                    case "R": { float x = f(t[i++]), y = f(t[i++]), w = f(t[i++]), h = f(t[i++]), rad = f(t[i++]); path.addRoundRect(new RectF(x, y, x + w, y + h), rad, rad, Path.Direction.CW); break; }
                    case "A": { float l = f(t[i++]), tp = f(t[i++]), r = f(t[i++]), b = f(t[i++]), st = f(t[i++]), sw = f(t[i++]); path.arcTo(new RectF(l, tp, r, b), st, sw, false); break; }
                    case "Z": path.close(); break;
                    default: break;
                }
            }
        }
        private static float f(String s) { return Float.parseFloat(s); }
        @Override public void draw(Canvas c) {
            Rect b = getBounds(); float s = Math.min(b.width(), b.height()) / 24f;
            c.save(); c.translate(b.left + (b.width() - 24 * s) / 2f, b.top + (b.height() - 24 * s) / 2f); c.scale(s, s);
            paint.setStrokeWidth(strokeUnits); c.drawPath(path, paint);
            for (float[] d : dots) c.drawCircle(d[0], d[1], strokeUnits * 0.55f, fill(paint));
            c.restore();
        }
        private static Paint fillP;
        private static Paint fill(Paint src) { if (fillP == null) { fillP = new Paint(Paint.ANTI_ALIAS_FLAG); fillP.setStyle(Paint.Style.FILL); } fillP.setColor(src.getColor()); return fillP; }
        @Override public void setAlpha(int a) { paint.setAlpha(a); }
        @Override public void setColorFilter(ColorFilter cf) { paint.setColorFilter(cf); }
        @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
        public void setColor(int color) { paint.setColor(color); invalidateSelf(); }
    }

    public static Icon draw(String name, int color) { return new Icon(name, color, 1.9f); }
    public static Icon draw(String name, int color, float stroke) { return new Icon(name, color, stroke); }

    /** plain icon view. */
    public static ImageView view(android.content.Context c, String name, int color, int sizeDp) {
        ImageView iv = new ImageView(c); iv.setImageDrawable(draw(name, color)); iv.setLayoutParams(Ui.lp(Ui.dp(sizeDp), Ui.dp(sizeDp))); iv.setScaleType(ImageView.ScaleType.FIT_CENTER); return iv;
    }
    /** icon inside a soft tinted rounded square — used by tiles, drawer rows, list rows. */
    public static ImageView badge(android.content.Context c, String name, int accent, int sizeDp) {
        ImageView iv = view(c, name, accent, sizeDp); int pad = Ui.dp(sizeDp * 0.24f); iv.setPadding(pad, pad, pad, pad);
        iv.setBackground(Ui.rounded((accent & 0x00FFFFFF) | (Ui.dark ? 0x2E000000 : 0x1A000000), 0, sizeDp * 0.32f)); return iv;
    }
    /** icon inside a filled circle (hero, avatars, big CTAs). */
    public static ImageView disc(android.content.Context c, String name, int fill, int fg, int sizeDp) {
        ImageView iv = view(c, name, fg, sizeDp); int pad = Ui.dp(sizeDp * 0.26f); iv.setPadding(pad, pad, pad, pad); iv.setBackground(Ui.rounded(fill, 0, sizeDp)); return iv;
    }
    /** icon → tinted for a View (e.g. TextView compound). */
    public static void tint(View v, int color) { if (v instanceof ImageView && ((ImageView) v).getDrawable() instanceof Icon) ((Icon) ((ImageView) v).getDrawable()).setColor(color); }
    public static int alpha(int color, int a) { return (color & 0x00FFFFFF) | (a << 24); }
    public static int WHITE = Color.WHITE;
}
