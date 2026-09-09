package ir.khajavy.supermarket;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;

/**
 * v2.2 — system (status-bar) notifications for the phone, like the PC's alert center:
 *  • پاسخ پشتیبانی      — vendor replied to a ticket (relay or PC)
 *  • نزدیک انقضا / منقضی — batches with stock reaching expiry
 *  • کمبود موجودی        — products at/below their alert threshold
 *  • همگام‌سازی          — rejected ops that need attention
 * Three channels so the user can mute each kind in Android settings. Soft sounds come
 * from {@link Sfx}; the channels themselves are silent so nothing plays twice.
 * A repeating inexact alarm (every ~30 min, survives app close; re-armed at boot) runs
 * {@link Checker} without any Gradle/WorkManager dependency.
 */
public final class Notify {
    private Notify() {}
    public static final String CH_SUPPORT = "support", CH_STOCK = "stock", CH_SYSTEM = "system";
    private static final int ID_SUPPORT = 101, ID_EXPIRY = 102, ID_LOW = 103, ID_SYNC = 104;
    public static final int REQ_PERMISSION = 77;

    public static void channels(Context c) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        nm.createNotificationChannel(silent(new NotificationChannel(CH_SUPPORT, "پاسخ پشتیبانی", NotificationManager.IMPORTANCE_HIGH), "پاسخ کارشناس پشتیبانی به درخواست‌های شما"));
        nm.createNotificationChannel(silent(new NotificationChannel(CH_STOCK, "انقضا و موجودی", NotificationManager.IMPORTANCE_DEFAULT), "کالاهای نزدیک انقضا و کمبود موجودی"));
        nm.createNotificationChannel(silent(new NotificationChannel(CH_SYSTEM, "سامانه و همگام‌سازی", NotificationManager.IMPORTANCE_LOW), "وضعیت همگام‌سازی و پیام‌های سامانه"));
    }
    private static NotificationChannel silent(NotificationChannel ch, String desc) { ch.setDescription(desc); ch.setSound(null, null); ch.enableVibration(true); return ch; }

    /** Android 13+: ask once for POST_NOTIFICATIONS (must be called from an Activity). */
    public static void askPermission(android.app.Activity a) {
        if (Build.VERSION.SDK_INT < 33) return;
        if (a.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != android.content.pm.PackageManager.PERMISSION_GRANTED && !"1".equals(Prefs.get("notif_asked", "")))
            { Prefs.set("notif_asked", "1"); a.requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, REQ_PERMISSION); }
    }
    public static boolean enabled(String kind) { return !"0".equals(Prefs.get("notif_" + kind, "1")); }

    public static void show(Context c, String channel, int id, String title, String text, String route, String sound) {
        if (!enabled(channel)) return;
        try {
            channels(c);
            Intent i = new Intent(c, AppActivity.class); i.putExtra("route", route); i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent pi = PendingIntent.getActivity(c, id, i, PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
            Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, channel) : new Notification.Builder(c);
            b.setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title).setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text)).setAutoCancel(true).setContentIntent(pi).setColor(Ui.TEAL);
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE); nm.notify(id, b.build());
            if (sound != null) Sfx.play(sound);
        } catch (Throwable ignore) {}
    }

    /* ---------------- checks ---------------- */
    public static void supportReply(Context c, int n) { show(c, CH_SUPPORT, ID_SUPPORT, "پاسخ جدید از پشتیبانی", Ui.fa(String.valueOf(n)) + " پاسخ جدید دریافت شد — برای مشاهده لمس کنید", "support", "alert"); }

    /** local (SQLite) checks — work in standalone AND paired mode, no network needed. */
    public static void checkLocal(Context c) {
        try {
            String day = Db.now().substring(0, 10);
            if (!day.equals(Prefs.get("notif_expiry_day", ""))) {
                List<String> ex = Db.expiringNames(7, 4); int nx = Db.expiringCount(0), ne = Db.expiringCount(7);
                if (nx + ne > 0) { show(c, CH_STOCK, ID_EXPIRY, nx > 0 ? "کالای منقضی‌شده در انبار" : "کالاهای نزدیک انقضا", (nx > 0 ? Ui.fa(String.valueOf(nx)) + " بچ منقضی · " : "") + Ui.fa(String.valueOf(ne)) + " بچ تا ۷ روز آینده: " + join(ex), "inventory", "alert"); Prefs.set("notif_expiry_day", day); }
                List<String> low = Db.lowStockNames(4);
                if (!low.isEmpty()) { show(c, CH_STOCK, ID_LOW, "کمبود موجودی", join(low), "inventory", "note"); }
            }
        } catch (Throwable ignore) {}
    }
    /** paired mode: PC-side support inbox (unread vendor replies). */
    public static void checkPcSupport(Context c) {
        if (Api.standalone() || !Api.online) return;
        try {
            Object r = Api.call("GET", "/support/tickets?limit=50", null, null); JSONArray a = r instanceof JSONArray ? (JSONArray) r : new JSONArray(); int unread = 0;
            for (int i = 0; i < a.length(); i++) { JSONObject t = a.optJSONObject(i); unread += t.optInt("unread", t.optInt("unread_count", 0)); }
            int seen = Integer.parseInt(Prefs.get("notif_support_seen", "0"));
            if (unread > seen) supportReply(c, unread - seen);
            Prefs.set("notif_support_seen", String.valueOf(unread));
        } catch (Throwable ignore) {}
    }
    public static void syncProblem(Context c, int rejected) { show(c, CH_SYSTEM, ID_SYNC, "همگام‌سازی نیاز به بررسی دارد", Ui.fa(String.valueOf(rejected)) + " مورد توسط رایانه رد شد — بخش همگام‌سازی را ببینید", "sync", "error"); }
    private static String join(List<String> l) { StringBuilder b = new StringBuilder(); for (String s : l) { if (b.length() > 0) b.append("، "); b.append(s); } return b.toString(); }

    /* ---------------- periodic background check ---------------- */
    public static void schedule(Context c) {
        try {
            AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
            PendingIntent pi = PendingIntent.getBroadcast(c, 1, new Intent(c, Checker.class), PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
            am.setInexactRepeating(AlarmManager.ELAPSED_REALTIME, android.os.SystemClock.elapsedRealtime() + 60_000L, AlarmManager.INTERVAL_HALF_HOUR, pi);
        } catch (Throwable ignore) {}
    }
    /** runs every ~30 min (and on BOOT_COMPLETED) even when the app is closed. */
    public static final class Checker extends BroadcastReceiver {
        @Override public void onReceive(Context c, Intent i) {
            final PendingResult pr = goAsync();
            new Thread(() -> {
                try {
                    Prefs.init(c); Db.init(c); Ui.init(c);
                    if (Intent.ACTION_BOOT_COMPLETED.equals(i.getAction())) { schedule(c); }
                    if (!"1".equals(Prefs.get("setup_done", ""))) return;
                    Api.base = Prefs.serverUrl(c) == null ? "" : Prefs.serverUrl(c); Api.token = Prefs.deviceToken(c) == null ? "" : Prefs.deviceToken(c);
                    checkLocal(c);
                    if (Api.standalone() || !Lic.allowed()) { int n = SupportRelay.poll(); if (n > 0) supportReply(c, n); }
                    else { Api.online = Api.health(); checkPcSupport(c); }
                } catch (Throwable ignore) {} finally { pr.finish(); }
            }).start();
        }
    }
}
