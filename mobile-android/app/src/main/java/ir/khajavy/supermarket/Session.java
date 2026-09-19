package ir.khajavy.supermarket;

/** v2.4 — login session on the phone: required on every cold start after logout/expiry,
 *  and automatically ended after IDLE_MS (30 minutes) without any user interaction. */
public final class Session {
    private Session() {}
    public static final long IDLE_MS = 30L * 60L * 1000L;
    static long idleMs() { try { long m = Long.parseLong(Local.setting("security.idle_minutes", "30")); return Math.max(1, m) * 60_000L; } catch (Exception e) { return IDLE_MS; } }
    public static void start() { Prefs.set("session_active", "1"); touch(); }
    public static void touch() { Prefs.set("session_last", String.valueOf(System.currentTimeMillis())); }
    public static void end() { Prefs.set("session_active", ""); Prefs.set("session_last", ""); }
    public static boolean expired() {
        if (!"1".equals(Prefs.get("session_active", ""))) return true;
        long last; try { last = Long.parseLong(Prefs.get("session_last", "0")); } catch (Exception e) { last = 0; }
        return System.currentTimeMillis() - last > idleMs();
    }
}
