package ir.khajavy.supermarket;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.function.Consumer;

/**
 * v2.0 — the NATIVE Android app shell (no WebView anywhere in this activity).
 *
 * Layout: sticky header (☰ menu, title, sync dot, ? tour) · content · 5-tab bar.
 * Navigation is a screen stack ({@link Screens}); the drawer lists every section
 * of the Windows app. The PC is reached only through JSON ({@link Api});
 * when it is unreachable every screen falls back to the phone's SQLite.
 */
public class AppActivity extends Activity {
    static final int REQ_SCAN = 31, REQ_PICK = 32;
    Consumer<android.net.Uri> pickCb;
    private FrameLayout content; private LinearLayout tabs; private TextView title; private View syncDot; private TextView syncTxt;
    private FrameLayout drawerLayer; private LinearLayout drawer;
    private final Deque<Screens.Screen> stack = new ArrayDeque<>();
    private Consumer<String> scanCb;
    private final Handler h = new Handler(Looper.getMainLooper());
    private final Runnable ticker = new Runnable() { @Override public void run() { Sync.kick(); h.postDelayed(this, 20000); } };

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        Prefs.init(this); Db.init(this); Ui.init(this);
        Api.base = Prefs.serverUrl(this) == null ? "" : Prefs.serverUrl(this);
        Api.token = Prefs.deviceToken(this) == null ? "" : Prefs.deviceToken(this);
        Ui.currencyLabel = Prefs.get("currency_label", "ریال");
        if (Api.base.isEmpty()) { startActivity(new Intent(this, PairActivity.class)); finish(); return; }
        getWindow().setStatusBarColor(Ui.BG2); getWindow().setNavigationBarColor(Ui.BG2);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        if (!Ui.dark) getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        buildShell();
        Sync.listener = (online, applied, rejected, pending) -> {
            syncDot.setBackground(Ui.rounded(online ? Ui.GREEN : Ui.RED, 0, 5));
            syncTxt.setText(online ? (pending > 0 ? "همگام‌سازی " + Ui.fa(String.valueOf(pending)) + " مورد…" : "متصل · همگام") : (Api.standalone() ? "مستقل" : "آفلاین · صف " + Ui.fa(String.valueOf(pending))));
            if (applied > 0) { Ui.toast("همگام شد: " + Ui.fa(String.valueOf(applied)) + " مورد"); Screens.Screen s = stack.peek(); if (s != null) s.refresh(); }
            if (rejected > 0) Ui.toast(Ui.fa(String.valueOf(rejected)) + " مورد رد شد — بخش همگام‌سازی");
            if (applied == 0 && rejected == 0 && online) { Screens.Screen s = stack.peek(); if (s != null && s.autoRefresh()) s.refresh(); }
        };
        Screens.loadConfig(this);
        open(new Screens.Home(this), false);
        Tour.maybe(this, "home");
    }
    @Override protected void onResume() { super.onResume(); h.post(ticker); }
    @Override protected void onPause() { super.onPause(); h.removeCallbacks(ticker); }

    /* ---------------- shell ---------------- */
    private void buildShell() {
        LinearLayout root = Ui.col(this); root.setBackgroundColor(Ui.BG);
        // header
        LinearLayout head = Ui.row(this); head.setBackgroundColor(Ui.BG2); head.setPadding(Ui.dp(8), Ui.dp(10), Ui.dp(8), Ui.dp(10)); head.setElevation(Ui.dp(3));
        head.addView(iconBtn("☰", () -> drawer(true)));
        title = Ui.text(this, "", 17, Ui.TEXT, true); title.setLayoutParams(Ui.weight(1)); title.setPadding(Ui.dp(6), 0, Ui.dp(6), 0); head.addView(title);
        LinearLayout st = Ui.col(this); st.setGravity(Gravity.END);
        LinearLayout sr = Ui.row(this); syncDot = new View(this); syncDot.setBackground(Ui.rounded(Ui.MUTED, 0, 5)); syncDot.setLayoutParams(Ui.lp(Ui.dp(9), Ui.dp(9))); sr.addView(syncDot);
        syncTxt = Ui.muted(this, "اتصال…"); syncTxt.setPadding(Ui.dp(5), 0, 0, 0); sr.addView(syncTxt); st.addView(sr);
        st.setOnClickListener(v -> open(new Screens.SyncScreen(this), true)); head.addView(st);
        head.addView(iconBtn("?", () -> Tour.show(this, current() == null ? "home" : current().key())));
        root.addView(head);
        // content
        content = new FrameLayout(this); content.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1)); root.addView(content);
        // tabs
        tabs = Ui.row(this); tabs.setBackgroundColor(Ui.BG2); tabs.setElevation(Ui.dp(8)); tabs.setPadding(0, Ui.dp(4), 0, Ui.dp(6)); root.addView(tabs);
        buildTabs(null);
        FrameLayout outer = new FrameLayout(this); outer.addView(root);
        // drawer layer
        drawerLayer = new FrameLayout(this); drawerLayer.setBackgroundColor(0x88000000); drawerLayer.setVisibility(View.GONE); drawerLayer.setOnClickListener(v -> drawer(false));
        drawer = Ui.col(this); drawer.setBackgroundColor(Ui.BG2); drawer.setElevation(Ui.dp(16)); drawer.setClickable(true);
        FrameLayout.LayoutParams dlp = new FrameLayout.LayoutParams(Ui.dp(300), ViewGroup.LayoutParams.MATCH_PARENT); dlp.gravity = Gravity.END; drawer.setLayoutParams(dlp);
        drawerLayer.addView(drawer); outer.addView(drawerLayer);
        setContentView(outer);
    }
    private TextView iconBtn(String glyph, Runnable r) { TextView t = Ui.text(this, glyph, 20, Ui.TEXT, true); t.setGravity(Gravity.CENTER); t.setLayoutParams(Ui.lp(Ui.dp(40), Ui.dp(40))); t.setBackground(Ui.rounded(Ui.CARD, 0, 12)); t.setOnClickListener(v -> r.run()); return t; }

    private static final String[][] TABS = {{"home", "خانه", "⌂"}, {"pos", "فروش", "▤"}, {"products", "کالاها", "▣"}, {"inventory", "انبار", "▥"}, {"more", "بیشتر", "☰"}};
    private void buildTabs(String active) {
        tabs.removeAllViews();
        for (String[] t : TABS) {
            boolean on = t[0].equals(active) || ("more".equals(t[0]) && active != null && !isTabKey(active));
            LinearLayout col = Ui.col(this); col.setGravity(Gravity.CENTER); col.setLayoutParams(Ui.weight(1)); col.setPadding(0, Ui.dp(4), 0, 0);
            View ind = new View(this); ind.setBackground(Ui.rounded(on ? Ui.PRIMARY : Color.TRANSPARENT, 0, 2)); ind.setLayoutParams(Ui.lp(Ui.dp(26), Ui.dp(3))); col.addView(ind);
            TextView ic = Ui.text(this, t[2], 20, on ? Ui.PRIMARY : Ui.MUTED, true); ic.setGravity(Gravity.CENTER); col.addView(ic);
            TextView lb = Ui.text(this, t[1], 11, on ? Ui.PRIMARY : Ui.MUTED, on); lb.setGravity(Gravity.CENTER); col.addView(lb);
            col.setOnClickListener(v -> { if ("more".equals(t[0])) drawer(true); else route(t[0]); });
            tabs.addView(col);
        }
    }
    private boolean isTabKey(String k) { for (String[] t : TABS) if (t[0].equals(k)) return true; return false; }

    /* ---------------- drawer: EVERY section ---------------- */
    static final String[][] GROUPS = {
        {"فروش و مشتری", "pos:صندوق فروش", "held:فاکتورهای نگه‌داشته", "invoices:فاکتورها / ابطال / مرجوعی", "customers:مشتریان و دفتر حساب", "marketing:جشنواره و کوپن"},
        {"کالا و انبار", "products:کالاها", "receive:ورود کالا", "inventory:انبار و موجودی", "stocktake:انبارگردانی", "stockops:ضایعات / اصلاح / انتقال", "warehouses:انبارها", "movements:گردش موجودی"},
        {"مدیریت", "home:داشبورد", "reports:گزارش‌ها", "accounting:حسابداری", "users:کاربران و نقش‌ها", "audit:لاگ حسابرسی"},
        {"سیستم", "settings:تنظیمات", "store:مشخصات فروشگاه", "sms:پیامک", "hardware:سخت‌افزار", "diagnostics:تست اتصالات", "support:درخواست پشتیبانی", "license:لایسنس", "sync:همگام‌سازی", "cloud:همگام‌سازی ابری", "device:تنظیمات دستگاه", "about:دربارهٔ برنامه"},
    };
    private void drawer(boolean open) {
        if (!open) { drawerLayer.setVisibility(View.GONE); return; }
        drawer.removeAllViews();
        LinearLayout head = Ui.row(this); head.setPadding(Ui.dp(16), Ui.dp(22), Ui.dp(16), Ui.dp(14)); head.setBackground(Ui.rounded(Ui.CARD, 0, 0));
        LinearLayout hc = Ui.col(this); hc.addView(Ui.text(this, Prefs.get("store_name", Prefs.storeName(this) == null ? "فروشگاه" : Prefs.storeName(this)), 15, Ui.TEXT, true)); hc.addView(Ui.muted(this, Screens.userName())); hc.setLayoutParams(Ui.weight(1)); head.addView(hc);
        drawer.addView(head);
        LinearLayout list = Ui.col(this); list.setPadding(Ui.dp(8), Ui.dp(6), Ui.dp(8), Ui.dp(6));
        String cur = current() == null ? "" : current().key();
        for (String[] g : GROUPS) {
            TextView sec = Ui.muted(this, g[0]); sec.setPadding(Ui.dp(10), Ui.dp(12), Ui.dp(10), Ui.dp(4)); list.addView(sec);
            for (int i = 1; i < g.length; i++) {
                String key = g[i].substring(0, g[i].indexOf(':')), label = g[i].substring(g[i].indexOf(':') + 1);
                if (!Screens.allowed(key)) continue;
                TextView t = Ui.text(this, label, 14, key.equals(cur) ? Color.WHITE : Ui.TEXT, key.equals(cur));
                t.setPadding(Ui.dp(12), Ui.dp(11), Ui.dp(12), Ui.dp(11)); t.setBackground(Ui.rounded(key.equals(cur) ? Ui.PRIMARY : Color.TRANSPARENT, 0, 12));
                t.setOnClickListener(v -> { drawer(false); route(key); }); list.addView(t);
            }
        }
        ScrollView sv = new ScrollView(this); sv.addView(list); sv.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1)); drawer.addView(sv);
        LinearLayout foot = Ui.col(this); foot.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(12)); foot.addView(Ui.divider(this));
        foot.addView(Ui.ghost(this, Ui.dark ? "پوستهٔ روشن" : "پوستهٔ تیره", () -> { Prefs.set("theme_resolved", Ui.dark ? "light" : "dark"); recreate(); }));
        foot.addView(Ui.danger(this, "خروج از حساب", () -> Ui.confirm(this, "از حساب خارج می‌شوید؟ داده‌های گوشی حفظ می‌شود.", () -> { Prefs.set("user_json", ""); Api.token = ""; startActivity(new Intent(this, LoginActivity.class)); finish(); })));
        drawer.addView(foot);
        drawerLayer.setVisibility(View.VISIBLE);
    }

    /* ---------------- navigation ---------------- */
    public void route(String key) { Screens.Screen s = Screens.create(this, key); if (s != null) open(s, !isTabKey(key)); }
    public void open(Screens.Screen s, boolean push) {
        if (!push) stack.clear();
        stack.push(s); show(s);
        Tour.maybe(this, s.key());
    }
    private void show(Screens.Screen s) {
        content.removeAllViews(); title.setText(s.title());
        View v = s.view(); content.addView(v, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        buildTabs(s.key()); s.load();
    }
    public Screens.Screen current() { return stack.peek(); }
    public void refreshCurrent() { Screens.Screen s = stack.peek(); if (s != null) s.refresh(); }
    public boolean back() {
        if (drawerLayer.getVisibility() == View.VISIBLE) { drawer(false); return true; }
        if (stack.size() > 1) { stack.pop(); show(stack.peek()); return true; }
        if (stack.size() == 1 && !"home".equals(stack.peek().key())) { open(new Screens.Home(this), false); return true; }
        return false;
    }
    @Override public void onBackPressed() {
        if (back()) return;
        new android.app.AlertDialog.Builder(this).setMessage(R.string.exit_confirm).setPositiveButton(R.string.exit_yes, (d, w) -> finish()).setNegativeButton(R.string.exit_no, null).show();
    }

    /* ---------------- native scanner ---------------- */
    public void scan(String title, Consumer<String> cb) {
        scanCb = cb;
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) { requestPermissions(new String[]{Manifest.permission.CAMERA}, 7); return; }
        Intent i = new Intent(this, ScanActivity.class); i.putExtra("title", title); startActivityForResult(i, REQ_SCAN);
    }
    @Override public void onRequestPermissionsResult(int code, String[] p, int[] r) { super.onRequestPermissionsResult(code, p, r); if (code == 7 && r.length > 0 && r[0] == PackageManager.PERMISSION_GRANTED && scanCb != null) scan("اسکن بارکد", scanCb); }
    @Override protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == REQ_PICK && res == RESULT_OK && data != null && data.getData() != null && pickCb != null) { Consumer<android.net.Uri> cb = pickCb; pickCb = null; cb.accept(data.getData()); return; }
        if (req == REQ_SCAN && res == RESULT_OK && data != null && scanCb != null) { String code = data.getStringExtra("code"); Consumer<String> cb = scanCb; scanCb = null; if (code != null) cb.accept(code.trim()); }
    }
}
