package ir.khajavy.supermarket;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/** v2.0 — sign in to the PC with a store user (alternative to QR pairing, and re-login after logout).
 *
 *  v3.5.11 — this screen is what the 30-minute idle lock sends the user to, so it runs many times
 *  a day. It used to mint a fresh device token and a fresh device_id on EVERY sign-in, which grew
 *  the PC's paired-device list without bound and, because the device id fed {@link Lic#hwid()},
 *  kept changing the phone's licence identity. It now always offers the id it already has so the
 *  PC refreshes that row instead of appending one, and never invents a time-based id.
 *
 *  v4.8.1 (بیلد ۴۸۲) — جفت‌شدن «دائمی» است:
 *   ۱) همان کاربر/رمزِ رایانه، بدون حضور رایانه هم وارد می‌شود اگر مدیر برای حساب
 *      «ورود آفلاین» را جداگانه مجاز کرده باشد (رمزسنج محلی در {@link Local#cacheUser}) — بی‌نیاز از بارکد.
 *   ۲) اگر رایانه IP عوض کرده/راه‌اندازی مجدد شده، خودکار از راه کلید اتصال (Discovery)
 *      پیدا می‌شود و ورود آنلاین دوباره برقرار می‌شود.
 *   ۳) توکن دستگاه برای «دستگاه آشنا» با هر ورود تازه می‌شود (بدون نیاز به مدیر).
 *   ۴) سیاست «دسترسی فقط به صورت بومی»: کاربر عادیِ local_only فقط وقتی وارد می‌شود که
 *      ورود از داخل شبکهٔ فروشگاه (مسیر lan) تأیید شده باشد؛ مدیر اصلی همیشه آزاد است. */
public class LoginActivity extends Activity {
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b); Prefs.init(this); Db.init(this); Ui.init(this); LockActivity.top = this;
        String url = getIntent().getStringExtra("url"); if (url == null) url = Prefs.serverUrl(this); final String base = url == null ? "" : url;
        getWindow().setStatusBarColor(Ui.BG);
        LinearLayout root = Ui.col(this); root.setBackground(new WelcomeBackdrop()); root.setPadding(Ui.dp(22), Ui.dp(64), Ui.dp(22), Ui.dp(24)); root.setGravity(Gravity.CENTER_HORIZONTAL);
        // v1.0.0 (RASA) — نشان برند روی صفحهٔ ورود (پیش‌تر یک «سبد خرید» عمومی بود؛
        // نشان این محصول باید همان نشان رسا سیستم باشد که لانچر هم دارد).
        ImageView logo = new ImageView(this); logo.setImageResource(R.mipmap.ic_launcher); logo.setLayoutParams(Ui.lp(Ui.dp(84), Ui.dp(84))); root.addView(logo);
        TextView t = Ui.text(this, "ورود به " + Prefs.get("store_name", "فروشگاه"), 19, Ui.TEXT, true); t.setGravity(Gravity.CENTER); t.setPadding(0, Ui.dp(12), 0, Ui.dp(2)); root.addView(t);
        TextView u = Ui.muted(this, base.contains("standalone.invalid") ? "حالت مستقل — کاربران همین گوشی" : base); u.setGravity(Gravity.CENTER); root.addView(u); root.addView(Ui.space(this, 18));
        LinearLayout cd = Ui.col(this); cd.setLayoutParams(Ui.match()); cd.setPadding(0, Ui.dp(24), 0, Ui.dp(12)); final EditText user = Ui.input(this, "نام کاربری"); final EditText pass = Ui.input(this, "رمز عبور"); pass.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD); cd.addView(user); cd.addView(pass); final TextView st = Ui.muted(this, "");
        cd.addView(Ui.primary(this, "ورود", () -> {
            st.setText("در حال ورود…");
            Api.base = base;
            final String username = Ui.str(user), password = Ui.str(pass);
            Api.bg(() -> {
                // ۱) ورود آنلاین به رایانه
                try { onlineLogin(base, username, password, st); return; }
                catch (Api.ApiError e) { if (!e.offline()) { final String m = e.getMessage(); Api.ui(() -> st.setText(m)); return; } }
                // ۲) شاید رایانه فقط IP عوض کرده — بپرس شبکه کلید اتصال ما را دارد (بدون بارکد)
                if (!Api.standalone()) {
                    String found = Discovery.find(Prefs.get("link_key", ""), 1500);
                    if (found != null && !found.equals(Api.base)) {
                        Api.base = found; Prefs.set("server_url", found);
                        try { onlineLogin(found, username, password, st); return; }
                        catch (Api.ApiError e) { if (!e.offline()) { final String m = e.getMessage(); Api.ui(() -> st.setText(m)); return; } }
                    }
                }
                // ۳) رایانه در دسترس نیست → ورود آفلاین با همان کاربر/رمز (حساب ذخیره‌شده)
                offlineLogin(username, password, st);
            });
        }));
        cd.addView(st); root.addView(cd);
        // v2.3: quick re-login with fingerprint (session token kept from the last login)
        String saved = Prefs.get("bio_token", "");
        if (Biometric.loginEnabled() && !saved.isEmpty() && Biometric.available(this))
            root.addView(Ui.primary(this, "ورود با اثر انگشت", () -> Biometric.prompt(this, "ورود به " + Prefs.get("store_name", "فروشگاه"), "اثر انگشت", ok -> { if (!ok) return; bioLogin(base, saved, st); })));
        root.addView(Ui.ghost(this, "بازگشت", this::finish)); root.addView(Ui.space(this, 140));
        setContentView(Ui.scroll(this, root));
    }

    /** v2.3 — ورود سریع با اثر انگشت (نشست قبلی)؛ سیاست «فقط بومی» همین‌جا هم اعمال می‌شود. */
    private void bioLogin(String base, String saved, TextView st) {
        Api.base = base;
        Api.token = saved;
        Prefs.set("device_token", saved);
        Api.bg(() -> {
            try {
                Object me = Api.call("GET", "/auth/me", null, null);
                JSONObject mj = me instanceof JSONObject ? (JSONObject) me : new JSONObject(Prefs.get("user_json", "{}"));
                if (!policyAllows(mj, Api.lastRoute)) {
                    Prefs.set("bio_token", "");
                    Api.ui(() -> st.setText("ورود آفلاین برای این کاربر مجاز نیست؛ با رمز یا مدیر فروشگاه پیگیری کنید"));
                    return;
                }
                Prefs.set("user_json", me.toString());
                Session.start();
                Api.ui(() -> {
                    startActivity(new Intent(this, AppActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
                    finish();
                });
            } catch (Exception e) {
                Api.ui(() -> st.setText("نشست منقضی شده؛ با رمز وارد شوید"));
            }
        });
    }

    /** سیاست شبکه و اجازهٔ استفاده از دادهٔ آفلاین مستقل‌اند: مدیر اصلی معاف است؛
     *  local_only فقط ورود آنلاین از relay را می‌بندد و offline_allowed مجوز ورود
     *  از SQLite را کنترل می‌کند. */
    static boolean offlineAllowed(JSONObject me) {
        if (me == null) return false;
        // Older PCs did not expose this switch; preserve their established local_only policy.
        return me.has("offline_allowed") ? me.optBoolean("offline_allowed", false)
                : !me.optBoolean("local_only", true);
    }
    static boolean policyAllows(JSONObject me, String route) {
        if (me == null) return false;
        if (me.optBoolean("is_admin")) return true;
        if (Api.standalone() || "offline".equals(route) || "local".equals(route)) return offlineAllowed(me);
        return !me.optBoolean("local_only", true) || "lan".equals(route);
    }

    /** cache the account on the phone so the SAME user/password works standalone later */
    static void cacheMe(JSONObject me, String password) {
        if (me == null || password == null) return;
        Local.cacheUser(me.optString("username"), me.optString("full_name"), password, me.optLong("id", 0),
                me.optJSONArray("roles") == null ? "[]" : me.optJSONArray("roles").toString(),
                me.optJSONArray("permissions") == null ? "[]" : me.optJSONArray("permissions").toString(),
                me.optJSONArray("allowed_views") == null ? "[]" : me.optJSONArray("allowed_views").toString(),
                me.optString("phone", ""), me.optString("job_title", ""), me.optString("store", ""),
                me.optString("hire_date", ""), me.optBoolean("is_active", true), me.optBoolean("local_only", true), offlineAllowed(me));
    }

    private void onlineLogin(String base, String username, String password, TextView st) throws Api.ApiError {
        String tok = Api.login(username, password);
        if (tok.isEmpty()) throw new Api.ApiError(401, "AUTH", "ورود ناموفق");
        String route = Api.lastRoute;   // مسیر همین ورود ملاک سیاست است، نه تماس‌های بعدی
        Api.token = tok;
        Prefs.set("bio_token", tok);
        JSONObject me = (JSONObject) Api.call("GET", "/auth/me", null, null);
        if (!Api.standalone() && "local".equals(Api.lastRoute))
            throw new Api.ApiError(0, "NETWORK", "پاسخ حساب از رایانه دریافت نشد؛ ورود آفلاین را بررسی می‌کنیم");
        if (!policyAllows(me, route)) throw new Api.ApiError(403, "LOCAL_ONLY", "این کاربر فقط داخل شبکهٔ فروشگاه می‌تواند وارد شود («دسترسی فقط به صورت بومی»)");
        if (!Api.standalone()) cacheMe(me, password);   // حساب‌های رایانه‌ای را محلی cache کن؛ حساب standalone را دوباره نساز
        // توکن دستگاه: برای دستگاهِ آشنا هر بار تازه می‌شود (ردیف همان می‌ماند) —
        // پس از انقضا/ابطال توکن هم دیگر بارکدی اسکن نمی‌شود.
        JSONObject dev = Api.obj("name", "گوشی " + android.os.Build.MODEL);
        String knownId = Prefs.deviceId(this);
        if (knownId == null || knownId.isEmpty()) knownId = Prefs.hwidSeed();
        try { dev.put("device_id", knownId); } catch (Exception ignore) {}
        String token = tok, devId = knownId;
        try {
            Object mint = Api.call("POST", "/mobile/pair/token", dev.toString(), "application/json");
            if (mint instanceof JSONObject) { token = ((JSONObject) mint).optString("token", tok); devId = ((JSONObject) mint).optString("device_id", devId); }
        } catch (Api.ApiError mintFail) {
            // build-492 — دستگاه ناشناخته + کاربر غیرمدیر (یا رایانه میانی): هرگز توکنِ
            // کاربرِ قبلی (Prefs.deviceToken) را جایگزین توکنِ کاربرِ فعلی (tok) نکن!
            // همان tok که از /auth/login برای همین کاربر صادر شده معتبر و اختصاصی اوست.
            token = tok;
        }
        Prefs.save(this, base, token, Prefs.get("store_name", ""), devId == null || devId.isEmpty() ? Prefs.hwidSeed() : devId);
        Api.token = token;
        Screens.user = me;
        Prefs.set("user_json", me.toString());
        Session.start();
        if (!Api.standalone()) { Prefs.set("lic_mode", "pc"); Sync.checkPcLicense(); Prefs.set("setup_done", "1"); }
        Api.online = true;
        Api.ui(() -> {
            if (!Lic.allowed()) { LockActivity.top = this; LockActivity.showIfNeeded(); finish(); return; }
            startActivity(new Intent(this, AppActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
            finish();
        });
    }

    /** v4.8.1 — رایانه در دسترس نیست: با همان کاربر/رمزِ ذخیره‌شده وارد می‌شویم.
     *  جفت‌شدن از بین نمی‌رود؛ Sync هنگام بازگشت به شبکه خودکار همگام می‌شود. */
    private void offlineLogin(String username, String password, TextView st) {
        try {
            String form = "username=" + Api.q(username) + "&password=" + Api.q(password);
            Local.handle("POST", "/auth/login", form);
            JSONObject me = (JSONObject) Local.handle("GET", "/auth/me", null);
            if (!policyAllows(me, "offline")) {
                Api.ui(() -> st.setText("ورود آفلاین برای این کاربر مجاز نیست؛ با مدیر فروشگاه تماس بگیرید"));
                return;
            }
            Api.online = false;
            Screens.user = me;
            Prefs.set("user_json", me.toString());
            Session.start();
            if (!Api.standalone()) { Prefs.set("lic_mode", "pc"); Prefs.set("setup_done", "1"); }   // همان جفت‌شدن قبلی پابرجاست
            Api.ui(() -> {
                Ui.toast("آفلاین وارد شدید — با اتصال به رایانه خودکار همگام می‌شود");
                startActivity(new Intent(this, AppActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
                finish();
            });
        } catch (Api.ApiError e) {
            final String m = e.getMessage();
            Api.ui(() -> st.setText(m));
        }
    }
}
