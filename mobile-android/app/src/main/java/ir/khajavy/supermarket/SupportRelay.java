package ir.khajavy.supermarket;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * v2.1 — direct support relay for phones WITHOUT a PC (standalone / locked).
 * Same transport and same inbox as the Windows build (bot relay), same message
 * layout, same routing key «TCK-000001@INSTALL8», so the operator answers from
 * the very same inbox and the reply is filed under the ticket on the phone.
 * Tickets and messages are kept in the phone's SQLite (kv "support_tickets").
 */
public final class SupportRelay {
    private SupportRelay() {}
    static final String URL_BASE = "https://botapi.rubika.ir/v3";
    static final String TOKEN = "CDJFAE0BITPJAHSUTQNWIIZKSMPOTEYATQNHZVDZYBWMUMYISOIRVWVINHFSRXVF";
    static final String OWNER = "khajavi8056";

    public static String installId() { String h = Lic.hwid(); return h.startsWith("AND-") ? h.substring(4) : h; }
    public static String installCode() { return Prefs.get("store_name", "فروشگاه") + " #" + installId(); }

    static JSONObject post(String method, JSONObject payload) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(URL_BASE + "/" + TOKEN + "/" + method).openConnection();
        try {
            c.setConnectTimeout(8000); c.setReadTimeout(15000); c.setRequestMethod("POST"); c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json");
            try (OutputStream os = c.getOutputStream()) { os.write(payload.toString().getBytes(StandardCharsets.UTF_8)); }
            int code = c.getResponseCode(); InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream(); byte[] buf = new byte[8192]; int n; while (in != null && (n = in.read(buf)) > 0) bo.write(buf, 0, n);
            JSONObject r = new JSONObject(bo.toString("UTF-8"));
            if (code >= 400 || !"OK".equals(r.optString("status", "OK"))) throw new Exception("HTTP " + code + " " + r.optString("status"));
            return r;
        } finally { c.disconnect(); }
    }

    static String inbox() throws Exception {
        String cached = Prefs.get("support_inbox", ""); if (!cached.isEmpty()) return cached;
        JSONObject r = post("getUpdates", Api.obj("limit", "100"));
        JSONArray ups = r.optJSONObject("data") == null ? null : r.optJSONObject("data").optJSONArray("updates");
        String found = null;
        for (int i = 0; ups != null && i < ups.length(); i++) {
            JSONObject u = ups.optJSONObject(i); JSONObject m = u.optJSONObject("new_message"); String chat = u.optString("chat_id", m == null ? "" : m.optString("chat_id"));
            if (chat.isEmpty()) continue; if (found == null) found = chat;
            String sender = (m == null ? "" : m.optString("sender_username", m.optString("username", ""))).toLowerCase().replace("@", "");
            if (OWNER.equals(sender)) { found = chat; break; }
        }
        if (found == null) throw new Exception("INBOX_UNKNOWN");
        Prefs.set("support_inbox", found); return found;
    }

    static JSONArray tickets() { try { return new JSONArray(Db.kv("support_tickets") == null ? "[]" : Db.kv("support_tickets")); } catch (Exception e) { return new JSONArray(); } }
    static void saveTickets(JSONArray a) { Db.kv("support_tickets", a.toString()); }

    /** Composes + sends a new ticket. Returns null on success, else a Persian message. The ticket is stored either way. */
    public static String send(JSONObject t) {
        JSONArray all = tickets();
        String number = String.format(java.util.Locale.US, "TCK-%06d", all.length() + 1);
        String ref = number + "@" + installId();
        String text = "🎫 درخواست پشتیبانی جدید — " + ref + "\n🆔 کد فروشگاه: " + installCode() + "   (برای پاسخ: روی همین پیام Reply بزنید یا پیام را با «" + ref + "» شروع کنید)\n"
                + "نوع: " + t.optString("type") + "   |   اولویت: " + t.optString("priority") + "\nموضوع: " + t.optString("subject") + "\n\n" + t.optString("description", "—") + "\n\n"
                + "🏪 فروشگاه: " + Prefs.get("store_name", "—") + "\n📞 تماس: " + t.optString("contact", "—") + "\n📱 دستگاه: " + t.optString("device", "android") + " (بدون رایانه)   |   نسخه: " + Version.NAME
                + "\n🔑 لایسنس: " + (Lic.masked().isEmpty() ? "لایسنس رایانه" : Lic.masked()) + " · HWID: " + Lic.hwid() + "\n🕒 " + Db.now();
        JSONObject rec = new JSONObject();
        try { rec.put("id", all.length() + 1); rec.put("number", number); rec.put("subject", t.optString("subject")); rec.put("type_label", t.optString("type")); rec.put("priority_label", t.optString("priority")); rec.put("description", t.optString("description")); rec.put("created_at", Db.now()); rec.put("status", "NEW"); rec.put("status_label", "ثبت‌شده"); rec.put("messages", new JSONArray()); rec.put("unread", 0); } catch (Exception ignore) {}
        String err = null;
        try { JSONObject r = post("sendMessage", Api.obj("chat_id", inbox(), "text", text)); rec.put("relay_ref", r.optJSONObject("data") == null ? "" : r.optJSONObject("data").optString("message_id")); rec.put("status", "SENT"); rec.put("status_label", "ارسال‌شده به پشتیبانی"); }
        catch (Exception e) { err = "ارسال انجام نشد (اینترنت را بررسی کنید) — درخواست ذخیره شد و بعداً دوباره ارسال می‌شود"; try { rec.put("status", "FAILED"); rec.put("status_label", "در انتظار ارسال مجدد"); rec.put("text", text); } catch (Exception ignore) {} }
        all.put(rec); saveTickets(all);
        return err;
    }

    /** Follow-up message on an existing ticket (reply-threaded in the inbox). */
    public static String reply(int id, String msg) {
        JSONArray all = tickets(); JSONObject t = null; for (int i = 0; i < all.length(); i++) if (all.optJSONObject(i).optInt("id") == id) t = all.optJSONObject(i);
        if (t == null) return "درخواست یافت نشد";
        String ref = t.optString("number") + "@" + installId();
        try {
            JSONObject p = Api.obj("chat_id", inbox(), "text", "💬 " + ref + " — " + installCode() + "\n" + msg); if (!t.optString("relay_ref").isEmpty()) p.put("reply_to_message_id", t.optString("relay_ref"));
            post("sendMessage", p);
            JSONObject m = new JSONObject(); m.put("direction", "OUT"); m.put("text", msg); m.put("created_at", Db.now()); t.optJSONArray("messages").put(m); saveTickets(all); return null;
        } catch (Exception e) { return "ارسال انجام نشد — اینترنت را بررسی کنید"; }
    }

    /** Resend failed tickets + fetch operator replies. Returns number of new replies. */
    public static int poll() {
        JSONArray all = tickets(); int got = 0; boolean dirty = false;
        try {
            String inbox = inbox();
            for (int i = 0; i < all.length(); i++) { JSONObject t = all.optJSONObject(i); if ("FAILED".equals(t.optString("status")) && t.has("text")) { try { JSONObject r = post("sendMessage", Api.obj("chat_id", inbox, "text", t.optString("text"))); t.put("relay_ref", r.optJSONObject("data").optString("message_id")); t.put("status", "SENT"); t.put("status_label", "ارسال‌شده به پشتیبانی"); t.remove("text"); dirty = true; } catch (Exception ignore) {} } }
            JSONObject q = Api.obj("limit", "100"); String off = Prefs.get("support_offset", ""); if (!off.isEmpty()) q.put("offset_id", off);
            JSONObject r = post("getUpdates", q); JSONObject d = r.optJSONObject("data"); JSONArray ups = d == null ? null : d.optJSONArray("updates");
            String mine = installId().toUpperCase();
            for (int i = 0; ups != null && i < ups.length(); i++) {
                JSONObject u = ups.optJSONObject(i); JSONObject m = u.optJSONObject("new_message"); if (m == null || "Bot".equals(m.optString("sender_type"))) continue;
                if (!inbox.equals(u.optString("chat_id", ""))) continue;
                String text = m.optString("text", ""); String rid = m.optString("reply_to_message_id", ""); JSONObject hit = null;
                for (int k = 0; k < all.length(); k++) { JSONObject t = all.optJSONObject(k); if (!rid.isEmpty() && rid.equals(t.optString("relay_ref"))) hit = t; else if (text.toUpperCase().contains(t.optString("number") + "@" + mine)) hit = t; }
                if (hit == null) continue;
                String mid = m.optString("message_id"); boolean dup = false; JSONArray ms = hit.optJSONArray("messages");
                for (int k = 0; k < ms.length(); k++) if (mid.equals(ms.optJSONObject(k).optString("mid"))) dup = true;
                if (dup) continue;
                JSONObject nm = new JSONObject(); nm.put("direction", "IN"); nm.put("mid", mid); nm.put("text", text.replaceFirst("^\\s*TCK-\\d{6}@[0-9A-Za-z\\-]+\\s*[:\\-—]?\\s*", "")); nm.put("created_at", Db.now()); ms.put(nm); hit.put("unread", hit.optInt("unread") + 1); got++; dirty = true;
            }
            if (d != null && !d.optString("next_offset_id").isEmpty()) Prefs.set("support_offset", d.optString("next_offset_id"));
        } catch (Exception ignore) {}
        if (dirty) saveTickets(all);
        return got;
    }
    public static void markRead(int id) { JSONArray all = tickets(); for (int i = 0; i < all.length(); i++) if (all.optJSONObject(i).optInt("id") == id) { try { all.optJSONObject(i).put("unread", 0); } catch (Exception ignore) {} } saveTickets(all); }
}
