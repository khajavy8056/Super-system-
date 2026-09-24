package ir.khajavy.supermarket;

import android.app.ActivityManager;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * v4.1 — the on-device inference engine for the Business Brain.
 *
 * The phone now runs the SAME engine the PC runs: llama.cpp's llama-server
 * (same upstream tag b6283 as the Windows installer bundles), started as a
 * subprocess and spoken to over HTTP — the exact architecture of
 * backend/app/services/business_brain/runtime.py, ported faithfully:
 * same launch flags, same /health wait, same /v1/chat/completions body,
 * same "fast" sampling preset, same reasoning-stripping. The model FILE is
 * byte-identical too (same registry pins, same sha256 gate in BrainModel),
 * so paired or standalone this is ONE system with ONE model — never two
 * different brains:
 *
 *  - PAIRED (the shop PC is reachable): the PC's brain answers — the full
 *    deterministic tool pipeline over the live shop data. The local engine is
 *    not used for answers, so the two never diverge.
 *  - STANDALONE (no PC): this engine + the verified model file answer ON the
 *    phone, clearly labelled as local, WITHOUT live shop data — and it says so
 *    instead of inventing numbers.
 *
 * The binary ships inside the APK as lib/arm64-v8a/libllamaserver.so (a static
 * aarch64 build; Android extracts it next to the app and allows executing it
 * from there). If it is missing the app says so honestly and nothing breaks.
 */
public final class BrainEngine {
    private BrainEngine() {}

    /** Same upstream llama.cpp tag as the PC installer (prepare_windows_installer.py LLAMA_TAG). */
    public static final String ENGINE_TAG = "b6283";
    /** The phone's engine port. The PC uses 8080; one port in one place each. */
    public static final int PORT = 8081;
    /** Context window on the phone: the product's own rule — smaller devices get less context. */
    public static final int CONTEXT = 2048;
    /** v4.3.1 — 924 MB into a phone's RAM can take a while on cheap storage;
     *  240 s with live progress notes instead of 120 s of silence. */
    private static final long LOAD_TIMEOUT_MS = 240_000;
    /** v4.3.1 — the last lines llama-server printed (the REAL reason on
     *  failure — previously the output was discarded, so «کار نمی‌کنه» had no
     *  explanation). */
    private static final java.util.ArrayDeque<String> TAIL = new java.util.ArrayDeque<>();

    /* ---------------- the binary ---------------- */
    public static File bin(Context c) {
        try { return new File(c.getApplicationInfo().nativeLibraryDir, "libllamaserver.so"); }
        catch (Exception e) { return new File("/dev/null"); }
    }
    public static boolean installed(Context c) { return bin(c).exists(); }

    /* ---------------- state (persisted, honest) ---------------- */
    public static final String STOPPED = "STOPPED", STARTING = "STARTING", RUNNING = "RUNNING", FAILED = "FAILED";
    public interface Listener { void onEngine(String state, String note); }
    private static volatile Listener listener;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    public static void listen(Listener l) { listener = l; }

    public static String state() { return Prefs.get("brain_engine_state", STOPPED); }
    public static String note() { return Prefs.get("brain_engine_note", ""); }
    /** v4.3.1 — the engine's own last words (English is fine: it is for diagnosis). */
    public static String tail() {
        synchronized (TAIL) { return String.join("\n", TAIL); }
    }
    private static void pushTail(String line) {
        if (line == null) return;
        synchronized (TAIL) {
            TAIL.addLast(line.trim());
            while (TAIL.size() > 25) TAIL.removeFirst();
        }
    }
    private static String lastTail() {
        synchronized (TAIL) { return TAIL.isEmpty() ? "" : TAIL.getLast(); }
    }

    private static void putState(String state, String note) {
        Prefs.set("brain_engine_state", state);
        Prefs.set("brain_engine_note", note);
        final Listener l = listener;
        if (l != null) MAIN.post(() -> l.onEngine(state, note));
    }

    /* ---------------- the process (mirrors runtime.py LlamaCppProvider) ---------------- */
    private static volatile Process proc;
    private static volatile Thread starter;

    public static synchronized boolean running() {
        return proc != null && proc.isAlive() && healthy(1500);
    }

    public static boolean usableWith(Context c, BrainModel.Spec s) {
        return installed(c) && BrainModel.ready(c, s);
    }

    /** Total RAM in MB — the same fit rule the backend registry applies. */
    public static long totalRamMb(Context c) {
        try {
            ActivityManager.MemoryInfo mi = new ActivityManager.MemoryInfo();
            ActivityManager am = (ActivityManager) c.getSystemService(Context.ACTIVITY_SERVICE);
            am.getMemoryInfo(mi);
            return mi.totalMem / (1024 * 1024);
        } catch (Exception e) { return 0; }
    }

    public static boolean fitsRam(Context c, BrainModel.Spec s) { return totalRamMb(c) >= s.minRamMb; }

    /** v4.3.2 — the registry's minRamMb is a PC-era conservative number (it exists
     *  so a "4 GB" Windows machine that reports 3.8 GB still installs). Applied to
     *  PHONES it wrongly refused to even TRY on 2-3 GB devices — the owner's
     *  «مدل روشن نمیشه» case. What the engine actually needs on a phone:
     *  the model weights (mmap'd) + ~400 MB overhead. Attempt when it fits. */
    public static long neededRamMb(BrainModel.Spec s) { return s.bytes / (1024 * 1024) + 400; }
    /** true = worth starting (the honest attempt); false = physically impossible. */
    public static boolean canRun(Context c, BrainModel.Spec s) { return totalRamMb(c) >= neededRamMb(s); }
    /** tight RAM → launch with half the context so the KV cache fits comfortably. */
    public static boolean tightRam(Context c, BrainModel.Spec s) { return totalRamMb(c) < s.bytes / (1024 * 1024) * 2 + 400; }

    /** Start llama-server with a READY model. Returns false (with an honest note) if it cannot. */
    public static synchronized void start(final Context c, final BrainModel.Spec s) {
        if (running()) { putState(RUNNING, "موتور محلی از قبل روشن است"); return; }
        // v4.3.1 — a llama-server that survived the app being closed (previous
        // run) still owns port 8081: ADOPT it instead of failing to bind.
        if (healthy(1200)) { putState(RUNNING, "موتور محلی (نمونهٔ قبلی) از قبل روشن است و پذیرفته شد"); return; }
        if (!installed(c)) {
            putState(FAILED, "موتور استنتاج در این نصب موجود نیست (libllamaserver.so)");
            return;
        }
        if (!BrainModel.ready(c, s)) {
            putState(FAILED, "فایل مدل تأییدشده روی گوشی نیست — اول آن را از تب «مدل محلی» دریافت کنید");
            return;
        }
        long ram = totalRamMb(c), need = neededRamMb(s);
        if (ram < need) {
            // v4.3.2 — a REFUSAL with real numbers and the honest alternative
            putState(FAILED, "حافظهٔ گوشی برای اجرای «" + s.label() + "» کافی نیست — رم گوشی: "
                    + Ui.num(ram) + " مگابایت، لازم: حدود " + Ui.num(need)
                    + " مگابایت. مغز فروشگاه روی رایانهٔ وصل‌شده کامل در دسترس است.");
            return;
        }
        final boolean tight = tightRam(c, s);
        final int ctx = tight ? 1024 : CONTEXT;   // v4.3.2 — half context in economy mode
        if (starter != null && starter.isAlive()) return;   // already starting
        int threads = Math.max(1, Runtime.getRuntime().availableProcessors() - 1);
        putState(STARTING, "در حال بارگذاری " + s.label() + " روی گوشی… (اولین بار چند لحظه طول می‌کشد"
                + (tight ? " — حالت اقتصادی رم با زمینهٔ متن کوچک‌تر" : "") + ")");
        starter = new Thread(() -> {
            try {
                File model = BrainModel.fileFor(c, s);
                ProcessBuilder pb = new ProcessBuilder(
                        bin(c).getAbsolutePath(),
                        "-m", model.getAbsolutePath(),
                        "--host", "127.0.0.1", "--port", String.valueOf(PORT),
                        "-c", String.valueOf(ctx),
                        "-t", String.valueOf(threads),
                        "--no-webui");
                pb.redirectErrorStream(true);
                proc = pb.start();
                // v4.3.1 — keep the last lines instead of discarding them: on
                // failure the manager sees the REAL reason, not a guess.
                Thread drain = new Thread(() -> {
                    try (BufferedReader r = new BufferedReader(new InputStreamReader(proc.getInputStream()))) {
                        String ln;
                        while ((ln = r.readLine()) != null) pushTail(ln);
                    } catch (Exception ignore) {}
                }, "brain-engine-drain");
                drain.setDaemon(true);
                drain.start();

                long deadline = System.currentTimeMillis() + LOAD_TIMEOUT_MS;
                long lastNote = 0;
                while (System.currentTimeMillis() < deadline) {
                    if (healthy(1500)) {
                        putState(RUNNING, "موتور محلی روشن است — " + s.label() + " (llama.cpp " + ENGINE_TAG + ")");
                        return;
                    }
                    if (proc != null && !proc.isAlive()) {
                        String why = lastTail();
                        putState(FAILED, "موتور بسته شد — رم گوشی: " + Ui.num(ram)
                                + " مگابایت، مدل: " + Ui.num(s.bytes / (1024 * 1024))
                                + " مگابایت؛ اگر اندروید آن را بست (کمبود رم)، از مغز روی رایانه استفاده کنید"
                                + (why.isEmpty() ? "" : " — آخرین پیام موتور: " + why));
                        proc = null;
                        return;
                    }
                    // v4.3.1 — live progress so a slow load never looks dead
                    if (System.currentTimeMillis() - lastNote > 10_000) {
                        lastNote = System.currentTimeMillis();
                        long secs = (LOAD_TIMEOUT_MS - (deadline - System.currentTimeMillis())) / 1000;
                        putState(STARTING, "در حال بارگذاری مدل روی گوشی… " + Ui.num(secs) + " ثانیه"
                                + (lastTail().isEmpty() ? "" : " — آخرین پیام موتور: " + lastTail()));
                    }
                    try { Thread.sleep(1000); } catch (InterruptedException ie) { return; }
                }
                putState(FAILED, "مدل در بازهٔ مجاز بارگذاری نشد"
                        + (lastTail().isEmpty() ? "" : " — آخرین پیام موتور: " + lastTail()));
                stop();
            } catch (Exception e) {
                putState(FAILED, "روشن‌کردن موتور ناموفق بود: " + e.getMessage());
                proc = null;
            }
        }, "brain-engine-start");
        starter.start();
    }

    public static synchronized void stop() {
        Process p = proc;
        proc = null;
        if (p != null) {
            p.destroy();
            try {
                if (!p.waitFor(3, java.util.concurrent.TimeUnit.SECONDS)) p.destroyForcibly();
            } catch (Exception ignore) {}
        }
        putState(STOPPED, "موتور محلی خاموش است");
    }

    /* ---------------- HTTP (same contract as the PC's runtime.py) ---------------- */
    static boolean healthy(int timeoutMs) {
        try {
            HttpURLConnection con = (HttpURLConnection) new URL("http://127.0.0.1:" + PORT + "/health").openConnection();
            con.setConnectTimeout(timeoutMs); con.setReadTimeout(timeoutMs);
            int code = con.getResponseCode();
            con.disconnect();
            return code == 200;
        } catch (Exception e) { return false; }
    }

    /**
     * One chat turn against the local engine. Messages is a JSONArray of
     * {"role":"system|user|assistant","content":…}. Returns the cleaned answer
     * text, or null with a note when the engine cannot answer.
     */
    public static String chat(JSONArray messages, int maxTokens) {
        try {
            JSONObject body = new JSONObject();
            body.put("messages", messages);
            body.put("max_tokens", maxTokens);
            body.put("stream", false);
            // the "fast" preset from backend prompts.py §33 — identical numbers
            body.put("temperature", 0.7); body.put("top_p", 0.8);
            body.put("top_k", 20); body.put("min_p", 0.0);
            body.put("chat_template_kwargs", new JSONObject().put("enable_thinking", false));

            HttpURLConnection con = (HttpURLConnection)
                    new URL("http://127.0.0.1:" + PORT + "/v1/chat/completions").openConnection();
            con.setConnectTimeout(5000); con.setReadTimeout(180000);
            con.setRequestMethod("POST");
            con.setRequestProperty("Content-Type", "application/json");
            con.setDoOutput(true);
            byte[] data = body.toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream out = con.getOutputStream()) { out.write(data); }
            int code = con.getResponseCode();
            if (code != 200) return null;
            java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
            try (InputStream in = con.getInputStream()) {
                byte[] b = new byte[8192]; int n;
                while ((n = in.read(b)) > 0) buf.write(b, 0, n);
            }
            con.disconnect();
            JSONObject resp = new JSONObject(buf.toString("UTF-8"));
            String content = resp.getJSONArray("choices").getJSONObject(0)
                    .getJSONObject("message").optString("content", "");
            return clean(content);
        } catch (Exception e) {
            return null;
        }
    }

    /** Port of the backend's reasoning-strip: <think>…</think> and stray markers never reach the manager. */
    static String clean(String s) {
        if (s == null) return "";
        String out = s;
        int a;
        while ((a = out.indexOf("<think")) >= 0) {
            int b = out.indexOf("</think>", a);
            out = b >= 0 ? out.substring(0, a) + out.substring(b + 8) : out.substring(0, a);
        }
        out = out.replace("<|im_start|>", "").replace("<|im_end|>", "").replace("```json", "").trim();
        return out.trim();
    }

    /* ---------------- the local-mode persona (a faithful port of prompts.py) ---------------- */
    public static final String SYSTEM_PROMPT =
            "تو «مغز فروشگاه سوپری‌من» هستی — هوش محلی و اختصاصی فروشگاه که روی همین دستگاه اجرا می‌شود و به هیچ سرویس ابری وصل نیست. "
          + "سازندهٔ تو «محمد صدیق خواجوی» است؛ اگر پرسیدند تو کی هستی، چی هستی یا چه کارهایی می‌توانی انجام دهی، صادقانه و روان معرفی کن.\n\n"
          + "تو «مغز کسب‌وکار» یک سوپرمارکت محلی در ایران هستی و با صاحب فروشگاه حرف می‌زنی.\n\n"
          + "قواعد قطعی:\n"
          + "۱) هیچ عددی از خودت نساز. فقط اعدادی را بنویس که در همین گفت‌وگو به تو داده شده است.\n"
          + "۲) لحن: ساده، محترمانه، حرفه‌ای و کوتاه. نه خودمانی، نه اداری و خشک. شوخی و تعریف بی‌مورد ممنوع.\n"
          + "۳) خروجی حداکثر چهار بخش کوتاه: وضعیت / دلیل / پیشنهاد / اقدام بعدی. جزئیات فنی را وارد نکن.\n"
          + "۴) اگر وضعیت نیازی به اقدام ندارد، صریح بگو «کاری لازم نیست» — پیشنهاد الکی نساز.\n"
          + "۵) سیاست‌های صاحب فروشگاه (اگر در گفت‌وگو آمده) بر نظر تو اولویت دارند.\n"
          + "۶) ساختار داخلی و نام فایل را برای مدیر ننویس.\n\n"
          + "این گفت‌وگو در «حالت محلی گوشی» انجام می‌شود: به داده‌های زندهٔ فروشگاه و ابزارها دسترسی نداری. "
          + "اگر سؤال به اعداد امروز فروشگاه نیاز دارد، صریح همان را بگو و پیشنهاد بده که وقتی رایانهٔ فروشگاه "
          + "در دسترس است، همان سؤال دوباره پرسیده شود.\n\n"
          + "قالب پیشنهادی پاسخ:\nوضعیت: ...\nدلیل: ...\nپیشنهاد: ...\nاقدام بعدی: ...\n";
}
