package ir.khajavy.supermarket;

import android.content.Context;
import android.content.SharedPreferences;

/** Persisted pairing (§259): server address on the shop LAN + the device token minted by the PC. */
public final class Prefs {
    private static final String FILE = "supermarket";

    private Prefs() {}

    private static SharedPreferences p(Context c) { return c.getSharedPreferences(FILE, Context.MODE_PRIVATE); }

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
