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

/** v2.0 — sign in to the PC with a store user (alternative to QR pairing, and re-login after logout). */
public class LoginActivity extends Activity {
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b); Prefs.init(this); Db.init(this); Ui.init(this); LockActivity.top = this;
        String url = getIntent().getStringExtra("url"); if (url == null) url = Prefs.serverUrl(this); final String base = url == null ? "" : url;
        getWindow().setStatusBarColor(Ui.BG);
        LinearLayout root = Ui.col(this); root.setBackgroundColor(Ui.BG); root.setPadding(Ui.dp(22), Ui.dp(48), Ui.dp(22), Ui.dp(24)); root.setGravity(Gravity.CENTER_HORIZONTAL);
        ImageView logo = new ImageView(this); logo.setImageResource(R.mipmap.ic_launcher); logo.setLayoutParams(Ui.lp(Ui.dp(84), Ui.dp(84))); root.addView(logo);
        TextView t = Ui.text(this, "ورود به " + Prefs.get("store_name", "فروشگاه"), 19, Ui.TEXT, true); t.setGravity(Gravity.CENTER); t.setPadding(0, Ui.dp(12), 0, Ui.dp(2)); root.addView(t);
        TextView u = Ui.muted(this, base); u.setGravity(Gravity.CENTER); root.addView(u); root.addView(Ui.space(this, 18));
        LinearLayout cd = Ui.card(this, null); EditText user = Ui.input(this, "نام کاربری"); EditText pass = Ui.input(this, "رمز عبور"); pass.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD); cd.addView(user); cd.addView(pass); TextView st = Ui.muted(this, ""); 
        cd.addView(Ui.primary(this, "ورود", () -> { st.setText("در حال ورود…"); Api.base = base; Api.bg(() -> { try { String tok = Api.login(Ui.str(user), Ui.str(pass)); if (tok.isEmpty()) throw new Api.ApiError(401, "AUTH", "ورود ناموفق"); Api.token = tok; Prefs.set("bio_token", tok); Object me = Api.call("GET", "/auth/me", null, null); JSONObject dev = Api.obj("name", "گوشی " + android.os.Build.MODEL); Object mint = null; try { mint = Api.call("POST", "/mobile/pair/token", dev.toString(), "application/json"); } catch (Api.ApiError ignore) {} String token = tok, devId = Prefs.deviceId(this); if (mint instanceof JSONObject) { token = ((JSONObject) mint).optString("token", tok); devId = ((JSONObject) mint).optString("device_id", devId); } Prefs.save(this, base, token, Prefs.get("store_name", ""), devId == null ? "login-" + Long.toHexString(System.currentTimeMillis()) : devId); Api.token = token; Prefs.set("user_json", me.toString()); if (!Api.standalone()) { Prefs.set("lic_mode", "pc"); Sync.checkPcLicense(); Prefs.set("setup_done", "1"); } Api.ui(() -> { if (!Lic.allowed()) { LockActivity.top = this; LockActivity.showIfNeeded(); finish(); return; } startActivity(new Intent(this, AppActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK)); finish(); }); } catch (Api.ApiError e) { Api.ui(() -> st.setText(e.getMessage())); } }); }));
        cd.addView(st); root.addView(cd);
        // v2.3: quick re-login with fingerprint (session token kept from the last login)
        String saved = Prefs.get("bio_token", "");
        if (Biometric.loginEnabled() && !saved.isEmpty() && Biometric.available(this))
            root.addView(Ui.primary(this, "ورود با اثر انگشت", () -> Biometric.prompt(this, "ورود به " + Prefs.get("store_name", "فروشگاه"), "اثر انگشت", ok -> { if (!ok) return; Api.base = base; Api.token = saved; Prefs.set("device_token", saved); Api.bg(() -> { try { Object me = Api.call("GET", "/auth/me", null, null); Prefs.set("user_json", me.toString()); Api.ui(() -> { startActivity(new Intent(this, AppActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK)); finish(); }); } catch (Exception e) { Api.ui(() -> { st.setText("نشست منقضی شده؛ با رمز وارد شوید"); }); } }); })));
        root.addView(Ui.ghost(this, "بازگشت", this::finish));
        setContentView(Ui.scroll(this, root));
    }
}
