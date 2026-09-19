package ir.khajavy.supermarket;

import android.content.Context;
import android.content.SharedPreferences;

/** Persisted pairing (§259): server address on the shop LAN + the device token minted by the PC. */
public final class Prefs {
    private static final String FILE = "supermarket";

    private Prefs() {}
    private static Context APP;
    public static void init(Context c) { APP = c.getApplicationContext(); }
    public static String deviceIdStatic() { return APP == null ? null : deviceId(APP); }
    public static String get(String k, String def) { return APP == null ? def : p(APP).getString(k, def); }
    public static void set(String k, String v) { if (APP != null) p(APP).edit().putString(k, v).apply(); }

    private static SharedPreferences p(Context c) { return c.getSharedPreferences(FILE, Context.MODE_PRIVATE); }

    /**
     * v3.5.11 — a seed for the device identity that cannot move under us.
     *
     * The identity used to be derived from {@code device_id}, which is minted by the shop PC (or
     * invented on the spot) and therefore changes whenever the phone pairs or signs in again. Two
     * bugs came out of that: the licence server counted a new device on every change until it
     * answered MAX_DEVICES_REACHED, and the standalone admin password — hashed with that same
     * identity — stopped verifying, so a correct password was reported as wrong after the idle
     * lock. ANDROID_ID needs no permission, is fixed per (device, signing key, user), and is
     * written to prefs the first time it is read, so even an OS that one day returned something
     * else could not move a shop's identity.
     */
    public static String hwidSeed() {
        String s = get("hwid_seed", "");
        if (!s.isEmpty()) return s;
        String v = "";
        try {
            if (APP != null) v = android.provider.Settings.Secure.getString(
                    APP.getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
        } catch (Exception ignore) {}
        // that literal is the value broken ROMs and emulators all report; treat it as "unknown"
        if (v == null || v.isEmpty() || "9774d56d682e549c".equals(v)) v = "rnd-" + java.util.UUID.randomUUID();
        set("hwid_seed", v);
        return v;
    }

    public static String serverUrl(Context ctx) { return p(ctx).getString("server_url", null); }
    public static String deviceToken(Context ctx) { return p(ctx).getString("device_token", null); }
    public static String deviceId(Context ctx) { return p(ctx).getString("device_id", null); }
    public static String storeName(Context ctx) { return p(ctx).getString("store_name", null); }

    public static void save(Context ctx, String url, String token, String store, String deviceId) {
        p(ctx).edit().putString("server_url", url).putString("device_token", token)
                .putString("store_name", store).putString("device_id", deviceId).apply();
    }

    public static void clear(Context ctx) { p(ctx).edit().clear().apply(); }

    /** Normalises user input: adds http://, strips trailing slashes. */
    public static String normalise(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) return "";
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }
}
