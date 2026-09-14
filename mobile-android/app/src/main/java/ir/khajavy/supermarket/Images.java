package ir.khajavy.supermarket;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.util.LruCache;
import android.widget.ImageView;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Product pictures on the phone (v3.4: OFFLINE ONLY).
 *
 *  • {@link #bind(ImageView, JSONObject)} shows the thumbnail for a product row (memory LRU + disk cache under
 *    files/thumbs). Sources, in order: the shop's own catalog.pack ({@code pack://<barcode>}, see {@link Catalog}),
 *    a picture the operator took ({@code file://…}), the paired PC ({@code /media/…} over the LAN).
 *  • {@link #setFromBytes} stores the operator's own photo (camera / gallery) in the app's private folder.
 *  No web search, no third-party shop APIs — the shop's own database is the only source of names and pictures.
 */
public final class Images {
    private Images() {}

    static final ExecutorService POOL = Executors.newFixedThreadPool(2);
    static final LruCache<String, Bitmap> MEM = new LruCache<String, Bitmap>(8 * 1024 * 1024) { @Override protected int sizeOf(String k, Bitmap b) { return b.getByteCount(); } };
    static final String UA = "SuperyMan-Android/" + Version.NAME + " (+https://github.com/khajavy8056/Super-system-)";

    /* ------------------------------------------------------------ display */
    static File thumbDir(Context c) { File d = new File(c.getFilesDir(), "thumbs"); d.mkdirs(); return d; }
    static File mediaDir(Context c) { File d = new File(c.getFilesDir(), "media/products"); d.mkdirs(); return d; }

    /** Full URL for a product's picture, or null. */
    /** Load a remote/local URL into an ImageView (async, memory cache only) — used by the picker grid. */
    public static void bindUrl(android.widget.ImageView iv, String url) {
        if (url == null || url.isEmpty()) return; Bitmap m = MEM.get(url); if (m != null) { iv.setImageBitmap(m); return; }
        iv.setTag(url); POOL.execute(() -> { byte[] b = download(url, 4 * 1024 * 1024); Bitmap bm = b == null ? null : decodeScaled(b, 320); if (bm == null) return; MEM.put(url, bm); Api.ui(() -> { if (url.equals(iv.getTag())) iv.setImageBitmap(bm); }); });
    }
    public static String urlOf(JSONObject p) {
        if (p == null) return null;
        // v3.4 — the shop's catalogue pack wins whenever it has this barcode (no network needed)
        String bc = p.optString("barcode", ""); if (!bc.isEmpty() && Ui.ctx != null && Catalog.has(Ui.ctx, bc)) return "pack://" + Db.norm(bc);
        String u = p.isNull("image_url") ? "" : p.optString("image_url", "");
        if (u.isEmpty() || "null".equals(u)) return null;
        if (u.startsWith("file://") || u.startsWith("http://") || u.startsWith("https://") || u.startsWith("pack://")) return u;
        String base = Api.base == null ? "" : Api.base;
        if (base.isEmpty() || base.contains("standalone.invalid")) return null;
        if (u.startsWith("/")) return base + u;
        return base + "/media/" + u.replaceFirst("^/?media/", "");
    }

    /** Show the thumbnail (async). Falls back to the placeholder already set on the view. */
    public static void bind(ImageView iv, JSONObject p) {
        final String url = urlOf(p);
        iv.setTag(url);
        if (url == null) return;
        Bitmap m = MEM.get(url);
        if (m != null) { iv.setImageBitmap(m); return; }
        POOL.execute(() -> {
            Bitmap b = load(iv.getContext(), url);
            if (b == null) return;
            MEM.put(url, b);
            iv.post(() -> { if (url.equals(iv.getTag())) iv.setImageBitmap(b); });
        });
    }

    static Bitmap load(Context c, String url) {
        try {
            if (url.startsWith("pack://")) { byte[] raw = Catalog.image(c, url.substring(7)); return raw == null ? null : decodeScaled(raw, 256); }
            File f = url.startsWith("file://") ? new File(new java.net.URI(url)) : new File(thumbDir(c), Integer.toHexString(url.hashCode()) + ".jpg");
            if (!f.exists() || f.length() == 0) {
                byte[] buf = download(url, 6 * 1024 * 1024);
                if (buf == null) return null;
                Bitmap full = decodeScaled(buf, 256);
                if (full == null) return null;
                try (FileOutputStream os = new FileOutputStream(f)) { full.compress(Bitmap.CompressFormat.JPEG, 82, os); }
                return full;
            }
            BitmapFactory.Options o = new BitmapFactory.Options(); o.inSampleSize = 1;
            Bitmap b = BitmapFactory.decodeFile(f.getPath(), o);
            if (b != null && Math.max(b.getWidth(), b.getHeight()) > 512) b = Bitmap.createScaledBitmap(b, 256, 256 * b.getHeight() / Math.max(1, b.getWidth()), true);
            return b;
        } catch (Exception e) { return null; }
    }

    static Bitmap decodeScaled(byte[] buf, int edge) {
        BitmapFactory.Options o = new BitmapFactory.Options(); o.inJustDecodeBounds = true; BitmapFactory.decodeByteArray(buf, 0, buf.length, o);
        if (o.outWidth <= 0) return null;
        int s = 1; while (o.outWidth / (s * 2) >= edge && o.outHeight / (s * 2) >= edge) s *= 2;
        BitmapFactory.Options o2 = new BitmapFactory.Options(); o2.inSampleSize = s;
        return BitmapFactory.decodeByteArray(buf, 0, buf.length, o2);
    }

    /* ------------------------------------------------------------ HTTP */
    static byte[] download(String url, int max) { return download(url, max, false); }
    static byte[] download(String url, int max, boolean browserUa) {
        if (!(Api.base != null && !Api.base.isEmpty() && url.startsWith(Api.base))) return null;   // v3.4: only the paired PC, never the internet
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection(); c.setConnectTimeout(8000); c.setReadTimeout(12000); c.setInstanceFollowRedirects(true);
            c.setRequestProperty("User-Agent", browserUa ? "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36" : UA); c.setRequestProperty("Accept", "image/*,application/json;q=0.9,*/*;q=0.5"); c.setRequestProperty("Accept-Language", "fa,en;q=0.8");
            if (Api.token != null && !Api.token.isEmpty() && Api.base != null && url.startsWith(Api.base)) c.setRequestProperty("Authorization", "Bearer " + Api.token);
            if (c.getResponseCode() != 200) return null;
            try (InputStream in = c.getInputStream(); java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream()) { byte[] b = new byte[16384]; int n; while ((n = in.read(b)) > 0) { bo.write(b, 0, n); if (bo.size() > max) return null; } return bo.toByteArray(); }
        } catch (Exception e) { return null; } finally { if (c != null) c.disconnect(); }
    }
    /** Own photo (camera/gallery). */
    public static JSONObject setFromBytes(Context c, long productId, byte[] buf, String source) {
        JSONObject rep = new JSONObject();
        try { JSONObject p = Db.productById(productId); if (p == null) { rep.put("ok", false); rep.put("reason", "PRODUCT_GONE"); return rep; }
            Bitmap bm = decodeScaled(buf, 640); if (bm == null || bm.getWidth() < 64 || bm.getHeight() < 64) { rep.put("ok", false); rep.put("reason", "INVALID_IMAGE"); return rep; }
            File f = new File(mediaDir(c), (p.optString("barcode", "p" + productId).replaceAll("[^A-Za-z0-9]", "")) + "-" + Long.toHexString(System.currentTimeMillis()) + ".jpg");
            try (FileOutputStream os = new FileOutputStream(f)) { bm.compress(Bitmap.CompressFormat.JPEG, 88, os); }
            String url = "file://" + f.getAbsolutePath(); p.put("image_url", url); Db.putProduct(p, p.optBoolean("_local") || productId < 0); MEM.remove(url);
            if (!Api.standalone() && productId > 0) { try { Api.upload("/products/" + productId + "/image/upload", new String[0][], "file", "photo.jpg", buf, "image/jpeg"); } catch (Exception ignore) {} }
            rep.put("ok", true); rep.put("source", source); rep.put("image_url", url); return rep; }
        catch (Exception e) { try { rep.put("ok", false); rep.put("reason", String.valueOf(e)); } catch (Exception ignore) {} return rep; }
    }


    /** Legacy hooks kept for callers: the phone never searches the web any more. */
    public static void findLater(long productId) {}
    public static int backfill() { return 0; }
    public static int queued() { return 0; }
    public static int missing() { JSONObject r = Local.one("SELECT COUNT(*) AS n FROM products WHERE is_active=1 AND (image_url IS NULL OR image_url='')"); return r == null ? 0 : r.optInt("n"); }
    public static void kick() { try { Local.exec("DELETE FROM kv WHERE k LIKE 'imgq_%'"); } catch (Exception ignore) {} }

    /** بانک کالا lookup — phone bank (catalog.pack + what the shop typed) then the paired PC's bank. Never online. */
    public static JSONObject lookupBarcode(String barcode) {
        String bc = barcode == null ? "" : Db.norm(barcode).replaceAll("[^0-9]", "");
        if (bc.length() < 8) return null;
        JSONObject b = Db.bankGet(bc);
        if (b != null) return Api.obj("name", b.optString("name"), "brand", b.optString("brand"), "image", b.optString("image_url"), "unit", b.optString("unit"), "category", b.optString("category"), "shop", "bank");
        if (!Api.standalone()) { try { Object r = Api.call("GET", "/bank/lookup/" + bc, null, null); if (r instanceof JSONObject) { JSONObject j = (JSONObject) r; Db.bankPut(j); return Api.obj("name", j.optString("name"), "brand", j.optString("brand"), "image", j.optString("image_url"), "unit", j.optString("unit"), "category", j.optString("category"), "shop", "pc"); } } catch (Exception ignore) {} }
        return null;
    }
    static boolean hasNet(android.content.Context ctx) { return false; }
}
