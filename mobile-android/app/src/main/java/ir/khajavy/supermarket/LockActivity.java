package ir.khajavy.supermarket;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * v2.1 — «لایسنس شما به پایان رسیده». Shown whenever {@link Lic#allowed()} is
 * false (PC licence expired/revoked, or the phone's own key expired). Nothing
 * else is reachable: only the support contact and — in standalone mode — a
 * field to enter a new key. Data on the phone is kept.
 */
public class LockActivity extends Activity {
    static volatile boolean showing = false;
    static volatile Activity top;

    public static void showIfNeeded() {
        if (Lic.allowed() || showing) return;
        Activity a = top; if (a == null || a.isFinishing()) return;
        showing = true; a.startActivity(new Intent(a, LockActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
    }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b); Prefs.init(this); Db.init(this); Ui.init(this); top = this;
        getWindow().setStatusBarColor(Ui.BG); getWindow().setNavigationBarColor(Ui.BG);
        LinearLayout root = Ui.col(this); root.setBackgroundColor(Ui.BG); root.setPadding(Ui.dp(24), Ui.dp(56), Ui.dp(24), Ui.dp(24)); root.setGravity(Gravity.CENTER_HORIZONTAL);
        ImageView logo = new ImageView(this); logo.setImageResource(R.mipmap.ic_launcher); logo.setLayoutParams(Ui.lp(Ui.dp(84), Ui.dp(84))); logo.setAlpha(0.5f); root.addView(logo);
        TextView t = Ui.text(this, "لایسنس شما به پایان رسیده", 22, Ui.RED, true); t.setGravity(Gravity.CENTER); t.setPadding(0, Ui.dp(18), 0, Ui.dp(6)); root.addView(t);
        TextView r = Ui.body(this, Lic.reason()); r.setGravity(Gravity.CENTER); root.addView(r);
        root.addView(Ui.space(this, 16));
        LinearLayout cd = Ui.card(this, null);
        if ("pc".equals(Lic.mode())) cd.addView(Ui.body(this, "این گوشی به رایانهٔ فروشگاه متصل است و اعتبار آن با لایسنس رایانه یکی است. پس از تمدید لایسنس روی رایانه، برنامه به‌صورت خودکار باز می‌شود."));
        else cd.addView(Ui.body(this, "برای ادامهٔ کار، لایسنس را تمدید کنید. اطلاعات فروشگاه روی گوشی حفظ شده و پس از فعال‌سازی در دسترس خواهد بود."));
        cd.addView(Ui.kv(this, "شناسهٔ دستگاه", Lic.hwid(), 0));
        if (!Lic.expires().isEmpty()) cd.addView(Ui.kv(this, "تاریخ انقضا", Ui.jdate(Lic.expires()), Ui.RED));
        root.addView(cd);
        root.addView(Ui.primary(this, "ارتباط با پشتیبانی", () -> startActivity(new Intent(this, SupportActivity.class))));
        if (!"pc".equals(Lic.mode())) root.addView(Ui.ghost(this, "وارد کردن کلید لایسنس جدید", () -> Ui.prompt(this, "کلید لایسنس", "XXXX-XXXX-XXXX-XXXX", false, key -> { Ui.toast("در حال بررسی…"); Api.bg(() -> { String err = Lic.activate(key); Api.ui(() -> { if (err != null) Ui.toast(err); else { Ui.toast("لایسنس فعال شد"); reopen(); } }); }); })));
        else root.addView(Ui.ghost(this, "بررسی دوباره با رایانه", () -> { Ui.toast("در حال بررسی…"); Api.bg(() -> { Sync.checkPcLicense(); Api.ui(() -> { if (Lic.allowed()) reopen(); else Ui.toast(Lic.reason()); }); }); }));
        TextView dev = Ui.muted(this, "طراحی و توسعه توسط خواجوی"); dev.setGravity(Gravity.CENTER); dev.setPadding(0, Ui.dp(18), 0, 0); root.addView(dev);
        setContentView(Ui.scroll(this, root));
    }
    void reopen() { showing = false; startActivity(new Intent(this, AppActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK)); finish(); }
    @Override protected void onResume() { super.onResume(); top = this; if (Lic.allowed()) reopen(); }
    @Override protected void onDestroy() { super.onDestroy(); showing = false; }
    @Override public void onBackPressed() { moveTaskToBack(true); }
}
