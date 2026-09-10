package ir.khajavy.supermarket;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * v2.3 — SMS straight from the phone (standalone mode, or paired but the PC is away).
 * Same providers, same settings keys and the same invoice template as the PC
 * (backend/app/services/sms.py): Melipayamak (line / pattern) and Kavenegar.
 * Messages are queued in kv "sms_queue" and retried by {@link #flush()} (called
 * after each checkout, on resume and by the 30-minute background checker), so a
 * dead network never blocks a sale and every message is eventually delivered.
 *
 * In paired mode the PC sends the invoice SMS itself (routers/pos.py) — the phone
 * only sends locally when Api.standalone() or when the PC is unreachable AND
 * "sms.phone_fallback" is on.
 */
public final class SmsLocal {
    private SmsLocal() {}
    static final String[] KEYS = {"sms.provider", "sms.melipayamak_mode", "sms.username", "sms.password", "sms.sender", "sms.melipayamak_body_id", "sms.api_key", "sms.send_invoice", "sms.template.invoice", "sms.admin_phone", "sms.phone_fallback"};
    static final String DEFAULT_TEMPLATE = "{store} | فاکتور {invoice} | مبلغ {amount} {currency}\nاز خرید شما سپاسگزاریم";

    public static String get(String k, String def) { String v = Prefs.get("sms_" + k, ""); return v.isEmpty() ? def : v; }
    public static void set(String k, String v) { Prefs.set("sms_" + k, v == null ? "" : v); }
    public static boolean configured() { String p = get("sms.provider", ""); if ("melipayamak".equals(p)) return !get("sms.username", "").isEmpty() && !get("sms.password", "").isEmpty() && ("pattern".equals(get("sms.melipayamak_mode", "line")) ? !get("sms.melipayamak_body_id", "").isEmpty() : !get("sms.sender", "").isEmpty()); if ("kavenegar".equals(p)) return !get("sms.api_key", "").isEmpty(); return false; }
    public static boolean sendInvoiceOn() { return !"false".equals(get("sms.send_invoice", "true")); }
    /** which side texts the customer for this sale. */
    public static boolean phoneShouldSend() { return Api.standalone() || (!Api.online && "true".equals(get("sms.phone_fallback", "false"))); }

    public static String renderInvoice(String invoiceNo, double amount) {
        String t = get("sms.template.invoice", DEFAULT_TEMPLATE);
        return t.replace("{store}", Prefs.get("store_name", "فروشگاه")).replace("{invoice}", invoiceNo).replace("{amount}", java.text.NumberFormat.getInstance(java.util.Locale.US).format(Math.round(amount))).replace("{currency}", Ui.currencyLabel).replace("{coupon_line}", "");
    }

    /* ---------------- queue ---------------- */
    public static JSONArray queue() { try { String j = Db.kv("sms_queue"); return j == null ? new JSONArray() : new JSONArray(j); } catch (Exception e) { return new JSONArray(); } }
    static void save(JSONArray q) { Db.kv("sms_queue", q.toString()); }
    public static void enqueue(String phone, String text, String ref) {
        if (phone == null || phone.trim().isEmpty()) return;
        JSONArray q = queue(); try { JSONObject m = new JSONObject(); m.put("id", "s" + System.currentTimeMillis()); m.put("phone", Db.norm(phone.trim())); m.put("text", text); m.put("ref", ref == null ? "" : ref); m.put("status", "PENDING"); m.put("tries", 0); m.put("at", Db.now()); q.put(m); } catch (Exception ignore) {}
        while (q.length() > 300) q.remove(0);
        save(q);
    }
    /** queue + try to deliver right now (never on the UI thread). */
    public static void enqueueAndSend(String phone, String text, String ref) { enqueue(phone, text, ref); Api.bg(SmsLocal::flush); }

    public static synchronized int flush() {
        if (!configured()) return 0;
        JSONArray q = queue(); int sent = 0; boolean dirty = false;
        for (int i = 0; i < q.length(); i++) {
            JSONObject m = q.optJSONObject(i); if (!"PENDING".equals(m.optString("status")) && !"RETRY".equals(m.optString("status"))) continue;
            try { String resp = send(m.optString("phone"), m.optString("text")); m.put("status", "SENT"); m.put("sent_at", Db.now()); m.put("response", resp); sent++; }
            catch (Exception e) { try { int tr = m.optInt("tries") + 1; m.put("tries", tr); m.put("error", String.valueOf(e.getMessage())); m.put("status", tr >= 5 ? "FAILED" : "RETRY"); } catch (Exception ignore) {} }
            dirty = true;
        }
        if (dirty) save(q);
        return sent;
    }
    public static void retry(String id) { JSONArray q = queue(); for (int i = 0; i < q.length(); i++) if (q.optJSONObject(i).optString("id").equals(id)) { try { q.optJSONObject(i).put("status", "PENDING"); q.optJSONObject(i).put("tries", 0); } catch (Exception ignore) {} } save(q); Api.bg(SmsLocal::flush); }

    /* ---------------- providers (identical wire format to the PC) ---------------- */
    public static String send(String phone, String text) throws Exception {
        String p = get("sms.provider", "");
        if ("melipayamak".equals(p)) return melipayamak(phone, text);
        if ("kavenegar".equals(p)) return kavenegar(phone, text);
        throw new Exception("سرویس پیامک انتخاب نشده");
    }
    static final String MELI = "https://rest.payamak-panel.com/api/SendSMS";
    static String melipayamak(String phone, String text) throws Exception {
        String mode = get("sms.melipayamak_mode", "line");
        StringBuilder form = new StringBuilder("username=" + enc(get("sms.username", "")) + "&password=" + enc(get("sms.password", "")));
        String method;
        if ("pattern".equals(mode)) { StringBuilder vars = new StringBuilder(); for (String part : text.split("\n")) { if (part.trim().isEmpty()) continue; if (vars.length() > 0) vars.append(';'); vars.append(part.trim()); } method = "BaseServiceNumber"; form.append("&text=").append(enc(vars.toString())).append("&to=").append(enc(phone)).append("&bodyId=").append(enc(get("sms.melipayamak_body_id", ""))); }
        else { method = "SendSMS"; form.append("&to=").append(enc(phone)).append("&from=").append(enc(get("sms.sender", ""))).append("&text=").append(enc(text)).append("&isFlash=false"); }
        String body = http("POST", MELI + "/" + method, form.toString().getBytes(StandardCharsets.UTF_8), "application/x-www-form-urlencoded");
        JSONObject j = new JSONObject(body); int ret = j.optInt("RetStatus", -1);
        if (ret != 1) throw new Exception(meliError(ret, j));
        return body;
    }
    public static String melipayamakCredit() throws Exception {
        String form = "username=" + enc(get("sms.username", "")) + "&password=" + enc(get("sms.password", ""));
        JSONObject j = new JSONObject(http("POST", MELI + "/GetCredit", form.getBytes(StandardCharsets.UTF_8), "application/x-www-form-urlencoded"));
        if (j.optInt("RetStatus", -1) != 1) throw new Exception(meliError(j.optInt("RetStatus", -1), j));
        return j.optString("Value");
    }
    static String meliError(int code, JSONObject j) {
        switch (code) { case 0: return "نام کاربری یا رمز وب‌سرویس اشتباه است"; case 2: return "اعتبار پنل کافی نیست"; case 3: return "محدودیت روزانه ارسال"; case 4: return "محدودیت حجم ارسال"; case 5: return "شمارهٔ فرستنده معتبر نیست"; case 6: return "سامانهٔ ملی‌پیامک در حال به‌روزرسانی است"; case 7: return "متن شامل کلمهٔ فیلترشده است"; case 9: return "ارسال از خط عمومی مجاز نیست (خط اختصاصی یا حالت الگو)"; case 10: return "کاربر وب‌سرویس فعال نیست"; case 11: return "ارسال نشد"; case 12: return "مدارک کاربر کامل نیست"; case 14: return "الگو تأیید نشده یا bodyId اشتباه است"; default: return "خطای ملی‌پیامک " + code + " " + j.optString("StrRetStatus", ""); }
    }
    static String kavenegar(String phone, String text) throws Exception {
        String body = http("GET", "https://api.kavenegar.com/v1/" + enc(get("sms.api_key", "")) + "/sms/send.json?receptor=" + enc(phone) + "&message=" + enc(text), null, null);
        JSONObject j = new JSONObject(body); JSONObject r = j.optJSONObject("return"); if (r != null && r.optInt("status") != 200) throw new Exception("کاوه‌نگار: " + r.optString("message"));
        return body;
    }
    static String enc(String s) throws Exception { return java.net.URLEncoder.encode(s == null ? "" : s, "UTF-8"); }
    static String http(String method, String url, byte[] body, String ctype) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setConnectTimeout(10000); c.setReadTimeout(20000); c.setRequestMethod(method);
            if (body != null) { c.setDoOutput(true); c.setRequestProperty("Content-Type", ctype); try (OutputStream os = c.getOutputStream()) { os.write(body); } }
            int code = c.getResponseCode(); java.io.InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream(); byte[] buf = new byte[4096]; int n; while (in != null && (n = in.read(buf)) > 0) bo.write(buf, 0, n);
            String txt = bo.toString("UTF-8"); if (code >= 400) throw new Exception("HTTP " + code + " " + txt.substring(0, Math.min(120, txt.length())));
            return txt;
        } finally { c.disconnect(); }
    }

    /** the same 8-step tutorial the PC shows (routers/sms.py:guide), for offline phones. */
    public static final String[][] GUIDE = {
        {"۱. ثبت‌نام در ملی‌پیامک", "در melipayamak.com ثبت‌نام کنید (موبایل + کد ملی؛ احراز هویت الزامی است) و وارد «پنل کاربری» شوید."},
        {"۲. انتخاب نوع خط", "• خط خدماتی اشتراکی + الگو (پیشنهاد ما): بدون خرید خط، به شماره‌های مسدودِ تبلیغات هم می‌رسد. پنل → «ارسال الگو (پترن)» → «ایجاد الگوی جدید».\n• خط اختصاصی: از «خطوط» خط بخرید و شمارهٔ آن را در «شمارهٔ خط ارسال» بنویسید."},
        {"۳. ساخت الگو (حالت الگو)", "متن را با متغیرهای ترتیبی بنویسید، مثلاً:\nفروشگاه {0} | فاکتور {1} | مبلغ {2} تومان\nاز خرید شما سپاسگزاریم\nپس از تأیید، «کد الگو (bodyId)» را در «شناسهٔ الگو» وارد کنید. تعداد خط‌های الگوی داخل برنامه باید با متغیرها یکی باشد."},
        {"۴. کاربر وب‌سرویس", "پنل → «تنظیمات» → «وب‌سرویس» → «ایجاد نام کاربری وب‌سرویس». نام کاربری و رمزِ وب‌سرویس (نه رمز ورود پنل) را این‌جا وارد کنید."},
        {"۵. شارژ اعتبار", "از «افزایش اعتبار» شارژ کنید؛ بدون اعتبار خطای «اعتبار کافی نیست» می‌گیرید."},
        {"۶. تنظیم در برنامه", "سرویس = ملی‌پیامک، حالت = الگو یا خط، مقادیر را ذخیره کنید و «تست اتصال» را بزنید (اعتبار پنل را نشان می‌دهد)."},
        {"۷. پیامک خودکار فاکتور", "«ارسال پیامک فاکتور» روشن باشد؛ مستقل از چاپ رسید است. به محض تأیید فاکتور برای مشتریِ دارای شمارهٔ موبایل ارسال می‌شود (مشتری آزاد = بدون پیامک)."},
        {"۸. کاوه‌نگار (جایگزین)", "panel.kavenegar.com → تنظیمات → API Key را کپی کنید؛ سرویس = کاوه‌نگار و کلید را وارد کنید."},
    };
}
