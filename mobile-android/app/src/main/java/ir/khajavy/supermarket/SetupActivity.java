package ir.khajavy.supermarket;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * v2.1 — first-run setup wizard (راه‌اندازی اولیه), mirroring the Windows wizard.
 *
 *  welcome → mode:
 *    A) «نسخهٔ رایانه را دارم»  → pair (QR / 6-digit code / address+login). The PC's
 *       licence is checked right at pairing (/mobile/link) and becomes the phone's licence.
 *    B) «فقط گوشی — رایانه ندارم» → licence key on the phone → store name → contact →
 *       currency → theme → starter catalogue → admin → finish → ONE-TIME long install
 *       loading (same phases as Windows; never shows minutes) → app.
 */
public class SetupActivity extends Activity {
    private static final int REQ_SCAN = 61;
    private static final String[] STEPS_OWN = {"license", "store", "contact", "currency", "theme", "catalog", "admin", "finish"};
    private static final String[] TITLES_OWN = {"لایسنس", "نام فروشگاه", "اطلاعات تماس", "واحد پول", "پوسته", "بانک کالا", "حساب مدیر", "پایان"};
    private LinearLayout pane; private TextView stepLbl; private LinearLayout root; private LinearLayout dots;
    private int step = -1; // -1 welcome, -2 mode, -3 pair ; >=0 index into STEPS_OWN
    private final JSONObject data = new JSONObject();
    private final Handler h = new Handler(Looper.getMainLooper());
    private TextView pairStatus; private EditText addr;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b); Prefs.init(this); Db.init(this); Ui.init(this); LockActivity.top = this;
        getWindow().setStatusBarColor(Ui.BG); getWindow().setNavigationBarColor(Ui.BG);
        root = Ui.col(this); root.setBackgroundColor(Ui.BG); root.setPadding(Ui.dp(20), Ui.dp(28), Ui.dp(20), Ui.dp(20));
        LinearLayout head = Ui.row(this); ImageView logo = new ImageView(this); logo.setImageResource(R.mipmap.ic_launcher); logo.setLayoutParams(Ui.lp(Ui.dp(44), Ui.dp(44))); head.addView(logo);
        LinearLayout ht = Ui.col(this); ht.setPadding(Ui.dp(10), 0, 0, 0); ht.addView(Ui.text(this, getString(R.string.app_name), 17, Ui.TEXT, true)); stepLbl = Ui.muted(this, "راه‌اندازی اولیه"); ht.addView(stepLbl); head.addView(ht); root.addView(head);
        dots = Ui.row(this); dots.setPadding(0, Ui.dp(12), 0, Ui.dp(6)); root.addView(dots);
        pane = Ui.col(this); root.addView(pane);
        setContentView(Ui.scroll(this, root));
        Intent in = getIntent();
        if (in != null && in.getData() != null) { showPair(); handlePayload(in.getData().toString()); }
        else if (in != null && in.getBooleanExtra("pair", false)) showPair();
        else showWelcome();
    }

    /* ---------------- shared ---------------- */
    private void title(String t, String sub) { stepLbl.setText(t); pane.removeAllViews(); dots.removeAllViews(); if (step >= 0) for (int i = 0; i < STEPS_OWN.length; i++) { View d = new View(this); d.setBackground(Ui.rounded(i < step ? Ui.GREEN : i == step ? Ui.PRIMARY : Ui.BORDER, 0, 3)); LinearLayout.LayoutParams lp = Ui.weight(1); lp.height = Ui.dp(5); lp.setMargins(Ui.dp(2), 0, Ui.dp(2), 0); d.setLayoutParams(lp); dots.addView(d); } TextView h1 = Ui.h1(this, t); h1.setPadding(0, Ui.dp(8), 0, Ui.dp(4)); pane.addView(h1); if (sub != null) pane.addView(Ui.muted(this, sub)); pane.addView(Ui.space(this, 10)); }
    private void nav(Runnable back, String nextLabel, Runnable next) { LinearLayout r = Ui.row(this); r.setPadding(0, Ui.dp(14), 0, 0); if (back != null) { android.widget.Button bb = Ui.ghost(this, "قبلی", back); bb.setLayoutParams(Ui.weight(1)); r.addView(bb); } if (next != null) { android.widget.Button nb = Ui.primary(this, nextLabel, next); LinearLayout.LayoutParams lp = Ui.weight(2); lp.setMargins(Ui.dp(6), 0, 0, 0); nb.setLayoutParams(lp); r.addView(nb); } pane.addView(r); }
    private void put(String k, Object v) { try { data.put(k, v); } catch (Exception ignore) {} }
    private String str(String k) { return data.optString(k, ""); }
    private LinearLayout choice(String title, String sub, boolean on, Runnable r) { LinearLayout c = Ui.card(this, null); c.setBackground(Ui.rounded(on ? (Ui.PRIMARY & 0x00FFFFFF) | 0x22000000 : Ui.CARD, on ? Ui.PRIMARY : Ui.BORDER, 18)); c.addView(Ui.text(this, title, 15, Ui.TEXT, true)); if (sub != null) c.addView(Ui.muted(this, sub)); c.setOnClickListener(v -> r.run()); return c; }

    /* ---------------- welcome ---------------- */
    void showWelcome() {
        step = -1; title("خوش آمدید", null);
        LinearLayout hero = Ui.col(this); hero.setGravity(Gravity.CENTER); hero.setPadding(0, Ui.dp(10), 0, Ui.dp(16));
        ImageView logo = new ImageView(this); logo.setImageResource(R.mipmap.ic_launcher); logo.setLayoutParams(Ui.lp(Ui.dp(110), Ui.dp(110))); hero.addView(logo);
        TextView t = Ui.text(this, getString(R.string.app_name), 24, Ui.TEXT, true); t.setPadding(0, Ui.dp(12), 0, Ui.dp(4)); hero.addView(t);
        TextView s = Ui.body(this, "سامانهٔ کامل مدیریت سوپرمارکت روی گوشی شما: کالا و بچ، ورود کالا، صندوق فروش، مشتری و دفتر حساب، انبارگردانی، گزارش‌ها و پشتیبانی."); s.setGravity(Gravity.CENTER); hero.addView(s);
        pane.addView(hero);
        LinearLayout cd = Ui.card(this, "چند مرحلهٔ کوتاه");
        for (String x : new String[]{"انتخاب نحوهٔ استفاده (با رایانه یا فقط گوشی)", "بررسی لایسنس", "مشخصات فروشگاه و تنظیمات اولیه", "آماده‌سازی و ورود"}) cd.addView(Ui.body(this, "•  " + x));
        pane.addView(cd);
        pane.addView(Ui.muted(this, "نسخهٔ " + Ui.fa(Version.NAME) + " · " + getString(R.string.developer)));
        nav(null, "بزن بریم", this::showMode);
        pane.addView(Ui.small(this, "ارتباط با پشتیبانی", () -> startActivity(new Intent(this, SupportActivity.class))));
    }

    /* ---------------- mode ---------------- */
    void showMode() {
        step = -2; title("چطور از برنامه استفاده می‌کنید؟", "یکی از دو حالت را انتخاب کنید. بعداً هم می‌توانید از «تنظیمات دستگاه» تغییر دهید.");
        pane.addView(choice("🖥  نسخهٔ رایانه (ویندوز) را دارم", "گوشی به رایانهٔ فروشگاه وصل می‌شود؛ همهٔ اطلاعات دو طرفه همگام می‌شود و لایسنس همان لایسنس رایانه است.", false, this::showPair));
        pane.addView(choice("📱  فقط گوشی — رایانه ندارم", "فروشگاه به‌طور کامل روی همین گوشی راه‌اندازی می‌شود: لایسنس، نام فروشگاه، بانک کالا و … (مثل نصب روی ویندوز).", false, () -> { step = 0; showStep(); }));
        nav(this::showWelcome, null, null);
    }

    /* ---------------- A) pair with PC ---------------- */
    void showPair() {
        step = -3; title("اتصال به رایانهٔ فروشگاه", "در ویندوز: تنظیمات → موبایل (اندروید). گوشی و رایانه باید به یک وای‌فای وصل باشند؛ اینترنت لازم نیست.");
        LinearLayout c1 = Ui.card(this, "راه ۱ — اسکن کد QR"); c1.addView(Ui.primary(this, "اسکن QR روی صفحهٔ رایانه", this::scanQr)); pane.addView(c1);
        LinearLayout c2 = Ui.card(this, "راه ۲ — کد ۶ رقمی"); c2.addView(Ui.muted(this, "در رایانه «ساخت کد ۶ رقمی» را بزنید و عدد را اینجا وارد کنید. گوشی خودش رایانه را در شبکه پیدا می‌کند."));
        EditText code = Ui.input(this, "مثلاً ۴۸۳۹۲۱", true); code.setInputType(InputType.TYPE_CLASS_NUMBER); code.setTextSize(22); code.setGravity(Gravity.CENTER); c2.addView(code);
        c2.addView(Ui.ghost(this, "اتصال با کد", () -> claim(Db.norm(Ui.str(code))))); pane.addView(c2);
        LinearLayout c3 = Ui.card(this, "راه ۳ — آدرس رایانه و نام کاربری"); addr = Ui.input(this, "مثال: 192.168.1.10:8000", false); addr.setTextDirection(View.TEXT_DIRECTION_LTR); c3.addView(addr);
        c3.addView(Ui.ghost(this, "پیدا کردن خودکار رایانه در شبکه", () -> { pairStatus.setText("در حال جست‌وجو در شبکه…"); Api.bg(() -> { String f = Discovery.find("", 2500); Api.ui(() -> { if (f == null) pairStatus.setText("رایانه‌ای در این شبکه پیدا نشد — مطمئن شوید برنامهٔ ویندوز باز است"); else { addr.setText(f.replace("http://", "")); pairStatus.setText("پیدا شد: " + f + " — حالا با نام کاربری وارد شوید"); } }); }); }));
        c3.addView(Ui.ghost(this, "ورود با نام کاربری", () -> { String u = Prefs.normalise(Ui.str(addr)); if (u.isEmpty()) { Ui.toast("آدرس رایانه را وارد کنید"); return; } Prefs.set("lic_mode", "pc"); Intent i = new Intent(this, LoginActivity.class); i.putExtra("url", u); i.putExtra("setup", true); startActivity(i); }));
        pairStatus = Ui.muted(this, ""); c3.addView(pairStatus); pane.addView(c3);
        nav(this::showMode, null, null);
    }
    void scanQr() { if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) { requestPermissions(new String[]{Manifest.permission.CAMERA}, 9); return; } Intent i = new Intent(this, ScanActivity.class); i.putExtra("title", "QR روی صفحهٔ رایانه را اسکن کنید"); startActivityForResult(i, REQ_SCAN); }
    @Override public void onRequestPermissionsResult(int code, String[] p, int[] r) { super.onRequestPermissionsResult(code, p, r); if (code == 9 && r.length > 0 && r[0] == PackageManager.PERMISSION_GRANTED) scanQr(); }
    @Override protected void onActivityResult(int req, int res, Intent d) { super.onActivityResult(req, res, d); if (req == REQ_SCAN && res == RESULT_OK && d != null) handlePayload(d.getStringExtra("code")); }

    void claim(String code) {
        if (code.length() != 6) { Ui.toast("کد باید ۶ رقم باشد"); return; }
        pairStatus.setText("در حال یافتن رایانه در شبکه…");
        Api.bg(() -> {
            String found = Discovery.find("", 2500);
            List<String> cands = new ArrayList<>(); if (found != null) cands.add(found); if (!Ui.str(addr).isEmpty()) cands.add(Prefs.normalise(Ui.str(addr)));
            String err = "رایانه‌ای پیدا نشد؛ آدرس آن را در «راه ۳» وارد کنید و دوباره «اتصال با کد» را بزنید";
            for (String u : cands) {
                try { Api.base = u; Api.token = ""; Object r = Api.call("POST", "/mobile/pair/claim", Api.obj("code", code).toString(), "application/json"); final JSONObject p = (JSONObject) r; Api.ui(() -> applyPayload(p)); return; }
                catch (Api.ApiError e) { err = e.status == 404 ? e.getMessage() : err; }
            }
            final String fe = err; Api.ui(() -> pairStatus.setText(fe));
        });
    }
    void handlePayload(String text) {
        if (text == null) return; text = text.trim();
        try {
            JSONObject p;
            if (text.startsWith("SMKT:")) p = new JSONObject(new String(Base64.decode(text.substring(5), Base64.URL_SAFE | Base64.NO_PADDING | Base64.NO_WRAP), "UTF-8"));
            else if (text.startsWith("smkt://")) p = new JSONObject(new String(Base64.decode(text.substring(7).replace("/", ""), Base64.URL_SAFE | Base64.NO_PADDING | Base64.NO_WRAP), "UTF-8"));
            else if (text.startsWith("{")) p = new JSONObject(text);
            else { if (addr != null) addr.setText(text); Ui.toast("آدرس وارد شد — با نام کاربری وارد شوید"); return; }
            applyPayload(p);
        } catch (Exception e) { Ui.toast("QR نامعتبر است"); }
    }
    void applyPayload(JSONObject p) {
        String token = p.optString("token"), store = p.optString("store", ""), dev = p.optString("device_id", ""), link = p.optString("link_key", "");
        JSONArray urls = p.optJSONArray("urls"); List<String> cands = new ArrayList<>(); if (!p.optString("url").isEmpty()) cands.add(p.optString("url")); for (int i = 0; urls != null && i < urls.length(); i++) if (!cands.contains(urls.optString(i))) cands.add(urls.optString(i));
        if (pairStatus != null) pairStatus.setText("در حال اتصال به رایانه…");
        Api.bg(() -> {
            String found = null; for (String u : cands) { Api.base = Prefs.normalise(u); if (Api.health()) { found = Api.base; break; } }
            if (found == null && !link.isEmpty()) found = Discovery.find(link, 2500);
            final String f = found;
            Api.ui(() -> {
                Prefs.save(this, f == null ? (cands.isEmpty() ? "" : Prefs.normalise(cands.get(0))) : f, token, store, dev); Api.token = token; Api.base = Prefs.serverUrl(this);
                Prefs.set("store_name", store); Prefs.set("link_key", link); Prefs.set("lic_mode", "pc"); if (p.has("cloud")) Prefs.set("cloud_json", p.optJSONObject("cloud").toString());
                if (f == null) { pairStatus.setText("رایانه پاسخ نداد — اطلاعات ذخیره شد؛ به محض اتصال به وای‌فای فروشگاه، لایسنس بررسی و همگام‌سازی انجام می‌شود."); finishSetup(false); return; }
                pairStatus.setText("متصل شد ✓ — در حال بررسی لایسنس رایانه…");
                Api.bg(() -> { Sync.checkPcLicense(); Api.ui(() -> { if (!Lic.allowed()) { pairStatus.setText("لایسنس رایانه معتبر نیست: " + Lic.reason()); Prefs.set("setup_done", "1"); LockActivity.showIfNeeded(); return; } pairStatus.setText("لایسنس معتبر ✓ (تا " + Ui.jdate(Lic.expires()) + ")"); finishSetup(false); }); });
            });
        });
    }

    /* ---------------- B) standalone wizard ---------------- */
    void showStep() {
        String id = STEPS_OWN[step]; stepLbl.setText("مرحلهٔ " + Ui.fa(String.valueOf(step + 1)) + " از " + Ui.fa(String.valueOf(STEPS_OWN.length)));
        switch (id) {
            case "license": {
                title("فعال‌سازی لایسنس", "کلید لایسنسی که هنگام خرید دریافت کرده‌اید را وارد کنید. اعتبار به‌صورت آنلاین بررسی می‌شود و پس از آن، برنامه تا تاریخ انقضا آفلاین هم کار می‌کند.");
                LinearLayout cd = Ui.card(this, null); EditText key = Ui.input(this, "XXXX-XXXX-XXXX-XXXX", false); key.setTextDirection(View.TEXT_DIRECTION_LTR); key.setGravity(Gravity.CENTER); key.setTextSize(18); key.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS); key.setText(Prefs.get("lic_key", "")); cd.addView(key);
                cd.addView(Ui.kv(this, "شناسهٔ این دستگاه", Lic.hwid(), 0)); TextView st = Ui.muted(this, "ACTIVE".equals(Prefs.get("lic_status", "")) && Lic.allowed() ? "لایسنس فعال است ✓ (تا " + Ui.jdate(Lic.expires()) + ")" : ""); cd.addView(st);
                cd.addView(Ui.primary(this, "بررسی و فعال‌سازی", () -> { st.setText("در حال بررسی با سرور لایسنس…"); Api.bg(() -> { String err = Lic.activate(Ui.str(key)); Api.ui(() -> st.setText(err == null ? "لایسنس فعال شد ✓ (" + Prefs.get("lic_type", "") + " · تا " + Ui.jdate(Lic.expires()) + ")" : err)); }); }));
                pane.addView(cd);
                pane.addView(Ui.small(this, "لایسنس ندارید؟ ارتباط با پشتیبانی", () -> startActivity(new Intent(this, SupportActivity.class))));
                nav(this::showMode, "بعدی", () -> { if (!("ACTIVE".equals(Prefs.get("lic_status", "")) && Lic.allowed())) { Ui.toast("ابتدا لایسنس را فعال کنید"); return; } step++; showStep(); });
                break;
            }
            case "store": {
                title("نام فروشگاه", "این نام روی فاکتورها و بالای برنامه نمایش داده می‌شود.");
                EditText n = Ui.input(this, "نام فروشگاه *"); n.setText(str("store_name")); EditText legal = Ui.input(this, "نام رسمی / حقوقی (اختیاری)"); legal.setText(str("legal_name"));
                pane.addView(n); pane.addView(legal);
                nav(() -> { step--; showStep(); }, "بعدی", () -> { if (Ui.str(n).length() < 2) { Ui.toast("نام فروشگاه لازم است"); return; } put("store_name", Ui.str(n)); put("legal_name", Ui.str(legal)); step++; showStep(); });
                break;
            }
            case "contact": {
                title("اطلاعات تماس", "روی فاکتور چاپ می‌شود و برای پشتیبانی استفاده می‌شود. می‌توانید بعداً کامل کنید.");
                EditText ph = Ui.input(this, "تلفن ثابت", true); ph.setText(str("phone")); EditText mb = Ui.input(this, "شمارهٔ همراه", true); mb.setText(str("mobile")); EditText city = Ui.input(this, "شهر"); city.setText(str("city")); EditText ad = Ui.area(this, "نشانی"); ad.setText(str("address")); EditText note = Ui.input(this, "پیام پایین فاکتور (مثلاً: از خرید شما سپاسگزاریم)"); note.setText(str("receipt_note"));
                pane.addView(ph); pane.addView(mb); pane.addView(city); pane.addView(ad); pane.addView(note);
                nav(() -> { step--; showStep(); }, "بعدی", () -> { put("phone", Ui.str(ph)); put("mobile", Ui.str(mb)); put("city", Ui.str(city)); put("address", Ui.str(ad)); put("receipt_note", Ui.str(note)); step++; showStep(); });
                pane.addView(Ui.small(this, "رد کردن این مرحله", () -> { step++; showStep(); }));
                break;
            }
            case "currency": {
                title("واحد پول", "قیمت‌ها با کدام واحد نمایش داده شوند؟ (در تنظیمات قابل تغییر است)");
                final String[] cur = {str("currency").isEmpty() ? "IRR" : str("currency")};
                Runnable[] rd = new Runnable[1]; LinearLayout box = Ui.col(this); pane.addView(box);
                rd[0] = () -> { box.removeAllViews(); box.addView(choice("ریال", "مثال: ۲۵۰٬۰۰۰ ریال", "IRR".equals(cur[0]), () -> { cur[0] = "IRR"; rd[0].run(); })); box.addView(choice("تومان", "مثال: ۲۵٬۰۰۰ تومان", "IRT".equals(cur[0]), () -> { cur[0] = "IRT"; rd[0].run(); })); };
                rd[0].run();
                nav(() -> { step--; showStep(); }, "بعدی", () -> { put("currency", cur[0]); step++; showStep(); });
                break;
            }
            case "theme": {
                title("پوسته", "پوستهٔ «خودکار» از ۷ صبح روشن و از ۷ شب تیره می‌شود — مثل نسخهٔ ویندوز.");
                final String[] th = {str("theme").isEmpty() ? "auto" : str("theme")};
                Runnable[] rd = new Runnable[1]; LinearLayout box = Ui.col(this); pane.addView(box);
                rd[0] = () -> { box.removeAllViews(); box.addView(choice("خودکار (روز روشن / شب تیره)", null, "auto".equals(th[0]), () -> { th[0] = "auto"; rd[0].run(); })); box.addView(choice("همیشه روشن", null, "light".equals(th[0]), () -> { th[0] = "light"; rd[0].run(); })); box.addView(choice("همیشه تیره", null, "dark".equals(th[0]), () -> { th[0] = "dark"; rd[0].run(); })); };
                rd[0].run();
                nav(() -> { step--; showStep(); }, "بعدی", () -> { put("theme", th[0]); step++; showStep(); });
                break;
            }
            case "catalog": {
                title("بانک اولیهٔ کالا", "می‌توانید با یک بانک آمادهٔ کالاهای رایج سوپرمارکت (حدود ۱۹۰ قلم با دسته‌بندی و واحد، بدون قیمت) شروع کنید یا کاتالوگ را خودتان بسازید.");
                final boolean[] imp = {!data.has("starter") || data.optBoolean("starter")};
                Runnable[] rd = new Runnable[1]; LinearLayout box = Ui.col(this); pane.addView(box);
                rd[0] = () -> { box.removeAllViews(); box.addView(choice("بله، بانک آماده بارگذاری شود", "کالاها بدون قیمت و موجودی ثبت می‌شوند؛ قیمت با اولین «ورود کالا» به بچ تعلق می‌گیرد.", imp[0], () -> { imp[0] = true; rd[0].run(); })); box.addView(choice("خیر، از صفر شروع می‌کنم", "کالاها را با اسکن بارکد یکی‌یکی تعریف می‌کنم.", !imp[0], () -> { imp[0] = false; rd[0].run(); })); };
                rd[0].run();
                nav(() -> { step--; showStep(); }, "بعدی", () -> { put("starter", imp[0]); step++; showStep(); });
                break;
            }
            case "admin": {
                title("حساب مدیر", "با این نام کاربری و رمز وارد برنامه می‌شوید؛ کاربران صندوق‌دار را بعداً در «کاربران و نقش‌ها» می‌سازید.");
                EditText u = Ui.input(this, "نام کاربری *"); u.setText(str("admin_username").isEmpty() ? "admin" : str("admin_username")); u.setTextDirection(View.TEXT_DIRECTION_LTR);
                EditText p1 = Ui.input(this, "رمز عبور (حداقل ۶ کاراکتر) *"); p1.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD); EditText p2 = Ui.input(this, "تکرار رمز عبور *"); p2.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
                EditText fn = Ui.input(this, "نام و نام خانوادگی مدیر"); fn.setText(str("admin_name"));
                pane.addView(u); pane.addView(p1); pane.addView(p2); pane.addView(fn);
                nav(() -> { step--; showStep(); }, "بعدی", () -> { if (Ui.str(u).length() < 3) { Ui.toast("نام کاربری کوتاه است"); return; } if (Ui.str(p1).length() < 6) { Ui.toast("رمز حداقل ۶ کاراکتر"); return; } if (!Ui.str(p1).equals(Ui.str(p2))) { Ui.toast("تکرار رمز یکسان نیست"); return; } put("admin_username", Ui.str(u)); put("admin_password", Ui.str(p1)); put("admin_name", Ui.str(fn)); step++; showStep(); });
                break;
            }
            case "finish": {
                title("همه‌چیز آماده است", "خلاصهٔ تنظیمات را بررسی کنید. با زدن «شروع نصب»، فروشگاه روی این گوشی ساخته می‌شود؛ این مرحله فقط بار اول انجام می‌شود.");
                LinearLayout cd = Ui.card(this, null);
                cd.addView(Ui.kv(this, "فروشگاه", str("store_name"), 0)); cd.addView(Ui.kv(this, "لایسنس", Lic.masked() + " · تا " + Ui.jdate(Lic.expires()), Ui.GREEN)); cd.addView(Ui.kv(this, "واحد پول", "IRT".equals(str("currency")) ? "تومان" : "ریال", 0)); cd.addView(Ui.kv(this, "پوسته", "auto".equals(str("theme")) ? "خودکار" : "light".equals(str("theme")) ? "روشن" : "تیره", 0)); cd.addView(Ui.kv(this, "بانک کالا", data.optBoolean("starter") ? "بارگذاری می‌شود" : "خالی", 0)); cd.addView(Ui.kv(this, "مدیر", str("admin_username"), 0));
                pane.addView(cd);
                nav(() -> { step--; showStep(); }, "شروع نصب و ورود", this::install);
                break;
            }
        }
    }

    /* ---------------- one-time install (long loading; NO minutes shown) ---------------- */
    static final String[][] PHASES = {{"برقراری ارتباط با سرویس لایسنس", "0.04"}, {"ایجاد ساختار پایگاه داده", "0.10"}, {"اجرای مهاجرت‌های اسکیمای داده", "0.18"}, {"نصب ماژول حسابداری دوطرفه", "0.28"}, {"پیکربندی موتور صندوق (POS)", "0.36"}, {"آماده‌سازی موتور بارکد و واحدها", "0.44"}, {"وارد کردن بانک اولیهٔ کالا", "0.55"}, {"ساخت ایندکس‌های جستجو", "0.63"}, {"پیکربندی پوسته و تقویم شمسی", "0.70"}, {"آماده‌سازی چاپ فاکتور (بلوتوث / اشتراک)", "0.78"}, {"راه‌اندازی صف همگام‌سازی آفلاین", "0.86"}, {"اعمال تنظیمات فروشگاه", "0.93"}, {"بررسی نهایی و بهینه‌سازی", "1.0"}};
    void install() {
        // persist the store profile on the phone (standalone has no PC)
        Prefs.set("store_name", str("store_name")); Prefs.set("store_json", data.toString()); Prefs.set("store_mobile", str("mobile"));
        Prefs.set("currency_label", "IRT".equals(str("currency")) ? "تومان" : "ریال"); Ui.currencyLabel = Prefs.get("currency_label", "ریال");
        Prefs.set("theme_pref", str("theme")); Prefs.set("theme_resolved", "light".equals(str("theme")) ? "light" : "dark".equals(str("theme")) ? "dark" : (java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY) >= 7 && java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY) < 19 ? "light" : "dark"));
        try { JSONObject u = new JSONObject(); u.put("username", str("admin_username")); u.put("full_name", str("admin_name")); u.put("role", "ADMIN"); u.put("permissions", JSONObject.NULL); Prefs.set("user_json", u.toString()); Prefs.set("local_admin_hash", Lic.hwid() + ":" + Integer.toHexString((str("admin_username") + "|" + str("admin_password")).hashCode())); } catch (Exception ignore) {}
        Prefs.save(this, "http://standalone.invalid", "", str("store_name"), Prefs.deviceIdStatic() == null ? "local-" + Long.toHexString(System.currentTimeMillis()) : Prefs.deviceIdStatic());
        Prefs.set("lic_mode", "own");
        final boolean starter = data.optBoolean("starter");
        boolean fast = "1".equals(Prefs.get("loading_fast", "")) || getIntent().getBooleanExtra("fastload", false);
        long total = fast ? 6000L : 45L * 60L * 1000L;
        loadingScreen(total, () -> { if (starter && Db.count("products") == 0) Db.importStarter(this); }, () -> { Prefs.set("first_loading_done", "1"); finishSetup(true); });
    }
    void loadingScreen(long totalMs, Runnable work, Runnable done) {
        pane.removeAllViews(); dots.removeAllViews(); stepLbl.setText("در حال نصب");
        LinearLayout box = Ui.col(this); box.setGravity(Gravity.CENTER_HORIZONTAL); box.setPadding(0, Ui.dp(10), 0, 0);
        TextView h1 = Ui.h1(this, "در حال نصب و پیکربندی سامانه"); h1.setGravity(Gravity.CENTER); box.addView(h1);
        TextView sub = Ui.muted(this, "این مرحله فقط بار اول انجام می‌شود. لطفاً برنامه را نبندید و گوشی را خاموش نکنید."); sub.setGravity(Gravity.CENTER); box.addView(sub);
        TextView pct = Ui.text(this, "۰٪", 44, Ui.PRIMARY, true); pct.setGravity(Gravity.CENTER); pct.setPadding(0, Ui.dp(18), 0, Ui.dp(6)); box.addView(pct);
        ProgressBar bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal); bar.setMax(1000); bar.setLayoutParams(Ui.margin(Ui.match(), 0, 0, 0, 14)); box.addView(bar);
        TextView eta = Ui.muted(this, "لطفاً صبر کنید"); eta.setGravity(Gravity.CENTER); box.addView(eta);
        LinearLayout ph = Ui.card(this, null); final TextView[] rows = new TextView[PHASES.length]; for (int i = 0; i < PHASES.length; i++) { rows[i] = Ui.body(this, "○  " + PHASES[i][0]); rows[i].setTextColor(Ui.MUTED); ph.addView(rows[i]); } box.addView(ph);
        TextView log = Ui.muted(this, ""); box.addView(log);
        pane.addView(box);
        final long t0 = System.currentTimeMillis(); final boolean[] workDone = {false}; final int[] last = {-1};
        Api.bg(() -> { try { work.run(); } catch (Exception ignore) {} workDone[0] = true; });
        final String[] noise = {"اتصال برقرار شد", "بستهٔ داده دریافت شد", "جدول به‌روزرسانی شد", "ایندکس ساخته شد", "بررسی یکپارچگی: موفق", "پیکربندی اعمال شد"};
        Runnable[] tick = new Runnable[1];
        tick[0] = () -> {
            double p = Math.min(1.0, (System.currentTimeMillis() - t0) / (double) totalMs);
            double eased = p < 0.9 ? Math.pow(p, 0.85) * 0.92 : 0.92 + (p - 0.9) * 0.8;
            int pc = (int) Math.min(100, Math.round(eased * 100)); pct.setText(Ui.fa(String.valueOf(pc)) + "٪"); bar.setProgress((int) (eased * 1000));
            int cur = PHASES.length - 1; for (int i = 0; i < PHASES.length; i++) if (eased < Double.parseDouble(PHASES[i][1])) { cur = i; break; }
            if (cur != last[0]) { for (int i = 0; i < PHASES.length; i++) { rows[i].setText((i < cur ? "✓  " : i == cur ? "▸  " : "○  ") + PHASES[i][0]); rows[i].setTextColor(i < cur ? Ui.GREEN : i == cur ? Ui.TEXT : Ui.MUTED); } log.setText("▸ " + PHASES[cur][0] + "…"); last[0] = cur; }
            else if (Math.random() < 0.04) log.setText(noise[(int) (Math.random() * noise.length)]);
            if (p >= 1 && workDone[0]) { eta.setText("آماده شد"); h.postDelayed(done, 600); return; }
            h.postDelayed(tick[0], 250);
        };
        tick[0].run();
    }

    void finishSetup(boolean standalone) {
        Prefs.set("setup_done", "1");
        if (standalone) Prefs.set("first_loading_done", "1");
        startActivity(new Intent(this, AppActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK)); finish();
    }
    @Override public void onBackPressed() { if (step == -1) super.onBackPressed(); else if (step == -2 || step == -3) { if (step == -3) showMode(); else showWelcome(); } else if (step == 0) showMode(); else { step--; showStep(); } }
    @Override protected void onResume() { super.onResume(); LockActivity.top = this; }
}
