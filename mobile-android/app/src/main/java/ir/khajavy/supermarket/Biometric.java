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

    public static boolean available(Context c) {
        try {
            if (Build.VERSION.SDK_INT >= 29) { android.hardware.biometrics.BiometricManager bm = c.getSystemService(android.hardware.biometrics.BiometricManager.class); return bm != null && bm.canAuthenticate() == android.hardware.biometrics.BiometricManager.BIOMETRIC_SUCCESS; }
            if (Build.VERSION.SDK_INT >= 28) { android.hardware.fingerprint.FingerprintManager fm = (android.hardware.fingerprint.FingerprintManager) c.getSystemService(Context.FINGERPRINT_SERVICE); return fm != null && fm.isHardwareDetected() && fm.hasEnrolledFingerprints(); }
            KeyguardManager km = (KeyguardManager) c.getSystemService(Context.KEYGUARD_SERVICE); return km != null && km.isDeviceSecure();
        } catch (Throwable t) { return false; }
    }
    public static boolean lockEnabled() { return "1".equals(Prefs.get("bio_lock", "")); }
    public static boolean loginEnabled() { return "1".equals(Prefs.get("bio_login", "")); }
    public static boolean lockDue() { return lockEnabled() && System.currentTimeMillis() - lastUnlock > 30_000L; }

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
