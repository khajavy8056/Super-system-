package ir.khajavy.supermarket;

import android.app.Dialog;
import android.content.Context;
import android.graphics.Color;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.GridLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.Calendar;
import java.util.function.Consumer;

/**
 * v2.1 — native Jalali (شمسی) calendar picker. Every date field in the app is a
 * read-only box that opens this sheet: month grid, ‹ › month navigation, year
 * chips, «امروز» and «پاک کردن». Returns the value as "۱۴۰۴/۰۶/۱۸" in the box
 * (what {@code Screen.dateIn} already parses to ISO).
 */
public final class DatePicker {
    private DatePicker() {}
    private static final String[] WD = {"ش", "ی", "د", "س", "چ", "پ", "ج"};

    /** A date "input": tap → calendar. Optional {@code initialIso} pre-fills. */
    public static EditText field(Context c, String hint, String initialIso) {
        EditText e = Ui.input(c, hint, true);
        e.setFocusable(false); e.setClickable(true); e.setCursorVisible(false); e.setLongClickable(false);
        e.setCompoundDrawablePadding(Ui.dp(8));
        e.setHint(hint + "  📅");
        if (initialIso != null && initialIso.length() >= 10) e.setText(fmt(Jalali.toJalali(Integer.parseInt(initialIso.substring(0, 4)), Integer.parseInt(initialIso.substring(5, 7)), Integer.parseInt(initialIso.substring(8, 10)))));
        e.setOnClickListener(v -> open(c, hint, Ui.str(e), j -> e.setText(j == null ? "" : fmt(j))));
        return e;
    }
    public static EditText field(Context c, String hint) { return field(c, hint, null); }

    static String fmt(int[] j) { return Ui.fa(String.format(java.util.Locale.US, "%04d/%02d/%02d", j[0], j[1], j[2])); }

    /** Opens the sheet; cb receives {jy,jm,jd} or null when cleared. */
    public static void open(Context c, String title, String current, Consumer<int[]> cb) {
        Calendar cal = Calendar.getInstance();
        int[] today = Jalali.toJalali(cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, cal.get(Calendar.DAY_OF_MONTH));
        int[] sel = null;
        if (current != null && !current.isEmpty()) { String iso = Jalali.toIso(current); if (iso != null) sel = Jalali.toJalali(Integer.parseInt(iso.substring(0, 4)), Integer.parseInt(iso.substring(5, 7)), Integer.parseInt(iso.substring(8, 10))); }
        final int[] view = {sel == null ? today[0] : sel[0], sel == null ? today[1] : sel[1]};
        final int[] picked = sel == null ? null : sel.clone();
        LinearLayout root = Ui.col(c);
        LinearLayout nav = Ui.row(c);
        TextView prev = navBtn(c, "‹"), next = navBtn(c, "›");
        TextView head = Ui.text(c, "", 16, Ui.TEXT, true); head.setGravity(Gravity.CENTER); head.setLayoutParams(Ui.weight(1));
        nav.addView(next); nav.addView(head); nav.addView(prev);   // RTL row: next (›) on the left visually
        root.addView(nav);
        LinearLayout years = Ui.row(c);
        root.addView(Ui.chips(c, years));
        GridLayout grid = new GridLayout(c); grid.setColumnCount(7); grid.setLayoutDirection(View.LAYOUT_DIRECTION_RTL); grid.setLayoutParams(Ui.margin(Ui.match(), 0, 8, 0, 8));
        root.addView(grid);
        TextView chosen = Ui.muted(c, ""); chosen.setGravity(Gravity.CENTER); root.addView(chosen);
        Dialog[] d = new Dialog[1];
        Runnable[] draw = new Runnable[1];
        draw[0] = () -> {
            head.setText(Jalali.MONTHS[view[1] - 1] + " " + Ui.fa(String.valueOf(view[0])));
            years.removeAllViews();
            for (int y = today[0] - 3; y <= today[0] + 6; y++) { final int yy = y; years.addView(Ui.chip(c, Ui.fa(String.valueOf(y)), y == view[0], () -> { view[0] = yy; draw[0].run(); })); }
            grid.removeAllViews();
            int cell = (c.getResources().getDisplayMetrics().widthPixels - Ui.dp(48)) / 7;
            for (String w : WD) { TextView t = Ui.text(c, w, 12, Ui.MUTED, true); t.setGravity(Gravity.CENTER); GridLayout.LayoutParams lp = new GridLayout.LayoutParams(); lp.width = cell; lp.height = Ui.dp(28); t.setLayoutParams(lp); grid.addView(t); }
            int[] g1 = Jalali.toGregorian(view[0], view[1], 1);
            Calendar f = Calendar.getInstance(); f.set(g1[0], g1[1] - 1, g1[2]);
            int dow = (f.get(Calendar.DAY_OF_WEEK) % 7); // Saturday=0
            for (int i = 0; i < dow; i++) { View sp = new View(c); GridLayout.LayoutParams lp = new GridLayout.LayoutParams(); lp.width = cell; lp.height = cell; sp.setLayoutParams(lp); grid.addView(sp); }
            int len = Jalali.monthLength(view[0], view[1]);
            for (int day = 1; day <= len; day++) {
                final int dd = day;
                boolean isToday = view[0] == today[0] && view[1] == today[1] && day == today[2];
                boolean isSel = picked != null && picked[0] == view[0] && picked[1] == view[1] && picked[2] == day;
                boolean friday = ((dow + day - 1) % 7) == 6;
                TextView t = Ui.text(c, Ui.fa(String.valueOf(day)), 14, isSel ? Color.WHITE : friday ? Ui.RED : Ui.TEXT, isSel || isToday);
                t.setGravity(Gravity.CENTER);
                GridLayout.LayoutParams lp = new GridLayout.LayoutParams(); lp.width = cell; lp.height = cell; lp.setMargins(Ui.dp(2), Ui.dp(2), Ui.dp(2), Ui.dp(2)); t.setLayoutParams(lp);
                t.setBackground(Ui.rounded(isSel ? Ui.PRIMARY : Color.TRANSPARENT, isToday && !isSel ? Ui.PRIMARY : 0, 12));
                t.setOnClickListener(v -> { int[] r = {view[0], view[1], dd}; d[0].dismiss(); cb.accept(r); });
                grid.addView(t);
            }
            chosen.setText(picked == null ? "تاریخی انتخاب نشده" : "انتخاب فعلی: " + fmt(picked));
        };
        prev.setOnClickListener(v -> { if (--view[1] < 1) { view[1] = 12; view[0]--; } draw[0].run(); });
        next.setOnClickListener(v -> { if (++view[1] > 12) { view[1] = 1; view[0]++; } draw[0].run(); });
        LinearLayout foot = Ui.row(c);
        Button2 tdy = new Button2(c, "امروز", () -> { d[0].dismiss(); cb.accept(today); });
        Button2 clr = new Button2(c, "پاک کردن", () -> { d[0].dismiss(); cb.accept(null); });
        foot.addView(tdy.v); foot.addView(Ui.space(c, 0)); foot.addView(clr.v);
        root.addView(foot);
        draw[0].run();
        d[0] = Ui.sheet(c, title == null ? "انتخاب تاریخ" : title, root);
    }
    private static TextView navBtn(Context c, String s) { TextView t = Ui.text(c, s, 24, Ui.PRIMARY, true); t.setGravity(Gravity.CENTER); t.setLayoutParams(Ui.lp(Ui.dp(44), Ui.dp(44))); t.setBackground(Ui.rounded(Ui.CARD, Ui.BORDER, 12)); return t; }
    /** tiny holder so footer buttons share weight. */
    private static final class Button2 { final View v; Button2(Context c, String s, Runnable r) { android.widget.Button b = Ui.ghost(c, s, r); LinearLayout.LayoutParams lp = Ui.weight(1); lp.setMargins(Ui.dp(4), 0, Ui.dp(4), 0); b.setLayoutParams(lp); v = b; } }
}
