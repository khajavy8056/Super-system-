package ir.khajavy.supermarket;

import org.json.JSONObject;

import android.app.AlertDialog;
import android.app.Dialog;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.content.res.ColorStateList;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.text.NumberFormat;
import java.util.Locale;

/**
 * v2.0 — native design system for the phone app (Material-like, RTL, Vazirmatn).
 * Everything is built in code (no XML inflation) so the Gradle-less toolchain
 * in scripts/android/build-apk.sh keeps working.
 */
public final class Ui {
    private Ui() {}
    public static Context ctx;
    /** foreground activity (set by AppActivity.onResume) — dialogs need an Activity, not the app context. */
    public static android.app.Activity top;
    public static Typeface FONT, FONT_BOLD;
    private static float density = 2f;
    public static boolean dark = true;

    // palette (calm, no neon — the user's rule)
    public static int BG, BG2, CARD, CARD2, BORDER, TEXT, MUTED, PRIMARY, PRIMARY2, GREEN, RED, AMBER, VIOLET, TEAL, GOLD;

    public static void init(Context c) {
        ctx = c.getApplicationContext(); density = c.getResources().getDisplayMetrics().density;
        try { FONT = Typeface.createFromAsset(c.getAssets(), "fonts/Vazirmatn-Regular.ttf"); FONT_BOLD = Typeface.createFromAsset(c.getAssets(), "fonts/Vazirmatn-Bold.ttf"); } catch (Exception e) { FONT = Typeface.DEFAULT; FONT_BOLD = Typeface.DEFAULT_BOLD; }
        setTheme(!"light".equals(Prefs.get("theme_resolved", "dark")));
    }
    public static void setTheme(boolean isDark) {
        dark = isDark;
        // v2.2 palette — follows the user's reference mockups: deep navy dark theme, soft
        // off-white light theme, one calm teal accent, no neon.
        if (dark) { BG = 0xFF1B2536; BG2 = 0xFF223046; CARD = 0xFF27364B; CARD2 = 0xFF2E3F56; BORDER = 0xFF35475F; TEXT = 0xFFEAF0F7; MUTED = 0xFF93A3B8; }
        else { BG = 0xFFEDF0F5; BG2 = 0xFFFFFFFF; CARD = 0xFFF7F8FB; CARD2 = 0xFFEEF1F6; BORDER = 0xFFDDE3EC; TEXT = 0xFF1C2433; MUTED = 0xFF6B7789; }
        TEAL = 0xFF2AA79B; PRIMARY = TEAL; PRIMARY2 = dark ? 0xFF1F8A80 : 0xFF3DBFB2; GREEN = 0xFF2FB673; RED = 0xFFE05252; AMBER = 0xFFE3A03A; GOLD = 0xFFD9A441; VIOLET = 0xFF7C6CE0;
    }
    public static int dp(float v) { return Math.round(v * density); }
    public static void toast(String s) { if (ctx != null) Api.ui(() -> Toast.makeText(ctx, s, Toast.LENGTH_SHORT).show()); }

    /* ---------------- numbers / dates ---------------- */
    private static final NumberFormat NF = NumberFormat.getInstance(Locale.US);
    public static String currencyLabel = "ریال";
    public static String money(double v) { return fa(NF.format(Math.round(v))) + " " + currencyLabel; }
    public static String num(double v) { return fa(v == Math.floor(v) ? NF.format((long) v) : String.format(Locale.US, "%.3f", v).replaceAll("0+$", "").replaceAll("\\.$", "")); }
    public static String fa(String s) { if (s == null) return ""; StringBuilder b = new StringBuilder(); for (char c : s.toCharArray()) b.append(c >= '0' && c <= '9' ? (char) ('۰' + c - '0') : c); return b.toString(); }
    public static String jdate(String iso) { if (iso == null || iso.length() < 10 || iso.equals("null")) return "—"; int[] j = Jalali.toJalali(Integer.parseInt(iso.substring(0, 4)), Integer.parseInt(iso.substring(5, 7)), Integer.parseInt(iso.substring(8, 10))); String t = iso.length() >= 16 ? " " + iso.substring(11, 16) : ""; return fa(j[0] + "/" + two(j[1]) + "/" + two(j[2]) + t); }
    private static String two(int n) { return n < 10 ? "0" + n : String.valueOf(n); }

    /* ---------------- text ---------------- */
    public static TextView text(Context c, String s, float sp, int color, boolean bold) {
        TextView t = new TextView(c); t.setText(s == null ? "" : s); t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp); t.setTextColor(color); t.setTypeface(bold ? FONT_BOLD : FONT);
        t.setTextDirection(View.TEXT_DIRECTION_RTL); t.setGravity(Gravity.START); t.setLayoutDirection(View.LAYOUT_DIRECTION_RTL); return t;
    }
    public static TextView h1(Context c, String s) { return text(c, s, 20, TEXT, true); }
    public static TextView h2(Context c, String s) { TextView t = text(c, s, 16, TEXT, true); t.setPadding(0, 0, 0, dp(6)); return t; }
    public static TextView body(Context c, String s) { return text(c, s, 14, TEXT, false); }
    public static TextView muted(Context c, String s) { return text(c, s, 12, MUTED, false); }
    public static TextView label(Context c, String s) { TextView t = text(c, s, 12, MUTED, false); t.setPadding(0, dp(8), 0, dp(4)); return t; }

    /* ---------------- containers ---------------- */
    public static LinearLayout col(Context c) { LinearLayout l = new LinearLayout(c); l.setOrientation(LinearLayout.VERTICAL); l.setLayoutDirection(View.LAYOUT_DIRECTION_RTL); return l; }
    public static LinearLayout row(Context c) { LinearLayout l = new LinearLayout(c); l.setOrientation(LinearLayout.HORIZONTAL); l.setGravity(Gravity.CENTER_VERTICAL); l.setLayoutDirection(View.LAYOUT_DIRECTION_RTL); return l; }
    public static LinearLayout.LayoutParams lp(int w, int h) { return new LinearLayout.LayoutParams(w, h); }
    public static LinearLayout.LayoutParams weight(float w) { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, w); return p; }
    public static LinearLayout.LayoutParams match() { return lp(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT); }
    public static LinearLayout.LayoutParams margin(LinearLayout.LayoutParams p, int l, int t, int r, int b) { p.setMargins(dp(l), dp(t), dp(r), dp(b)); return p; }
    public static GradientDrawable rounded(int fill, int stroke, float radius) { GradientDrawable g = new GradientDrawable(); g.setColor(fill); if (stroke != 0) g.setStroke(dp(1), stroke); g.setCornerRadius(dp(radius)); return g; }
    /** soft diagonal gradient (top-right → bottom-left, matches the mockups). */
    public static GradientDrawable gradient(int from, int to, int stroke, float radius) { GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.TR_BL, new int[]{from, to}); if (stroke != 0) g.setStroke(dp(1), stroke); g.setCornerRadius(dp(radius)); return g; }
    /** default card surface: subtle gradient, 20dp radius, hairline border. */
    public static GradientDrawable surface(float radius) { return gradient(dark ? CARD2 : BG2, CARD, BORDER, radius); }
    public static LinearLayout card(Context c) { LinearLayout l = col(c); l.setBackground(surface(20)); l.setPadding(dp(16), dp(14), dp(16), dp(14)); l.setElevation(dark ? 0 : dp(1.5f)); l.setLayoutParams(margin(match(), 0, 0, 0, 12)); return l; }
    /** hero card (dashboard welcome): teal gradient, white text. */
    public static LinearLayout hero(Context c) { LinearLayout l = col(c); l.setBackground(gradient(PRIMARY2, PRIMARY, 0, 22)); l.setPadding(dp(18), dp(18), dp(18), dp(18)); l.setLayoutParams(margin(match(), 0, 0, 0, 12)); return l; }
    /** dashboard tile: rounded icon badge + label + big value (+ optional custom view below). */
    public static LinearLayout tile(Context c, String icon, int accent, String label, String value, View extra) {
        LinearLayout l = col(c); l.setBackground(surface(20)); l.setPadding(dp(14), dp(14), dp(14), dp(14)); l.setMinimumHeight(dp(118));
        LinearLayout top = row(c); TextView ic = text(c, icon, 16, accent, true); ic.setGravity(Gravity.CENTER); ic.setBackground(rounded((accent & 0x00FFFFFF) | (dark ? 0x33000000 : 0x1F000000), 0, 12)); ic.setLayoutParams(lp(dp(34), dp(34))); top.addView(ic);
        TextView lb = muted(c, label); lb.setPadding(dp(8), 0, 0, 0); lb.setLayoutParams(weight(1)); top.addView(lb); l.addView(top);
        TextView v = text(c, value, 19, TEXT, true); v.setPadding(0, dp(10), 0, 0); l.addView(v);
        if (extra != null) l.addView(extra); return l;
    }
    /** tiny sparkline built from views (no canvas needed). */
    public static View spark(Context c, double[] vals, int color) {
        LinearLayout r = row(c); r.setGravity(Gravity.BOTTOM); r.setLayoutParams(margin(lp(ViewGroup.LayoutParams.MATCH_PARENT, dp(34)), 0, 8, 0, 0)); r.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        double mx = 1; for (double v : vals) mx = Math.max(mx, v);
        for (int i = 0; i < vals.length; i++) { View b = new View(c); b.setBackground(rounded(i == vals.length - 1 ? color : (color & 0x00FFFFFF) | 0x66000000, 0, 3)); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, Math.max(dp(4), (int) (dp(32) * vals[i] / mx)), 1); p.setMargins(dp(2), 0, dp(2), 0); b.setLayoutParams(p); r.addView(b); }
        return r;
    }
    /** circular avatar with initials. */
    public static TextView avatar(Context c, String name, int size) { String s = name == null || name.trim().isEmpty() ? "؟" : name.trim().substring(0, 1); TextView t = text(c, s, size / 2.4f, Color.WHITE, true); t.setGravity(Gravity.CENTER); t.setBackground(gradient(PRIMARY2, PRIMARY, 0, size)); t.setLayoutParams(lp(dp(size), dp(size))); return t; }
    /** card containing a single muted note. */
    public static LinearLayout note(Context c, String title, String text) { LinearLayout l = card(c, title); l.addView(muted(c, text)); return l; }
    public static LinearLayout card(Context c, String title) { LinearLayout l = card(c); if (title != null) l.addView(h2(c, title)); return l; }
    public static ScrollView scroll(Context c, View inner) { ScrollView s = new ScrollView(c); s.setFillViewport(true); s.setVerticalScrollBarEnabled(false); s.addView(inner); return s; }
    public static View divider(Context c) { View v = new View(c); v.setBackgroundColor(BORDER); v.setLayoutParams(margin(lp(ViewGroup.LayoutParams.MATCH_PARENT, dp(1)), 0, 8, 0, 8)); return v; }
    public static View space(Context c, int h) { View v = new View(c); v.setLayoutParams(lp(ViewGroup.LayoutParams.MATCH_PARENT, dp(h))); return v; }

    /* ---------------- inputs ---------------- */
    public static EditText input(Context c, String hint, boolean numeric) {
        EditText e = new EditText(c); e.setHint(hint); e.setTypeface(FONT); e.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15); e.setTextColor(TEXT); e.setHintTextColor(MUTED);
        e.setBackground(rounded(dark ? BG2 : Color.WHITE, BORDER, 14)); e.setPadding(dp(14), dp(12), dp(14), dp(12)); e.setLayoutParams(margin(match(), 0, 0, 0, 6));
        e.setTextDirection(numeric ? View.TEXT_DIRECTION_LTR : View.TEXT_DIRECTION_RTL); e.setLayoutDirection(View.LAYOUT_DIRECTION_RTL); e.setGravity(numeric ? Gravity.START : Gravity.START);
        if (numeric) e.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        e.setSingleLine(true); return e;
    }
    public static EditText input(Context c, String hint) { return input(c, hint, false); }
    public static EditText area(Context c, String hint) { EditText e = input(c, hint, false); e.setSingleLine(false); e.setMinLines(3); e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE); return e; }
    public static double numVal(EditText e, double def) { try { String s = Db.norm(e.getText().toString()).replace(",", ""); return s.isEmpty() ? def : Double.parseDouble(s); } catch (Exception ex) { return def; } }
    public static String str(EditText e) { return e.getText().toString().trim(); }

    /* ---------------- buttons ---------------- */
    public static Button btn(Context c, String s, int fill, int textColor, Runnable onClick) {
        Button b = new Button(c); b.setText(s); b.setAllCaps(false); b.setTypeface(FONT_BOLD); b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14); b.setTextColor(textColor);
        b.setBackground(new RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), fill == PRIMARY ? gradient(PRIMARY2, PRIMARY, 0, 14) : rounded(fill, fill == CARD || fill == BG2 || fill == CARD2 ? BORDER : 0, 14), null));
        b.setMinHeight(dp(46)); b.setMinimumHeight(dp(46)); b.setPadding(dp(14), 0, dp(14), 0); b.setStateListAnimator(null); b.setElevation(0);
        b.setLayoutParams(margin(match(), 0, 4, 0, 4)); if (onClick != null) b.setOnClickListener(v -> onClick.run()); return b;
    }
    public static Button primary(Context c, String s, Runnable r) { return btn(c, s, PRIMARY, Color.WHITE, r); }
    public static Button success(Context c, String s, Runnable r) { return btn(c, s, GREEN, Color.WHITE, r); }
    public static Button danger(Context c, String s, Runnable r) { Button b = btn(c, s, Color.TRANSPARENT, RED, r); b.setBackground(new RippleDrawable(ColorStateList.valueOf(0x22E05252), rounded(Color.TRANSPARENT, RED, 14), null)); return b; }
    /** big call-to-action (POS «پرداخت»). */
    public static Button cta(Context c, String s, Runnable r) { Button b = primary(c, s, r); b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16); b.setMinHeight(dp(54)); b.setMinimumHeight(dp(54)); b.setBackground(new RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), gradient(PRIMARY2, PRIMARY, 0, 16), null)); return b; }
    public static Button ghost(Context c, String s, Runnable r) { return btn(c, s, BG2, TEXT, r); }
    public static Button small(Context c, String s, Runnable r) { Button b = ghost(c, s, r); b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12); b.setMinHeight(dp(34)); b.setMinimumHeight(dp(34)); b.setLayoutParams(margin(lp(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT), 4, 2, 0, 2)); return b; }
    public static Button chip(Context c, String s, boolean active, Runnable r) { Button b = small(c, s, r); b.setBackground(rounded(active ? PRIMARY : CARD2, active ? 0 : BORDER, 20)); b.setTextColor(active ? Color.WHITE : TEXT); b.setPadding(dp(14), 0, dp(14), 0); return b; }
    /** icon-less pill chip with a leading glyph (POS: مشتری / کوپن / تخفیف). */
    public static Button pill(Context c, String glyph, String s, boolean active, Runnable r) { return chip(c, glyph + "  " + s, active, r); }

    /* ---------------- list rows ---------------- */
    /** two-line list row (title / subtitle) with an optional trailing value and click. */
    public static LinearLayout item(Context c, String title, String sub, String trailing, int trailingColor, Runnable onClick) {
        LinearLayout r = row(c); r.setBackground(new RippleDrawable(ColorStateList.valueOf(0x22FFFFFF), surface(16), null)); r.setPadding(dp(14), dp(12), dp(14), dp(12)); r.setLayoutParams(margin(match(), 0, 0, 0, 8));
        LinearLayout col = col(c); col.addView(text(c, title, 14, TEXT, true)); if (sub != null && !sub.isEmpty()) { TextView s = muted(c, sub); s.setPadding(0, dp(2), 0, 0); col.addView(s); }
        col.setLayoutParams(weight(1)); r.addView(col);
        if (trailing != null) { TextView t = text(c, trailing, 14, trailingColor == 0 ? TEXT : trailingColor, true); t.setGravity(Gravity.END); t.setPadding(dp(8), 0, 0, 0); r.addView(t); }
        if (onClick != null) { r.setClickable(true); r.setOnClickListener(v -> onClick.run()); }
        return r;
    }
    /** v2.5 — 44dp product thumbnail (placeholder = first letter tile, replaced async by the picture). */
    public static android.widget.ImageView thumb(Context c, JSONObject p, int sizeDp) {
        android.widget.ImageView iv = new android.widget.ImageView(c); iv.setLayoutParams(margin(lp(dp(sizeDp), dp(sizeDp)), 0, 0, 10, 0)); iv.setScaleType(android.widget.ImageView.ScaleType.CENTER_CROP);
        iv.setBackground(rounded((PRIMARY & 0x00FFFFFF) | 0x22000000, 0, 12)); iv.setClipToOutline(true);
        String n = p == null ? "" : p.optString("name", ""); iv.setImageBitmap(letterTile(n.isEmpty() ? "🛍" : n.substring(0, 1), dp(sizeDp)));
        Images.bind(iv, p); return iv;
    }
    static android.graphics.Bitmap letterTile(String ch, int px) {
        android.graphics.Bitmap b = android.graphics.Bitmap.createBitmap(px, px, android.graphics.Bitmap.Config.ARGB_8888); android.graphics.Canvas cv = new android.graphics.Canvas(b);
        android.graphics.Paint pt = new android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG); pt.setColor(PRIMARY); pt.setTextSize(px * 0.42f); pt.setTextAlign(android.graphics.Paint.Align.CENTER); if (FONT != null) pt.setTypeface(FONT);
        cv.drawText(ch, px / 2f, px / 2f - (pt.descent() + pt.ascent()) / 2f, pt); return b;
    }
    /** product list row: thumbnail + title/sub + trailing. */
    public static LinearLayout pitem(Context c, JSONObject p, String title, String sub, String trailing, int trailingColor, Runnable onClick) {
        LinearLayout r = item(c, title, sub, trailing, trailingColor, onClick); r.addView(thumb(c, p, 44), 0); return r;
    }
    /** key/value line inside a card. */
    public static LinearLayout kv(Context c, String k, String v, int vColor) {
        LinearLayout r = row(c); r.setPadding(0, dp(5), 0, dp(5));
        TextView kt = muted(c, k); kt.setLayoutParams(weight(1)); r.addView(kt);
        TextView vt = text(c, v, 13, vColor == 0 ? TEXT : vColor, true); r.addView(vt); return r;
    }
    /** KPI tile. */
    public static LinearLayout kpi(Context c, String label, String value, String sub, int accent) {
        LinearLayout l = col(c); l.setBackground(surface(20)); l.setPadding(dp(14), dp(14), dp(14), dp(14));
        View bar = new View(c); bar.setBackground(rounded(accent, 0, 2)); bar.setLayoutParams(margin(lp(dp(28), dp(3)), 0, 0, 0, 8)); l.addView(bar);
        l.addView(muted(c, label)); TextView v = text(c, value, 18, TEXT, true); v.setPadding(0, dp(2), 0, 0); l.addView(v);
        if (sub != null) l.addView(muted(c, sub)); return l;
    }
    public static LinearLayout grid2(Context c, View a, View b) {
        LinearLayout r = row(c); r.setLayoutParams(margin(match(), 0, 0, 0, 10));
        LinearLayout.LayoutParams la = weight(1); la.setMargins(0, 0, dp(5), 0); a.setLayoutParams(la);
        LinearLayout.LayoutParams lb = weight(1); lb.setMargins(dp(5), 0, 0, 0); b.setLayoutParams(lb);
        r.addView(a); r.addView(b); return r;
    }
    public static TextView badge(Context c, String s, int color) { TextView t = text(c, s, 11, color, true); t.setBackground(rounded((color & 0x00FFFFFF) | 0x22000000, 0, 10)); t.setPadding(dp(8), dp(2), dp(8), dp(2)); return t; }
    public static TextView empty(Context c, String s) { TextView t = muted(c, s); t.setGravity(Gravity.CENTER); t.setPadding(0, dp(24), 0, dp(24)); return t; }
    public static HorizontalScrollView chips(Context c, LinearLayout inner) { HorizontalScrollView h = new HorizontalScrollView(c); h.setHorizontalScrollBarEnabled(false); h.setLayoutDirection(View.LAYOUT_DIRECTION_RTL); h.addView(inner); return h; }

    /* ---------------- sheets / dialogs ---------------- */
    /** Bottom sheet with a drag handle; returns the dialog so callers can dismiss. */
    public static Dialog sheet(Context c, String title, View content) {
        Dialog d = new Dialog(c); d.requestWindowFeature(Window.FEATURE_NO_TITLE);
        LinearLayout root = col(c); root.setBackground(rounded(dark ? BG2 : Color.WHITE, 0, 24)); root.setPadding(dp(16), dp(10), dp(16), dp(20));
        View handle = new View(c); handle.setBackground(rounded(BORDER, 0, 2)); LinearLayout.LayoutParams hp = lp(dp(44), dp(4)); hp.gravity = Gravity.CENTER_HORIZONTAL; hp.bottomMargin = dp(12); handle.setLayoutParams(hp); root.addView(handle);
        if (title != null) { TextView t = h1(c, title); t.setPadding(0, 0, 0, dp(10)); root.addView(t); }
        ScrollView sv = new ScrollView(c); sv.addView(content); sv.setLayoutParams(lp(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)); root.addView(sv);
        d.setContentView(root);
        Window w = d.getWindow();
        if (w != null) { w.setBackgroundDrawableResource(android.R.color.transparent); w.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT); w.setGravity(Gravity.BOTTOM); w.setWindowAnimations(android.R.style.Animation_InputMethod); w.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE); }
        d.show(); return d;
    }
    /** v2.5.3 — clear success feedback: green check card (centre), soft sound, auto-dismiss; then `after` (usually go back to the list). */
    public static void done(Context c, String title, String detail, Runnable after) {
        Sfx.play("success");
        if (!(c instanceof android.app.Activity)) c = top;
        if (c == null || ((android.app.Activity) c).isFinishing()) { toast(title); if (after != null) after.run(); return; }
        try {
            Dialog d = new Dialog(c); d.requestWindowFeature(Window.FEATURE_NO_TITLE);
            LinearLayout root = col(c); root.setGravity(Gravity.CENTER_HORIZONTAL); root.setBackground(rounded(dark ? BG2 : Color.WHITE, 0, 24)); root.setPadding(dp(28), dp(26), dp(28), dp(24));
            TextView ck = text(c, "✓", 34, Color.WHITE, true); ck.setGravity(Gravity.CENTER); ck.setBackground(rounded(GREEN, 0, 40)); ck.setLayoutParams(margin(lp(dp(72), dp(72)), 0, 0, 0, 14)); root.addView(ck);
            TextView t = h1(c, title); t.setGravity(Gravity.CENTER); root.addView(t);
            if (detail != null && !detail.isEmpty()) { TextView m = muted(c, detail); m.setGravity(Gravity.CENTER); m.setPadding(0, dp(6), 0, 0); root.addView(m); }
            d.setContentView(root); Window w = d.getWindow(); if (w != null) { w.setBackgroundDrawableResource(android.R.color.transparent); w.setLayout(dp(280), ViewGroup.LayoutParams.WRAP_CONTENT); w.setDimAmount(0.35f); }
            d.setCancelable(true); d.setOnDismissListener(x -> { if (after != null) after.run(); }); d.show();
            Api.ui(() -> { try { if (d.isShowing()) d.dismiss(); } catch (Exception ignore) {} }, 1400);
        } catch (Exception e) { toast(title); if (after != null) after.run(); }
    }
    public static void confirm(Context c, String msg, Runnable yes) { new AlertDialog.Builder(c).setMessage(msg).setPositiveButton("بله", (d, w) -> yes.run()).setNegativeButton("انصراف", null).show(); }
    public static void prompt(Context c, String title, String hint, boolean numeric, java.util.function.Consumer<String> cb) {
        LinearLayout l = col(c); EditText e = input(c, hint, numeric); l.addView(e);
        Dialog[] ref = new Dialog[1];
        l.addView(primary(c, "تأیید", () -> { ref[0].dismiss(); cb.accept(str(e)); }));
        ref[0] = sheet(c, title, l);
    }
    public static ImageView img(Context c, int size) { ImageView i = new ImageView(c); i.setLayoutParams(lp(dp(size), dp(size))); i.setScaleType(ImageView.ScaleType.CENTER_CROP); i.setBackground(rounded(BG2, BORDER, 12)); i.setClipToOutline(true); return i; }
    public static FrameLayout frame(Context c) { FrameLayout f = new FrameLayout(c); f.setLayoutDirection(View.LAYOUT_DIRECTION_RTL); return f; }
}
