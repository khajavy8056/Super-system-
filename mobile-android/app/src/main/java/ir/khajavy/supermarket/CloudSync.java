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
 *  push: queued ops → ops-<device>-<ts>.json   (the PC applies + deletes them)
 *  pull: snapshot.json (products / batches / customers) → local SQLite
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
            String tok = token(c); String api = c.optString("api_url", "https://www.googleapis.com/drive/v3"), up = c.optString("upload_url", "https://www.googleapis.com/upload/drive/v3");
            int pushed = 0;
            List<JSONObject> ops = Db.ops();
            if (!ops.isEmpty()) {
                JSONArray push = new JSONArray(); for (JSONObject o : ops) { JSONObject op = new JSONObject(); op.put("id", o.getString("id")); op.put("type", o.getString("type")); op.put("payload", Sync.cleanLocalIds(o.getJSONObject("payload"))); op.put("created_at", o.optString("created_at")); push.put(op); }
                JSONObject file = new JSONObject(); file.put("device_id", Prefs.deviceIdStatic()); file.put("token", Api.token); file.put("push", push); file.put("generated_at", Db.now());
                String name = "ops-" + Prefs.deviceIdStatic() + "-" + System.currentTimeMillis() + ".json";
                String boundary = "smkt-boundary-7f3a"; JSONObject meta = new JSONObject(); meta.put("name", name); meta.put("parents", new JSONArray().put("appDataFolder"));
                java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
                bo.write(("--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" + meta + "\r\n--" + boundary + "\r\nContent-Type: application/json\r\n\r\n").getBytes(StandardCharsets.UTF_8)); bo.write(file.toString().getBytes(StandardCharsets.UTF_8)); bo.write(("\r\n--" + boundary + "--").getBytes(StandardCharsets.UTF_8));
                http("POST", up + "/files?uploadType=multipart", bo.toByteArray(), "multipart/related; boundary=" + boundary, tok);
                for (JSONObject o : ops) { Db.opDelete(o.getString("id")); pushed++; }
                Prefs.set("cloud_last_push", Db.now());
            }
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
            Prefs.set("cloud_last_error", "");
            return pushed;
        } catch (Exception e) { Prefs.set("cloud_last_error", String.valueOf(e.getMessage())); return -1; }
    }
}
