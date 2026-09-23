package ir.khajavy.supermarket;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * v4.2.1 — the ~1 GB model download keeps running WHEN THE USER CLOSES THE APP.
 *
 * The owner's rule: «الان دانلود حتی با بستن برنامه باید در پس زمینه ادامه
 * پیدا کنه». A bare thread dies with the process the moment Android reclaims
 * it; a FOREGROUND SERVICE keeps the process alive (Android will not kill a
 * process with an active foreground service under normal memory pressure) and
 * shows a live progress notification («دریافت مدل تخصصی سوپری‌من · ۳۷٪»), the
 * same pattern the first-install service (InstallService) already uses.
 *
 * The service is only the anchor + the notification; the download itself still
 * runs through {@link BrainModel}'s single resumable worker (partial file kept,
 * sha256-verified, official sources only), and every state change lands in
 * Prefs exactly as before — the Model tab keeps working unchanged.
 *
 * If the process is killed anyway, the .part file stays and the next open
 * resumes from the same byte — nothing is ever restarted from zero.
 */
public final class BrainModelService extends Service {
    public static final String CH = "model-dl";
    static final int NID = 121;

    /** Start the anchor service for the model currently being fetched. */
    public static void start(Context c, String modelId) {
        try {
            Intent i = new Intent(c, BrainModelService.class);
            i.putExtra("model_id", modelId);
            if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i); else c.startService(i);
        } catch (Throwable ignore) { /* starting must never break the download */ }
    }

    public static void stop(Context c) {
        try { c.stopService(new Intent(c, BrainModelService.class)); } catch (Throwable ignore) {}
    }

    private NotificationManager nm;
    private String modelId = "", modelTitle = "مدل مغز فروشگاه";

    @Override public void onCreate() {
        super.onCreate();
        Prefs.init(this); Ui.init(this);
        nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CH, "دریافت مدل هوش مصنوعی",
                    NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("پیشرفت دریافت مدل مغز فروشگاه");
            ch.setSound(null, null);
            nm.createNotificationChannel(ch);
        }
        // must call startForeground immediately after startForegroundService
        startForeground(NID, build(0, "در حال آماده‌سازی دریافت…", ""));
    }

    @Override public int onStartCommand(Intent i, int f, int id) {
        if (i != null && i.getStringExtra("model_id") != null) {
            modelId = i.getStringExtra("model_id");
            BrainModel.Spec s = BrainModel.find(modelId);
            if (s != null) modelTitle = s.label();
        }
        nm.notify(NID, build(0, "در حال دریافت " + modelTitle, "می‌توانید برنامه را ببندید؛ دریافت ادامه می‌یابد"));
        return START_STICKY;
    }

    /** Live progress line — called by BrainModel.putState on every UI tick. */
    public static void progress(Context c, String modelId, int pct, long done, long total, boolean verifying) {
        try {
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel ch = new NotificationChannel(CH, "دریافت مدل هوش مصنوعی",
                        NotificationManager.IMPORTANCE_LOW);
                ch.setSound(null, null);
                nm.createNotificationChannel(ch);
            }
            BrainModel.Spec s = BrainModel.find(modelId);
            String title = (s != null ? s.label() : "مدل مغز فروشگاه");
            String text = verifying
                    ? "در حال تأیید سلامت فایل · " + Ui.num(pct) + "٪"
                    : Ui.num(Math.round(done / 1048576.0)) + " از " + Ui.num(Math.round(total / 1048576.0))
                      + " مگابایت · " + Ui.num(pct) + "٪ — می‌توانید برنامه را ببندید";
            Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CH) : new Notification.Builder(c);
            b.setSmallIcon(android.R.drawable.stat_sys_download).setOngoing(true).setOnlyAlertOnce(true)
                    .setColor(Ui.PRIMARY).setContentTitle((verifying ? "تأیید " : "دریافت ") + title)
                    .setContentText(text).setProgress(100, pct, false).setContentIntent(pi(c));
            nm.notify(NID, b.build());
        } catch (Throwable ignore) {}
    }

    private static PendingIntent pi(Context c) {
        Intent i = new Intent(c, AppActivity.class);
        i.putExtra("route", "brain");
        i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(c, 6, i, PendingIntent.FLAG_UPDATE_CURRENT
                | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
    }

    private Notification build(int pct, String title, String text) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CH) : new Notification.Builder(this);
        b.setSmallIcon(android.R.drawable.stat_sys_download).setOngoing(true).setOnlyAlertOnce(true)
                .setColor(Ui.PRIMARY).setContentTitle(title).setContentText(text)
                .setProgress(100, pct, false).setContentIntent(pi(this));
        return b.build();
    }

    @Override public IBinder onBind(Intent i) { return null; }
}
