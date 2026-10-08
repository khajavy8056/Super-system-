package ir.khajavy.supermarket;

import android.os.Handler;
import android.os.Looper;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * v2.0 — NATIVE JSON client for the shop PC's REST API (no WebView, no HTML).
 *
 * The phone exchanges ONLY data with the PC: every screen calls these methods,
 * parses JSON and renders native Android views. Successful GETs are mirrored
 * into the local SQLite cache so every section stays readable when the PC is
 * off; writes made offline go to the operation queue (see {@link Sync}).
 */
public final class Api {
    public static final class ApiError extends Exception {
        public final int status; public final String code;
        public ApiError(int status, String code, String message) { super(message); this.status = status; this.code = code; }
        public boolean offline() { return status == 0 || status >= 500; }
    }
    public interface Cb<T> { void ok(T result); }
    public interface ErrCb { void err(ApiError e); }

    private static final ExecutorService POOL = Executors.newFixedThreadPool(4);
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    public static volatile String base = "";
    public static volatile String token = "";
    public static volatile boolean online = false;
    /** v4.8.1 — how the LAST successful call was served: "lan" (direct on the
     *  shop network), "relay" (online relay, i.e. from outside), or "local"
     *  (phone's own SQLite). LoginActivity applies local_only to online routes
     *  and offline_allowed to cached SQLite sign-in. */
    public static volatile String lastRoute = "lan";

    private Api() {}

    public static boolean standalone() { return base == null || base.isEmpty() || base.contains("standalone.invalid"); }

    /* ---------------- async (main-thread callbacks) ---------------- */
    public static void get(String path, Cb<Object> ok, ErrCb err) { run("GET", path, null, ok, err, true); }
    public static void post(String path, JSONObject body, Cb<Object> ok, ErrCb err) { run("POST", path, body == null ? "{}" : body.toString(), ok, err, false); }
    public static void put(String path, JSONObject body, Cb<Object> ok, ErrCb err) { run("PUT", path, body == null ? "{}" : body.toString(), ok, err, false); }
    public static void patch(String path, JSONObject body, Cb<Object> ok, ErrCb err) { run("PATCH", path, body == null ? "{}" : body.toString(), ok, err, false); }
    public static void delete(String path, Cb<Object> ok, ErrCb err) { run("DELETE", path, null, ok, err, false); }

    private static long activeUserId() {
        long localId = Db.localUserId();
        if (localId > 0) return localId;
        if (Screens.user != null && Screens.user.optLong("id", 0) > 0) return Screens.user.optLong("id", 0);
        try { return new JSONObject(Prefs.get("user_json", "{}")).optLong("id", 0); }
        catch (Exception e) { return 0; }
    }
    private static String cacheKey(String path, long userId) { return userId > 0 ? "u/" + userId + path : null; }
    private static void run(String method, String path, String body, Cb<Object> ok, ErrCb err, boolean cacheable) {
        final long requestUserId = activeUserId();
        final String scopedCacheKey = cacheKey(path, requestUserId);
        POOL.execute(() -> {
            try {
                Object r = call(method, path, body, "application/json");
                if (cacheable && scopedCacheKey != null) Db.cachePut(scopedCacheKey, r == null ? "null" : r.toString());
                if (!standalone()) online = !"local".equals(lastRoute);
                if (requestUserId > 0 && activeUserId() != requestUserId) return;
                MAIN.post(() -> { if (ok != null) ok.ok(r); });
            } catch (ApiError e) {
                if (e.offline()) online = false;
                if (cacheable && e.offline() && scopedCacheKey != null) {
                    String cached = Db.cacheGet(scopedCacheKey);
                    if (cached != null) {
                        try { Object r = parse(cached); if (requestUserId > 0 && activeUserId() != requestUserId) return; MAIN.post(() -> { Ui.toast("آفلاین — آخرین نسخهٔ ذخیره‌شده"); if (ok != null) ok.ok(r); }); return; } catch (Exception ignore) {}
                    }
                }
                if (requestUserId > 0 && activeUserId() != requestUserId) return;
                MAIN.post(() -> { if (err != null) err.err(e); else Ui.toast(e.getMessage()); });
            } catch (Throwable t) {   // v3.3: a bug/OOM inside a local handler must surface as an error card, never kill the app
                ApiError e = new ApiError(500, "LOCAL", t instanceof OutOfMemoryError ? "حافظهٔ گوشی کافی نبود" : "خطای داخلی: " + t);
                MAIN.post(() -> { if (err != null) err.err(e); else Ui.toast(e.getMessage()); });
            }
        });
    }
    /** v3.3: background work that must never take the app down. */
    public static void bg(Runnable r) { POOL.execute(() -> { try { r.run(); } catch (Throwable t) { android.util.Log.w("Api", "bg task failed: " + t); } }); }

    /* ---------------- blocking (call from a worker thread) ---------------- */
    public static Object call(String method, String path, String body, String contentType) throws ApiError {
        return callWithToken(token, method, path, body, contentType);
    }
    /** Use a captured session for long sync cycles so an account switch cannot pair one user's queue with another token. */
    public static Object callWithToken(String requestToken, String method, String path, String body, String contentType) throws ApiError {
        // v2.4: standalone → the phone answers every endpoint itself from SQLite (Local).
        if (standalone()) { lastRoute = "local"; return Local.handle(method, path, body); }
        if (Relay.active && Relay.available()) { Object r = viaRelay(method, path, body, contentType, requestToken); lastRoute = "relay"; return r; }
        try { Object r = callPc(method, path, body, contentType, requestToken); lastRoute = "lan"; return r; }
        catch (ApiError e) {
            // Paired but PC unreachable: reads use the local mirror; HR writes and
            // the two read-only POS benefit validators use local rules/snapshots.
            boolean localOfferValidation = "POST".equals(method)
                    && ("/pos/campaigns/eligible".equals(path) || "/marketing/coupons/validate".equals(path));
            if (e.offline() && ("GET".equals(method) || path.startsWith("/hr/") || localOfferValidation)) {
                try { Object r = Local.handle(method, path, body); lastRoute = "local"; return r; }
                catch (ApiError localError) { if (!"GET".equals(method)) throw localError; }
            }
            throw e;
        }
    }
    /** Cleartext is permitted only to loopback/private-LAN endpoints used by the paired shop PC.
     * Public internet endpoints must use HTTPS before any bearer token is sent. */
    static void requireSafeEndpoint(String endpoint) throws Exception {
        java.net.URL parsed = new URL(endpoint);
        if (parsed.getUserInfo() != null) throw new SecurityException("Credentials in endpoint URL are forbidden");
        if ("https".equalsIgnoreCase(parsed.getProtocol())) return;
        if (!"http".equalsIgnoreCase(parsed.getProtocol()) || !privateHost(parsed.getHost()))
            throw new SecurityException("Public or untrusted cleartext endpoint refused");
    }
    private static boolean privateHost(String host) {
        if (host == null || host.isEmpty()) return false;
        String h = host.toLowerCase(java.util.Locale.ROOT);
        if ("localhost".equals(h) || h.endsWith(".local")) return true;
        try {
            java.net.InetAddress[] addresses = java.net.InetAddress.getAllByName(host);
            if (addresses.length == 0) return false;
            for (java.net.InetAddress address : addresses) {
                if (address.isAnyLocalAddress() || address.isLoopbackAddress() || address.isLinkLocalAddress() || address.isSiteLocalAddress()) continue;
                byte[] b = address.getAddress();
                if (b.length == 16 && (b[0] & 0xfe) == 0xfc) continue; // IPv6 unique-local fc00::/7
                return false;
            }
            return true;
        } catch (Exception e) { return false; }
    }

    static Object callPc(String method, String path, String body, String contentType, String requestToken) throws ApiError {
        HttpURLConnection c = null;
        try {
            String endpoint = base + "/api" + path;
            requireSafeEndpoint(endpoint);
            c = (HttpURLConnection) new URL(endpoint).openConnection();
            c.setConnectTimeout(4000); c.setReadTimeout(20000);
            if ("PATCH".equals(method)) { c.setRequestMethod("POST"); c.setRequestProperty("X-HTTP-Method-Override", "PATCH"); }
            else c.setRequestMethod(method);
            c.setRequestProperty("Accept", "application/json");
            c.setRequestProperty("User-Agent", "SupermarketAndroid/" + Version.NAME + " native");
            if (requestToken != null && !requestToken.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + requestToken);
            if (body != null) {
                c.setDoOutput(true); c.setRequestProperty("Content-Type", contentType);
                try (OutputStream os = c.getOutputStream()) { os.write(body.getBytes(StandardCharsets.UTF_8)); }
            }
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            String text = in == null ? "" : slurp(in);
            if (code == 204 || text.isEmpty()) { if (code >= 400) throw new ApiError(code, "HTTP_" + code, "خطای " + code); return null; }
            Object parsed = parse(text);
            if (code == 402) { ApiError le = errorFrom(code, parsed); if ("pc".equals(Lic.mode())) { Lic.pcLocked(le.getMessage()); MAIN.post(() -> { LockActivity.showIfNeeded(); }); } throw le; }
            if (code >= 400) throw errorFrom(code, parsed);
            return parsed;
        } catch (ApiError e) { throw e;
        } catch (SecurityException e) { throw new ApiError(0, "INSECURE_ENDPOINT", "ارتباط رمزگذاری‌نشده با نشانی عمومی مجاز نیست؛ از شبکهٔ محلی امن استفاده کنید");
        } catch (Exception e) { throw new ApiError(0, "NETWORK", "ارتباط با رایانهٔ فروشگاه برقرار نشد");
        } finally { if (c != null) c.disconnect(); }
    }

    /** v2.3: same request, carried by the online relay (PC not on this network). */
    static Object viaRelay(String method, String path, String body, String contentType, String requestToken) throws ApiError {
        try {
            String[] r = Relay.call(method, path, body, contentType == null ? "application/json" : contentType, requestToken);
            int code = Integer.parseInt(r[0]); String text = r[1];
            if (code == 204 || text.isEmpty()) { if (code >= 400) throw new ApiError(code, "HTTP_" + code, "خطای " + code); return null; }
            Object parsed = parse(text);
            if (code == 402) { ApiError le = errorFrom(code, parsed); if ("pc".equals(Lic.mode())) { Lic.pcLocked(le.getMessage()); MAIN.post(LockActivity::showIfNeeded); } throw le; }
            if (code >= 400) throw errorFrom(code, parsed);
            return parsed;
        } catch (ApiError e) { throw e;
        } catch (Exception e) { Relay.active = false; throw new ApiError(0, "NETWORK", "ارتباط از طریق رله برقرار نشد: " + e.getMessage()); }
    }

    /** multipart/form-data (support attachments, store logo). */
    public static Object upload(String path, String[][] fields, String fileField, String fileName, byte[] data, String mime) throws ApiError {
        if (standalone()) throw new ApiError(0, "STANDALONE", "حالت مستقل: رایانه‌ای متصل نیست");
        String boundary = "----SM" + UUID.randomUUID().toString().replace("-", "");
        HttpURLConnection c = null;
        try {
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            for (String[] f : fields) if (f[1] != null) bo.write(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + f[0] + "\"\r\n\r\n" + f[1] + "\r\n").getBytes(StandardCharsets.UTF_8));
            if (data != null) {
                bo.write(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + fileField + "\"; filename=\"" + fileName + "\"\r\nContent-Type: " + mime + "\r\n\r\n").getBytes(StandardCharsets.UTF_8));
                bo.write(data); bo.write("\r\n".getBytes(StandardCharsets.UTF_8));
            }
            bo.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
            c = (HttpURLConnection) new URL(base + "/api" + path).openConnection();
            c.setConnectTimeout(4000); c.setReadTimeout(60000); c.setRequestMethod("POST"); c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            if (token != null && !token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
            try (OutputStream os = c.getOutputStream()) { os.write(bo.toByteArray()); }
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            String text = in == null ? "" : slurp(in);
            Object parsed = text.isEmpty() ? null : parse(text);
            if (code == 402) { ApiError le = errorFrom(code, parsed); if ("pc".equals(Lic.mode())) { Lic.pcLocked(le.getMessage()); MAIN.post(() -> { LockActivity.showIfNeeded(); }); } throw le; }
            if (code >= 400) throw errorFrom(code, parsed);
            return parsed;
        } catch (ApiError e) { throw e;
        } catch (Exception e) { throw new ApiError(0, "NETWORK", "ارسال فایل ناموفق بود");
        } finally { if (c != null) c.disconnect(); }
    }

    /** raw GET bytes (receipt PNG, QR PNG, media). */
    public static byte[] bytes(String absoluteOrPath) throws ApiError {
        HttpURLConnection c = null;
        try {
            String u = absoluteOrPath.startsWith("http") ? absoluteOrPath : base + absoluteOrPath;
            requireSafeEndpoint(u);
            URL target = new URL(u);
            c = (HttpURLConnection) target.openConnection();
            c.setConnectTimeout(4000); c.setReadTimeout(20000);
            URL server = base == null || base.isEmpty() ? null : new URL(base);
            if (server != null && server.getHost().equalsIgnoreCase(target.getHost()) && server.getPort() == target.getPort()
                    && server.getProtocol().equalsIgnoreCase(target.getProtocol()) && token != null && !token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
            if (c.getResponseCode() >= 400) throw new ApiError(c.getResponseCode(), "HTTP", "خطای دریافت فایل");
            ByteArrayOutputStream bo = new ByteArrayOutputStream(); byte[] buf = new byte[8192]; int n;
            try (InputStream in = c.getInputStream()) { while ((n = in.read(buf)) > 0) bo.write(buf, 0, n); }
            return bo.toByteArray();
        } catch (ApiError e) { throw e;
        } catch (Exception e) { throw new ApiError(0, "NETWORK", "ارتباط برقرار نشد");
        } finally { if (c != null) c.disconnect(); }
    }

    /** OAuth2 password login (form-encoded) → token. */
    public static String login(String username, String password) throws ApiError {
        String form = "username=" + enc(username) + "&password=" + enc(password);
        Object r = call("POST", "/auth/login", form, "application/x-www-form-urlencoded");
        return r instanceof JSONObject ? ((JSONObject) r).optString("access_token", "") : "";
    }

    public static boolean health() {
        if (standalone()) return false;
        if (healthAt(base)) { Relay.active = false; return true; }
        // v2.3: the PC publishes its current LAN addresses on the relay — try them (fast path) before falling back to the relay itself
        String lan = Prefs.get("pc_lan_json", "");
        if (!lan.isEmpty()) { try { org.json.JSONArray a = new org.json.JSONArray(lan.substring(0, lan.lastIndexOf('|'))); for (int i = 0; i < a.length(); i++) { String u = Prefs.normalise(a.optString(i)); if (!u.equals(base) && healthAt(u)) { base = u; Prefs.set("server_url", u); Relay.active = false; return true; } } } catch (Exception ignore) {} }
        if (Relay.available() && Relay.pcOnline()) { Relay.active = true; return true; }
        return false;
    }
    /** plain LAN health check of one base URL. */
    public static boolean healthAt(String b) {
        if (b == null || b.isEmpty()) return false;
        HttpURLConnection c = null;
        try { String endpoint = b + "/health"; requireSafeEndpoint(endpoint); c = (HttpURLConnection) new URL(endpoint).openConnection(); c.setConnectTimeout(2500); c.setReadTimeout(2500); return c.getResponseCode() == 200; }
        catch (Exception e) { return false; } finally { if (c != null) c.disconnect(); }
    }

    /* ---------------- helpers ---------------- */
    public static void ui(Runnable r) { MAIN.post(r); }
    public static void ui(Runnable r, long delayMs) { MAIN.postDelayed(r, delayMs); }

    static Object parse(String text) throws JSONException { return new JSONTokener(text).nextValue(); }
    private static String enc(String s) { try { return java.net.URLEncoder.encode(s, "UTF-8"); } catch (Exception e) { return s; } }
    public static String q(String s) { return enc(s == null ? "" : s); }

    private static ApiError errorFrom(int code, Object parsed) {
        String msg = "خطای " + code, ecode = "HTTP_" + code;
        if (parsed instanceof JSONObject) {
            Object d = ((JSONObject) parsed).opt("detail");
            if (d instanceof JSONObject) { JSONObject dj = (JSONObject) d; msg = dj.optString("message", dj.optString("code", msg)); ecode = dj.optString("code", ecode); }
            else if (d instanceof JSONArray) { JSONArray a = (JSONArray) d; if (a.length() > 0) { JSONObject f = a.optJSONObject(0); msg = f == null ? a.optString(0) : f.optString("msg", msg); } }
            else if (d != null) msg = String.valueOf(d);
        }
        if (code == 401) msg = "نشست منقضی شده؛ دوباره وارد شوید";
        if (code == 403) msg = "دسترسی لازم را ندارید";
        return new ApiError(code, ecode, msg);
    }
    private static String slurp(InputStream in) throws Exception {
        ByteArrayOutputStream bo = new ByteArrayOutputStream(); byte[] buf = new byte[8192]; int n;
        while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
        return new String(bo.toByteArray(), StandardCharsets.UTF_8);
    }
    public static JSONObject obj(String... kv) {
        JSONObject o = new JSONObject();
        try { for (int i = 0; i + 1 < kv.length; i += 2) { if (kv[i + 1] != null) o.put(kv[i], kv[i + 1]); } } catch (JSONException ignore) {}
        return o;
    }
}
