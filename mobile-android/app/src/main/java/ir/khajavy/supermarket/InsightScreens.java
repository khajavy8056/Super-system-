package ir.khajavy.supermarket;

import android.app.Dialog;
import android.content.Intent;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * v3.0 — «هوش فروشگاه» screens: suggestion feed with one-tap execution,
 * per-action before/after measurement, the profit-impact card on the
 * dashboard, and the Backup screen (create / share / import).
 */
public final class InsightScreens {
    private InsightScreens() {}

    static int prioColor(int p) { return p <= 1 ? Ui.RED : p == 2 ? Ui.AMBER : Ui.TEAL; }
    static String prioLabel(int p) { return p <= 1 ? "فوری" : p == 2 ? "مهم" : "پیشنهاد"; }
    static String kindIcon(String k) { switch (k) { case "CROSS_SELL": case "BASKET_NUDGE": return "cart"; case "EXPIRY_LADDER": return "calendar"; case "DEAD_STOCK": return "box"; case "VELOCITY": return "trend"; case "CASHFLOW": return "bank"; case "VIP": return "star"; case "CHURN": return "users"; case "PRICE_GAP": return "tag"; case "LOSS_PREV": return "shield"; case "SEASON": return "chart"; } return "star"; }

    /* ---------------- dashboard card (called from Screens.Home) ---------------- */
    public static void dashboardCard(Screens.Screen sc, LinearLayout body, AppActivity a) {
        LinearLayout card = Ui.card(sc.c, null); LinearLayout hd = Ui.row(sc.c); hd.setGravity(Gravity.CENTER_VERTICAL); hd.addView(Icons.view(sc.c, "star", Ui.GOLD, 20)); TextView t = Ui.h2(sc.c, "هوش فروشگاه"); t.setPadding(Ui.dp(8), 0, 0, 0); t.setLayoutParams(Ui.weight(1)); hd.addView(t); card.addView(hd);
        TextView ph = Ui.muted(sc.c, "در حال تحلیل…"); card.addView(ph); card.setOnClickListener(v -> a.route("insights")); body.addView(card);
        Api.get("/insights/summary", r -> { JSONObject s = (JSONObject) r; card.removeView(ph);
            double tg = s.optDouble("total_gain"), mg = s.optDouble("month_gain"); int open = s.optInt("open");
            card.addView(Ui.grid2(sc.c, Ui.kpi(sc.c, "اثر اندازه‌گیری‌شده (کل)", Ui.money(tg), Ui.num(s.optInt("accepted")) + " اقدام اجراشده", tg >= 0 ? Ui.GREEN : Ui.RED), Ui.kpi(sc.c, "اثر ۳۰ روز اخیر", Ui.money(mg), s.optDouble("share_of_month_profit") > 0 ? Ui.fa(String.valueOf(Math.round(s.optDouble("share_of_month_profit") * 100))) + "٪ سود دوره" : null, Ui.VIOLET)));
            JSONArray top = s.optJSONArray("top"); if (top != null) for (int i = 0; i < Math.min(3, top.length()); i++) { JSONObject x = top.optJSONObject(i); card.addView(Ui.kv(sc.c, x.optString("title"), (x.optDouble("gain") >= 0 ? "+" : "") + Ui.money(x.optDouble("gain")), x.optDouble("gain") >= 0 ? Ui.GREEN : Ui.RED)); }
            card.addView(Ui.ghost(sc.c, open > 0 ? Ui.num(open) + " پیشنهاد باز — مشاهده" : "همهٔ پیشنهادها", () -> a.route("insights"))); }, e -> { ph.setText("هوش فروشگاه در دسترس نیست"); });
    }

    /* ---------------- suggestions feed ---------------- */
    public static final class Feed extends Screens.Screen {
        int tab = 0; JSONObject summary = new JSONObject();
        Feed(AppActivity a) { super(a); }
        public String key() { return "insights"; } public String title() { return "هوش فروشگاه"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            loading();
            get("/insights/summary", r -> { summary = (JSONObject) r; String st = tab == 0 ? "NEW" : tab == 1 ? "ACCEPTED,MEASURED" : "DISMISSED,SNOOZED,EXPIRED"; get("/insights?status=" + st + "&limit=80", rr -> render(arr(rr))); });
        }
        void render(JSONArray items) {
            clear();
            LinearLayout hero = Ui.hero(c); hero.addView(Ui.text(c, "هوش فروشگاه", 20, 0xFFFFFFFF, true)); hero.addView(Ui.text(c, "تحلیل محلی روی داده‌های خودتان — پیشنهادها را با یک لمس اجرا کنید؛ اثر واقعی هر اقدام اندازه‌گیری می‌شود.", 12, 0xDDFFFFFF, false));
            LinearLayout kp = Ui.row(c); kp.setPadding(0, Ui.dp(10), 0, 0);
            kp.addView(heroKpi("اثر کل", Ui.money(summary.optDouble("total_gain")))); kp.addView(heroKpi("۳۰ روز اخیر", Ui.money(summary.optDouble("month_gain")))); kp.addView(heroKpi("باز", Ui.num(summary.optInt("open")))); hero.addView(kp);
            LinearLayout br = Ui.row(c); br.setPadding(0, Ui.dp(10), 0, 0); android.widget.Button run = Ui.small(c, "تحلیل دوباره", () -> { Ui.toast("در حال تحلیل…"); post("/insights/run", new JSONObject(), r -> { JSONObject x = (JSONObject) r; Ui.done(Ui.ctx, "تحلیل انجام شد", Ui.num(x.optInt("created")) + " پیشنهاد تازه · " + Ui.num(x.optInt("refreshed")) + " به‌روزرسانی", null); load(); }); }); br.addView(run);
            android.widget.Button rep = Ui.small(c, "گزارش هفتگی", () -> get("/insights/report", r -> { JSONObject x = (JSONObject) r; LinearLayout l = Ui.col(c); TextView tv = Ui.body(c, x.optString("narrative")); tv.setLineSpacing(0, 1.35f); l.addView(tv); Ui.sheet(c, "گزارش هوش فروشگاه", l); })); br.addView(rep);
            android.widget.Button lst = Ui.small(c, "لیست سفارش", () -> get("/insights/tasks", r -> { JSONArray t = arr(r); LinearLayout l = Ui.col(c); if (t.length() == 0) l.addView(Ui.empty(c, "لیست سفارش خالی است")); for (int i = 0; i < t.length(); i++) { JSONObject x = t.optJSONObject(i); l.addView(Ui.kv(c, x.optString("name"), Ui.num(x.optDouble("qty")) + " عدد", Ui.AMBER)); } Ui.sheet(c, "لیست سفارش پیشنهادی", l); })); br.addView(lst); hero.addView(br); body.addView(hero);
            body.addView(tabs(new String[]{"پیشنهادها", "اجراشده و اثر", "بایگانی"}, tab, k -> { tab = k; load(); }));
            if (items.length() == 0) { body.addView(Ui.empty(c, tab == 0 ? "پیشنهاد بازی نیست — با فروش بیشتر، تحلیل دقیق‌تر می‌شود" : "موردی نیست")); return; }
            for (int i = 0; i < items.length(); i++) body.addView(card(items.optJSONObject(i)));
        }
        View heroKpi(String l, String v) { LinearLayout t = Ui.col(c); t.setLayoutParams(Ui.weight(1)); t.addView(Ui.text(c, v, 15, 0xFFFFFFFF, true)); t.addView(Ui.text(c, l, 11, 0xCCFFFFFF, false)); return t; }
        View card(JSONObject x) {
            LinearLayout card = Ui.card(c, null); card.setLayoutParams(Ui.margin(Ui.match(), 0, 0, 0, 10));
            LinearLayout hd = Ui.row(c); hd.setGravity(Gravity.CENTER_VERTICAL); hd.addView(Icons.view(c, kindIcon(x.optString("kind")), prioColor(x.optInt("priority")), 20)); LinearLayout tc = Ui.col(c); tc.setLayoutParams(Ui.weight(1)); tc.setPadding(Ui.dp(8), 0, 0, 0); tc.addView(Ui.text(c, x.optString("title"), 14.5f, Ui.TEXT, true)); tc.addView(Ui.muted(c, x.optString("label") + " · " + prioLabel(x.optInt("priority")))); hd.addView(tc);
            String st = x.optString("status"); if ("NEW".equals(st) && x.optDouble("expected_gain") > 0) hd.addView(Ui.badge(c, "~" + Ui.money(x.optDouble("expected_gain")) + "/ماه", Ui.GREEN)); else if (!x.isNull("measured_gain")) { double g = x.optDouble("measured_gain"); hd.addView(Ui.badge(c, (g >= 0 ? "+" : "") + Ui.money(g), g >= 0 ? Ui.GREEN : Ui.RED)); } else if ("ACCEPTED".equals(st)) hd.addView(Ui.badge(c, "در حال سنجش", Ui.AMBER)); card.addView(hd);
            TextView b = Ui.body(c, x.optString("body")); b.setLineSpacing(0, 1.3f); b.setPadding(0, Ui.dp(8), 0, 0); card.addView(b);
            JSONObject res = x.optJSONObject("result"), base = x.optJSONObject("baseline");
            if (res != null && base != null) { LinearLayout m = Ui.col(c); m.setBackground(Ui.rounded(0x14000000, 0, 12)); m.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8)); m.setLayoutParams(Ui.margin(Ui.match(), 0, 8, 0, 0)); m.addView(Ui.text(c, "قبل و بعد (" + res.optString("unit") + ")", 12, Ui.MUTED, true));
                m.addView(Ui.kv(c, "قبل (" + Ui.num(base.optDouble("window_days")) + " روز)", Ui.num(base.optDouble("value")), 0)); m.addView(Ui.kv(c, "بعد (" + Ui.num(res.optDouble("elapsed_days")) + " روز)", Ui.num(res.optDouble("value")) + (res.isNull("change_pct") ? "" : "  (" + (res.optDouble("change_pct") >= 0 ? "+" : "") + Ui.fa(String.valueOf(res.optDouble("change_pct"))) + "٪)"), res.isNull("change_pct") || res.optDouble("change_pct") >= 0 ? Ui.GREEN : Ui.RED));
                m.addView(Ui.kv(c, "اثر بر سود (تعدیل‌شده با روند فروشگاه)", Ui.money(res.optDouble("adjusted_gain")), res.optDouble("adjusted_gain") >= 0 ? Ui.GREEN : Ui.RED)); if (!res.isNull("projected_month")) m.addView(Ui.kv(c, "برآورد ماهانه", Ui.money(res.optDouble("projected_month")), 0)); if (!res.optBoolean("enough_data")) m.addView(Ui.muted(c, "برای سنجش دقیق حداقل یک روز فروش لازم است")); card.addView(m); }
            JSONArray acts = x.optJSONArray("actions");
            if ("NEW".equals(st) || "SNOOZED".equals(st)) { LinearLayout ar = Ui.col(c); ar.setPadding(0, Ui.dp(8), 0, 0);
                if (acts != null && acts.length() > 0) { StringBuilder sb = new StringBuilder(); for (int i = 0; i < acts.length(); i++) sb.append(i > 0 ? " · " : "").append(acts.optJSONObject(i).optString("label")); ar.addView(Ui.muted(c, "اقدام‌ها: " + sb)); }
                LinearLayout r = Ui.row(c); android.widget.Button ok = Ui.primary(c, "اجرا و سنجش اثر", () -> Ui.confirm(c, "این پیشنهاد اجرا شود؟ اقدام‌های آن هم‌اکنون انجام و اثرش از امروز اندازه‌گیری می‌شود.", () -> post("/insights/" + x.optLong("id") + "/accept", new JSONObject(), rr -> { JSONObject o = (JSONObject) rr; JSONArray ex = o.optJSONArray("executed"); StringBuilder sb = new StringBuilder(); for (int i = 0; ex != null && i < ex.length(); i++) { JSONObject e = ex.optJSONObject(i); sb.append(e.optBoolean("ok") ? "✓ " : "✗ ").append(e.optString("type")).append("\n"); } Sfx.play("ok"); Ui.done(Ui.ctx, "اجرا شد", sb.toString().trim(), null); load(); }))); ok.setLayoutParams(Ui.weight(1)); r.addView(ok);
                r.addView(Ui.small(c, "بعداً", () -> post("/insights/" + x.optLong("id") + "/snooze", j("days", "7"), rr -> load()))); r.addView(Ui.small(c, "رد", () -> post("/insights/" + x.optLong("id") + "/dismiss", new JSONObject(), rr -> load()))); ar.addView(r); card.addView(ar); }
            else if ("ACCEPTED".equals(st)) { card.addView(Ui.small(c, "سنجش دوباره", () -> post("/insights/" + x.optLong("id") + "/measure", new JSONObject(), rr -> load()))); }
            card.setOnLongClickListener(v -> { get("/insights/" + x.optLong("id") + "?narrate=1", rr -> { JSONObject o = (JSONObject) rr; LinearLayout l = Ui.col(c); TextView tv = Ui.body(c, o.optString("narrative").isEmpty() ? o.optString("body") : o.optString("narrative")); tv.setLineSpacing(0, 1.35f); l.addView(tv); l.addView(Ui.muted(c, "شواهد: " + o.optJSONObject("evidence"))); Ui.sheet(c, x.optString("title"), l); }); return true; });
            return card;
        }
    }

    /* ---------------- Backup (create / share / import) ---------------- */
    public static final class Backup extends Screens.Screen {
        Backup(AppActivity a) { super(a); }
        public String key() { return "backup"; } public String title() { return "پشتیبان‌گیری"; }
        public void load() {
            clear();
            LinearLayout info = Ui.card(c, "پشتیبان‌گیری و بازیابی"); info.addView(Ui.body(c, "پشتیبان یک فایل کامل از همهٔ داده‌های گوشی است (کالاها، فاکتورها، مشتریان، تنظیمات، هوش فروشگاه). آن را در جای امنی (فضای ابری، رایانه) نگه دارید.")); info.addView(Ui.kv(c, "آخرین پشتیبان", Db.kv("last_backup") == null ? "—" : Ui.jdate(Db.kv("last_backup")), 0)); info.addView(Ui.kv(c, "آخرین بازیابی", Db.kv("last_restore") == null ? "—" : Ui.jdate(Db.kv("last_restore")), 0)); info.addView(Ui.kv(c, "پشتیبان خودکار روزانه", "true".equals(Local.setting("backup.auto_daily", "true")) ? "روشن" : "خاموش", 0)); body.addView(info);
            LinearLayout act = Ui.card(c, "اقدام‌ها");
            act.addView(Ui.primary(c, "تهیهٔ پشتیبان اکنون", () -> Api.bg(() -> { try { java.io.File f = Local.backup(a); Api.ui(() -> { Sfx.play("ok"); Ui.done(Ui.ctx, "پشتیبان ساخته شد", f.getName() + " (" + Ui.num(f.length() / 1024) + " KB)", null); load(); }); } catch (Exception e) { Ui.toast("خطا: " + e.getMessage()); } })));
            act.addView(Ui.ghost(c, "تهیه و ارسال (اشتراک‌گذاری فایل)", () -> Api.bg(() -> { try { java.io.File f = Local.backup(a); Api.ui(() -> share(f)); } catch (Exception e) { Ui.toast("خطا: " + e.getMessage()); } })));
            act.addView(Ui.ghost(c, "بازیابی از فایل پشتیبان…", () -> Ui.confirm(c, "با بازیابی، داده‌های فعلی گوشی با فایل پشتیبان جایگزین می‌شود (یک نسخهٔ امن از داده‌های فعلی هم گرفته می‌شود). ادامه می‌دهید؟", this::pick)));
            body.addView(act);
            LinearLayout list = Ui.card(c, "پشتیبان‌های روی گوشی"); java.io.File dir = new java.io.File(a.getExternalFilesDir(null), "backups"); java.io.File[] fs = dir.listFiles(); int n = 0;
            if (fs != null) { java.util.Arrays.sort(fs, (x, y) -> Long.compare(y.lastModified(), x.lastModified())); for (java.io.File f : fs) { if (!f.getName().endsWith(".db")) continue; n++; final java.io.File ff = f; list.addView(Ui.item(c, f.getName(), Ui.num(f.length() / 1024) + " KB", "بازیابی", Ui.PRIMARY, () -> { LinearLayout l = Ui.col(c); l.addView(Ui.ghost(c, "اشتراک‌گذاری این فایل", () -> share(ff))); l.addView(Ui.primary(c, "بازیابی از این نسخه", () -> Ui.confirm(c, "داده‌های فعلی با «" + ff.getName() + "» جایگزین شود؟", () -> restore(() -> { try { return new java.io.FileInputStream(ff); } catch (Exception e) { return null; } })))); Ui.sheet(c, ff.getName(), l); })); } }
            if (n == 0) list.addView(Ui.empty(c, "هنوز پشتیبانی ساخته نشده")); body.addView(list);
        }
        void share(java.io.File f) { try { android.net.Uri u = BackupProvider.uri(a, f); Intent i = new Intent(Intent.ACTION_SEND); i.setType("application/octet-stream"); i.putExtra(Intent.EXTRA_STREAM, u); i.putExtra(Intent.EXTRA_SUBJECT, "پشتیبان سوپری من — " + f.getName()); i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION); Biometric.markInternal(); a.startActivity(Intent.createChooser(i, "ارسال فایل پشتیبان")); } catch (Exception e) { Ui.toast("اشتراک‌گذاری ممکن نشد: " + e.getMessage()); } }
        void pick() { Intent i = new Intent(Intent.ACTION_GET_CONTENT); i.setType("*/*"); i.addCategory(Intent.CATEGORY_OPENABLE); a.pickCb = uri -> restore(() -> { try { return a.getContentResolver().openInputStream(uri); } catch (Exception e) { return null; } }); Biometric.markInternal(); a.startActivityForResult(Intent.createChooser(i, "انتخاب فایل پشتیبان"), AppActivity.REQ_PICK); }
        void restore(java.util.function.Supplier<java.io.InputStream> src) { Ui.toast("در حال بازیابی…"); Api.bg(() -> { try (java.io.InputStream in = src.get()) { if (in == null) throw new Exception("فایل خوانده نشد"); Local.restore(a, in); Api.ui(() -> { Sfx.play("ok"); Screens.loadConfig(a); Ui.done(Ui.ctx, "بازیابی انجام شد", "داده‌ها از فایل پشتیبان بارگذاری شدند.", () -> a.route("home")); }); } catch (Exception e) { Api.ui(() -> Ui.toast("بازیابی ناموفق: " + e.getMessage())); } }); }
    }
}
