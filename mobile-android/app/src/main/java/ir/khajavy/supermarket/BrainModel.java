package ir.khajavy.supermarket;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;

/**
 * v4.0 — the local Business-Brain model on the phone.
 *
 * The APK stays small on purpose (the user asked for exactly this): the ~1 GB
 * Qwen GGUF file is NOT bundled — it downloads AFTER install, on demand, into
 * the app's private data folder, and only ever from the official source with a
 * pinned sha256. A file whose hash does not match is deleted and reported, never
 * kept "to be safe".
 *
 * Honesty rules mirrored from the backend ModelManager:
 *  - states are real (DOWNLOADING / PAUSED / VERIFYING / READY / CORRUPT);
 *  - a partial download resumes instead of restarting;
 *  - nothing is ever reported READY without a full sha256 pass;
 *  - the file lives in getFilesDir() so uninstalling the app removes it too.
 */
public final class BrainModel {
    private BrainModel() {}

    /** The registry pins — mirror of backend model_registry.py (official Qwen sources).
     *  url = Hugging Face (primary); altUrl = ModelScope, where the Qwen org publishes
     *  the SAME files (same sha256) — used when the first source is unreachable. */
    public static final class Spec {
        public final String id, file, url, altUrl, sha256; public final long bytes; public final int minRamMb;
        Spec(String id, String file, String url, String altUrl, String sha256, long bytes, int minRamMb) {
            this.id = id; this.file = file; this.url = url; this.altUrl = altUrl; this.sha256 = sha256;
            this.bytes = bytes; this.minRamMb = minRamMb;
        }
        /** v4.2.1 — the owner's product name for this model (NOT the technical id). */
        public String label() { return bytes > 1_000_000_000L ? "مدل تخصصی سوپری‌من" : "سوپری‌من لایت"; }
    }

    public static final Spec[] MODELS = {
        new Spec("qwen2.5-1.5b-instruct-q4_k_m", "qwen2.5-1.5b-instruct-q4_k_m.gguf",
                 "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
                 "https://modelscope.cn/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/master/qwen2.5-1.5b-instruct-q4_k_m.gguf",
                 "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e", 1117320736L, 4096),
        new Spec("qwen2.5-1.5b-instruct-q3_k_m", "qwen2.5-1.5b-instruct-q3_k_m.gguf",
                 "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q3_k_m.gguf",
                 "https://modelscope.cn/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/master/qwen2.5-1.5b-instruct-q3_k_m.gguf",
                 "58cb5c05ecef48e82961f1a2be6544145ea26136f69dddda4bbbd092f0e4b993", 924455968L, 3584),
    };

    public static Spec find(String id) { for (Spec s : MODELS) if (s.id.equals(id)) return s; return null; }
    public static Spec recommended() { return MODELS[1]; }   // the light one first on phones
    /** v4.3.1 — the spec the ENGINE should run: whichever model is actually
     *  READY (the owner downloaded one of them), recommended as tie-breaker.
     *  Before, start() always took recommended() — if the user had fetched the
     *  OTHER model, the engine refused even though a model was ready. */
    public static Spec readySpec(Context c) {
        Spec rec = recommended();
        if (READY.equals(stateOf(rec.id)) && ready(c, rec)) return rec;
        for (Spec s : MODELS) if (READY.equals(stateOf(s.id)) && ready(c, s)) return s;
        return null;
    }
    /** true when ANY model has a download state (used to never auto-download again). */
    public static boolean anyState() {
        for (Spec s : MODELS) if (!stateOf(s.id).isEmpty()) return true;
        return false;
    }

    /* ---------------- storage ---------------- */
    public static File dir(Context c) { return new File(c.getFilesDir(), "brain/models"); }
    public static File fileFor(Context c, Spec s) { return new File(new File(dir(c), s.id), s.file); }
    private static File partFor(Context c, Spec s) { return new File(new File(dir(c), s.id), s.file + ".part"); }

    /* ---------------- state (persisted in Prefs as JSON) ---------------- */
    public static final String DOWNLOADING = "DOWNLOADING", PAUSED = "PAUSED", VERIFYING = "VERIFYING",
            READY = "READY", CORRUPT = "CORRUPT";

    public interface Listener { void onState(String modelId, String state, long done, long total, String note); }
    private static final java.util.Map<String, Listener> LISTENERS = new java.util.concurrent.ConcurrentHashMap<>();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static volatile Thread worker;
    private static volatile boolean cancel = false;
    /** v4.2.1 — app context for the download notifications (set when a download starts). */
    private static volatile Context appCtx;

    /** Register a named listener; re-registering the same owner replaces it. */
    public static void listen(String owner, Listener l) { if (l == null) LISTENERS.remove(owner); else LISTENERS.put(owner, l); }
    public static void listen(Listener l) { listen("ui", l); }

    public static String stateOf(String id) {
        // v4.4.0 — ROOT FIX of «آماده است ولی می‌گوید مدل تأییدشده نیست»: the state
        // map stores a JSONObject per id, and org.json's optString() on an
        // OBJECT value returns the fallback (""), never the state. Every
        // official check (ready/readySpec/autoSetup) therefore always saw ""
        // even though the badge/note (fed by the live listener) said READY.
        try { JSONObject all = new JSONObject(Prefs.get("brain_model_state", "{}"));
            JSONObject one = all.optJSONObject(id);
            return one == null ? "" : one.optString("state", ""); } catch (Exception e) { return ""; }
    }
    public static String noteOf(String id) {
        try { JSONObject all = new JSONObject(Prefs.get("brain_model_state", "{}"));
            return all.optJSONObject(id) == null ? "" : all.optJSONObject(id).optString("note", ""); } catch (Exception e) { return ""; }
    }
    public static long doneOf(String id) {
        try { JSONObject all = new JSONObject(Prefs.get("brain_model_state", "{}"));
            return all.optJSONObject(id) == null ? 0 : all.optJSONObject(id).optLong("done", 0); } catch (Exception e) { return 0; }
    }
    private static void putState(String id, String state, long done, String note) {
        try {
            JSONObject all = new JSONObject(Prefs.get("brain_model_state", "{}"));
            JSONObject one = all.optJSONObject(id);
            if (one == null) { one = new JSONObject(); all.put(id, one); }
            one.put("state", state); one.put("done", done); one.put("note", note);
            one.put("at", System.currentTimeMillis());
            Prefs.set("brain_model_state", all.toString());
        } catch (Exception ignore) {}
        for (Listener l : LISTENERS.values()) {
            MAIN.post(() -> l.onState(id, state, done, specBytes(id), note));
        }
        // v4.2.1 — the owner's rule: a VISIBLE progress line while downloading,
        // in the status bar as well, not only inside the Model tab.
        Context ac = appCtx;
        if (ac != null) {
            long total = specBytes(id);
            int pct = total > 0 ? (int) Math.min(100, done * 100 / total) : 0;
            if (DOWNLOADING.equals(state) || VERIFYING.equals(state)) {
                BrainModelService.progress(ac, id, pct, done, total, VERIFYING.equals(state));
            }
        }
    }
    private static long specBytes(String id) { Spec s = find(id); return s == null ? 0 : s.bytes; }

    public static boolean ready(Context c, Spec s) {
        return READY.equals(stateOf(s.id)) && fileFor(c, s).exists() && fileFor(c, s).length() == s.bytes;
    }

    /** v4.2 — true when the current network is Wi-Fi/unmetered (safe for a ~1 GB model). */
    public static boolean unmetered(Context c) {
        try {
            android.net.ConnectivityManager cm = (android.net.ConnectivityManager)
                    c.getSystemService(Context.CONNECTIVITY_SERVICE);
            return cm != null && !cm.isActiveNetworkMetered()
                    && cm.getActiveNetworkInfo() != null
                    && cm.getActiveNetworkInfo().isConnected();
        } catch (Exception e) { return false; }
    }

    /** v4.2 — the owner's rule: on first open, if the phone is on Wi-Fi and no model
     *  was ever fetched, start the recommended download by itself (once per install).
     *  On mobile data we never burn the user's gigabytes without asking. */
    public static void autoSetup(Context c) {
        // v4.3.1 — the owner's rule: a model the user (or a corruption) already
        // touched is NEVER auto-downloaded again — auto only on a truly fresh
        // install. A paused download, though, quietly CONTINUES on Wi-Fi.
        boolean fresh = false;
        if (!"1".equals(Prefs.get("brain_model_auto", ""))) {
            Prefs.set("brain_model_auto", "1");
            fresh = true;
        }
        if (fresh && !anyState() && unmetered(c)) {
            Spec s = recommended();
            if (!READY.equals(stateOf(s.id)) && !CORRUPT.equals(stateOf(s.id))) {
                Ui.toast("دریافت " + s.label() + " (~" + Ui.num(Math.round(s.bytes / 1048576.0))
                        + " مگابایت) آغاز شد — از تب «مدل محلی» پیشرفت را ببینید");
                download(c, s);
                return;
            }
        }
        // v4.3.1 — auto-resume what was paused, on Wi-Fi only, never on mobile data
        if (unmetered(c)) {
            for (Spec s : MODELS) {
                if (PAUSED.equals(stateOf(s.id))) {
                    Ui.toast("ادامهٔ دریافت " + s.label() + " از همان‌جا آغاز شد");
                    download(c, s);
                    return;
                }
            }
        }
    }

    /* ---------------- download (single worker, resumable, cancellable) ---------------- */
    public static synchronized void download(Context c, Spec s) {
        if (worker != null && worker.isAlive()) { Ui.toast("یک دریافت مدل در حال اجراست؛ تا پایان آن صبر کنید"); return; }
        cancel = false;
        appCtx = c.getApplicationContext();
        putState(s.id, DOWNLOADING, partFor(c, s).length(), "در حال دریافت از مخزن رسمی");
        // v4.2.1 — foreground-service anchor: the download survives the app being
        // closed/swiped away, with a live progress notification ( BrainModelService ).
        BrainModelService.start(appCtx, s.id);
        worker = new Thread(() -> run(c.getApplicationContext(), s), "brain-model-dl");
        worker.start();
    }

    public static void pause() { cancel = true; }

    public static void delete(Context c, Spec s) {
        partFor(c, s).delete();
        fileFor(c, s).delete();
        putState(s.id, "", 0, "حذف شد");
    }

    private static void run(Context c, Spec s) {
        File part = partFor(c, s);
        File target = fileFor(c, s);
        try {
            part.getParentFile().mkdirs();
            boolean got = false;
            for (String src : new String[]{s.url, s.altUrl}) {
                if (src == null || src.isEmpty()) continue;
                try {
                    fetchFrom(c, s, src, part);
                    got = true;
                    break;
                } catch (Cancelled ce) {
                    putState(s.id, PAUSED, part.length(), "متوقف شد — با «ادامه» از همان‌جا برمی‌گردد");
                    return;
                } catch (Exception e) {
                    // this official source failed — the partial is kept, try the next one
                    putState(s.id, DOWNLOADING, part.length(),
                             "این منبع رسمی پاسخ نداد؛ تلاش از منبع رسمی دیگر…");
                }
            }
            if (!got) throw new IllegalStateException("هیچ‌کدام از منابع رسمی پاسخ ندادند");

            // §38: nothing is READY without a full sha256 pass over the file
            putState(s.id, VERIFYING, part.length(), "در حال تأیید هش فایل…");
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            int n; long lastUi = 0;
            try (InputStream fin = new FileInputStream(part)) {
                long hashed = 0;
                while ((n = fin.read(BUF)) > 0) {
                    if (cancel) break;
                    md.update(BUF, 0, n); hashed += n;
                    if (System.currentTimeMillis() - lastUi > 400) {
                        lastUi = System.currentTimeMillis();
                        putState(s.id, VERIFYING, hashed, "تأیید " + percent(hashed, part.length()));
                    }
                }
            }
            if (cancel) { putState(s.id, PAUSED, part.length(), "متوقف شد"); return; }
            StringBuilder hex = new StringBuilder();
            for (byte b : md.digest()) hex.append(String.format("%02x", b));
            if (!hex.toString().equals(s.sha256)) {
                part.delete();
                putState(s.id, CORRUPT, 0, "هش فایل با مقدار رسمی نمی‌خواند؛ فایل حذف شد");
                Notify.progressDone(c, "مدل تأیید نشد", "فایل دریافت‌شده با مخزن رسمی نمی‌خواند و حذف شد؛ دوباره تلاش کنید");
                return;
            }
            if (target.exists()) target.delete();
            if (!part.renameTo(target)) throw new IllegalStateException("نوشتن فایل نهایی ناموفق بود");
            putState(s.id, READY, target.length(), "آماده — هش تأیید شد");
            Notify.progressDone(c, "مدل مغز فروشگاه آماده شد", "فایل مدل تأیید و در حافظهٔ برنامه ذخیره شد");
        } catch (Exception e) {
            putState(s.id, PAUSED, part.exists() ? part.length() : 0,
                     "دریافت قطع شد (" + e.getMessage() + ") — با «ادامه» از همان‌جا برمی‌گردد");
        } finally {
            // v4.2.1 — release the foreground-service anchor on every exit path;
            // a paused/failed download needs no live notification (it resumes).
            BrainModelService.stop(c);
        }
    }

    private static final class Cancelled extends RuntimeException {}

    /** Stream one official source into ``part`` (resuming if a partial exists). */
    private static void fetchFrom(Context c, Spec s, String src, File part) throws Exception {
        long have = part.exists() ? part.length() : 0;
        HttpURLConnection con = (HttpURLConnection) new URL(src).openConnection();
        con.setConnectTimeout(30000); con.setReadTimeout(60000);
        con.setRequestProperty("User-Agent", "SupermarketMobile/4.1");
        if (have > 0) con.setRequestProperty("Range", "bytes=" + have + "-");
        int code = con.getResponseCode();
        if (code == 416) { // the .part is already the whole file
            part.delete(); have = 0;
            con.disconnect();
            con = (HttpURLConnection) new URL(src).openConnection();
            con.setConnectTimeout(30000); con.setReadTimeout(60000);
            con.setRequestProperty("User-Agent", "SupermarketMobile/4.1");
            code = con.getResponseCode();
        }
        if (code != 200 && code != 206) { con.disconnect(); throw new IllegalStateException("HTTP " + code); }
        long total = s.bytes;
        if (code == 200 && have > 0) { part.delete(); have = 0; }   // no resume support → restart clean
        InputStream in = con.getInputStream();
        OutputStream out = new FileOutputStream(part, have > 0 && code == 206);
        long done = have; long lastUi = 0;
        int n;
        while ((n = in.read(BUF)) > 0) {
            if (cancel) { out.flush(); out.close(); in.close(); con.disconnect(); throw new Cancelled(); }
            out.write(BUF, 0, n);
            done += n;
            if (System.currentTimeMillis() - lastUi > 400) {
                lastUi = System.currentTimeMillis();
                putState(s.id, DOWNLOADING, done, total > 0 ? percent(done, total) : "");
            }
        }
        out.flush(); out.close(); in.close(); con.disconnect();
    }

    private static final byte[] BUF = new byte[256 * 1024];

    private static String percent(long done, long total) {
        if (total <= 0) return "";
        return Ui.num(Math.round(done * 100.0 / total)) + "٪";
    }
}
