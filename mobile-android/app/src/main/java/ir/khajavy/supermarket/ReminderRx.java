package ir.khajavy.supermarket;

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

/**
 * v4.4.0 — the manager's reminders, on the phone (owner's request):
 * «نیمه‌فردا یادم بنداز … نوتیف باید بده و پاپ‌آپ بشه؛ وقتی بزنه دوباره یادآوری
 * کن، چند ساعت بعد برای مدیر پیامک بفرسته؛ اگه جواب نداد بازم پیامک کنه».
 *
 * The reminder itself is created by the brain (chat: «فردا X را یادم بنداز» →
 * the create_followup tool) on the PC. This receiver shows the due reminder as
 * a popup-style notification with two buttons:
 *
 *   • «انجام شد»      → POST /brain/reminders/{id}/ack   (the loop ends)
 *   • «دوباره یادآوری» → POST /brain/reminders/{id}/snooze {hours:2}
 *
 * Snoozing twice (or ignoring) escalates ON THE PC: the backend sends an SMS
 * to the manager's phone (setting brain.manager_phone) and keeps re-sending
 * every few hours until acknowledged — exactly the flow the owner described.
 */
public final class ReminderRx extends BroadcastReceiver {
    public static final String CH = "reminders";
    static final int NID_BASE = 1310;
    public static final String ACTION_ACK = "ir.khajavy.supermarket.REMINDER_ACK";
    public static final String ACTION_SNOOZE = "ir.khajavy.supermarket.REMINDER_SNOOZE";

    @Override public void onReceive(Context c, Intent i) {
        final int id = i.getIntExtra("id", 0);
        String action = i.getAction() == null ? "" : i.getAction();
        if (id <= 0) return;
        final PendingResult pr = goAsync();
        new Thread(() -> {
            try {
                Prefs.init(c); Db.init(c); Ui.init(c);
                Api.base = Prefs.serverUrl(c) == null ? "" : Prefs.serverUrl(c);
                Api.token = Prefs.deviceToken(c) == null ? "" : Prefs.deviceToken(c);
                if (ACTION_ACK.equals(action)) {
                    Api.call("POST", "/brain/reminders/" + id + "/ack", "{}", "application/json");
                    Ui.toast("یادآوری «انجام شد» علامت خورد");
                    cancel(c, id);
                } else if (ACTION_SNOOZE.equals(action)) {
                    Api.call("POST", "/brain/reminders/" + id + "/snooze",
                             "{\"hours\":2}", "application/json");
                    Ui.toast("دوباره یادآوری می‌کنم — اگر پاسخ ندهید برای مدیر پیامک می‌رود");
                    cancel(c, id);
                }
            } catch (Exception e) {
                Ui.toast("یادآوری به‌روز نشد: " + e.getMessage());
            } finally { pr.finish(); }
        }, "reminder-rx").start();
    }

    static void cancel(Context c, int id) {
        try {
            ((NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE)).cancel(NID_BASE + id);
        } catch (Exception ignore) {}
    }

    /** The popup notification for ONE due reminder, with its two action buttons. */
    public static void show(Context c, int id, String title, String note, String dueFa) {
        try {
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel ch = new NotificationChannel(CH, "یادآوری‌های مغز فروشگاه",
                        NotificationManager.IMPORTANCE_HIGH);
                ch.setDescription("یادآوری‌هایی که از مغز فروشگاه خواسته‌اید");
                nm.createNotificationChannel(ch);
            }
            Intent open = new Intent(c, AppActivity.class);
            open.putExtra("route", "brain");
            open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent pi = PendingIntent.getActivity(c, id, open, PendingIntent.FLAG_UPDATE_CURRENT
                    | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
            PendingIntent ack = PendingIntent.getBroadcast(c, id,
                    new Intent(c, ReminderRx.class).setAction(ACTION_ACK).putExtra("id", id),
                    PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
            PendingIntent snooze = PendingIntent.getBroadcast(c, 1000 + id,
                    new Intent(c, ReminderRx.class).setAction(ACTION_SNOOZE).putExtra("id", id),
                    PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
            Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CH) : new Notification.Builder(c);
            b.setSmallIcon(android.R.drawable.ic_dialog_info).setColor(Ui.GOLD)
                    .setContentTitle("یادآوری: " + title)
                    .setContentText((note == null || note.isEmpty() ? "" : note + " — ") + dueFa)
                    .setStyle(new Notification.BigTextStyle().bigText((note == null ? "" : note + "\n") + dueFa
                            + "\nاگر پاسخ ندهید، برای مدیر پیامک یادآوری ارسال می‌شود."))
                    .setContentIntent(pi).setAutoCancel(true)
                    .addAction(new Notification.Action.Builder(null, "انجام شد", ack).build())
                    .addAction(new Notification.Action.Builder(null, "دوباره یادآوری (۲ ساعت)", snooze).build());
            nm.notify(NID_BASE + id, b.build());
        } catch (Exception ignore) {}
    }

    /** Poll the PC for due reminders (called from the periodic Checker). */
    public static void poll(Context c) {
        if (Api.standalone()) return;   // Api.call itself marks offline and never throws out
        try {
            Object r = Api.call("GET", "/brain/reminders/due", null, null);
            JSONObject o = r instanceof JSONObject ? (JSONObject) r : null;
            JSONArray a = o != null ? o.optJSONArray("reminders") : null;
            if (a == null) return;
            for (int i = 0; i < a.length() && i < 5; i++) {
                JSONObject f = a.optJSONObject(i);
                if (f == null) continue;
                show(c, f.optInt("id", 0), f.optString("title", "یادآوری"),
                     f.optString("note", ""), "سررسید: " + Ui.jdate(f.optString("due_at", "")));
            }
        } catch (Exception ignore) {}
    }
}
