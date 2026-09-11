package ir.khajavy.supermarket;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.util.LruCache;
import android.widget.ImageView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * v2.5 — product pictures on the phone.
 *
 *  • {@link #bind(ImageView, JSONObject)} shows the thumbnail for a product row
 *    (memory LRU + disk cache under files/thumbs). Paired phones load
 *    {@code image_url} from the PC (/media/…); standalone phones use the picture
 *    they found themselves.
 *  • {@link #findLater(long)} queues a background lookup by NAME (same free,
 *    keyless source ladder as the Windows side: OpenFoodFacts barcode → OFF text
 *    search → Wikimedia Commons → Wikipedia → DuckDuckGo) and stores the picture
 *    in the phone's own media folder; the product row gets {@code image_url = file://…}.
 *  • {@link #backfill()} queues every product without a picture (starter catalogue).
 */
public final class Images {
    private Images() {}

    static final ExecutorService POOL = Executors.newFixedThreadPool(2);
    static final LruCache<String, Bitmap> MEM = new LruCache<String, Bitmap>(8 * 1024 * 1024) { @Override protected int sizeOf(String k, Bitmap b) { return b.getByteCount(); } };
    static final String UA = "SuperyMan-Android/" + Version.NAME + " (+https://github.com/khajavy8056/Super-system-)";
    static final AtomicBoolean draining = new AtomicBoolean(false);

    /* ------------------------------------------------------------ display */
    static File thumbDir(Context c) { File d = new File(c.getFilesDir(), "thumbs"); d.mkdirs(); return d; }
    static File mediaDir(Context c) { File d = new File(c.getFilesDir(), "media/products"); d.mkdirs(); return d; }

    /** Full URL for a product's picture, or null. */
    public static String urlOf(JSONObject p) {
        if (p == null) return null;
        String u = p.isNull("image_url") ? "" : p.optString("image_url", "");
        if (u.isEmpty() || "null".equals(u)) return null;
        if (u.startsWith("file://") || u.startsWith("http://") || u.startsWith("https://")) return u;
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
    static byte[] download(String url, int max) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection(); c.setConnectTimeout(8000); c.setReadTimeout(12000); c.setInstanceFollowRedirects(true);
            c.setRequestProperty("User-Agent", UA); c.setRequestProperty("Accept", "image/*,application/json;q=0.9,*/*;q=0.5"); c.setRequestProperty("Accept-Language", "fa,en;q=0.8");
            if (Api.token != null && !Api.token.isEmpty() && Api.base != null && url.startsWith(Api.base)) c.setRequestProperty("Authorization", "Bearer " + Api.token);
            if (c.getResponseCode() != 200) return null;
            try (InputStream in = c.getInputStream(); java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream()) { byte[] b = new byte[16384]; int n; while ((n = in.read(b)) > 0) { bo.write(b, 0, n); if (bo.size() > max) return null; } return bo.toByteArray(); }
        } catch (Exception e) { return null; } finally { if (c != null) c.disconnect(); }
    }
    static JSONObject getJson(String url) { byte[] b = download(url, 2 * 1024 * 1024); if (b == null) return null; try { String s = new String(b, "UTF-8").trim(); return s.startsWith("{") ? new JSONObject(s) : null; } catch (Exception e) { return null; } }
    static String enc(String s) { try { return URLEncoder.encode(s, "UTF-8"); } catch (Exception e) { return s; } }

    /* ------------------------------------------------------------ name → picture */
    static final String[][] FA_EN = {{"شیر", "milk"}, {"ماست", "yogurt"}, {"پنیر", "cheese"}, {"کره", "butter"}, {"خامه", "cream"}, {"دوغ", "doogh"}, {"رب", "tomato paste"}, {"گوجه", "tomato"}, {"سس", "sauce"}, {"کچاپ", "ketchup"}, {"مایونز", "mayonnaise"}, {"برنج", "rice"}, {"ماکارونی", "pasta"}, {"آرد", "flour"}, {"نان", "bread"}, {"روغن", "oil"}, {"زیتون", "olive"}, {"شکر", "sugar"}, {"قند", "sugar cubes"}, {"نمک", "salt"}, {"چای", "tea"}, {"قهوه", "coffee"}, {"عدس", "lentils"}, {"لوبیا", "beans"}, {"نخود", "chickpeas"}, {"کنسرو", "canned"}, {"تن", "tuna"}, {"مرغ", "chicken"}, {"گوشت", "meat"}, {"سوسیس", "sausage"}, {"تخم‌مرغ", "eggs"}, {"آب", "water"}, {"معدنی", "mineral"}, {"نوشابه", "soda"}, {"دلستر", "malt beverage"}, {"آبمیوه", "juice"}, {"بیسکویت", "biscuit"}, {"کیک", "cake"}, {"شکلات", "chocolate"}, {"آدامس", "chewing gum"}, {"چیپس", "chips"}, {"پفک", "cheese puffs"}, {"بستنی", "ice cream"}, {"ویفر", "wafer"}, {"خرما", "dates"}, {"پودر", "powder"}, {"لباسشویی", "laundry detergent"}, {"ظرفشویی", "dishwashing liquid"}, {"مایع", "liquid"}, {"صابون", "soap"}, {"شامپو", "shampoo"}, {"خمیردندان", "toothpaste"}, {"دستمال", "tissue"}, {"پوشک", "diapers"}, {"سیب", "apple"}, {"موز", "banana"}, {"پرتقال", "orange"}, {"خیار", "cucumber"}, {"پیاز", "onion"}, {"سیب‌زمینی", "potato"}, {"هویج", "carrot"}, {"لیمو", "lemon"}, {"زعفران", "saffron"}, {"عسل", "honey"}, {"مربا", "jam"}, {"حلوا", "halva"}, {"سرکه", "vinegar"}, {"غلات", "cereal"}, {"پرچرب", "whole"}, {"کم‌چرب", "low fat"}, {"باتری", "battery"}, {"لامپ", "light bulb"}};
    static final java.util.Set<String> STOP = new java.util.HashSet<>(java.util.Arrays.asList("عدد", "بسته", "کیلو", "کیلوگرم", "گرم", "گرمی", "لیتر", "لیتری", "میلی", "تایی", "بزرگ", "کوچک", "متوسط", "مخصوص", "ویژه", "یک", "دو", "و"));

    static List<String> tokens(String name) { List<String> out = new ArrayList<>(); String n = Db.norm(name == null ? "" : name).replaceAll("[0-9]+", " "); for (String t : n.split("[\\s\\-_/،,()«»\"']+")) { t = t.trim(); if (t.length() >= 2 && !STOP.contains(t)) out.add(t); } return out; }
    static String faQuery(String name, String brand) { String q = android.text.TextUtils.join(" ", tokens(name)); if (brand != null && !brand.isEmpty() && !q.contains(brand)) q += " " + brand; return q.trim(); }
    static String enQuery(String name, String brand) { StringBuilder sb = new StringBuilder(); for (String t : tokens(name)) { if (t.matches("[a-z0-9]+")) sb.append(t).append(' '); else for (String[] m : FA_EN) if (m[0].equals(t)) { sb.append(m[1]).append(' '); break; } } if (brand != null) sb.append(brand); return sb.toString().trim(); }
    static double score(String title, String name, String brand) {
        if (title == null || title.isEmpty()) return 0.25; String t = Db.norm(title).toLowerCase();
        List<String> want = tokens(name); String[] en = enQuery(name, null).split(" "); double hit = 0, total = want.size() + 0.8 * en.length;
        for (String w : want) if (t.contains(w)) hit++; for (String w : en) if (!w.isEmpty() && t.contains(w)) hit += 0.8;
        double s = total == 0 ? 0 : hit / total; if (brand != null && !brand.isEmpty() && t.contains(Db.norm(brand).toLowerCase())) s += 0.25;
        for (String bad : new String[]{"plant", "flower", "field", "farm", "tree", "seedling", "botanical", "illustration", "drawing", "map", "logo"}) if (t.contains(bad)) { s -= 0.35; break; }
        return Math.max(0, Math.min(1, s));
    }

    /** [url, source, title, score] candidates, best first. */
    static List<String[]> candidates(String name, String brand, String barcode, boolean web) {
        List<String[]> out = new ArrayList<>();
        // 1) OFF by barcode
        if (barcode != null && barcode.matches("[0-9]{8,14}") && !barcode.matches("^(02|2[0-9]).*")) { JSONObject j = getJson("https://world.openfoodfacts.org/api/v2/product/" + barcode + ".json?fields=product_name,image_front_url,image_url"); if (j != null && j.optInt("status") == 1) { JSONObject p = j.optJSONObject("product"); String u = p == null ? "" : p.optString("image_front_url", p.optString("image_url", "")); if (!u.isEmpty()) { out.add(new String[]{u, "openfoodfacts:barcode", p.optString("product_name"), "1.0"}); return out; } } }
        // 2) OFF text search
        for (String q : new String[]{faQuery(name, brand), enQuery(name, brand)}) { if (q.isEmpty()) continue; JSONObject j = getJson("https://world.openfoodfacts.org/cgi/search.pl?search_simple=1&action=process&json=1&page_size=8&fields=product_name,product_name_fa,brands,image_front_url,image_url&search_terms=" + enc(q)); JSONArray ps = j == null ? null : j.optJSONArray("products"); for (int i = 0; ps != null && i < ps.length(); i++) { JSONObject p = ps.optJSONObject(i); String u = p.optString("image_front_url", p.optString("image_url", "")); if (u.isEmpty()) continue; String title = p.optString("product_name_fa", "") + " " + p.optString("product_name", "") + " " + p.optString("brands", ""); double s = score(title, name, brand); if (s >= 0.34) out.add(new String[]{u, "openfoodfacts:search", title, String.valueOf(s)}); } if (!out.isEmpty()) break; }
        if (best(out) >= 0.75) return sort(out);
        // 3) Wikimedia Commons
        for (String q : new String[]{faQuery(name, brand), enQuery(name, brand)}) { if (q.isEmpty()) continue; JSONObject j = getJson("https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrlimit=8&prop=imageinfo&iiprop=url|mime&iiurlwidth=600&format=json&gsrsearch=" + enc(q + " filetype:bitmap")); JSONObject pages = j == null || j.optJSONObject("query") == null ? null : j.optJSONObject("query").optJSONObject("pages"); if (pages == null) continue; java.util.Iterator<String> it = pages.keys(); boolean any = false; while (it.hasNext()) { JSONObject p = pages.optJSONObject(it.next()); JSONArray ii = p.optJSONArray("imageinfo"); JSONObject i0 = ii == null || ii.length() == 0 ? null : ii.optJSONObject(0); if (i0 == null) continue; String mime = i0.optString("mime", ""), u = i0.optString("thumburl", i0.optString("url", "")); if (u.isEmpty() || !mime.startsWith("image/") || mime.contains("svg")) continue; String title = p.optString("title", "").replace("File:", ""); double s = score(title, name, brand); if (s >= 0.34) { out.add(new String[]{u, "wikimedia-commons", title, String.valueOf(s)}); any = true; } } if (any) break; }
        if (best(out) >= 0.75) return sort(out);
        // 4) Wikipedia page image
        for (String[] lq : new String[][]{{"fa", faQuery(name, null)}, {"en", enQuery(name, null)}}) { if (lq[1].isEmpty()) continue; JSONObject j = getJson("https://" + lq[0] + ".wikipedia.org/w/api.php?action=query&generator=search&gsrlimit=4&prop=pageimages&piprop=thumbnail|name&pithumbsize=600&format=json&gsrsearch=" + enc(lq[1])); JSONObject pages = j == null || j.optJSONObject("query") == null ? null : j.optJSONObject("query").optJSONObject("pages"); if (pages == null) continue; java.util.Iterator<String> it = pages.keys(); boolean any = false; while (it.hasNext()) { JSONObject p = pages.optJSONObject(it.next()); JSONObject th = p.optJSONObject("thumbnail"); if (th == null) continue; String title = p.optString("title", "") + " " + p.optString("pageimage", ""); double s = score(title, name, brand) * 0.9; if (s >= 0.34) { out.add(new String[]{th.optString("source"), "wikipedia:" + lq[0], title, String.valueOf(s)}); any = true; } } if (any) break; }
        if (best(out) >= 0.75 || !web) return sort(out);
        // 5) DuckDuckGo images (keyless)
        try { String q = faQuery(name, brand).isEmpty() ? enQuery(name, brand) : faQuery(name, brand); byte[] html = download("https://duckduckgo.com/?iax=images&ia=images&q=" + enc(q), 2 * 1024 * 1024); if (html != null) { java.util.regex.Matcher m = java.util.regex.Pattern.compile("vqd=\"?([\\d-]+)").matcher(new String(html, "UTF-8")); if (m.find()) { JSONObject j = getJson("https://duckduckgo.com/i.js?l=ir-fa&o=json&f=,,,,,&p=1&q=" + enc(q) + "&vqd=" + m.group(1)); JSONArray rs = j == null ? null : j.optJSONArray("results"); for (int i = 0; rs != null && i < Math.min(10, rs.length()); i++) { JSONObject r = rs.optJSONObject(i); String u = r.optString("image", ""); if (u.isEmpty()) continue; double s = score(r.optString("title", ""), name, brand) * 0.85; if (s >= 0.34) out.add(new String[]{u, "duckduckgo", r.optString("title", ""), String.valueOf(s)}); } } } } catch (Exception ignore) {}
        return sort(out);
    }
    static double best(List<String[]> l) { double b = -1; for (String[] x : l) b = Math.max(b, Double.parseDouble(x[3])); return b; }
    static List<String[]> sort(List<String[]> l) { java.util.Collections.sort(l, (a, b) -> Double.compare(Double.parseDouble(b[3]), Double.parseDouble(a[3]))); List<String[]> out = new ArrayList<>(); java.util.Set<String> seen = new java.util.HashSet<>(); for (String[] x : l) if (seen.add(x[0])) out.add(x); return out; }

    /** Blocking: find, validate, store, update the product row. Returns a report. */
    public static JSONObject findNow(Context c, long productId) {
        JSONObject rep = new JSONObject();
        try {
            JSONObject p = Db.productById(productId); if (p == null) { rep.put("ok", false); rep.put("reason", "PRODUCT_GONE"); return rep; }
            String brand = null; if (!p.isNull("brand_id")) { JSONObject b = Local.one("SELECT name FROM brands WHERE id=?", p.optLong("brand_id")); brand = b == null ? null : b.optString("name"); }
            boolean web = "true".equals(Local.setting("images.web_fallback", "true"));
            List<String[]> cands = candidates(p.optString("name"), brand, p.optString("barcode"), web);
            int tried = 0;
            for (String[] cd : cands) { if (tried++ >= 6) break; byte[] buf = download(cd[0], 8 * 1024 * 1024); if (buf == null || buf.length < 1024) continue; Bitmap bm = decodeScaled(buf, 512); if (bm == null || bm.getWidth() < 64 || bm.getHeight() < 64) continue;
                File f = new File(mediaDir(c), (p.optString("barcode", "p" + productId).replaceAll("[^A-Za-z0-9]", "")) + "-" + Integer.toHexString(cd[0].hashCode()) + ".jpg");
                try (FileOutputStream os = new FileOutputStream(f)) { bm.compress(Bitmap.CompressFormat.JPEG, 88, os); }
                String url = "file://" + f.getAbsolutePath(); p.put("image_url", url); Db.putProduct(p, p.optBoolean("_local") || productId < 0); MEM.remove(url);
                // paired phone: tell the PC too, so the picture reaches Windows and the other phones
                if (!Api.standalone() && productId > 0) { try { JSONObject body = new JSONObject(); body.put("product_id", productId); Sync.queue("PRODUCT_IMAGE_FIND", body, "تصویر " + p.optString("name"), "img-" + productId); } catch (Exception ignore) {} }
                rep.put("ok", true); rep.put("source", cd[1]); rep.put("title", cd[2]); rep.put("score", Double.parseDouble(cd[3])); rep.put("image_url", url); return rep; }
            rep.put("ok", false); rep.put("reason", cands.isEmpty() ? "NO_CANDIDATES" : "NO_VALID_IMAGE"); rep.put("tried", tried);
        } catch (Exception e) { try { rep.put("ok", false); rep.put("reason", String.valueOf(e)); } catch (Exception ignore) {} }
        return rep;
    }

    /* ------------------------------------------------------------ background queue */
    public static void findLater(long productId) { if (!"true".equals(Local.setting("images.auto_find", "true"))) return; try { Db.kv("imgq_" + productId, "0"); } catch (Exception ignore) {} kick(); }
    public static int backfill() { int n = 0; for (JSONObject p : Local.rows("SELECT id FROM products WHERE is_active=1 AND (image_url IS NULL OR image_url='')")) { Db.kv("imgq_" + p.optLong("id"), "0"); n++; } kick(); return n; }
    public static int queued() { JSONObject r = Local.one("SELECT COUNT(*) AS n FROM kv WHERE k LIKE 'imgq_%'"); return r == null ? 0 : r.optInt("n"); }
    public static int missing() { JSONObject r = Local.one("SELECT COUNT(*) AS n FROM products WHERE is_active=1 AND (image_url IS NULL OR image_url='')"); return r == null ? 0 : r.optInt("n"); }
    public static void kick() {
        if (!draining.compareAndSet(false, true)) return;
        POOL.execute(() -> { try {
            Context c = Ui.ctx; if (c == null) return;
            for (JSONObject row : Local.rows("SELECT k, v FROM kv WHERE k LIKE 'imgq_%' ORDER BY k LIMIT 40")) {
                long pid = Long.parseLong(row.optString("k").substring(5)); int tries = Integer.parseInt(row.optString("v", "0"));
                JSONObject p = Db.productById(pid);
                if (p == null || (!p.isNull("image_url") && !p.optString("image_url").isEmpty())) { Local.exec("DELETE FROM kv WHERE k=?", "imgq_" + pid); continue; }
                JSONObject rep = findNow(c, pid);
                if (rep.optBoolean("ok") || tries >= 6 || "NO_VALID_IMAGE".equals(rep.optString("reason"))) Local.exec("DELETE FROM kv WHERE k=?", "imgq_" + pid);
                else Db.kv("imgq_" + pid, String.valueOf(tries + 1));   // offline → retried on the next kick (app open / network change)
                if (!rep.optBoolean("ok") && "NO_CANDIDATES".equals(rep.optString("reason")) && tries >= 1) break;   // probably offline: stop hammering
            }
        } catch (Exception ignore) {} finally { draining.set(false); } });
    }
}
