package ir.khajavy.supermarket;

import java.util.Calendar;

/** Jalali calendar arithmetic (same algorithm as frontend/jalali.js). */
public final class Jalali {
    private Jalali() {}
    public static final String[] MONTHS = {"فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"};
    private static int div(int a, int b) { return a / b; }
    private static int mod(int a, int b) { return a - (a / b) * b; }
    private static int g2d(int gy, int gm, int gd) { int d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4) + div(153 * mod(gm + 9, 12) + 2, 5) + gd - 34840408; return d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752; }
    private static int[] d2g(int jdn) { int j = 4 * jdn + 139361631; j = j + div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908; int i = div(mod(j, 1461), 4) * 5 + 308; int gd = div(mod(i, 153), 5) + 1, gm = mod(div(i, 153), 12) + 1, gy = div(j, 1461) - 100100 + div(8 - gm, 6); return new int[]{gy, gm, gd}; }
    private static int[] jalCal(int jy) {
        int[] breaks = {-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178};
        int gy = jy + 621, leapJ = -14, jp = breaks[0], jm = 0, jump = 0, n, i;
        for (i = 1; i < breaks.length; i++) { jm = breaks[i]; jump = jm - jp; if (jy < jm) break; leapJ = leapJ + div(jump, 33) * 8 + div(mod(jump, 33), 4); jp = jm; }
        n = jy - jp; leapJ = leapJ + div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
        if (mod(jump, 33) == 4 && jump - n == 4) leapJ += 1;
        int leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150, march = 20 + leapJ - leapG;
        if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
        int leap = mod(mod(n + 1, 33) - 1, 4); if (leap == -1) leap = 4;
        return new int[]{leap, gy, march};
    }
    private static int j2d(int jy, int jm, int jd) { int[] r = jalCal(jy); return g2d(r[1], 3, r[2]) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1; }
    private static int[] d2j(int jdn) {
        int gy = d2g(jdn)[0], jy = gy - 621; int[] r = jalCal(jy); int jdn1f = g2d(gy, 3, r[2]), jd, jm, k = jdn - jdn1f;
        if (k >= 0) { if (k <= 185) { jm = 1 + div(k, 31); jd = mod(k, 31) + 1; return new int[]{jy, jm, jd}; } else k -= 186; }
        else { jy -= 1; k += 179; if (r[0] == 1) k += 1; }
        jm = 7 + div(k, 30); jd = mod(k, 30) + 1; return new int[]{jy, jm, jd};
    }
    public static int[] toJalali(int gy, int gm, int gd) { return d2j(g2d(gy, gm, gd)); }
    public static int[] toGregorian(int jy, int jm, int jd) { return d2g(j2d(jy, jm, jd)); }
    public static int monthLength(int jy, int jm) { if (jm <= 6) return 31; if (jm <= 11) return 30; return jalCal(jy)[0] == 0 ? 30 : 29; }
    /** "1404/06/18" (Persian or Latin digits) → "2025-09-09" or null. */
    public static String toIso(String j) {
        String s = Db.norm(j); String[] p = s.split("[/\\-.]"); if (p.length != 3) return null;
        try { int jy = Integer.parseInt(p[0]), jm = Integer.parseInt(p[1]), jd = Integer.parseInt(p[2]); if (jm < 1 || jm > 12 || jd < 1 || jd > monthLength(jy, jm)) return null; int[] g = toGregorian(jy, jm, jd); return String.format("%04d-%02d-%02d", g[0], g[1], g[2]); } catch (Exception e) { return null; }
    }
    public static String todayIso() { Calendar c = Calendar.getInstance(); return String.format("%04d-%02d-%02d", c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH)); }
    public static String daysAgoIso(int days) { Calendar c = Calendar.getInstance(); c.add(Calendar.DAY_OF_MONTH, -days); return String.format("%04d-%02d-%02d", c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH)); }
    public static String todayLong() { Calendar c = Calendar.getInstance(); int[] j = toJalali(c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH)); String[] wd = {"یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه"}; return wd[c.get(Calendar.DAY_OF_WEEK) - 1] + " " + Ui.fa(String.valueOf(j[2])) + " " + MONTHS[j[1] - 1] + " " + Ui.fa(String.valueOf(j[0])); }
}
