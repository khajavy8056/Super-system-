package ir.khajavy.supermarket;

import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.UUID;

/**
 * v4.0 — «مغز فروشگاه» on the phone: the same admin-only Decision Center the
 * Windows panel has, over the SAME /api/brain contract (§88).
 *
 * What the owner sees here is deliberately a subset of what the server knows:
 * short Persian cards with بررسی / اجرا / بعداً / رد, the reasoning on expand,
 * and an answer-only chat. Tool calls, raw JSON and the model's reasoning text
 * are never rendered — the server strips them and so does this screen.
 *
 * Offline honesty: an approve/reject made while the PC is unreachable is queued
 * (pending_sync) and replayed when the link returns; if the server refuses it
 * (already resolved elsewhere, …) the refusal is SHOWN as a conflict — it is
 * never silently dropped and never silently overwritten.
 */
public final class BrainScreens {
    private BrainScreens() {}

    static String statusLabel(String s) {
        switch (s == null ? "" : s) {
            case "NEEDS_DECISION": return "نیازمند تصمیم";
            case "WAITING_APPROVAL": return "منتظر تأیید";
            case "RUNNING": return "در حال اجرا";
            case "MONITORING": return "در حال پایش";
            case "COMPLETED": return "اجرا شد";
            case "MEASURED": return "اندازه‌گیری شد";
            case "FAILED": return "ناموفق";
            case "RESOLVED": return "بسته شد";
            case "NO_ACTION": return "بدون اقدام";
        }
        return s == null ? "" : s;
    }
    static int statusColor(String s) {
        switch (s == null ? "" : s) {
            case "NEEDS_DECISION": case "WAITING_APPROVAL": case "FAILED": return Ui.RED;
            case "RUNNING": case "MONITORING": return Ui.AMBER;
            case "COMPLETED": case "MEASURED": return Ui.GREEN;
        }
        return Ui.MUTED;
    }
    static String riskLabel(String r) {
        if ("high".equals(r)) return "ریسک بالا";
        if ("medium".equals(r)) return "ریسک متوسط";
        if ("low".equals(r)) return "ریسک کم";
        return "بی‌ریسک";
    }

    /* ================================================================ decision center */
    public static final class Center extends Screens.Screen {
        int tab = 0;
        JSONObject status = new JSONObject();
        Center(AppActivity a) { super(a); }
        public String key() { return "brain"; }
        public String title() { return "مغز فروشگاه"; }
        public boolean autoRefresh() { return false; }

        public void load() {
            loading();
            replayQueue();   // offline approvals first — the desk must be current
            BrainModel.autoSetup(c);   // v4.2: fetch the model by itself on first open + Wi-Fi
            Api.get("/brain/status", r -> { status = (JSONObject) r; afterStatus(); },
                    e -> { status = new JSONObject(); renderStandalone(); });
        }
        void renderStandalone() {
            clear();
            LinearLayout hero = Ui.hero(c);
            hero.addView(Ui.text(c, "مغز فروشگاه", 20, 0xFFFFFFFF, true));
            hero.addView(Ui.text(c, "رایانهٔ فروشگاه در دسترس نیست — حالت مستقل گوشی.", 12, 0xDDFFFFFF, false));
            LinearLayout br = Ui.row(c); br.setPadding(0, Ui.dp(10), 0, 0);
            android.widget.Button chat = Ui.small(c, "گفت‌وگو با مغز محلی", () -> a.open(new Chat(a), true));
            chat.setLayoutParams(Ui.weight(1)); br.addView(chat);
            hero.addView(br);
            body.addView(hero);
            body.addView(Ui.body(c, "وقتی رایانه وصل باشد، کارت‌های تصمیم و گفت‌وگو با دادهٔ زندهٔ فروشگاه همین‌جا می‌آید. همین حالا هم همان مدل روی خود گوشی جواب می‌دهد — اگر مدل را نگرفته‌اید، پایین همین صفحه («مدل محلی») بگیرید."));
            modelTab();
        }
        void afterStatus() {
            get("/brain/decisions?limit=100", r -> render(((JSONObject) r).optJSONArray("decisions")));
        }

        void render(JSONArray all) {
            clear();
            // ---- honest runtime header: what answers the questions today
            JSONObject runtime = status.optJSONObject("runtime");
            JSONObject model = status.optJSONObject("model");
            boolean noModel = runtime == null || "deterministic".equals(runtime.optString("provider"));
            LinearLayout hero = Ui.hero(c);
            hero.addView(Ui.text(c, "مغز فروشگاه", 20, 0xFFFFFFFF, true));
            String mode = status.optString("local_mode", "local_only");
            String modeFa = "cloud_only".equals(mode) ? "فقط ابر" : "cloud_fallback".equals(mode) ? "محلی + ابر در صورت نیاز"
                    : "local_preferred".equals(mode) ? "محلی با اولویت محلی" : "فقط محلی";
            hero.addView(Ui.text(c, noModel
                    ? "پاسخ‌ها از موتور قطعی می‌آیند (مدل محلی نصب نشده) — این محدودیت پنهان نمی‌شود."
                    : "پاسخ‌ها از مدل محلی رایانه ساخته می‌شود.", 12, 0xDDFFFFFF, false));
            hero.addView(Ui.text(c, "حالت هوش مصنوعی: " + modeFa + " · مدل فعال: "
                    + (model == null ? "—" : (model.optString("active") == null || model.optString("active").isEmpty() ? "—" : model.optString("active"))), 12, 0xDDFFFFFF, false));
            LinearLayout br = Ui.row(c); br.setPadding(0, Ui.dp(10), 0, 0);
            android.widget.Button chat = Ui.small(c, "گفت‌وگو با مغز", () -> a.open(new Chat(a), true));
            chat.setLayoutParams(Ui.weight(1)); br.addView(chat);
            android.widget.Button scan = Ui.small(c, "بررسی الان", () -> {
                Ui.toast("در حال بررسی وضعیت…");
                post("/brain/proactive/run?force=true", new JSONObject(), r -> { Ui.toast("بررسی انجام شد"); load(); });
            });
            scan.setLayoutParams(Ui.weight(1)); br.addView(scan);
            hero.addView(br);
            body.addView(hero);

            // ---- offline queue + conflicts (never silent)
            JSONArray queue = readJson("brain_queue"), conflicts = readJson("brain_conflicts");
            if (queue.length() > 0 || conflicts.length() > 0) {
                LinearLayout q = Ui.card(c, "همگام‌سازی و تعارض‌ها");
                if (queue.length() > 0) q.addView(Ui.muted(c, Ui.num(queue.length()) + " اقدام آفلاین در انتظار اتصال به رایانه"));
                for (int i = 0; i < conflicts.length(); i++) {
                    JSONObject x = conflicts.optJSONObject(i);
                    LinearLayout row = Ui.row(c);
                    TextView t = Ui.body(c, "رد شد: " + x.optString("label"));
                    t.setLayoutParams(Ui.weight(1)); row.addView(t);
                    row.addView(Ui.badge(c, "تعارض", Ui.RED));
                    LinearLayout detail = Ui.col(c);
                    detail.addView(Ui.body(c, x.optString("error")));
                    detail.addView(Ui.muted(c, Ui.jdate(x.optString("at"))));
                    row.setOnClickListener(v -> Ui.sheet(c, "جزئیات تعارض", Ui.scroll(c, detail)));
                    q.addView(row);
                }
                if (conflicts.length() > 0) q.addView(Ui.small(c, "پاک‌کردن تعارض‌های دیده‌شده", () -> { Prefs.set("brain_conflicts", "[]"); load(); }));
                body.addView(q);
            }

            body.addView(tabs(new String[]{"روی میز", "اجراها و نتایج", "پیگیری‌ها", "مدل محلی"}, tab, k -> { tab = k; load(); }));

            if (tab == 3) { modelTab(); return; }

            String want = tab == 0
                    ? "NEEDS_DECISION,WAITING_APPROVAL,RUNNING,MONITORING"
                    : "COMPLETED,MEASURED,FAILED,RESOLVED,NO_ACTION";
            JSONArray items = new JSONArray();
            for (int i = 0; all != null && i < all.length(); i++)
                if (("," + want + ",").contains("," + all.optJSONObject(i).optString("status") + ","))
                    items.put(all.optJSONObject(i));

            if (tab == 2) { followups(); return; }

            if (items.length() == 0) {
                body.addView(Ui.empty(c, tab == 0
                        ? "الان تصمیمی روی میز نیست. اگر وضعیت فروشگاه عادی باشد، همین پاسخ درست است."
                        : "موردی ثبت نشده."));
                return;
            }
            LinearLayout list = Ui.col(c); body.addView(list);
            for (int i = 0; i < items.length(); i++) card(items.optJSONObject(i));
        }

        void card(JSONObject d) {
            long id = d.optLong("id");
            String st = d.optString("status");
            LinearLayout card = Ui.card(c);
            LinearLayout head = Ui.row(c);
            head.addView(Icons.view(c, "wand", Ui.GOLD, 20));
            LinearLayout hc = Ui.col(c); hc.setPadding(Ui.dp(8), 0, 0, 0); hc.setLayoutParams(Ui.weight(1));
            hc.addView(Ui.muted(c, d.optString("decision_kind", "تصمیم") + " · " + d.optString("priority_label", "")));
            hc.addView(Ui.text(c, d.optString("title"), 14.5f, Ui.TEXT, true));
            head.addView(hc);
            head.addView(Ui.badge(c, statusLabel(st), statusColor(st)));
            card.addView(head);
            if (!d.optString("reason").isEmpty()) card.addView(Ui.muted(c, d.optString("reason")));
            double gain = d.optDouble("gain_toman");
            LinearLayout foot = Ui.row(c); foot.setPadding(0, Ui.dp(6), 0, 0);
            if (gain > 0) foot.addView(Ui.text(c, "اثر تخمینی: " + Ui.money(gain), 12, Ui.GREEN, true));
            if (d.optBoolean("pending_sync")) foot.addView(Ui.badge(c, "در انتظار همگام‌سازی", Ui.AMBER));
            View sp = new View(c); sp.setLayoutParams(Ui.weight(1)); foot.addView(sp);
            foot.addView(Ui.muted(c, Ui.jdate(d.optString("created_at"))));
            card.addView(foot);

            LinearLayout act = Ui.row(c); act.setPadding(0, Ui.dp(8), 0, 0);
            act.addView(Ui.small(c, "بررسی", () -> detail(id)));
            if (tab == 0) {
                act.addView(Ui.small(c, "اجرا", () -> act(id, "approve", new JSONObject(), "اجرا")));
                act.addView(Ui.small(c, "بعداً", () -> {
                    JSONObject b = new JSONObject(); try { b.put("days", 3); } catch (Exception ignore) {}
                    act(id, "snooze", b, "به تعویق");
                }));
                act.addView(Ui.small(c, "رد", () -> {
                    JSONObject b = new JSONObject(); try { b.put("reason", "مدیر در گوشی رد کرد"); } catch (Exception ignore) {}
                    act(id, "reject", b, "رد");
                }));
            } else if ("COMPLETED".equals(st) || "MONITORING".equals(st) || "MEASURED".equals(st)) {
                act.addView(Ui.small(c, "اندازه‌گیری نتیجه", () -> act(id, "measure", new JSONObject(), "اندازه‌گیری")));
            }
            card.addView(act);
            body.addView(card);
        }

        void act(long id, String verb, JSONObject body, String label) {
            if ("approve".equals(verb)) Ui.confirm(c, "اجرای این تصمیم تأیید می‌شود؟ اقدام‌ها از طریق موتور اقدام فروشگاه اجرا و نتیجه‌اش اندازه‌گیری می‌شود.", () -> send(id, verb, body, label));
            else send(id, verb, body, label);
        }
        void send(long id, String verb, JSONObject payload, String label) {
            final String path = "/brain/decisions/" + id + "/" + verb;
            Api.post(path, payload, r -> { Ui.toast(label + " شد"); load(); }, e -> {
                if (e.offline()) { queueOp("POST", path, payload.toString(), "تصمیم #" + Ui.num(id) + " — " + label); load(); }
                else Ui.toast(e.getMessage());
            });
        }

        void detail(long id) {
            get("/brain/decisions/" + id, r -> {
                JSONObject d = (JSONObject) r;
                LinearLayout l = Ui.col(c); l.setPadding(0, Ui.dp(4), 0, Ui.dp(8));
                l.addView(Ui.body(c, d.optString("problem")));
                if (!d.optString("reason").isEmpty()) { l.addView(Ui.label(c, "دلیل")); l.addView(Ui.body(c, d.optString("reason"))); }
                JSONArray options = d.optJSONArray("options");
                if (options != null && options.length() > 0) {
                    l.addView(Ui.label(c, "گزینه‌ها"));
                    for (int i = 0; i < options.length(); i++) {
                        JSONObject o = options.optJSONObject(i);
                        LinearLayout row = Ui.row(c); row.setPadding(0, Ui.dp(4), 0, Ui.dp(4));
                        LinearLayout t = Ui.col(c); t.setLayoutParams(Ui.weight(1));
                        t.addView(Ui.body(c, o.optString("label")));
                        if (!o.optString("description").isEmpty()) t.addView(Ui.muted(c, o.optString("description")));
                        row.addView(t);
                        JSONObject eco = o.optJSONObject("economics");
                        if (eco != null && eco.optDouble("gain_toman") > 0)
                            row.addView(Ui.text(c, Ui.money(eco.optDouble("gain_toman")), 12, Ui.GREEN, true));
                        row.addView(Ui.badge(c, riskLabel(o.optString("risk")), o.optBoolean("requires_approval") ? Ui.AMBER : Ui.MUTED));
                        l.addView(row);
                    }
                }
                JSONObject pv = d.optJSONObject("policy_verdict");
                if (pv != null && !pv.optString("reason").isEmpty()) {
                    l.addView(Ui.label(c, "سیاست فروشگاه")); l.addView(Ui.body(c, pv.optString("reason")));
                }
                JSONObject m = d.optJSONObject("measurement");
                if (m != null && !m.optString("metric").isEmpty()) {
                    l.addView(Ui.label(c, "قرارداد اندازه‌گیری"));
                    l.addView(Ui.muted(c, "معیار " + m.optString("metric") + " · بازهٔ " + Ui.num(m.optInt("window_days", 14)) + " روزه"));
                }
                JSONObject ex = d.optJSONObject("execution");
                if (ex != null && ex.optJSONArray("executions") != null && ex.optJSONArray("executions").length() > 0) {
                    l.addView(Ui.label(c, "اجرا"));
                    JSONArray es = ex.optJSONArray("executions");
                    for (int i = 0; i < es.length(); i++) {
                        JSONObject e = es.optJSONObject(i);
                        l.addView(Ui.muted(c, (e.optBoolean("ok") ? "✓ " : "✗ ") + e.optString("type")));
                    }
                }
                if (d.optString("outcome") != null && !d.optString("outcome").isEmpty())
                    l.addView(Ui.kv(c, "نتیجه", d.optString("outcome"), Ui.TEXT));
                Ui.sheet(c, "تصمیم #" + Ui.num(id), Ui.scroll(c, l));
            });
        }

        void followups() {
            get("/brain/followups", r -> {
                JSONArray items = ((JSONObject) r).optJSONArray("followups");
                if (items == null || items.length() == 0) { body.addView(Ui.empty(c, "پیگیری بازی نیست.")); return; }
                for (int i = 0; i < items.length(); i++) {
                    JSONObject f = items.optJSONObject(i);
                    LinearLayout card = Ui.card(c);
                    LinearLayout head = Ui.row(c);
                    head.addView(Icons.view(c, "bell", Ui.AMBER, 18));
                    LinearLayout t = Ui.col(c); t.setPadding(Ui.dp(8), 0, 0, 0); t.setLayoutParams(Ui.weight(1));
                    t.addView(Ui.text(c, f.optString("title"), 14, Ui.TEXT, true));
                    head.addView(t);
                    if ("MEASURE".equals(f.optString("kind"))) head.addView(Ui.badge(c, "اندازه‌گیری", Ui.AMBER));
                    card.addView(head);
                    if (!f.optString("note").isEmpty()) card.addView(Ui.muted(c, f.optString("note")));
                    card.addView(Ui.small(c, "ثبت نتیجه", () -> resolve(f)));
                    body.addView(card);
                }
            });
        }

        void resolve(JSONObject f) {
            final long id = f.optLong("id");
            LinearLayout l = Ui.col(c);
            final EditText in = Ui.area(c, "چه اتفاقی افتاد؟ (مثلاً: مشتری پرداخت کرد، فروش ۱۵٪ بالا رفت)");
            l.addView(in);
            android.widget.Button ok = Ui.primary(c, "ثبت", () -> {
                String result = in.getText().toString().trim();
                JSONObject b = new JSONObject(); try { b.put("result", result); } catch (Exception ignore) {}
                Api.post("/brain/followups/" + id + "/resolve", b, r -> { Ui.toast("ثبت شد"); load(); }, e -> {
                    if (e.offline()) { queueOp("POST", "/brain/followups/" + id + "/resolve", b.toString(), "پیگیری: " + f.optString("title")); load(); }
                    else Ui.toast(e.getMessage());
                });
            });
            ok.setLayoutParams(Ui.margin(Ui.match(), 0, 8, 0, 0));
            l.addView(ok);
            Ui.sheet(c, "نتیجهٔ پیگیری", l);
        }

        /* ---------------- the local model (downloads AFTER install, as app data) ---------------- */
        void modelTab() {
            body.addView(engineCard());
            LinearLayout why = Ui.card(c, "مدل تخصصی سوپری‌من");
            why.addView(Ui.body(c, "فایل مدل داخل نصب برنامه نیست؛ پس از نصب، از مخزن رسمی سازنده دریافت، هش SHA-256 آن تأیید و در حافظهٔ خود برنامه نگه داشته می‌شود (حذف برنامه، آن را هم پاک می‌کند)."));
            why.addView(Ui.muted(c, "حجم دریافت حدود ۰٫۹ تا ۱٫۱ گیگابایت است — وای‌فای توصیه می‌شود. دریافت با «توقف» قابل قطع و از همان‌جا قابل ادامه است؛ اگر منبع اول (Hugging Face) در دسترس نباشد، همان فایل از منبع رسمی دیگر (ModelScope) گرفته می‌شود."));
            why.addView(Ui.muted(c, "این همان فایل مدلِ رایانهٔ فروشگاه است (شناسه و هش یکسان) — یک مدل، نه دو مدل. وقتی گوشی با رایانه جفت است، پاسخ‌ها از مغزِ رایانه می‌آید؛ در حالت مستقل، همین فایل روی خود گوشی اجرا می‌شود."));
            body.addView(why);
            for (BrainModel.Spec s : BrainModel.MODELS) body.addView(modelCard(s));
        }

        /** v4.1 — the on-device engine: same llama.cpp (b6283) the PC runs, inside the APK. */
        LinearLayout engineCard() {
            final LinearLayout card = Ui.card(c);
            LinearLayout head = Ui.row(c);
            head.addView(Icons.view(c, "wand", Ui.GOLD, 18));
            LinearLayout t = Ui.col(c); t.setPadding(Ui.dp(8), 0, 0, 0); t.setLayoutParams(Ui.weight(1));
            t.addView(Ui.text(c, "موتور استنتاج روی گوشی", 13.5f, Ui.TEXT, true));
            t.addView(Ui.muted(c, "llama.cpp " + BrainEngine.ENGINE_TAG + " — همان موتور رایانه، داخل همین برنامه"));
            head.addView(t);
            final String st = BrainEngine.state();
            if (BrainEngine.RUNNING.equals(st)) head.addView(Ui.badge(c, "روشن", Ui.GREEN));
            else if (BrainEngine.STARTING.equals(st)) head.addView(Ui.badge(c, "در حال روشن‌شدن", Ui.AMBER));
            else if (BrainEngine.FAILED.equals(st)) head.addView(Ui.badge(c, "خطا", Ui.RED));
            else head.addView(Ui.badge(c, "خاموش", Ui.AMBER));
            card.addView(head);

            final TextView note = Ui.muted(c, engineNote());
            note.setPadding(0, Ui.dp(6), 0, 0);
            card.addView(note);

            LinearLayout act = Ui.row(c); act.setPadding(0, Ui.dp(8), 0, 0);
            if (BrainEngine.installed(c)) {
                if (BrainEngine.RUNNING.equals(st) || BrainEngine.STARTING.equals(st)) {
                    act.addView(Ui.small(c, "خاموش‌کردن موتور", () -> { BrainEngine.stop(); load(); }));
                } else {
                    android.widget.Button start = Ui.primary(c, "روشن‌کردن و آزمایش موتور محلی", () -> {
                        BrainEngine.start(c, BrainModel.recommended());
                        Ui.toast("در حال بارگذاری مدل روی گوشی… چند لحظه صبر کنید");
                        new android.os.Handler(android.os.Looper.getMainLooper()).postDelayed(this::load, 1500);
                    });
                    start.setLayoutParams(Ui.weight(1)); act.addView(start);
                }
            } else {
                note.setText("موتور محلی در این نصب موجود نیست — پاسخ‌ها از رایانهٔ فروشگاه می‌آید.");
            }
            card.addView(act);
            BrainEngine.listen((state, n) -> {
                android.os.Handler hh = new android.os.Handler(android.os.Looper.getMainLooper());
                hh.post(this::load);
            });
            return card;
        }

        String engineNote() {
            String st = BrainEngine.state();
            String n = BrainEngine.note();
            long ram = BrainEngine.totalRamMb(c);
            BrainModel.Spec rec = BrainModel.recommended();
            String fit = BrainEngine.fitsRam(c, rec)
                    ? "حافظهٔ گوشی برای مدل پیشنهادی کافی است (" + Ui.num(ram) + " مگابایت رم)"
                    : "حافظهٔ گوشی برای مدل پیشنهادی کافی به نظر نمی‌رسد (" + Ui.num(ram) + " مگابایت رم؛ حداقل " + Ui.num(rec.minRamMb) + ")";
            return (n.isEmpty() ? "موتور محلی برای پاسخ‌گویی در حالت مستقل (بدون رایانه) است." : n) + " — " + fit;
        }
        LinearLayout modelCard(final BrainModel.Spec s) {
            final LinearLayout card = Ui.card(c);
            LinearLayout head = Ui.row(c);
            // v4.2.1 — the owner asked for a proper icon for the model
            android.widget.ImageView ic = new android.widget.ImageView(c);
            ic.setImageResource(R.drawable.ic_model);
            ic.setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(34), Ui.dp(34)));
            head.addView(ic);
            LinearLayout t = Ui.col(c); t.setPadding(Ui.dp(8), 0, 0, 0); t.setLayoutParams(Ui.weight(1));
            t.addView(Ui.text(c, s.label(), 13.5f, Ui.TEXT, true));   // branded name, not the technical id
            t.addView(Ui.muted(c, "حجم: " + Ui.num(Math.round(s.bytes / 1048576.0))
                    + " مگابایت · حداقل رم: " + Ui.num(s.minRamMb) + " مگابایت"));
            head.addView(t);
            final String st = BrainModel.stateOf(s.id);
            if (BrainModel.READY.equals(st)) head.addView(Ui.badge(c, "آماده", Ui.GREEN));
            else if (BrainModel.DOWNLOADING.equals(st) || BrainModel.VERIFYING.equals(st)) head.addView(Ui.badge(c, "در حال دریافت", Ui.AMBER));
            else if (BrainModel.PAUSED.equals(st)) head.addView(Ui.badge(c, "متوقف", Ui.AMBER));
            else if (BrainModel.CORRUPT.equals(st)) head.addView(Ui.badge(c, "تأیید نشد", Ui.RED));
            card.addView(head);

            final LinearLayout progWrap = Ui.col(c);
            final TextView note = Ui.muted(c, BrainModel.noteOf(s.id));
            final ProgressBar bar = new ProgressBar(c, null, android.R.attr.progressBarStyleHorizontal);
            bar.setMax(10000);
            LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(10));
            bp.setMargins(0, Ui.dp(6), 0, Ui.dp(4)); bar.setLayoutParams(bp);
            progWrap.addView(bar); progWrap.addView(note);
            card.addView(progWrap);

            Runnable paint = () -> {
                String state = BrainModel.stateOf(s.id);
                long done = BrainModel.doneOf(s.id);
                bar.setProgress(state.equals(BrainModel.VERIFYING) || state.equals(BrainModel.DOWNLOADING)
                        ? (int) Math.min(10000, done * 10000 / Math.max(1, s.bytes)) : 0);
                progWrap.setVisibility(state.isEmpty() ? View.GONE : View.VISIBLE);
                note.setText(BrainModel.noteOf(s.id));
            };
            paint.run();

            LinearLayout act = Ui.row(c); act.setPadding(0, Ui.dp(8), 0, 0);
            if (BrainModel.READY.equals(BrainModel.stateOf(s.id))) {
                act.addView(Ui.small(c, "حذف فایل", () -> { Ui.confirm(c, "فایل مدل از گوشی حذف شود؟", () -> { BrainModel.delete(c, s); load(); }); }));
            } else if (BrainModel.DOWNLOADING.equals(BrainModel.stateOf(s.id)) || BrainModel.VERIFYING.equals(BrainModel.stateOf(s.id))) {
                act.addView(Ui.small(c, "توقف", () -> { BrainModel.pause(); }));
            } else {
                String label = BrainModel.PAUSED.equals(BrainModel.stateOf(s.id)) ? "ادامهٔ دریافت" : "دریافت مدل";
                android.widget.Button dl = Ui.primary(c, label, () -> {
                    Ui.toast("دریافت از مخزن رسمی آغاز شد — حدود " + Ui.num(Math.round(s.bytes / 1048576.0)) + " مگابایت");
                    BrainModel.download(c, s);
                });
                dl.setLayoutParams(Ui.weight(1)); act.addView(dl);
            }
            card.addView(act);

            BrainModel.listen("card:" + s.id, (modelId, state, done, total, n) -> {
                if (!modelId.equals(s.id)) return;
                if (state.equals(BrainModel.READY) || state.equals(BrainModel.CORRUPT)) { load(); return; }
                bar.setProgress((int) Math.min(10000, done * 10000 / Math.max(1, s.bytes)));
                note.setText(n);
                progWrap.setVisibility(View.VISIBLE);
            });
            return card;
        }

        /* ---------------- offline queue (§ never silent overwrite) ---------------- */
        static JSONArray readJson(String key) {
            try { return new JSONArray(Prefs.get(key, "[]")); } catch (Exception e) { return new JSONArray(); }
        }
        static void queueOp(String method, String path, String body, String label) {
            try {
                JSONArray q = readJson("brain_queue");
                JSONObject op = new JSONObject();
                op.put("id", UUID.randomUUID().toString()); op.put("method", method);
                op.put("path", path); op.put("body", body); op.put("label", label);
                op.put("at", java.time.Instant.now().toString());
                q.put(op); Prefs.set("brain_queue", q.toString());
                Ui.toast("رایانه در دسترس نیست — در صف نگه داشته شد");
            } catch (Exception ignore) {}
        }
        static void replayQueue() {
            final JSONArray q = readJson("brain_queue");
            if (q.length() == 0 || Api.standalone()) return;
            Api.bg(() -> {
                for (int i = 0; i < q.length(); i++) {
                    JSONObject op = q.optJSONObject(i);
                    try {
                        Api.call(op.optString("method"), op.optString("path"), op.optString("body", "{}"), "application/json");
                        removeOp(op.optString("id"), "brain_queue");
                    } catch (Api.ApiError e) {
                        if (e.offline()) return;   // still offline: keep the rest queued
                        conflict(op.optString("label"), e.getMessage());
                        removeOp(op.optString("id"), "brain_queue");
                    } catch (Exception e) {
                        conflict(op.optString("label"), String.valueOf(e));
                        removeOp(op.optString("id"), "brain_queue");
                    }
                }
            });
        }
        static void removeOp(String id, String key) {
            JSONArray q = readJson(key), out = new JSONArray();
            for (int i = 0; i < q.length(); i++) if (!q.optJSONObject(i).optString("id").equals(id)) out.put(q.optJSONObject(i));
            Prefs.set(key, out.toString());
        }
        static void conflict(String label, String error) {
            try {
                JSONArray cs = readJson("brain_conflicts");
                JSONObject x = new JSONObject();
                x.put("label", label); x.put("error", error); x.put("at", java.time.Instant.now().toString());
                cs.put(x); Prefs.set("brain_conflicts", cs.toString());
                Api.ui(() -> Ui.toast("یک اقدام آفلاین رد شد — بخش تعارض‌های مغز را ببینید"));
            } catch (Exception ignore) {}
        }
    }

    /* ================================================================ chat */
    public static final class Chat extends Screens.Screen {
        LinearLayout log;
        EditText in;
        /** v4.3 — the mic button (speech → question) and the voice-mode toggle. */
        android.widget.Button micBtn, vmBtn;
        /** v4.1 — the standalone-mode conversation (system prompt + this session's turns). */
        JSONArray local;
        Chat(AppActivity a) { super(a); }
        public String key() { return "brainChat"; }
        public String title() { return "گفت‌وگو با مغز فروشگاه"; }

        @Override public View view() {
            LinearLayout root = Ui.col(a); root.setPadding(Ui.dp(14), Ui.dp(10), Ui.dp(14), Ui.dp(10));
            // v4.2.1 — a proper chat header: the model's own icon + branded subtitle
            LinearLayout head = Ui.row(c);
            head.setPadding(0, 0, 0, Ui.dp(10));
            android.widget.ImageView hic = new android.widget.ImageView(c);
            hic.setImageResource(R.drawable.ic_model);
            hic.setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(40), Ui.dp(40)));
            head.addView(hic);
            LinearLayout ht = Ui.col(c); ht.setPadding(Ui.dp(10), 0, 0, 0);
            ht.addView(Ui.text(c, "گفت‌وگو با مغز فروشگاه", 15.5f, Ui.TEXT, true));
            ht.addView(Ui.muted(c, "مدل تخصصی سوپری‌من — محلی و آفلاین، مخصوص همین فروشگاه"));
            head.addView(ht);
            root.addView(head);
            // v4.3 — حالت صوتی: گفتار شما فرستاده می‌شود و پاسخ بلند خوانده می‌شود.
            // The MODEL is unchanged (owner's rule) — voice is only ears + mouth.
            LinearLayout vr = Ui.row(c); vr.setPadding(0, 0, 0, Ui.dp(8));
            vmBtn = Ui.small(c, "", () -> {});
            vmBtn.setLayoutParams(Ui.weight(1));
            vmBtn.setOnClickListener(v -> {
                boolean on = !BrainVoice.voiceMode();
                BrainVoice.setVoiceMode(on);
                if (on) BrainVoice.initTts(c);
                paintVoiceMode();
                Ui.toast(on ? "حالت صوتی روشن شد — دکمهٔ «گفتار» را بزنید و صحبت کنید؛ پاسخ بلند خوانده می‌شود"
                        : "حالت صوتی خاموش شد");
            });
            vr.addView(vmBtn);
            paintVoiceMode();
            root.addView(vr);
            log = Ui.col(a);
            ScrollView sv = new ScrollView(c); sv.addView(log);
            sv.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
            sv.setFillViewport(true);
            root.addView(sv);
            LinearLayout row = Ui.row(c); row.setPadding(0, Ui.dp(8), 0, 0);
            // v4.3 — the mic: press, speak Persian, the text lands in the input
            // (and is sent immediately in voice mode). Uses the system recognizer.
            micBtn = Ui.small(c, "گفتار", this::tapMic);
            row.addView(micBtn);
            in = Ui.input(c, "مثلاً: این هفته چقدر پول لازم دارم؟");
            in.setLayoutParams(Ui.weight(1)); row.addView(in);
            row.addView(Ui.primary(c, "بپرس", this::send));
            root.addView(row);
            root.addView(Ui.muted(c, "وصل به رایانه: پاسخ‌ها از دادهٔ همین فروشگاه ساخته می‌شود و عددی که از ابزار نیامده نمایش داده نمی‌شود. بدون رایانه: اگر مدل محلی گرفته و موتور روشن باشد، همان مدل روی خود گوشی پاسخ می‌دهد (با برچسب «محلی») و بدون دادهٔ زندهٔ فروشگاه."));
            try {
                local = new JSONArray();
                local.put(new JSONObject().put("role", "system").put("content", BrainEngine.SYSTEM_PROMPT));
            } catch (Exception ignore) { local = new JSONArray(); }
            return root;
        }
        void paintVoiceMode() {
            if (vmBtn == null) return;
            vmBtn.setText(BrainVoice.voiceMode()
                    ? "حالت صوتی: روشن — پاسخ‌ها بلند خوانده می‌شوند"
                    : "حالت صوتی: خاموش");
        }

        /** v4.3 — press, speak; the recognized Persian text goes into the input
         *  (and is sent immediately in voice mode → the conversation is spoken). */
        void tapMic() {
            BrainVoice.toggleListen(a, text -> {
                in.setText(text);
                if (BrainVoice.voiceMode()) send();
            }, on -> micBtn.setText(on ? "در حال شنیدن…" : "گفتار"));
        }

        public void load() {
            log.removeAllViews();
            log.addView(Ui.muted(c, "در حال خواندن گفت‌وگو…"));
            get("/brain/chat/history?limit=40", r -> {
                JSONArray ms = ((JSONObject) r).optJSONArray("messages");
                log.removeAllViews();
                if (ms == null || ms.length() == 0) { log.addView(Ui.empty(c, "سؤالت را بپرس — از وضعیت واقعی فروشگاه جواب می‌گیرم.")); return; }
                for (int i = 0; i < ms.length(); i++) bubble(ms.optJSONObject(i).optString("role"), ms.optJSONObject(i).optString("content"));
            });
        }
        String nowTime() {
            try { return Ui.fa(new java.text.SimpleDateFormat("HH:mm", java.util.Locale.US)
                    .format(new java.util.Date())); } catch (Exception e) { return ""; }
        }

        LinearLayout bubbleBase(boolean user) {
            LinearLayout b = Ui.col(c);
            b.setPadding(Ui.dp(14), Ui.dp(10), Ui.dp(14), Ui.dp(10));
            if (user) b.setBackground(Ui.gradient(Ui.PRIMARY, Ui.PRIMARY2, 0, 18));
            else b.setBackground(Ui.rounded(Ui.CARD2, Ui.BORDER, 18));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.gravity = user ? android.view.Gravity.START : android.view.Gravity.END;   // RTL: شما راست، مغز چپ
            lp.setMargins(0, 0, 0, Ui.dp(8));
            b.setLayoutParams(lp);
            return b;
        }

        void scrollDown() {
            View v = (View) log.getParent();
            if (v instanceof ScrollView) ((ScrollView) v).fullScroll(View.FOCUS_DOWN);
        }

        void bubble(String role, String text) {
            boolean user = "USER".equals(role);
            LinearLayout b = bubbleBase(user);
            if (!user) {
                LinearLayout h = Ui.row(c);
                android.widget.ImageView av = new android.widget.ImageView(c);
                av.setImageResource(R.drawable.ic_model);
                av.setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(20), Ui.dp(20)));
                h.addView(av);
                TextView nm = Ui.muted(c, "مغز فروشگاه");
                nm.setPadding(Ui.dp(6), 0, 0, 0);
                h.addView(nm);
                b.addView(h);
            }
            TextView t = Ui.text(c, text, 13.5f, user ? 0xFFFFFFFF : Ui.TEXT, false);
            t.setLineSpacing(0, 1.35f);
            b.addView(t);
            TextView meta = Ui.text(c, (user ? "شما · " : "") + nowTime(), 10,
                    user ? 0xCCFFFFFF : Ui.MUTED, false);
            meta.setPadding(0, Ui.dp(4), 0, 0);
            b.addView(meta);
            if (!user) {   // v4.3 — re-read this answer aloud at any time
                android.widget.Button rd = Ui.small(c, "بخوان", () -> BrainVoice.speak(c, text, null));
                LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                rp.topMargin = Ui.dp(6);
                rd.setLayoutParams(rp);
                b.addView(rd);
            }
            log.addView(b);
            b.post(this::scrollDown);
        }

        /** v4.2.1 — animated "typing" bubble (three pulsing dots) while the brain works. */
        LinearLayout thinkingBubble(String label) {
            LinearLayout b = bubbleBase(false);
            LinearLayout h = Ui.row(c);
            android.widget.ImageView av = new android.widget.ImageView(c);
            av.setImageResource(R.drawable.ic_model);
            av.setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(20), Ui.dp(20)));
            h.addView(av);
            TextView nm = Ui.muted(c, "مغز فروشگاه");
            nm.setPadding(Ui.dp(6), 0, 0, 0);
            h.addView(nm);
            TextView dots = Ui.text(c, "● · ·", 13, Ui.MUTED, true);
            dots.setPadding(Ui.dp(10), 0, 0, 0);
            h.addView(dots);
            b.addView(h);
            TextView l = Ui.muted(c, label);
            l.setPadding(0, Ui.dp(4), 0, 0);
            b.addView(l);
            final String[] frames = {"● · ·", "· ● ·", "· · ●"};
            final int[] ix = {0};
            final android.os.Handler hh = new android.os.Handler(android.os.Looper.getMainLooper());
            final Runnable tick = new Runnable() {
                @Override public void run() {
                    if (!dots.isAttachedToWindow()) return;   // the bubble was removed: stop
                    ix[0] = (ix[0] + 1) % frames.length;
                    dots.setText(frames[ix[0]]);
                    hh.postDelayed(this, 350);
                }
            };
            hh.postDelayed(tick, 350);
            return b;
        }
        void send() {
            String q = in.getText().toString().trim();
            if (q.isEmpty()) return;
            in.setText("");
            BrainVoice.stopSpeak();   // v4.3 — a new question cuts the previous reading
            bubble("USER", q);
            // standalone (no PC paired) → the local engine answers directly
            if (Api.standalone()) { localAnswer(q); return; }
            final LinearLayout thinking = thinkingBubble("در حال بررسی داده‌های فروشگاه…");
            log.addView(thinking);
            JSONObject b = new JSONObject(); try { b.put("question", q); b.put("prefer_llm", true); } catch (Exception ignore) {}
            Api.post("/brain/chat", b, r -> {
                log.removeView(thinking);
                JSONObject x = (JSONObject) r;
                bubble("ASSISTANT", x.optString("text"));
                if (BrainVoice.voiceMode()) BrainVoice.speak(c, x.optString("text"), null);   // v4.3
                JSONArray w = x.optJSONArray("warnings");
                if (w != null && w.length() > 0) {
                    StringBuilder sb = new StringBuilder();
                    for (int i = 0; i < w.length(); i++) {
                        String k = w.optString(i);
                        sb.append("MODEL_FAILED".equals(k) ? "مدل محلی پاسخ نداد؛ پاسخ قطعی نمایش داده شد"
                                : "NUMBER_REJECTED".equals(k) ? "عددی که منبع نداشت حذف شد"
                                : "DATA_QUALITY".equals(k) ? "کیفیت داده پایین است" : k).append("، ");
                    }
                    String s = sb.toString();
                    LinearLayout warn = Ui.card(c, null);
                    warn.addView(Ui.muted(c, "نکته: " + s.substring(0, Math.max(0, s.length() - 2))));
                    log.addView(warn);
                }
            }, e -> {
                log.removeView(thinking);
                if (e.offline() && localUsable()) { localAnswer(q); return; }
                bubble("ASSISTANT", Api.standalone() || e.offline()
                        ? "رایانهٔ فروشگاه در دسترس نیست و مدل محلی آماده نیست. مغز بدون دادهٔ همین لحظهٔ فروشگاه عددی نمی‌سازد؛ مدل را از تب «مدل محلی» بگیرید و دوباره بپرسید."
                        : "نتوانستم پاسخ بگیرم: " + e.getMessage());
            });
        }

        boolean localUsable() {
            return BrainEngine.usableWith(c, BrainModel.recommended());
        }

        /** v4.1 — standalone mode: the SAME model file runs ON the phone (labelled, honest). */
        void localAnswer(String q) {
            final LinearLayout thinking = thinkingBubble("در حال پاسخ با مدل محلی روی خود گوشی…");
            log.addView(thinking);
            try { local.put(new JSONObject().put("role", "user").put("content", q)); } catch (Exception ignore) {}
            final JSONArray msgs = local;
            new Thread(() -> {
                BrainModel.Spec s = BrainModel.recommended();
                if (!BrainEngine.running()) BrainEngine.start(c, s);
                String ans = BrainEngine.running() ? BrainEngine.chat(msgs, 512) : null;
                final String answer = ans == null ? "" : ans;
                a.runOnUiThread(() -> {
                    log.removeView(thinking);
                    if (answer.isEmpty()) {
                        bubble("ASSISTANT", "مدل محلی پاسخ نداد. وضعیت موتور: " + BrainEngine.note());
                        return;
                    }
                    try { local.put(new JSONObject().put("role", "assistant").put("content", answer)); } catch (Exception ignore) {}
                    bubble("ASSISTANT", answer);
                    if (BrainVoice.voiceMode()) BrainVoice.speak(c, answer, null);   // v4.3
                    LinearLayout tag = Ui.card(c, null);
                    tag.addView(Ui.muted(c, "پاسخ از مدل محلی روی خود گوشی (همان مدل رایانه، llama.cpp) — بدون دادهٔ زندهٔ فروشگاه؛ برای پاسخ با دادهٔ واقعی، وقتی رایانه وصل است دوباره بپرسید."));
                    log.addView(tag);
                });
            }, "brain-local-chat").start();
        }
    }
}
