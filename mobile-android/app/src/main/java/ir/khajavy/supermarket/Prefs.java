package ir.khajavy.supermarket;

import android.content.Context;
import android.content.SharedPreferences;

/** Persisted server address (§259: the phone talks to the shop server over the LAN). */
public final class Prefs {
    private static final String FILE = "supermarket";
    private static final String KEY_URL = "server_url";

    private Prefs() {}

    public static String serverUrl(Context ctx) {
        SharedPreferences p = ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE);
        return p.getString(KEY_URL, null);
    }

    public static void setServerUrl(Context ctx, String url) {
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putString(KEY_URL, url).apply();
    }

    /** Normalises user input: adds http://, strips trailing slashes. */
    public static String normalise(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) return "";
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }
}
