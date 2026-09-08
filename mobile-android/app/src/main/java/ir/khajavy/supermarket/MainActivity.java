package ir.khajavy.supermarket;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashMap;
import java.util.Map;

/**
 * Supermarket — Android companion (v1.6).
 *
 * The whole mobile web app (frontend/mobile + fonts + icons) ships INSIDE the
 * APK under assets/www and is served to the WebView from the private origin
 * https://app.local/ (see {@link #serveAsset}). Nothing is downloaded from the
 * internet; the phone talks to the shop PC over the LAN only when it can, and
 * works from its local cache/queue the rest of the time (store-and-forward sync
 * against POST /api/mobile/sync).
 *
 * Deliberately no AndroidX: the app compiles with the bare android.jar so it
 * can be built offline / on CI without Maven access (see scripts/android/).
 */
public class MainActivity extends Activity {
    static final String ORIGIN = "https://app.local";
    private static final int REQ_CAMERA = 11;
    private WebView web;
    private PermissionRequest pendingPermission;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.parseColor("#0f1420"));
        getWindow().setNavigationBarColor(Color.parseColor("#0f1420"));
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0f1420"));
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0f1420"));
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setAllowFileAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW); // app.local (https) → LAN server (http)
        s.setUserAgentString(s.getUserAgentString() + " SupermarketAndroid/" + Version.NAME);
        web.addJavascriptInterface(new Bridge(), "SupermarketAndroid");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if (ORIGIN.equals(u.getScheme() + "://" + u.getHost())) {
                    String path = u.getPath() == null ? "/" : u.getPath();
                    if (path.startsWith("/media/")) return proxyToServer(path);   // product images live on the PC
                    return serveAsset(path);
                }
                return null;
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (url.startsWith(ORIGIN)) return false;
                String base = Prefs.serverUrl(MainActivity.this);
                if (base != null && url.startsWith(base)) return false;
                startActivity(new android.content.Intent(android.content.Intent.ACTION_VIEW, request.getUrl()));
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                // camera for barcode / QR scanning
                if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                    request.grant(request.getResources());
                } else {
                    pendingPermission = request;
                    requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
                }
            }
        });

        if (savedInstanceState == null) {
            String start = Prefs.serverUrl(this) == null ? ORIGIN + "/mobile/setup.html" : ORIGIN + "/mobile/index.html";
            web.loadUrl(start);
        } else {
            web.restoreState(savedInstanceState);
        }
    }

    /** Serve a bundled file from assets/www; unknown paths fall back to the SPA shell. */
    private WebResourceResponse serveAsset(String path) {
        String p = path.equals("/") ? "/mobile/index.html" : path;
        if (p.endsWith("/")) p += "index.html";
        try {
            InputStream in = getAssets().open("www" + p);
            return new WebResourceResponse(mime(p), p.endsWith(".woff2") ? null : "utf-8", 200, "OK", headers(), in);
        } catch (IOException e) {
            byte[] body = ("Not found: " + p).getBytes();
            return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found", headers(), new ByteArrayInputStream(body));
        }
    }

    /** Fetch /media/* from the shop server (works only when the LAN is reachable). */
    private WebResourceResponse proxyToServer(String path) {
        String base = Prefs.serverUrl(this);
        if (base == null) return null;
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(base + path).openConnection();
            c.setConnectTimeout(3000);
            c.setReadTimeout(5000);
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            String ct = c.getContentType() == null ? mime(path) : c.getContentType();
            return new WebResourceResponse(ct.split(";")[0], null, code, code >= 400 ? "Error" : "OK", headers(), in);
        } catch (IOException e) {
            return new WebResourceResponse("text/plain", "utf-8", 503, "Offline", headers(), new ByteArrayInputStream(new byte[0]));
        }
    }

    private static Map<String, String> headers() {
        Map<String, String> h = new HashMap<>();
        h.put("Access-Control-Allow-Origin", "*");
        h.put("Cache-Control", "no-cache");
        return h;
    }

    private static String mime(String p) {
        if (p.endsWith(".html")) return "text/html";
        if (p.endsWith(".js")) return "application/javascript";
        if (p.endsWith(".css")) return "text/css";
        if (p.endsWith(".svg")) return "image/svg+xml";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".jpg") || p.endsWith(".jpeg")) return "image/jpeg";
        if (p.endsWith(".woff2")) return "font/woff2";
        if (p.endsWith(".json") || p.endsWith(".webmanifest")) return "application/json";
        return "application/octet-stream";
    }

    /** JS ↔ Android bridge (window.SupermarketAndroid). */
    public class Bridge {
        @JavascriptInterface public String getServerUrl() { String u = Prefs.serverUrl(MainActivity.this); return u == null ? "" : u; }
        @JavascriptInterface public String getDeviceToken() { String t = Prefs.deviceToken(MainActivity.this); return t == null ? "" : t; }
        @JavascriptInterface public String getDeviceId() { String t = Prefs.deviceId(MainActivity.this); return t == null ? "" : t; }
        @JavascriptInterface public String getStoreName() { String t = Prefs.storeName(MainActivity.this); return t == null ? "" : t; }
        @JavascriptInterface public String version() { return Version.NAME; }
        @JavascriptInterface public boolean isPaired() { return Prefs.serverUrl(MainActivity.this) != null; }

        /** Called by setup.html after a QR scan / manual entry: {url, token, store, device_id}. */
        @JavascriptInterface public void pair(String url, String token, String store, String deviceId) {
            Prefs.save(MainActivity.this, Prefs.normalise(url), token, store, deviceId);
            runOnUiThread(() -> web.loadUrl(ORIGIN + "/mobile/index.html"));
        }

        @JavascriptInterface public void unpair() {
            Prefs.clear(MainActivity.this);
            runOnUiThread(() -> web.loadUrl(ORIGIN + "/mobile/setup.html"));
        }

        @JavascriptInterface public void exitApp() { runOnUiThread(MainActivity.this::finishAffinity); }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) { web.goBack(); return; }
        new AlertDialog.Builder(this)
                .setMessage(R.string.exit_confirm)
                .setPositiveButton(R.string.exit_yes, (d, w) -> finish())
                .setNegativeButton(R.string.exit_no, null)
                .show();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        if (code == REQ_CAMERA && pendingPermission != null) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED)
                pendingPermission.grant(pendingPermission.getResources());
            else pendingPermission.deny();
            pendingPermission = null;
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (web != null) web.saveState(out);
    }
}
