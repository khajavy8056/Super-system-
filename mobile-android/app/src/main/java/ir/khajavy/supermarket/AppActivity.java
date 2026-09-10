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
        LockActivity.top = this;
        if (Api.base.isEmpty() || !Lic.setupDone() || InstallService.running()) { startActivity(new Intent(this, SetupActivity.class)); finish(); return; }
        if (!Lic.allowed()) { LockActivity.showing = false; LockActivity.showIfNeeded(); finish(); return; }
        if (!"1".equals(Prefs.get("first_loading_done", ""))) Prefs.set("first_loading_done", "1");
        Lic.recheckIfDue();
        Sync.watchNetwork(this);
        getWindow().setStatusBarColor(Ui.BG2); getWindow().setNavigationBarColor(Ui.BG2);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        if (!Ui.dark) getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        buildShell();
        Sync.listener = (online, applied, rejected, pending) -> {
            syncDot.setBackground(Ui.rounded(online ? Ui.GREEN : Ui.RED, 0, 5));
            syncTxt.setText(online ? (pending > 0 ? "همگام‌سازی " + Ui.fa(String.valueOf(pending)) + " مورد…" : (Relay.active ? "متصل از راه دور · همگام" : "متصل · همگام")) : (Api.standalone() ? "مستقل" : "آفلاین · صف " + Ui.fa(String.valueOf(pending))));
            if (applied > 0) { Ui.toast("همگام شد: " + Ui.fa(String.valueOf(applied)) + " مورد"); Screens.Screen s = stack.peek(); if (s != null) s.refresh(); }
            if (rejected > 0) { Ui.toast(Ui.fa(String.valueOf(rejected)) + " مورد رد شد — بخش همگام‌سازی"); Notify.syncProblem(this, rejected); }
            if (applied == 0 && rejected == 0 && online) { Screens.Screen s = stack.peek(); if (s != null && s.autoRefresh()) s.refresh(); }
        };
        Screens.loadConfig(this);
        Notify.channels(this); Notify.schedule(this); Notify.askPermission(this);
        String r0 = getIntent() == null ? null : getIntent().getStringExtra("route");
        open(new Screens.Home(this), false);
        if (r0 != null && !r0.isEmpty() && !"home".equals(r0)) route(r0);
        else { Tour.maybe(this, "home"); if (!"1".equals(Prefs.get("welcomed_" + Db.now().substring(0, 10), ""))) { Prefs.set("welcomed_" + Db.now().substring(0, 10), "1"); Sfx.play("welcome"); } }
        Api.bg(() -> Notify.checkLocal(this));
    }
    private boolean bioShowing = false;
    void bioGate() {
        if (bioShowing || !Biometric.lockDue()) return;
        bioShowing = true; View veil = new View(this); veil.setBackgroundColor(Ui.BG); veil.setClickable(true); ((android.view.ViewGroup) getWindow().getDecorView().findViewById(android.R.id.content)).addView(veil);
        Biometric.prompt(this, "باز کردن سوپری من", "اثر انگشت یا رمز گوشی", ok -> { bioShowing = false; if (ok) ((android.view.ViewGroup) veil.getParent()).removeView(veil); else finishAffinity(); });
    }
    @Override protected void onResume() { super.onResume(); LockActivity.top = this; h.post(ticker); bioGate(); if (!Lic.allowed()) LockActivity.showIfNeeded(); if (Api.standalone()) Api.bg(() -> { int n = SupportRelay.poll(); if (n > 0) { Notify.supportReply(this, n); Api.ui(() -> Ui.toast(Ui.fa(String.valueOf(n)) + " پاسخ جدید از پشتیبانی")); } }); else Api.bg(() -> Notify.checkPcSupport(this)); }
    @Override protected void onNewIntent(Intent i) { super.onNewIntent(i); setIntent(i); String r = i == null ? null : i.getStringExtra("route"); if (r != null && !r.isEmpty()) route(r); }
    @Override protected void onPause() { super.onPause(); h.removeCallbacks(ticker); }

    /* ---------------- shell ---------------- */
    private void buildShell() {
        LinearLayout root = Ui.col(this); root.setBackgroundColor(Ui.BG);
        // header
        LinearLayout head = Ui.row(this); head.setBackgroundColor(Ui.BG2); head.setPadding(Ui.dp(10), Ui.dp(10), Ui.dp(10), Ui.dp(10)); head.setElevation(Ui.dp(2));
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
        tabs = Ui.row(this); tabs.setBackgroundColor(Ui.BG2); tabs.setElevation(Ui.dp(10)); tabs.setPadding(Ui.dp(6), Ui.dp(6), Ui.dp(6), Ui.dp(8)); root.addView(tabs);
        buildTabs(null);
        FrameLayout outer = new FrameLayout(this); outer.addView(root);
        // drawer layer
        drawerLayer = new FrameLayout(this); drawerLayer.setBackgroundColor(0x88000000); drawerLayer.setVisibility(View.GONE); drawerLayer.setOnClickListener(v -> drawer(false));
        drawer = Ui.col(this); drawer.setBackgroundColor(Ui.BG2); drawer.setElevation(Ui.dp(16)); drawer.setClickable(true);
        FrameLayout.LayoutParams dlp = new FrameLayout.LayoutParams(Ui.dp(304), ViewGroup.LayoutParams.MATCH_PARENT); dlp.gravity = Gravity.END; drawer.setLayoutParams(dlp);
        drawerLayer.addView(drawer); outer.addView(drawerLayer);
        setContentView(outer);
    }
    private TextView iconBtn(String glyph, Runnable r) { TextView t = Ui.text(this, glyph, 19, Ui.TEXT, true); t.setGravity(Gravity.CENTER); t.setLayoutParams(Ui.lp(Ui.dp(40), Ui.dp(40))); t.setBackground(Ui.rounded(Ui.CARD2, Ui.BORDER, 12)); t.setOnClickListener(v -> r.run()); return t; }

    private static final String[][] TABS = {{"home", "خانه", "⌂"}, {"pos", "فروش", "🛒"}, {"products", "کالاها", "🏷"}, {"inventory", "انبار", "📦"}, {"more", "بیشتر", "☰"}};
    private void buildTabs(String active) {
        tabs.removeAllViews();
        for (String[] t : TABS) {
            boolean on = t[0].equals(active) || ("more".equals(t[0]) && active != null && !isTabKey(active));
            LinearLayout col = Ui.col(this); col.setGravity(Gravity.CENTER); LinearLayout.LayoutParams wp = Ui.weight(1); wp.setMargins(Ui.dp(2), 0, Ui.dp(2), 0); col.setLayoutParams(wp); col.setPadding(0, Ui.dp(6), 0, Ui.dp(4));
            col.setBackground(Ui.rounded(on ? (Ui.PRIMARY & 0x00FFFFFF) | (Ui.dark ? 0x33000000 : 0x1F000000) : Color.TRANSPARENT, 0, 14));
            TextView ic = Ui.text(this, t[2], 18, on ? Ui.PRIMARY : Ui.MUTED, true); ic.setGravity(Gravity.CENTER); col.addView(ic);
            TextView lb = Ui.text(this, t[1], 11, on ? Ui.PRIMARY : Ui.MUTED, on); lb.setGravity(Gravity.CENTER); lb.setPadding(0, Ui.dp(2), 0, 0); col.addView(lb);
            col.setOnClickListener(v -> { if ("more".equals(t[0])) drawer(true); else route(t[0]); });
            tabs.addView(col);
        }
    }
    private boolean isTabKey(String k) { for (String[] t : TABS) if (t[0].equals(k)) return true; return false; }

    /* ---------------- drawer: EVERY section ---------------- */
    static final String[][] GROUPS = {
        {"🛒 فروش و مشتری", "pos:صندوق فروش", "held:فاکتورهای نگه‌داشته", "customers:مشتریان و دفتر حساب"},
        {"🧾 فاکتورها", "invoices:فاکتورها / ابطال / مرجوعی", "reports:گزارش‌ها", "accounting:حسابداری"},
        {"📦 کالا و موجودی", "products:کالاها", "receive:ورود کالا", "inventory:انبار و موجودی", "stocktake:انبارگردانی", "stockops:ضایعات / اصلاح / انتقال", "warehouses:انبارها", "movements:گردش موجودی"},
        {"🎁 جشنواره و کوپن", "marketing:جشنواره و کوپن", "sms:پیامک"},
        {"⚙ مدیریت و سیستم", "home:داشبورد", "users:کاربران و نقش‌ها", "audit:لاگ حسابرسی", "settings:تنظیمات", "store:مشخصات فروشگاه", "hardware:سخت‌افزار", "diagnostics:تست اتصالات", "notifications:اعلان‌ها", "support:درخواست پشتیبانی", "license:لایسنس", "sync:همگام‌سازی", "cloud:همگام‌سازی ابری", "device:تنظیمات دستگاه", "about:دربارهٔ برنامه"},
    };
    private final java.util.Set<String> openGroups = new java.util.HashSet<>();
    private void drawer(boolean open) {
        if (!open) { drawerLayer.setVisibility(View.GONE); return; }
        drawer.removeAllViews(); drawer.setBackgroundColor(Ui.BG);
        String store = Prefs.get("store_name", Prefs.storeName(this) == null ? "فروشگاه" : Prefs.storeName(this));
        LinearLayout head = Ui.row(this); head.setPadding(Ui.dp(16), Ui.dp(26), Ui.dp(16), Ui.dp(16)); head.setBackground(Ui.gradient(Ui.dark ? Ui.CARD2 : Ui.BG2, Ui.dark ? Ui.BG2 : Ui.CARD, 0, 0));
        head.addView(Ui.avatar(this, store, 52));
        LinearLayout hc = Ui.col(this); hc.setPadding(Ui.dp(12), 0, 0, 0); hc.addView(Ui.text(this, store, 16, Ui.TEXT, true)); hc.addView(Ui.muted(this, "فروشگاه من · " + Screens.userName())); hc.setLayoutParams(Ui.weight(1)); head.addView(hc);
        drawer.addView(head); drawer.addView(Ui.divider(this));
        LinearLayout list = Ui.col(this); list.setPadding(Ui.dp(10), Ui.dp(6), Ui.dp(10), Ui.dp(6));
        String cur = current() == null ? "" : current().key();
        if (openGroups.isEmpty()) { for (String[] g : GROUPS) for (int i = 1; i < g.length; i++) if (g[i].startsWith(cur + ":")) openGroups.add(g[0]); if (openGroups.isEmpty()) openGroups.add(GROUPS[0][0]); }
        for (String[] g : GROUPS) {
            boolean opened = openGroups.contains(g[0]);
            LinearLayout gh = Ui.row(this); gh.setPadding(Ui.dp(12), Ui.dp(12), Ui.dp(12), Ui.dp(12)); gh.setBackground(Ui.surface(16)); gh.setLayoutParams(Ui.margin(Ui.match(), 0, 4, 0, 4));
            TextView gt = Ui.text(this, g[0], 14, Ui.TEXT, true); gt.setLayoutParams(Ui.weight(1)); gh.addView(gt); gh.addView(Ui.text(this, opened ? "⌃" : "⌄", 14, Ui.MUTED, true));
            gh.setOnClickListener(v -> { if (opened) openGroups.remove(g[0]); else openGroups.add(g[0]); drawer(true); }); list.addView(gh);
            if (!opened) continue;
            for (int i = 1; i < g.length; i++) {
                String key = g[i].substring(0, g[i].indexOf(':')), label = g[i].substring(g[i].indexOf(':') + 1);
                if (!Screens.allowed(key)) continue;
                boolean on = key.equals(cur);
                TextView t = Ui.text(this, "•  " + label, 13, on ? Ui.PRIMARY : Ui.TEXT, on);
                t.setPadding(Ui.dp(22), Ui.dp(10), Ui.dp(12), Ui.dp(10)); t.setBackground(Ui.rounded(on ? (Ui.PRIMARY & 0x00FFFFFF) | 0x22000000 : Color.TRANSPARENT, 0, 12));
                t.setOnClickListener(v -> { drawer(false); route(key); }); list.addView(t);
            }
        }
        ScrollView sv = new ScrollView(this); sv.setVerticalScrollBarEnabled(false); sv.addView(list); sv.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1)); drawer.addView(sv);
        LinearLayout foot = Ui.col(this); foot.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(14)); foot.addView(Ui.divider(this));
        // theme switch row
        LinearLayout th = Ui.row(this); th.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8)); th.setBackground(Ui.surface(14));
        TextView tl = Ui.text(this, Ui.dark ? "🌙  پوستهٔ تیره" : "☀  پوستهٔ روشن", 13, Ui.TEXT, true); tl.setLayoutParams(Ui.weight(1)); th.addView(tl);
        android.widget.Switch sw = new android.widget.Switch(this); sw.setChecked(!Ui.dark); sw.setOnCheckedChangeListener((b, on) -> { Prefs.set("theme_resolved", on ? "light" : "dark"); Prefs.set("theme_mode", on ? "light" : "dark"); recreate(); }); th.addView(sw);
        foot.addView(th);
        foot.addView(Ui.ghost(this, "💬  ارتباط با پشتیبانی", () -> { drawer(false); route("support"); }));
        foot.addView(Ui.danger(this, "خروج از حساب", () -> Ui.confirm(this, "از حساب خارج می‌شوید؟ داده‌های گوشی حفظ می‌شود.", () -> { Prefs.set("user_json", ""); Api.token = ""; if (Api.standalone()) { Prefs.set("setup_done", ""); startActivity(new Intent(this, SetupActivity.class)); } else startActivity(new Intent(this, LoginActivity.class)); finish(); })));
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
        if (req == Biometric.REQ_KEYGUARD) { bioShowing = false; if (res == RESULT_OK) { Biometric.lastUnlock = System.currentTimeMillis(); recreate(); } else finishAffinity(); return; }
        if (req == REQ_PICK && res == RESULT_OK && data != null && data.getData() != null && pickCb != null) { Consumer<android.net.Uri> cb = pickCb; pickCb = null; cb.accept(data.getData()); return; }
        if (req == REQ_SCAN && res == RESULT_OK && data != null && scanCb != null) { String code = data.getStringExtra("code"); Consumer<String> cb = scanCb; scanCb = null; if (code != null) cb.accept(code.trim()); }
    }
}
