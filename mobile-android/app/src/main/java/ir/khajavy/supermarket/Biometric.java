package ir.khajavy.supermarket;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.hardware.biometrics.BiometricPrompt;
import android.os.Build;
import android.os.CancellationSignal;

/**
 * v2.3 — fingerprint / face unlock for the phone app (no Gradle deps: uses the
 * platform BiometricPrompt on Android 9+, and the device credential screen on
 * older phones). Two uses:
 *  • «قفل با اثر انگشت» (Prefs bio_lock=1): every time the app comes to the
 *    foreground after 30 s away, the user must authenticate.
 *  • quick re-login: after «خروج از حساب» the stored session can be reopened
 *    with a fingerprint instead of typing the password (Prefs bio_login=1).
 */
public final class Biometric {
    private Biometric() {}
    public static final int REQ_KEYGUARD = 61;
    public static volatile long lastUnlock = System.currentTimeMillis();
    /** v2.8.1 — set when the app truly leaves the foreground (user switched app / screen off).
     *  Internal hops (barcode scanner, image picker, share sheet, permission dialogs) do NOT
     *  count: they were re-prompting for the fingerprint after every scan. */
    public static volatile long leftAt = 0L;
    public static volatile boolean internalHop = false;
    public static void touch() { lastUnlock = System.currentTimeMillis(); }
    public static void markInternal() { internalHop = true; }
    public static void onBackground() { if (internalHop) { internalHop = false; return; } leftAt = System.currentTimeMillis(); }

    public static boolean available(Context c) {
        try {
            if (Build.VERSION.SDK_INT >= 29) { android.hardware.biometrics.BiometricManager bm = c.getSystemService(android.hardware.biometrics.BiometricManager.class); return bm != null && bm.canAuthenticate() == android.hardware.biometrics.BiometricManager.BIOMETRIC_SUCCESS; }
            if (Build.VERSION.SDK_INT >= 28) { android.hardware.fingerprint.FingerprintManager fm = (android.hardware.fingerprint.FingerprintManager) c.getSystemService(Context.FINGERPRINT_SERVICE); return fm != null && fm.isHardwareDetected() && fm.hasEnrolledFingerprints(); }
            KeyguardManager km = (KeyguardManager) c.getSystemService(Context.KEYGUARD_SERVICE); return km != null && km.isDeviceSecure();
        } catch (Throwable t) { return false; }
    }
    public static boolean lockEnabled() { return "1".equals(Prefs.get("bio_lock", "")); }
    public static boolean loginEnabled() { return "1".equals(Prefs.get("bio_login", "")); }
    /** Lock only when the app was actually in the background for > 60 s. */
    public static boolean lockDue() {
        if (!lockEnabled() || leftAt == 0L) return false;
        boolean due = System.currentTimeMillis() - leftAt > 60_000L; leftAt = 0L; return due;
    }

    public interface Cb { void done(boolean ok); }

    public static void prompt(Activity a, String title, String sub, Cb cb) {
        if (Build.VERSION.SDK_INT >= 28) {
            try {
                BiometricPrompt.Builder b = new BiometricPrompt.Builder(a).setTitle(title).setSubtitle(sub);
                if (Build.VERSION.SDK_INT >= 30) b.setAllowedAuthenticators(android.hardware.biometrics.BiometricManager.Authenticators.BIOMETRIC_WEAK | android.hardware.biometrics.BiometricManager.Authenticators.DEVICE_CREDENTIAL);
                else if (Build.VERSION.SDK_INT >= 29) b.setDeviceCredentialAllowed(true);
                else b.setNegativeButton("انصراف", a.getMainExecutor(), (d, w) -> cb.done(false));
                b.build().authenticate(new CancellationSignal(), a.getMainExecutor(), new BiometricPrompt.AuthenticationCallback() {
                    @Override public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult r) { lastUnlock = System.currentTimeMillis(); cb.done(true); }
                    @Override public void onAuthenticationError(int code, CharSequence err) { cb.done(false); }
                });
                return;
            } catch (Throwable ignore) {}
        }
        try {
            KeyguardManager km = (KeyguardManager) a.getSystemService(Context.KEYGUARD_SERVICE);
            Intent i = km == null ? null : km.createConfirmDeviceCredentialIntent(title, sub);
            if (i != null) { a.startActivityForResult(i, REQ_KEYGUARD); return; }
        } catch (Throwable ignore) {}
        cb.done(true);  // no secure lock on this phone → nothing to check
    }
}
