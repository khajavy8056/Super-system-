package ir.khajavy.supermarket;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;

/**
 * v2.2 — soft sound effects for the phone, mirroring the PC's frontend/sfx.js.
 * Tones are synthesized (sine/triangle with a gentle envelope), so no audio files
 * are bundled and the Gradle-less build stays tiny. Every level is deliberately
 * low: a shop till must not be loud. Prefs "sfx"="0" disables.
 *
 *  success — sale completed / activation     add   — item added to cart / scan hit
 *  error   — soft low double-tone            note  — ordinary notification
 *  alert   — gentle two-note chime           void  — invoice voided (descending)
 *  hold / resume — invoice parked / restored welcome — short instrumental on start
 */
public final class Sfx {
    private Sfx() {}
    private static final int SR = 22050;
    private static final double C4 = 261.63, E4 = 329.63, F4 = 349.23, G4 = 392, A4 = 440, C5 = 523.25, D5 = 587.33, E5 = 659.25, F5 = 698.46, G5 = 783.99, A5 = 880, B5 = 987.77, C6 = 1046.5;

    public static boolean enabled() { return !"0".equals(Prefs.get("sfx", "1")); }
    public static float volume() { try { return Math.max(0f, Math.min(1f, Float.parseFloat(Prefs.get("sfx_vol", "0.35")))); } catch (Exception e) { return 0.35f; } }

    public static void play(String name) {
        if (!enabled()) return;
        Api.bg(() -> { try { render(name); } catch (Throwable ignore) {} });
    }

    /** one note: freq, start (s), duration (s), gain, 0=sine 1=triangle, optional slide target. */
    private static final class N { final double f, t0, d, g, slide; final int type; N(double f, double t0, double d, double g, int type, double slide) { this.f = f; this.t0 = t0; this.d = d; this.g = g; this.type = type; this.slide = slide; } }
    private static N s(double f, double t0, double d, double g) { return new N(f, t0, d, g, 0, 0); }
    private static N t(double f, double t0, double d, double g) { return new N(f, t0, d, g, 1, 0); }
    private static N sl(double f, double t0, double d, double g, double to) { return new N(f, t0, d, g, 1, to); }

    static N[] pattern(String name) {
        switch (name) {
            case "success": return new N[]{t(C5, 0, .22, .16), t(E5, .09, .22, .16), t(G5, .18, .22, .16), t(C6, .27, .22, .16), s(G5 * 2, .36, .35, .07)};
            case "add": return new N[]{t(880, 0, .06, .05), s(1320, .045, .09, .09)};
            case "error": return new N[]{sl(260, 0, .14, .11, 220), sl(230, .17, .2, .11, 180)};
            case "alert": return new N[]{s(B5, 0, .18, .12), s(E5 * 2, .16, .3, .1)};
            case "void": return new N[]{t(G5, 0, .12, .12), t(E5, .12, .12, .12), t(C5, .24, .3, .12), s(C4, .24, .4, .07)};
            case "hold": return new N[]{s(A5, 0, .09, .09), s(E5, .09, .16, .09)};
            case "resume": return new N[]{s(E5, 0, .09, .09), s(A5, .09, .18, .09)};
            case "welcome": return new N[]{t(C5, 0, .5, .13), t(E5, .18, .5, .13), t(G5, .36, .5, .13), t(C6, .54, .55, .13), t(B5, .9, .5, .12), t(G5, 1.08, .5, .12), t(A5, 1.35, .5, .12), t(C6, 1.53, .7, .12), s(C4, 0, .9, .08), s(G4, .9, .9, .08), s(A4, 1.35, .9, .08), s(F4, 1.98, .9, .08), t(C6, 2.3, 1.0, .11), s(E5, 2.3, 1.0, .05)};
            case "note": default: return new N[]{s(A5, 0, .16, .09), s(A5 * 1.5, .05, .2, .04)};
        }
    }

    private static void render(String name) {
        N[] ns = pattern(name); double end = 0; for (N n : ns) end = Math.max(end, n.t0 + n.d);
        int len = (int) ((end + 0.05) * SR); float[] buf = new float[len]; float vol = volume();
        for (N n : ns) {
            int a = (int) (n.t0 * SR), b = Math.min(len, (int) ((n.t0 + n.d) * SR)); double ph = 0;
            for (int i = a; i < b; i++) {
                double p = (i - a) / (double) (b - a); double f = n.slide > 0 ? n.f * Math.pow(n.slide / n.f, p) : n.f;
                ph += 2 * Math.PI * f / SR; double x = n.type == 1 ? (2 / Math.PI) * Math.asin(Math.sin(ph)) : Math.sin(ph);
                double env = p < 0.06 ? p / 0.06 : Math.pow(1 - (p - 0.06) / 0.94, 2.2);
                buf[i] += (float) (x * env * n.g);
            }
        }
        // soft clip + one-pole low-pass so nothing sounds harsh
        float prev = 0; for (int i = 0; i < len; i++) { float v = buf[i] * vol * 1.6f; v = (float) Math.tanh(v); prev = prev + 0.35f * (v - prev); buf[i] = prev; }
        AudioTrack tr = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                .setAudioFormat(new AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_FLOAT).setSampleRate(SR).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                .setBufferSizeInBytes(len * 4).setTransferMode(AudioTrack.MODE_STATIC).build();
        tr.write(buf, 0, len, AudioTrack.WRITE_BLOCKING); tr.play();
        try { Thread.sleep((long) ((end + 0.15) * 1000)); } catch (InterruptedException ignore) {}
        tr.release();
    }
}
