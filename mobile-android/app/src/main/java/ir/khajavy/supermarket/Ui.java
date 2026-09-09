package ir.khajavy.supermarket;

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
    public static Typeface FONT, FONT_BOLD;
    private static float density = 2f;
    public static boolean dark = true;

    // palette (calm, no neon — the user's rule)
    public static int BG, BG2, CARD, BORDER, TEXT, MUTED, PRIMARY, GREEN, RED, AMBER, VIOLET, TEAL;

    public static void init(Context c) {
        ctx = c.getApplicationContext(); density = c.getResources().getDisplayMetrics().density;
        try { FONT = Typeface.createFromAsset(c.getAssets(), "fonts/Vazirmatn-Regular.ttf"); FONT_BOLD = Typeface.createFromAsset(c.getAssets(), "fonts/Vazirmatn-Bold.ttf"); } catch (Exception e) { FONT = Typeface.DEFAULT; FONT_BOLD = Typeface.DEFAULT_BOLD; }
        setTheme(!"light".equals(Prefs.get("theme_resolved", "dark")));
    }
    public static void setTheme(boolean isDark) {
        dark = isDark;
        if (dark) { BG = 0xFF0F1420; BG2 = 0xFF171E2E; CARD = 0xFF1C2437; BORDER = 0xFF2A3550; TEXT = 0xFFE8ECF5; MUTED = 0xFF8B95AC; }
        else { BG = 0xFFF4F6FB; BG2 = 0xFFFFFFFF; CARD = 0xFFFFFFFF; BORDER = 0xFFD8DEEA; TEXT = 0xFF13192A; MUTED = 0xFF66708A; }
        PRIMARY = 0xFF3B82F6; GREEN = 0xFF2FB673; RED = 0xFFE5484D; AMBER = 0xFFE9A23B; VIOLET = 0xFF7C5CFF; TEAL = 0xFF2BB5A8;
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
    public static LinearLayout card(Context c) { LinearLayout l = col(c); l.setBackground(rounded(CARD, BORDER, 18)); l.setPadding(dp(14), dp(14), dp(14), dp(14)); l.setElevation(dp(2)); l.setLayoutParams(margin(match(), 0, 0, 0, 12)); return l; }
    /** card containing a single muted note. */
    public static LinearLayout note(Context c, String title, String text) { LinearLayout l = card(c, title); l.addView(muted(c, text)); return l; }
    public static LinearLayout card(Context c, String title) { LinearLayout l = card(c); if (title != null) l.addView(h2(c, title)); return l; }
    public static ScrollView scroll(Context c, View inner) { ScrollView s = new ScrollView(c); s.setFillViewport(true); s.setVerticalScrollBarEnabled(false); s.addView(inner); return s; }
    public static View divider(Context c) { View v = new View(c); v.setBackgroundColor(BORDER); v.setLayoutParams(margin(lp(ViewGroup.LayoutParams.MATCH_PARENT, dp(1)), 0, 8, 0, 8)); return v; }
    public static View space(Context c, int h) { View v = new View(c); v.setLayoutParams(lp(ViewGroup.LayoutParams.MATCH_PARENT, dp(h))); return v; }

    /* ---------------- inputs ---------------- */
    public static EditText input(Context c, String hint, boolean numeric) {
        EditText e = new EditText(c); e.setHint(hint); e.setTypeface(FONT); e.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15); e.setTextColor(TEXT); e.setHintTextColor(MUTED);
        e.setBackground(rounded(BG2, BORDER, 12)); e.setPadding(dp(12), dp(11), dp(12), dp(11)); e.setLayoutParams(margin(match(), 0, 0, 0, 6));
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
        b.setBackground(new RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), rounded(fill, fill == CARD || fill == BG2 ? BORDER : 0, 12), null));
        b.setMinHeight(dp(44)); b.setMinimumHeight(dp(44)); b.setPadding(dp(14), 0, dp(14), 0); b.setStateListAnimator(null); b.setElevation(0);
        b.setLayoutParams(margin(match(), 0, 4, 0, 4)); if (onClick != null) b.setOnClickListener(v -> onClick.run()); return b;
    }
    public static Button primary(Context c, String s, Runnable r) { return btn(c, s, PRIMARY, Color.WHITE, r); }
    public static Button success(Context c, String s, Runnable r) { return btn(c, s, GREEN, Color.WHITE, r); }
    public static Button danger(Context c, String s, Runnable r) { return btn(c, s, 0x22E5484D, RED, r); }
    public static Button ghost(Context c, String s, Runnable r) { return btn(c, s, BG2, TEXT, r); }
    public static Button small(Context c, String s, Runnable r) { Button b = ghost(c, s, r); b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12); b.setMinHeight(dp(34)); b.setMinimumHeight(dp(34)); b.setLayoutParams(margin(lp(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT), 4, 2, 0, 2)); return b; }
    public static Button chip(Context c, String s, boolean active, Runnable r) { Button b = small(c, s, r); b.setBackground(rounded(active ? PRIMARY : BG2, active ? 0 : BORDER, 20)); b.setTextColor(active ? Color.WHITE : TEXT); return b; }

    /* ---------------- list rows ---------------- */
    /** two-line list row (title / subtitle) with an optional trailing value and click. */
    public static LinearLayout item(Context c, String title, String sub, String trailing, int trailingColor, Runnable onClick) {
        LinearLayout r = row(c); r.setBackground(new RippleDrawable(ColorStateList.valueOf(0x22FFFFFF), rounded(CARD, BORDER, 14), null)); r.setPadding(dp(12), dp(10), dp(12), dp(10)); r.setLayoutParams(margin(match(), 0, 0, 0, 8));
        LinearLayout col = col(c); col.addView(text(c, title, 14, TEXT, true)); if (sub != null && !sub.isEmpty()) { TextView s = muted(c, sub); s.setPadding(0, dp(2), 0, 0); col.addView(s); }
        col.setLayoutParams(weight(1)); r.addView(col);
        if (trailing != null) { TextView t = text(c, trailing, 14, trailingColor == 0 ? TEXT : trailingColor, true); t.setGravity(Gravity.END); t.setPadding(dp(8), 0, 0, 0); r.addView(t); }
        if (onClick != null) { r.setClickable(true); r.setOnClickListener(v -> onClick.run()); }
        return r;
    }
    /** key/value line inside a card. */
    public static LinearLayout kv(Context c, String k, String v, int vColor) {
        LinearLayout r = row(c); r.setPadding(0, dp(5), 0, dp(5));
        TextView kt = muted(c, k); kt.setLayoutParams(weight(1)); r.addView(kt);
        TextView vt = text(c, v, 13, vColor == 0 ? TEXT : vColor, true); r.addView(vt); return r;
    }
    /** KPI tile. */
    public static LinearLayout kpi(Context c, String label, String value, String sub, int accent) {
        LinearLayout l = col(c); l.setBackground(rounded(CARD, BORDER, 16)); l.setPadding(dp(12), dp(12), dp(12), dp(12));
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
        LinearLayout root = col(c); root.setBackground(rounded(BG2, 0, 22)); root.setPadding(dp(16), dp(10), dp(16), dp(20));
        View handle = new View(c); handle.setBackground(rounded(BORDER, 0, 2)); LinearLayout.LayoutParams hp = lp(dp(44), dp(4)); hp.gravity = Gravity.CENTER_HORIZONTAL; hp.bottomMargin = dp(12); handle.setLayoutParams(hp); root.addView(handle);
        if (title != null) { TextView t = h1(c, title); t.setPadding(0, 0, 0, dp(10)); root.addView(t); }
        ScrollView sv = new ScrollView(c); sv.addView(content); sv.setLayoutParams(lp(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)); root.addView(sv);
        d.setContentView(root);
        Window w = d.getWindow();
        if (w != null) { w.setBackgroundDrawableResource(android.R.color.transparent); w.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT); w.setGravity(Gravity.BOTTOM); w.setWindowAnimations(android.R.style.Animation_InputMethod); w.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE); }
        d.show(); return d;
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
