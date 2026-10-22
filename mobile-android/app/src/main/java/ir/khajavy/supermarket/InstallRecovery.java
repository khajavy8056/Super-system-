package ir.khajavy.supermarket;

/**
 * One-time migration for installations upgraded from builds that held the first-run
 * wizard behind a timed foreground-service screen. Database/catalogue preparation is
 * now local-first: the schema is opened before entering the app and the optional seed
 * catalogue is imported asynchronously by {@link Db#bootstrap(android.content.Context)}.
 */
final class InstallRecovery {
    private InstallRecovery() {}

    /**
     * Release a persisted legacy install gate. The old timer did not represent required
     * work; it could leave a completed store on a loading screen for 45 minutes. A
     * non-empty install_t0 is written only after the wizard has saved the local licence,
     * store profile and administrator account, so it is safe to open the app and let the
     * normal background bootstrap resume any interrupted, chunked catalogue import.
     */
    static boolean releaseLegacyDelay() {
        String startedAt = Prefs.get("install_t0", "");
        String serverUrl = Prefs.get("server_url", "");
        if (startedAt == null || startedAt.isEmpty()) return false;
        if (!"own".equals(Prefs.get("lic_mode", "")) || !serverUrl.contains("standalone.invalid")) return false;

        Prefs.set("setup_done", "1");
        Prefs.set("first_loading_done", "1");
        Prefs.set("install_work_done", "1");
        Prefs.set("install_t0", "");
        Prefs.set("install_total", "");
        android.util.Log.i("InstallRecovery", "Released legacy timed first-run gate; local bootstrap will resume in background");
        return true;
    }
}
