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

    /** The registry pins — mirror of backend model_registry.py (official Qwen repo). */
    public static final class Spec {
        public final String id, file, url, sha256; public final long bytes;
        Spec(String id, String file, String url, String sha256, long bytes) {
            this.id = id; this.file = file; this.url = url; this.sha256 = sha256; this.bytes = bytes;
        }
        public String label() { return "Qwen2.5 1.5B · " + (bytes > 1_000_000_000L ? "کیفیت پایه" : "سبک (گوشی‌های ضعیف‌تر)"); }
    }

    public static final Spec[] MODELS = {
        new Spec("qwen2.5-1.5b-instruct-q4_k_m", "qwen2.5-1.5b-instruct-q4_k_m.gguf",
                 "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
                 "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e", 1117320736L),
        new Spec("qwen2.5-1.5b-instruct-q3_k_m", "qwen2.5-1.5b-instruct-q3_k_m.gguf",
                 "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q3_k_m.gguf",
                 "58cb5c05ecef48e82961f1a2be6544145ea26136f69dddda4bbbd092f0e4b993", 924455968L),
    };

    public static Spec find(String id) { for (Spec s : MODELS) if (s.id.equals(id)) return s; return null; }
    public static Spec recommended() { return MODELS[1]; }   // the light one first on phones

    /* ---------------- storage ---------------- */
    public static File dir(Context c) { return new File(c.getFilesDir(), "brain/models"); }
    public static File fileFor(Context c, Spec s) { return new File(new File(dir(c), s.id), s.file); }
    private static File partFor(Context c, Spec s) { return new File(new File(dir(c), s.id), s.file + ".part"); }

    /* ---------------- state (persisted in Prefs as JSON) ---------------- */
    public static final String DOWNLOADING = "DOWNLOADING", PAUSED = "PAUSED", VERIFYING = "VERIFYING",
            READY = "READY", CORRUPT = "CORRUPT";

    public interface Listener { void onState(String modelId, String state, long done, long total, String note); }
    private static volatile Listener listener;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static volatile Thread worker;
    private static volatile boolean cancel = false;

    public static void listen(Listener l) { listener = l; }

    public static String stateOf(String id) {
        try { JSONObject all = new JSONObject(Prefs.get("brain_model_state", "{}"));
            return all.optString(id, ""); } catch (Exception e) { return ""; }
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
        final Listener l = listener;
        if (l != null) MAIN.post(() -> l.onState(id, state, done, specBytes(id), note));
    }
    private static long specBytes(String id) { Spec s = find(id); return s == null ? 0 : s.bytes; }

    public static boolean ready(Context c, Spec s) {
        return READY.equals(stateOf(s.id)) && fileFor(c, s).exists() && fileFor(c, s).length() == s.bytes;
    }

    /* ---------------- download (single worker, resumable, cancellable) ---------------- */
    public static synchronized void download(Context c, Spec s) {
        if (worker != null && worker.isAlive()) { Ui.toast("یک دریافت مدل در حال اجراست؛ تا پایان آن صبر کنید"); return; }
        cancel = false;
        putState(s.id, DOWNLOADING, partFor(c, s).length(), "در حال دریافت از مخزن رسمی");
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
            long have = part.exists() ? part.length() : 0;
            HttpURLConnection con = (HttpURLConnection) new URL(s.url).openConnection();
            con.setConnectTimeout(30000); con.setReadTimeout(60000);
            con.setRequestProperty("User-Agent", "SupermarketMobile/4.0");
            if (have > 0) con.setRequestProperty("Range", "bytes=" + have + "-");
            int code = con.getResponseCode();
            if (code == 416) { // the .part is already the whole file
                part.delete(); have = 0;
                con = (HttpURLConnection) new URL(s.url).openConnection();
                con.setConnectTimeout(30000); con.setReadTimeout(60000);
                con.setRequestProperty("User-Agent", "SupermarketMobile/4.0");
                code = con.getResponseCode();
            }
            if (code != 200 && code != 206) throw new IllegalStateException("HTTP " + code);
            long total = s.bytes;
            if (code == 200 && have > 0) { part.delete(); have = 0; }   // no resume support → restart clean
            InputStream in = con.getInputStream();
            OutputStream out = new FileOutputStream(part, have > 0 && code == 206);
            byte[] buf = new byte[256 * 1024];
            long done = have; long lastUi = 0;
            int n;
            while ((n = in.read(buf)) > 0) {
                if (cancel) break;
                out.write(buf, 0, n);
                done += n;
                if (System.currentTimeMillis() - lastUi > 400) {
                    lastUi = System.currentTimeMillis();
                    putState(s.id, DOWNLOADING, done, total > 0 ? percent(done, total) : "");
                }
            }
            out.flush(); out.close(); in.close();
            if (cancel) { putState(s.id, PAUSED, done, "متوقف شد — با «ادامه» از همان‌جا برمی‌گردد"); return; }

            // §38: nothing is READY without a full sha256 pass over the file
            putState(s.id, VERIFYING, done, "در حال تأیید هش فایل…");
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            try (InputStream fin = new FileInputStream(part)) {
                long hashed = 0; lastUi = 0;
                while ((n = fin.read(buf)) > 0) {
                    if (cancel) break;
                    md.update(buf, 0, n); hashed += n;
                    if (System.currentTimeMillis() - lastUi > 400) {
                        lastUi = System.currentTimeMillis();
                        putState(s.id, VERIFYING, hashed, "تأیید " + percent(hashed, done));
                    }
                }
            }
            if (cancel) { putState(s.id, PAUSED, done, "متوقف شد"); return; }
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
        }
    }

    private static String percent(long done, long total) {
        if (total <= 0) return "";
        return Ui.num(Math.round(done * 100.0 / total)) + "٪";
    }
}
