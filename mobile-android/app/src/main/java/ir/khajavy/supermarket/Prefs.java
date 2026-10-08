package ir.khajavy.supermarket;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Persisted pairing settings; bearer/OAuth credentials are AES-GCM sealed with an Android Keystore key. */
public final class Prefs {
    private static final String FILE = "supermarket";
    private static final String KEY_ALIAS = "ir.khajavy.supermarket.prefs.v1";
    private static final String SEALED = "enc1:";

    private Prefs() {}
    private static Context APP;
    public static void init(Context c) { APP = c.getApplicationContext(); }
    public static String deviceIdStatic() { return APP == null ? null : deviceId(APP); }

    private static boolean secret(String k) {
        return "device_token".equals(k) || "bio_token".equals(k) || "cloud_json".equals(k)
                || "cloud_tok".equals(k) || "link_key".equals(k) || "relay_json".equals(k)
                || "offline_users".equals(k);
    }
    public static String get(String k, String def) { return APP == null ? def : read(p(APP), k, def); }
    public static void set(String k, String v) { if (APP != null) write(p(APP), k, v); }

    private static String read(SharedPreferences prefs, String key, String def) {
        String value = prefs.getString(key, def);
        if (value == null || !secret(key)) return value;
        if (value.startsWith(SEALED)) return unseal(key, value);
        // One-time migration of prior plaintext preferences. Do not return a credential from
        // a partially-written/corrupt ciphertext; authentication must fail closed instead.
        write(prefs, key, value);
        return value;
    }
    private static void write(SharedPreferences prefs, String key, String value) {
        if (value == null) { prefs.edit().remove(key).apply(); return; }
        String stored = secret(key) ? seal(key, value) : value;
        prefs.edit().putString(key, stored).apply();
    }

    private static SecretKey secretKey() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore"); ks.load(null);
        java.security.Key existing = ks.getKey(KEY_ALIAS, null);
        if (existing instanceof SecretKey) return (SecretKey) existing;
        KeyGenerator gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        gen.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build());
        return gen.generateKey();
    }
    private static String seal(String name, String plain) {
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, secretKey());
            cipher.updateAAD(name.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            byte[] encrypted = cipher.doFinal(plain.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return SEALED + Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + ":"
                    + Base64.encodeToString(encrypted, Base64.NO_WRAP);
        } catch (Exception e) {
            throw new IllegalStateException("Cannot protect local credential preference " + name, e);
        }
    }
    private static String unseal(String name, String value) {
        try {
            String[] parts = value.split(":", 3);
            if (parts.length != 3 || !SEALED.substring(0, SEALED.length() - 1).equals(parts[0]))
                throw new IllegalArgumentException("Malformed protected preference");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, secretKey(), new GCMParameterSpec(128, Base64.decode(parts[1], Base64.NO_WRAP)));
            cipher.updateAAD(name.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return new String(cipher.doFinal(Base64.decode(parts[2], Base64.NO_WRAP)), java.nio.charset.StandardCharsets.UTF_8);
        } catch (Exception e) {
            throw new IllegalStateException("Cannot decrypt local credential preference " + name, e);
        }
    }

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
    public static String deviceToken(Context ctx) { return read(p(ctx), "device_token", null); }
    public static String deviceId(Context ctx) { return p(ctx).getString("device_id", null); }
    public static String storeName(Context ctx) { return p(ctx).getString("store_name", null); }

    public static void save(Context ctx, String url, String token, String store, String deviceId) {
        SharedPreferences prefs = p(ctx);
        prefs.edit().putString("server_url", url).putString("store_name", store).putString("device_id", deviceId).apply();
        write(prefs, "device_token", token);
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
