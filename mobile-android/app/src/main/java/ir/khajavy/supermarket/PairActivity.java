package ir.khajavy.supermarket;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * v2.0 — first-run pairing (native). Three ways in:
 *  1. scan the QR the Windows app shows (settings → موبایل / setup wizard) — payload "SMKT:<base64url json>"
 *  2. type the PC address and sign in with a store user (LoginActivity)
 *  3. standalone — work on this phone only; pair later from تنظیمات دستگاه.
 */
public class PairActivity extends Activity {
    private static final int REQ_SCAN = 41;
    private EditText addr; private TextView status;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b); Prefs.init(this); Db.init(this); Ui.init(this);
        getWindow().setStatusBarColor(Ui.BG); getWindow().setNavigationBarColor(Ui.BG);
        LinearLayout root = Ui.col(this); root.setBackgroundColor(Ui.BG); root.setPadding(Ui.dp(22), Ui.dp(40), Ui.dp(22), Ui.dp(24)); root.setGravity(Gravity.CENTER_HORIZONTAL);
        ImageView logo = new ImageView(this); logo.setImageResource(R.mipmap.ic_launcher); logo.setLayoutParams(Ui.lp(Ui.dp(96), Ui.dp(96))); root.addView(logo);
        TextView t = Ui.text(this, "سامانه جامع مدیریت سوپرمارکت", 20, Ui.TEXT, true); t.setGravity(Gravity.CENTER); t.setPadding(0, Ui.dp(14), 0, Ui.dp(4)); root.addView(t);
        TextView st = Ui.muted(this, "اپ اندروید بومی · نسخهٔ " + Ui.fa(Version.NAME)); st.setGravity(Gravity.CENTER); root.addView(st);
        root.addView(Ui.space(this, 22));
        LinearLayout c1 = Ui.card(this, "اتصال به رایانهٔ فروشگاه");
        c1.addView(Ui.body(this, "در ویندوز: تنظیمات → موبایل (اندروید) → کد QR را با این گوشی اسکن کنید. گوشی و رایانه باید به یک وای‌فای وصل باشند؛ اینترنت لازم نیست."));
        c1.addView(Ui.primary(this, "اسکن QR رایانه", this::scanQr));
        c1.addView(Ui.label(this, "یا آدرس رایانه را وارد کنید"));
        addr = Ui.input(this, "مثال: 192.168.1.10:8000", false); addr.setTextDirection(View.TEXT_DIRECTION_LTR); c1.addView(addr);
        c1.addView(Ui.ghost(this, "ورود با نام کاربری", () -> { String u = Prefs.normalise(Ui.str(addr)); if (u.isEmpty()) { Ui.toast("آدرس رایانه را وارد کنید"); return; } Intent i = new Intent(this, LoginActivity.class); i.putExtra("url", u); startActivity(i); }));
        status = Ui.muted(this, ""); c1.addView(status); root.addView(c1);
        LinearLayout c2 = Ui.card(this, "بدون رایانه");
        c2.addView(Ui.body(this, "همین حالا با این گوشی کار را شروع کنید (کالا، ورود، فروش، مشتری). هر زمان به رایانهٔ فروشگاه وصل شدید، همه‌چیز خودکار همگام می‌شود."));
        c2.addView(Ui.ghost(this, "شروع مستقل", () -> { Prefs.save(this, "http://standalone.invalid", "", Prefs.get("store_name", "فروشگاه من"), Prefs.deviceIdStatic() == null ? "local-" + Long.toHexString(System.currentTimeMillis()) : Prefs.deviceIdStatic()); go(); }));
        root.addView(c2);
        TextView dev = Ui.muted(this, "طراحی و توسعه توسط خواجوی"); dev.setGravity(Gravity.CENTER); dev.setPadding(0, Ui.dp(12), 0, 0); root.addView(dev);
        setContentView(Ui.scroll(this, root));
        Intent in = getIntent(); if (in != null && in.getData() != null) handlePayload(in.getData().toString());
    }
    void scanQr() { if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) { requestPermissions(new String[]{Manifest.permission.CAMERA}, 9); return; } Intent i = new Intent(this, ScanActivity.class); i.putExtra("title", "QR روی صفحهٔ رایانه را اسکن کنید"); startActivityForResult(i, REQ_SCAN); }
    @Override public void onRequestPermissionsResult(int code, String[] p, int[] r) { super.onRequestPermissionsResult(code, p, r); if (code == 9 && r.length > 0 && r[0] == PackageManager.PERMISSION_GRANTED) scanQr(); }
    @Override protected void onActivityResult(int req, int res, Intent data) { super.onActivityResult(req, res, data); if (req == REQ_SCAN && res == RESULT_OK && data != null) handlePayload(data.getStringExtra("code")); }

    void handlePayload(String text) {
        if (text == null) return; text = text.trim();
        try {
            JSONObject p;
            if (text.startsWith("SMKT:")) p = new JSONObject(new String(Base64.decode(text.substring(5), Base64.URL_SAFE | Base64.NO_PADDING | Base64.NO_WRAP), "UTF-8"));
            else if (text.startsWith("{")) p = new JSONObject(text);
            else { addr.setText(text); Ui.toast("آدرس وارد شد — با نام کاربری وارد شوید"); return; }
            String token = p.optString("token"), store = p.optString("store", ""), dev = p.optString("device_id", "");
            JSONArray urls = p.optJSONArray("urls"); java.util.List<String> cands = new java.util.ArrayList<>(); if (!p.optString("url").isEmpty()) cands.add(p.optString("url")); for (int i = 0; urls != null && i < urls.length(); i++) if (!cands.contains(urls.optString(i))) cands.add(urls.optString(i));
            status.setText("در حال یافتن رایانه…");
            Api.bg(() -> { String found = null; for (String u : cands) { Api.base = Prefs.normalise(u); if (Api.health()) { found = Api.base; break; } } final String f = found;
                Api.ui(() -> { if (f == null) { status.setText("هیچ‌کدام از آدرس‌ها پاسخ نداد: " + cands + " — وای‌فای را بررسی کنید"); if (!cands.isEmpty()) { Prefs.save(this, Prefs.normalise(cands.get(0)), token, store, dev); Api.token = token; Ui.toast("ذخیره شد؛ پس از اتصال همگام می‌شود"); go(); } return; } Prefs.save(this, f, token, store, dev); Api.token = token; Prefs.set("store_name", store); status.setText("متصل شد: " + f); Ui.toast("جفت‌سازی انجام شد"); go(); }); });
        } catch (Exception e) { Ui.toast("QR نامعتبر است"); }
    }
    void go() { startActivity(new Intent(this, AppActivity.class)); finish(); }
}
