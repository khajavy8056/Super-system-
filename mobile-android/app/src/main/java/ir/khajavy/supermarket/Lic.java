package ir.khajavy.supermarket;

import org.json.JSONObject;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * v2.1 — licence on the phone. Two modes (chosen in the setup wizard):
 *
 *  PC mode ("pc"):      the phone never holds a key. Every sync asks the PC
 *                        (GET /api/mobile/link → license.allowed); any 402 from
 *                        the PC also locks the phone. The last verdict is cached
 *                        so the phone stays usable offline until the PC's known
 *                        expiry date — exactly like the PC itself.
 *  Standalone ("own"):  the key is activated from the phone against the same
 *                        licence server the Windows build uses (same protocol,
 *                        HWID = per-phone id). Same rules: valid until the known
 *                        expiry even offline; without an expiry, 7-day grace.
 *
 * When not allowed → {@link LockActivity}: «لایسنس شما به پایان رسیده» with
 * nothing but the support contact.
 */
public final class Lic {
    private Lic() {}
    public static final String SERVER = "https://soft-hat-4eba.khajavi8056.workers.dev/";
    private static final SimpleDateFormat ISO = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
    private static final long DAY = 86400000L;

    public static String mode() { return Prefs.get("lic_mode", ""); }               // "" | pc | own
    public static boolean setupDone() { return "1".equals(Prefs.get("setup_done", "")); }
    public static String hwid() {
        String id = Prefs.deviceIdStatic(); if (id == null) id = "phone";
        try { MessageDigest md = MessageDigest.getInstance("SHA-1"); byte[] h = md.digest(("android|" + id + "|" + android.os.Build.SERIAL + android.os.Build.MODEL).getBytes("UTF-8")); StringBuilder b = new StringBuilder(); for (int i = 0; i < 8; i++) b.append(String.format("%02X", h[i])); return "AND-" + b; } catch (Exception e) { return "AND-" + id; }
    }

    /** Local verdict from the cached state (no network). */
    public static boolean allowed() {
        if (!setupDone()) return true;
        String st = Prefs.get("lic_status", "");
        if (!"ACTIVE".equals(st)) return false;
        String exp = Prefs.get("lic_expires", "");
        long now = System.currentTimeMillis();
        if (!exp.isEmpty()) { try { return ISO.parse(exp).getTime() + DAY > now; } catch (Exception e) { return false; } }
        long checked = Long.parseLong(Prefs.get("lic_checked", "0"));
        return now - checked < 7 * DAY;
    }
    public static String reason() {
        String st = Prefs.get("lic_status", ""), exp = Prefs.get("lic_expires", "");
        if ("EXPIRED".equals(st) || (!exp.isEmpty() && !allowed())) return "مدت اعتبار لایسنس " + (exp.isEmpty() ? "" : "در " + Ui.jdate(exp) + " ") + "به پایان رسیده است";
        if ("REVOKED".equals(st)) return "لایسنس باطل شده است";
        if ("ACTIVE".equals(st)) return "بیش از ۷ روز است که لایسنس به‌صورت آنلاین تأیید نشده؛ برای ادامه به اینترنت (یا رایانهٔ فروشگاه) متصل شوید";
        String m = Prefs.get("lic_message", ""); return m.isEmpty() ? "لایسنس فعال نیست" : m;
    }
    public static String expires() { return Prefs.get("lic_expires", ""); }

    static void store(String status, String expires, String type, String owner, String message) {
        Prefs.set("lic_status", status); Prefs.set("lic_expires", expires == null ? "" : expires); Prefs.set("lic_type", type == null ? "" : type);
        Prefs.set("lic_owner", owner == null ? "" : owner); Prefs.set("lic_message", message == null ? "" : message); Prefs.set("lic_checked", String.valueOf(System.currentTimeMillis()));
    }

    /** PC mode: apply the verdict the PC returned (from /mobile/link or a 402 body). */
    public static void fromPc(JSONObject lic) {
        if (lic == null) return;
        boolean ok = lic.optBoolean("allowed", false);
        String status = lic.optString("status", ok ? "ACTIVE" : "EXPIRED");
        if (ok) status = "ACTIVE"; else if ("ACTIVE".equals(status)) status = "EXPIRED";
        store(status, lic.isNull("expires") ? "" : lic.optString("expires"), Prefs.get("lic_type", "PC"), Prefs.get("lic_owner", ""), lic.optString("reason", ""));
        if (!ok) Prefs.set("lic_locked_by_pc", "1"); else Prefs.set("lic_locked_by_pc", "");
    }
    public static void pcLocked(String reason) { store("EXPIRED", Prefs.get("lic_expires", ""), Prefs.get("lic_type", "PC"), Prefs.get("lic_owner", ""), reason); }

    /** Standalone: blocking activation / re-check against the licence server. Returns null on success, else a Persian message. */
    public static String activate(String key) {
        key = key == null ? "" : Db.norm(key).trim().toUpperCase();
        if (key.length() < 8) return "کلید لایسنس کوتاه است";
        HttpURLConnection c = null;
        try {
            String u = SERVER + (SERVER.contains("?") ? "&" : "?") + "api_action=validate&key=" + java.net.URLEncoder.encode(key, "UTF-8") + "&hwid=" + java.net.URLEncoder.encode(hwid(), "UTF-8");
            c = (HttpURLConnection) new URL(u).openConnection(); c.setConnectTimeout(8000); c.setReadTimeout(12000); c.setRequestProperty("User-Agent", "SupermarketAndroid/" + Version.NAME);
            int code = c.getResponseCode(); InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream(); byte[] buf = new byte[4096]; int n; while (in != null && (n = in.read(buf)) > 0) bo.write(buf, 0, n);
            JSONObject d = new JSONObject(bo.toString("UTF-8"));
            String status = d.optString("status", "").toUpperCase();
            if (!"SUCCESS".equals(status) && !"ACTIVE".equals(status) && !"OK".equals(status)) {
                String msg = d.optString("message", "");
                if (msg.isEmpty()) msg = "EXPIRED".equals(status) ? "این لایسنس منقضی شده است" : "INVALID".equals(status) || "NOT_FOUND".equals(status) ? "کلید لایسنس معتبر نیست" : "HWID_MISMATCH".equals(status) ? "این لایسنس روی دستگاه دیگری فعال شده است" : "REVOKED".equals(status) ? "این لایسنس باطل شده است" : "پاسخ سرور: " + status;
                store(status.isEmpty() ? "INVALID" : status, "", "", "", msg);
                return msg;
            }
            String exp = d.optString("expires", ""); if (exp.length() > 10) exp = exp.substring(0, 10);
            Prefs.set("lic_key", key); Prefs.set("lic_mode", "own");
            store("ACTIVE", exp, d.optString("type", "FULL"), d.optString("owner", ""), "");
            return null;
        } catch (Exception e) {
            return "ارتباط با سرور لایسنس برقرار نشد — اینترنت را بررسی کنید";
        } finally { if (c != null) c.disconnect(); }
    }

    /** Background re-validation (standalone, once a day) — never downgrades on a network error. */
    public static void recheckIfDue() {
        if (!"own".equals(mode())) return;
        long checked = Long.parseLong(Prefs.get("lic_checked", "0"));
        if (System.currentTimeMillis() - checked < DAY) return;
        String key = Prefs.get("lic_key", ""); if (key.isEmpty()) return;
        Api.bg(() -> activate(key));
    }
    public static String masked() { String k = Prefs.get("lic_key", ""); return k.length() >= 8 ? k.substring(0, 4) + "-****-****-" + k.substring(k.length() - 4) : ""; }
    public static String today() { return ISO.format(new Date()); }
}
