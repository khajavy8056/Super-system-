package ir.khajavy.supermarket;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.Bundle;
import android.view.View;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.TextView;

import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

/**
 * Native Android shell for the mobile PWA (§257).
 *
 * Why a WebView and not a Trusted Web Activity: a TWA needs a public HTTPS
 * origin plus Digital Asset Links, but this system is local-first — the server
 * runs on the shop PC over plain LAN HTTP (§259). A WebView with camera access
 * lets the existing /mobile/ PWA (barcode scanning, offline stocktake queue,
 * service worker) run unchanged, fully offline.
 */
public class MainActivity extends AppCompatActivity {
    private static final int REQ_CAMERA = 11;
    private WebView web;
    private PermissionRequest pendingPermission;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String base = Prefs.serverUrl(this);
        if (base == null) {
            startActivity(new Intent(this, SetupActivity.class));
            finish();
            return;
        }
        setContentView(R.layout.activity_main);
        web = findViewById(R.id.webview);
        SwipeRefreshLayout swipe = findViewById(R.id.swipe);
        TextView banner = findViewById(R.id.offline_banner);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setUserAgentString(s.getUserAgentString() + " SupermarketAndroid/" + BuildConfig.VERSION_NAME);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                // keep navigation inside the shop server; anything else opens externally
                String url = request.getUrl().toString();
                if (url.startsWith(base)) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, request.getUrl()));
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                swipe.setRefreshing(false);
                banner.setVisibility(isOnline() ? View.GONE : View.VISIBLE);
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                // camera for barcode scanning (§22)
                if (ContextCompat.checkSelfPermission(MainActivity.this, Manifest.permission.CAMERA)
                        == PackageManager.PERMISSION_GRANTED) {
                    request.grant(request.getResources());
                } else {
                    pendingPermission = request;
                    ActivityCompat.requestPermissions(MainActivity.this,
                            new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
                }
            }
        });
        swipe.setOnRefreshListener(() -> web.reload());
        web.setOnLongClickListener(v -> false);

        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (web.canGoBack()) web.goBack(); else finish();
            }
        });

        if (savedInstanceState == null) web.loadUrl(base + "/mobile/");
        else web.restoreState(savedInstanceState);
    }

    private boolean isOnline() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        NetworkInfo n = cm == null ? null : cm.getActiveNetworkInfo();
        return n != null && n.isConnected();
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
