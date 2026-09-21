package ir.khajavy.supermarket;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * v2.3 — phone side of the online relay (relay/server.py). When the PC is not on
 * this Wi-Fi, every API call is wrapped as JSON and posted to
 * {relay}/r/{store}/call; the PC (services/relay_client.py) answers within seconds.
 * Same endpoints, same token, same permissions — the app does not know the difference.
 *
 * Route order (see {@link Api#health()} / {@link Sync}): LAN → relay → Drive.
 */
public final class Relay {
    private Relay() {}
    public static volatile boolean active = false;      // currently routing through the relay
    public static volatile long lastOk = 0;

    static JSONObject cfg() { try { String j = Prefs.get("relay_json", ""); return j.isEmpty() ? null : new JSONObject(j); } catch (Exception e) { return null; } }
    public static boolean available() { JSONObject c = cfg(); return c != null && !c.optString("url").isEmpty() && !c.optString("key").isEmpty(); }
    public static String label() { JSONObject c = cfg(); return c == null ? "" : c.optString("url").replace("https://", "").replace("http://", ""); }
    static String base(JSONObject c) { return c.optString("url").replaceAll("/+$", "") + "/r/" + c.optString("store"); }

    /** Is the PC currently connected to the relay? (also refreshes its LAN addresses for the fast path). */
    public static boolean pcOnline() {
        JSONObject c = cfg(); if (c == null) return false;
        try {
            JSONObject j = new JSONObject(raw("GET", base(c) + "/beacon?key=" + enc(c.optString("key")), null));
            if (j.optJSONArray("lan") != null && j.optJSONArray("lan").length() > 0) Prefs.set("pc_lan_json", j.optJSONArray("lan").toString() + "|" + j.optInt("port", 0));
            return j.optBoolean("pc_online");
        } catch (Exception e) { return false; }
    }

    /** {status, body} — throws on relay/network failure. */
    public static String[] call(String method, String path, String body, String contentType, String token) throws Exception {
        JSONObject c = cfg(); if (c == null) throw new Exception("relay not configured");
        JSONObject req = new JSONObject(); req.put("method", method); req.put("path", "/api" + path);
        JSONObject h = new JSONObject(); h.put("Accept", "application/json"); if (token != null && !token.isEmpty()) h.put("Authorization", "Bearer " + token); if (body != null) h.put("Content-Type", contentType == null ? "application/json" : contentType); req.put("headers", h);
        if (body != null) req.put("body", body);
        String resp = raw("POST", base(c) + "/call?key=" + enc(c.optString("key")), req.toString());
        JSONObject j = new JSONObject(resp);
        if (j.has("detail") && !j.has("status")) throw new Exception(j.optString("message", j.optString("detail")));
        lastOk = System.currentTimeMillis();
        return new String[]{String.valueOf(j.optInt("status", 502)), j.isNull("body") ? "" : j.optString("body")};
    }

    static String raw(String method, String url, String json) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setConnectTimeout(8000); c.setReadTimeout(32000); c.setRequestMethod(method);
            if (json != null) { c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json"); try (OutputStream os = c.getOutputStream()) { os.write(json.getBytes(StandardCharsets.UTF_8)); } }
            int code = c.getResponseCode(); java.io.InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream(); byte[] buf = new byte[8192]; int n; while (in != null && (n = in.read(buf)) > 0) bo.write(buf, 0, n);
            String txt = bo.toString("UTF-8");
            if (code == 503 || code == 504) { try { JSONObject j = new JSONObject(txt); throw new Exception(j.optString("message", "PC offline")); } catch (org.json.JSONException e) { throw new Exception("HTTP " + code); } }
            if (code >= 400) throw new Exception("HTTP " + code + " " + txt.substring(0, Math.min(100, txt.length())));
            return txt;
        } finally { c.disconnect(); }
    }
    static String enc(String s) throws Exception { return java.net.URLEncoder.encode(s == null ? "" : s, "UTF-8"); }
}
