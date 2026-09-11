package ir.khajavy.supermarket;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/**
 * v2.3 — the one-time first-store installation (the long loading of the setup
 * wizard) runs as a FOREGROUND SERVICE, so the user can leave the app, lock the
 * phone or take a call: progress keeps running and is shown as a live progress
 * notification in the status bar («در حال نصب سامانه ۳۷٪»). Re-opening the app
 * resumes the same screen at the same percentage (start time and duration are
 * persisted in Prefs: install_t0 / install_total). When it finishes the setup is
 * marked done and a «آماده است» notification opens the app.
 */
public final class InstallService extends Service {
    public static final String CH = "install";
    static final int NID = 120;
    final Handler h = new Handler(Looper.getMainLooper());
    Runnable tick;
    NotificationManager nm;

    public static void start(Context c, long totalMs) {
        if (Prefs.get("install_t0", "").isEmpty()) { Prefs.set("install_t0", String.valueOf(System.currentTimeMillis())); Prefs.set("install_total", String.valueOf(totalMs)); }
        Intent i = new Intent(c, InstallService.class);
        if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i); else c.startService(i);
    }
    public static boolean running() { return !Prefs.get("install_t0", "").isEmpty() && !"1".equals(Prefs.get("first_loading_done", "")); }
    public static double progress() { try { long t0 = Long.parseLong(Prefs.get("install_t0", "0")), tot = Long.parseLong(Prefs.get("install_total", "1")); return Math.min(1.0, (System.currentTimeMillis() - t0) / (double) Math.max(1, tot)); } catch (Exception e) { return 0; } }
    /** eased percentage (same curve as the on-screen loading). */
    public static int percent() { double p = progress(); double eased = p < 0.9 ? Math.pow(p, 0.85) * 0.92 : 0.92 + (p - 0.9) * 0.8; return (int) Math.min(100, Math.round(eased * 100)); }

    @Override public void onCreate() {
        super.onCreate(); Prefs.init(this); Db.init(this); Ui.init(this);
        nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) { NotificationChannel ch = new NotificationChannel(CH, "نصب اولیهٔ سامانه", NotificationManager.IMPORTANCE_LOW); ch.setSound(null, null); nm.createNotificationChannel(ch); }
        startForeground(NID, build(percent(), false));
        // the real work (starter catalogue import) happens once, early, on a worker thread
        Api.bg(() -> { try { if ("1".equals(Prefs.get("install_starter", "")) && Db.count("products") == 0) { Db.importStarter(this); Images.kick(); } } catch (Exception ignore) {} Prefs.set("install_work_done", "1"); });
        tick = () -> {
            int pc = percent();
            if (progress() >= 1 && "1".equals(Prefs.get("install_work_done", ""))) { finish(); return; }
            nm.notify(NID, build(pc, false)); h.postDelayed(tick, 4000);
        };
        h.post(tick);
    }
    void finish() {
        Prefs.set("first_loading_done", "1"); Prefs.set("setup_done", "1"); Prefs.set("install_t0", "");
        nm.notify(NID + 1, build(100, true)); Sfx.play("success");
        stopForeground(true); stopSelf();
    }
    Notification build(int pc, boolean done) {
        Intent i = new Intent(this, done ? AppActivity.class : SetupActivity.class); i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(this, 5, i, PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, done ? Notify.CH_SYSTEM : CH) : new Notification.Builder(this);
        b.setSmallIcon(android.R.drawable.stat_sys_download_done).setContentIntent(pi).setOngoing(!done).setOnlyAlertOnce(true).setColor(Ui.TEAL);
        if (done) b.setContentTitle("سوپری من آماده است ✓").setContentText("نصب اولیه کامل شد — برای شروع لمس کنید").setAutoCancel(true);
        else b.setContentTitle("در حال نصب و پیکربندی سامانه · " + Ui.fa(String.valueOf(pc)) + "٪").setContentText(SetupActivity.phaseAt(pc / 100.0) + " — می‌توانید برنامه را ببندید").setProgress(100, pc, false);
        return b.build();
    }
    @Override public int onStartCommand(Intent i, int f, int id) { return START_STICKY; }
    @Override public void onDestroy() { h.removeCallbacksAndMessages(null); super.onDestroy(); }
    @Override public IBinder onBind(Intent i) { return null; }
}
