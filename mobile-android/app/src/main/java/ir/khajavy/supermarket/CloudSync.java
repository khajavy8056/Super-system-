package ir.khajavy.supermarket;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * v2.1 — internet fallback when the PC is not on this Wi-Fi: the phone talks to
 * the SAME Google Drive appDataFolder the PC uses (credentials arrive inside the
 * pairing QR / code / «/mobile/link» once the owner has signed in on the PC).
 *
 *  pull: snapshot.json (products / batches / customers) → local SQLite
 *  push: intentionally withheld until the PC protocol has authenticated per-user acknowledgements;
 *        local operations remain queued and are sent through the authenticated LAN/relay API.
 *
 * Nothing here runs unless cloud_json is present; a failure never blocks LAN sync.
 */
public final class CloudSync {
    private CloudSync() {}
    static JSONObject cfg() { try { String j = Prefs.get("cloud_json", ""); return j.isEmpty() ? null : new JSONObject(j); } catch (Exception e) { return null; } }
    public static boolean available() { JSONObject c = cfg(); return c != null && !c.optString("refresh_token").isEmpty(); }
    public static String account() { JSONObject c = cfg(); return c == null ? "" : c.optString("account", ""); }

    static String token(JSONObject c) throws Exception {
        long exp = Long.parseLong(Prefs.get("cloud_tok_exp", "0")); String t = Prefs.get("cloud_tok", "");
        if (!t.isEmpty() && exp > System.currentTimeMillis()) return t;
        String body = "client_id=" + enc(c.optString("client_id")) + "&client_secret=" + enc(c.optString("client_secret")) + "&refresh_token=" + enc(c.optString("refresh_token")) + "&grant_type=refresh_token";
        JSONObject r = new JSONObject(http("POST", c.optString("token_url", "https://oauth2.googleapis.com/token"), body.getBytes(StandardCharsets.UTF_8), "application/x-www-form-urlencoded", null));
        if (!r.has("access_token")) throw new Exception(r.optString("error_description", r.optString("error", "token")));
        Prefs.set("cloud_tok", r.optString("access_token")); Prefs.set("cloud_tok_exp", String.valueOf(System.currentTimeMillis() + (r.optLong("expires_in", 3600) - 60) * 1000));
        return r.optString("access_token");
    }
    static String enc(String s) throws Exception { return java.net.URLEncoder.encode(s, "UTF-8"); }
    static String http(String method, String url, byte[] body, String ctype, String bearer) throws Exception {
        Api.requireSafeEndpoint(url);
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setConnectTimeout(10000); c.setReadTimeout(30000); c.setRequestMethod("PATCH".equals(method) ? "POST" : method); if ("PATCH".equals(method)) c.setRequestProperty("X-HTTP-Method-Override", "PATCH");
            if (bearer != null) c.setRequestProperty("Authorization", "Bearer " + bearer);
            if (body != null) { c.setDoOutput(true); c.setRequestProperty("Content-Type", ctype); try (OutputStream os = c.getOutputStream()) { os.write(body); } }
            int code = c.getResponseCode(); InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream(); byte[] buf = new byte[8192]; int n; while (in != null && (n = in.read(buf)) > 0) bo.write(buf, 0, n);
            String txt = bo.toString("UTF-8"); if (code >= 400) throw new Exception("HTTP " + code + " " + txt.substring(0, Math.min(160, txt.length())));
            return txt;
        } finally { c.disconnect(); }
    }

    /** Full cycle; returns applied-count-equivalent (ops uploaded) or -1 when unavailable/failed. */
    public static int run() {
        JSONObject c = cfg(); if (c == null || c.optString("refresh_token").isEmpty()) return -1;
        try {
            String tok = token(c); String api = c.optString("api_url", "https://www.googleapis.com/drive/v3");
            int pushed = 0;
            long activeUserId = Screens.user == null ? 0 : Screens.user.optLong("id", 0);
            boolean pendingOps = !Db.opsForUser(activeUserId).isEmpty();
            // Do not put an API bearer token inside a persistent Drive file or delete local
            // operations merely because Drive accepted an upload. The PC-side cloud protocol
            // needs an authenticated, per-operation acknowledgement before this can be enabled.
            // Pending operations remain safely queued and are sent over the LAN/relay sync route.

            // pull snapshot
            JSONObject list = new JSONObject(http("GET", api + "/files?spaces=appDataFolder&q=" + enc("name = 'snapshot.json' and trashed = false") + "&fields=" + enc("files(id,name,modifiedTime)"), null, null, tok));
            JSONArray files = list.optJSONArray("files");
            if (files != null && files.length() > 0) {
                JSONObject f = files.getJSONObject(0); String mod = f.optString("modifiedTime");
                if (!mod.equals(Prefs.get("cloud_snapshot_mod", ""))) {
                    JSONObject snap = new JSONObject(http("GET", api + "/files/" + f.getString("id") + "?alt=media", null, null, tok));
                    Db.applyPull(snap, true); Prefs.set("cloud_snapshot_mod", mod); Prefs.set("cloud_last_pull", Db.now());
                }
            }
            Prefs.set("cloud_last_error", pendingOps
                    ? "عملیات فروش تا افزودن تأیید امن رایانه در صف محلی می‌ماند؛ از شبکهٔ محلی همگام‌سازی می‌شود"
                    : "");
            return pushed;
        } catch (Exception e) { Prefs.set("cloud_last_error", String.valueOf(e.getMessage())); return -1; }
    }
}
