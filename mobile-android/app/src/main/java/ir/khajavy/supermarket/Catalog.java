package ir.khajavy.supermarket;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.HashMap;
import java.util.Map;
import java.util.function.BiConsumer;

/**
 * v3.4 — «بانک محصولات» on the phone: ONE file (catalog.pack) built by the Windows app from the shop's own
 * Excel + picture folders. Layout (little-endian):
 *   "SUPERYPK1" | u64 dbLen | sqlite bytes | u64 imgCount | [u16 bcLen | bc | u32 len | bytes]* | index | u64 indexOff
 *   index = [u16 bcLen | bc | u64 off | u32 len]*
 * The pack lives in the app's PRIVATE files dir; pictures are read by seeking into it — no picture file is ever
 * written where the gallery could see it. Works fully offline. Re-import = replace.
 */
public final class Catalog {
    private Catalog() {}
    static final byte[] MAGIC = "SUPERYPK1".getBytes();
    private static volatile Map<String, long[]> INDEX;      // barcode → {offset, length}
    private static volatile File PACK;

    public static File file(Context c) { return new File(c.getFilesDir(), "catalog.pack"); }
    public static boolean present(Context c) { File f = file(c); return f.isFile() && f.length() > 64; }
    public static JSONObject info(Context c) {
        JSONObject j = new JSONObject();
        try { File f = file(c); j.put("exists", present(c)); j.put("bytes", f.isFile() ? f.length() : 0); j.put("at", f.isFile() ? f.lastModified() : 0);
            j.put("items", Db.kv("catalog_items") == null ? 0 : Integer.parseInt(Db.kv("catalog_items"))); j.put("images", index(c).size()); j.put("version", Db.kv("catalog_version")); } catch (Exception ignore) {}
        return j;
    }

    /* ------------------------------------------------------------ images */
    static synchronized Map<String, long[]> index(Context c) {
        File f = file(c);
        if (INDEX != null && PACK != null && PACK.equals(f) && f.lastModified() == lastMod) return INDEX;
        Map<String, long[]> m = new HashMap<>();
        if (f.isFile() && f.length() > 64) {
            try (RandomAccessFile r = new RandomAccessFile(f, "r")) {
                byte[] mg = new byte[MAGIC.length]; r.readFully(mg);
                if (java.util.Arrays.equals(mg, MAGIC)) {
                    r.seek(f.length() - 8); long idxOff = le64(r);
                    r.seek(idxOff); long end = f.length() - 8;
                    while (r.getFilePointer() < end) { int bl = le16(r); byte[] b = new byte[bl]; r.readFully(b); long off = le64(r); long len = le32(r); m.put(new String(b, "UTF-8"), new long[]{off, len}); }
                }
            } catch (Exception e) { android.util.Log.w("Catalog", "index: " + e); }
        }
        INDEX = m; PACK = f; lastMod = f.lastModified(); return m;
    }
    private static long lastMod;
    static void invalidate() { INDEX = null; }
    public static boolean has(Context c, String barcode) { return barcode != null && index(c).containsKey(Db.norm(barcode)); }
    /** Raw picture bytes for a barcode (null when the pack has none). */
    public static byte[] image(Context c, String barcode) {
        long[] e = index(c).get(Db.norm(barcode == null ? "" : barcode)); if (e == null) return null;
        try (RandomAccessFile r = new RandomAccessFile(file(c), "r")) {
            r.seek(e[0]); int bl = le16(r); r.skipBytes(bl); long n = le32(r); if (n != e[1] || n > 20 * 1024 * 1024) return null;
            byte[] b = new byte[(int) n]; r.readFully(b); return b;
        } catch (Exception ex) { return null; }
    }

    /* ------------------------------------------------------------ import */
    public interface Progress { void on(String phase, int done, int total); }

    /** Copy a pack from any stream (file picker / PC download) into private storage and apply it. */
    public static JSONObject importFrom(Context c, InputStream in, long expected, Progress pr) throws Exception {
        File tmp = new File(c.getFilesDir(), "catalog.pack.tmp");
        long got = 0; int last = -1;
        try (FileOutputStream os = new FileOutputStream(tmp)) {
            byte[] buf = new byte[64 * 1024]; int n;
            while ((n = in.read(buf)) > 0) { os.write(buf, 0, n); got += n; int pct = expected > 0 ? (int) (got * 100 / expected) : -1; if (pr != null && pct != last) { last = pct; pr.on("download", (int) (got / 1024), (int) (expected / 1024)); } }
        } finally { try { in.close(); } catch (Exception ignore) {} }
        try (FileInputStream fi = new FileInputStream(tmp)) { byte[] mg = new byte[MAGIC.length]; if (fi.read(mg) != MAGIC.length || !java.util.Arrays.equals(mg, MAGIC)) { tmp.delete(); throw new Exception("این فایل بستهٔ بانک محصولات نیست (catalog.pack)"); } }
        File dst = file(c); if (dst.exists()) dst.delete(); if (!tmp.renameTo(dst)) throw new Exception("ذخیرهٔ بسته ناموفق بود");
        invalidate(); Images.MEM.evictAll();
        return apply(c, pr);
    }

    /** Read the embedded SQLite → upsert products (standalone) + بانک کالا (both modes) + categories. */
    public static JSONObject apply(Context c, Progress pr) throws Exception {
        File f = file(c); File dbf = new File(c.getFilesDir(), "catalog.db");
        try (RandomAccessFile r = new RandomAccessFile(f, "r"); FileOutputStream os = new FileOutputStream(dbf)) {
            r.seek(MAGIC.length); long dbLen = le64(r); byte[] buf = new byte[64 * 1024]; long left = dbLen;
            while (left > 0) { int n = r.read(buf, 0, (int) Math.min(buf.length, left)); if (n <= 0) break; os.write(buf, 0, n); left -= n; }
        }
        int created = 0, updated = 0, total = 0; String version = null;
        SQLiteDatabase cd = SQLiteDatabase.openDatabase(dbf.getPath(), null, SQLiteDatabase.OPEN_READONLY);
        try {
            try (Cursor m = cd.rawQuery("SELECT v FROM meta WHERE k='version'", null)) { if (m.moveToFirst()) version = m.getString(0); }
            try (Cursor m = cd.rawQuery("SELECT COUNT(*) FROM items", null)) { if (m.moveToFirst()) total = m.getInt(0); }
            Map<String, long[]> idx = index(c);
            boolean standalone = Api.standalone();
            Db.beginBulk();
            try (Cursor it = cd.rawQuery("SELECT barcode, name, category, subcategory, brand, unit, has_image FROM items", null)) {
                int i = 0;
                while (it.moveToNext()) {
                    String bc = it.getString(0), name = it.getString(1), cat = s(it, 2), sub = s(it, 3), brand = s(it, 4), unit = s(it, 5);
                    if (bc == null || name == null || name.trim().isEmpty()) continue;
                    // بانک کالا: highest rank (IMPORT) below USER → what the shop typed by hand still wins
                    Db.bankPut(Api.obj("barcode", bc, "name", name, "brand", brand, "unit", unit, "category", sub.isEmpty() ? cat : sub, "image_url", idx.containsKey(bc) ? "pack://" + bc : "", "source", "IMPORT"));
                    if (standalone) {
                        JSONObject p = Db.productByBarcode(bc);
                        if (p == null) { p = Db.localProduct(bc, name, null); created++; }
                        else if (!name.equals(p.optString("name")) && "1".equals(Db.kv("catalog_rename"))) { p.put("name", name); updated++; }
                        long catId = categoryId(sub.isEmpty() ? cat : sub);
                        if (catId > 0 && p.optLong("category_id", 0) != catId) { p.put("category_id", catId); }
                        if (idx.containsKey(bc) && (p.isNull("image_url") || p.optString("image_url").isEmpty() || p.optString("image_url").startsWith("pack://"))) p.put("image_url", "pack://" + bc);
                        Db.putProduct(p, p.optBoolean("_local") || p.optLong("id") < 0);
                    }
                    if (++i % 100 == 0 && pr != null) pr.on("apply", i, total);
                }
            } finally { Db.endBulk(); }
        } finally { cd.close(); dbf.delete(); }
        Db.kv("catalog_items", String.valueOf(total)); if (version != null) Db.kv("catalog_version", version); Db.kv("catalog_at", Db.now());
        JSONObject rep = new JSONObject();
        try { rep.put("ok", true); rep.put("items", total); rep.put("images", index(c).size()); rep.put("created", created); rep.put("updated", updated); rep.put("bytes", f.length()); } catch (Exception ignore) {}
        try { Local.audit("CATALOG_IMPORT", "Catalog", "pack", null, rep); } catch (Exception ignore) {}
        return rep;
    }

    static long categoryId(String name) {
        if (name == null || name.trim().isEmpty()) return 0; name = name.trim();
        JSONObject r = Local.one("SELECT id FROM categories WHERE name=?", name); if (r != null) return r.optLong("id");
        Local.exec("INSERT INTO categories(name) VALUES(?)", name); r = Local.one("SELECT id FROM categories WHERE name=?", name); return r == null ? 0 : r.optLong("id");
    }

    /** Paired phone: pull the pack from the PC over the LAN (streams straight into private storage). */
    public static JSONObject fetchFromPc(Context c, Progress pr) throws Exception {
        if (Api.standalone()) throw new Exception("این گوشی به رایانه‌ای متصل نیست — فایل catalog.pack را از رایانه کپی و انتخاب کنید");
        HttpURLConnection h = (HttpURLConnection) new URL(Api.base + "/api/catalog/pack").openConnection();
        h.setConnectTimeout(6000); h.setReadTimeout(120000); h.setRequestProperty("Authorization", "Bearer " + Api.token); h.setRequestProperty("User-Agent", "SupermarketAndroid/" + Version.NAME);
        int code = h.getResponseCode();
        if (code == 404) throw new Exception("روی رایانه هنوز بستهٔ بانک محصولات ساخته نشده — در ویندوز: تنظیمات → بانک محصولات → «وارد کردن»");
        if (code != 200) throw new Exception("دریافت از رایانه ناموفق (" + code + ")");
        long len = h.getContentLengthLong();
        return importFrom(c, h.getInputStream(), len, pr);
    }

    /* ------------------------------------------------------------ helpers */
    private static String s(Cursor c, int i) { return c.isNull(i) ? "" : c.getString(i); }
    private static int le16(RandomAccessFile r) throws Exception { byte[] b = new byte[2]; r.readFully(b); return ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getShort() & 0xFFFF; }
    private static long le32(RandomAccessFile r) throws Exception { byte[] b = new byte[4]; r.readFully(b); return ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getInt() & 0xFFFFFFFFL; }
    private static long le64(RandomAccessFile r) throws Exception { byte[] b = new byte[8]; r.readFully(b); return ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getLong(); }
}
