package ir.khajavy.supermarket;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;

import java.util.ArrayList;
import java.util.Locale;

/**
 * v4.3 — VOICE conversation for the Business Brain (owner's request):
 * «مدل رو از همین مدلی که فعلاً هست نمی‌خوام سنگین‌تر بشه — صوتی باشه که
 * هم پیام صوتی رو درک کنم هم صوتی صحبت کنم؛ همون متن رو صوتی بخونه».
 *
 * The rule that shapes this class: the AI MODEL STAYS EXACTLY THE SAME (the
 * ~1 GB «مدل تخصصی سوپری‌من» — no heavier model, no second model). Voice is
 * pure INPUT/OUTPUT around it, built from what the device already has, so
 * nothing new is downloaded:
 *
 *  • ears  = the system speech recognizer (fa-IR, prefers offline) — what
 *    Telegram/keyboard dictation use. Zero app weight.
 *  • mouth = the system text-to-speech engine reading THE SAME answer text
 *    aloud (not a different generated voice — the owner's words: «همون متن
 *    به صورت صوتی می‌خونه»).
 *
 * Honesty rules (mirrored from the rest of the product):
 *  • if the device has no Persian TTS voice, we SAY so in Persian with the
 *    exact setting to fix it — never a silent failure;
 *  • if speech recognition is unavailable, we say that too;
 *  • nothing is recorded, stored or sent anywhere — recognition results go
 *    straight into the chat input as if typed.
 */
public final class BrainVoice {
    private BrainVoice() {}

    /** what the recognizer understood (runs on the UI thread). */
    public interface OnHeard { void onHeard(String text); }
    /** listening state for the mic button's label. */
    public interface ListenUi { void onListening(boolean on); }

    public static final int REQ_MIC = 78;

    /* ================= mouth: text-to-speech ================= */

    private static TextToSpeech tts;
    /** setLanguage() result — >= 0 means a Persian voice exists on this device. */
    private static int langState = Integer.MIN_VALUE;

    public static synchronized void initTts(Context c) {
        if (tts != null) return;
        try {
            Context app = c.getApplicationContext();
            tts = new TextToSpeech(app, status -> {
                if (status != TextToSpeech.SUCCESS) { langState = -1; return; }
                try { langState = tts.setLanguage(new Locale("fa", "IR")); }
                catch (Exception e) { langState = -2; }
            });
        } catch (Exception e) { tts = null; langState = -2; }
    }

    /** true when the device answered with a usable Persian voice. */
    public static boolean voiceReady() { return tts != null && langState >= 0; }

    /** honest Persian note when there is no Persian voice installed. */
    public static String voiceNote() {
        return "صدای فارسی روی این دستگاه نصب نیست — از تنظیمات گوشی (زبان و ورودی ← خروجی تبدیل متن به گفتار) صدای فارسی را نصب یا فعال کنید تا خواندن صوتی کار کند.";
    }

    /** Read the answer aloud — the SAME text the user just read (owner's rule). */
    public static void speak(Context c, String text, Runnable onDone) {
        initTts(c);
        if (tts == null || text == null || text.trim().isEmpty()) { if (onDone != null) onDone.run(); return; }
        if (!voiceReady()) { Ui.toast(voiceNote()); if (onDone != null) onDone.run(); return; }
        try {
            tts.setLanguage(new Locale("fa", "IR"));
            tts.setSpeechRate(1f);
            if (onDone != null) {
                final String id = "brain_" + System.currentTimeMillis();
                final Handler main = new Handler(Looper.getMainLooper());
                tts.setOnUtteranceProgressListener(new android.speech.tts.UtteranceProgressListener() {
                    @Override public void onStart(String u) {}
                    @Override public void onDone(String u) { if (u.equals(id)) main.post(onDone); }
                    @Override public void onError(String u) { if (u.equals(id)) main.post(onDone); }
                });
                tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, id);
            } else {
                tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "brain");
            }
        } catch (Exception e) { if (onDone != null) onDone.run(); }
    }

    public static void stopSpeak() {
        try { if (tts != null) tts.stop(); } catch (Exception ignore) {}
    }

    /* ================= voice mode (auto-read + auto-send) ================= */

    /** ON by default — this is the voice conversation the owner asked for:
     *  speak → the question is sent → the answer is read aloud. */
    public static boolean voiceMode() { return !"0".equals(Prefs.get("brain_voice_mode", "1")); }
    public static void setVoiceMode(boolean on) {
        Prefs.set("brain_voice_mode", on ? "1" : "0");
        if (!on) stopSpeak();
    }

    /* ================= ears: speech-to-text ================= */

    private static SpeechRecognizer sr;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    public static boolean listening() { return sr != null; }

    /** Toggle Persian speech recognition. Must be called on the UI thread. */
    public static void toggleListen(final Activity a, final OnHeard cb, final ListenUi ui) {
        if (sr != null) { stopListen(); if (ui != null) ui.onListening(false); return; }
        if (a.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            a.requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO}, REQ_MIC);
            return;
        }
        if (!SpeechRecognizer.isRecognitionAvailable(a)) {
            Ui.toast("شنیدار گفتار روی این گوشی در دسترس نیست");
            return;
        }
        try {
            sr = SpeechRecognizer.createSpeechRecognizer(a);
            sr.setRecognitionListener(new RecognitionListener() {
                @Override public void onReadyForSpeech(Bundle p) { if (ui != null) ui.onListening(true); }
                @Override public void onBeginningOfSpeech() {}
                @Override public void onRmsChanged(float v) {}
                @Override public void onBufferReceived(byte[] b) {}
                @Override public void onEndOfSpeech() {}
                @Override public void onError(int err) {
                    stopListen();
                    if (ui != null) ui.onListening(false);
                    if (err == SpeechRecognizer.ERROR_NO_MATCH || err == SpeechRecognizer.ERROR_SPEECH_TIMEOUT)
                        Ui.toast("صدایی تشخیص داده نشد — دوباره تلاش کنید");
                    else if (err == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS)
                        Ui.toast("اجازهٔ ضبط صدا داده نشده");
                    else
                        Ui.toast("شنیدن صوتی ناموفق بود (کد " + err + ")");
                }
                @Override public void onResults(Bundle p) {
                    stopListen();
                    if (ui != null) ui.onListening(false);
                    try {
                        ArrayList<String> r = p.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                        if (r != null && !r.isEmpty() && cb != null) cb.onHeard(r.get(0));
                    } catch (Exception ignore) {}
                }
                @Override public void onPartialResults(Bundle p) {}
                @Override public void onEvent(int e, Bundle p) {}
            });
            Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fa-IR");
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "fa-IR");
            i.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true);   // offline when the device can
            sr.startListening(i);
        } catch (Exception e) {
            stopListen();
            Ui.toast("شنیدن صوتی در دسترس نیست: " + e.getMessage());
        }
    }

    public static void stopListen() {
        try { if (sr != null) sr.destroy(); } catch (Exception ignore) {}
        sr = null;
    }

    /** Called when the app goes to the background — never talk behind the user's back. */
    public static void onBackground() { stopSpeak(); stopListen(); }
}
