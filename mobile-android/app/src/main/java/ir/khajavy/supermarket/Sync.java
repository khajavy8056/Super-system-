package ir.khajavy.supermarket;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;

/**
 * v2.0 — bidirectional data exchange with the shop PC (native, no web).
 *
 *  push: every operation made on the phone (sale, receipt, product, customer,
 *        count) is queued in SQLite and replayed through POST /api/mobile/sync
 *        — idempotent by op id, same services the Windows app uses.
 *  pull: rows changed on the PC since the last cursor come back in the same
 *        call and are merged into the phone's SQLite (products/batches/customers).
 *
 * Runs on every app start, every 20 s while the app is open, immediately after
 * each local write, and whenever connectivity returns. So: a product added on
 * the PC appears on the phone within seconds — and vice-versa.
 */
public final class Sync {
    public interface Listener { void onSync(boolean online, int applied, int rejected, int pending); }
    public static volatile Listener listener;
    private static volatile boolean running = false;
    private static volatile long lastRun = 0, lastCloud = 0;

    private Sync() {}

    public static void kick() { if (!running) Api.bg(Sync::runBlocking); }
    public static void kickIfStale(long ms) { if (System.currentTimeMillis() - lastRun > ms) kick(); }

    /** Full cycle on a worker thread. */
    public static synchronized void runBlocking() {
        running = true;
        try {
            boolean up = Api.health();
            // v2.1: the PC's IP may have changed — ask the LAN who holds our link key
            if (!up && !Api.standalone()) { String found = Discovery.find(Prefs.get("link_key", ""), 1500); if (found != null && !found.equals(Api.base)) { Api.base = found; Prefs.set("server_url", found); up = Api.health(); } }
            Api.online = up;
            if (up && "pc".equals(Lic.mode())) checkPcLicense();
            int applied = 0, rejected = 0;
            if (up) {
                List<JSONObject> ops = Db.ops();
                JSONArray push = new JSONArray();
                for (JSONObject o : ops) {
                    JSONObject op = new JSONObject();
                    op.put("id", o.getString("id")); op.put("type", o.getString("type")); op.put("payload", cleanLocalIds(o.getJSONObject("payload"))); op.put("created_at", o.optString("created_at"));
                    push.put(op);
                }
                String cursor = Db.kv("cursor");
                JSONObject body = new JSONObject();
                body.put("device_id", Prefs.deviceIdStatic()); body.put("cursor", cursor == null ? JSONObject.NULL : cursor); body.put("push", push); body.put("pull", true); body.put("limit", 2000);
                Object r = Api.call("POST", "/mobile/sync", body.toString(), "application/json");
                JSONObject res = (JSONObject) r;
                JSONArray ap = res.optJSONArray("applied");
                for (int i = 0; ap != null && i < ap.length(); i++) {
                    JSONObject a = ap.getJSONObject(i); String id = a.optString("id"); String st = a.optString("status");
                    JSONObject src = null; for (JSONObject o : ops) if (o.optString("id").equals(id)) src = o;
                    if ("APPLIED".equals(st) || "DUPLICATE".equals(st)) {
                        applied++;
                        JSONObject result = a.optJSONObject("result");
                        if (src != null && result != null && result.has("invoice_number") && !src.isNull("local_no")) Db.markInvoiceSynced(src.optString("local_no"), result.optString("invoice_number"));
                        JSONObject adj = result == null ? null : result.optJSONObject("adjusted");
                        if (adj != null) Db.conflictAdd(id, src == null ? id : src.optString("label"), "قیمت روی رایانه متفاوت بود: گوشی " + Ui.money(adj.optDouble("phone_total")) + " ← رایانه " + Ui.money(adj.optDouble("pc_total")) + " (فاکتور با مبلغ رایانه ثبت شد)");
                        Db.opDelete(id);
                    } else {
                        rejected++;
                        Db.conflictAdd(id, src == null ? id : src.optString("label"), a.optString("error", "رد شد"));
                        Db.opDelete(id);
                    }
                }
                JSONObject pull = res.optJSONObject("pull");
                if (pull != null) Db.applyPull(pull, cursor == null);
                if (res.has("cursor")) Db.kv("cursor", res.optString("cursor"));
                Db.kv("last_sync", Db.now());
                // after the first successful sync the local (negative-id) rows have been replaced by the PC's truth
                if (applied > 0) Db.applyPull(fetchFull(), true);
            }
            // v2.1: PC not reachable on this network → exchange through the shared Drive folder (if the owner connected one)
            if (!up && !Api.standalone() && CloudSync.available() && System.currentTimeMillis() - lastCloud > 60000) { lastCloud = System.currentTimeMillis(); int n = CloudSync.run(); if (n >= 0) { applied += n; Db.kv("last_sync", Db.now()); } }
            lastRun = System.currentTimeMillis();
            final int a = applied, rj = rejected, p = Db.opCount(); final boolean on = up;
            Listener l = listener; if (l != null) Api.ui(() -> l.onSync(on, a, rj, p));
        } catch (Exception e) {
            Api.online = false; lastRun = System.currentTimeMillis();
            Listener l = listener; if (l != null) Api.ui(() -> l.onSync(false, 0, 0, Db.opCount()));
        } finally { running = false; }
    }

    /** PC mode: the phone's licence IS the PC's licence. */
    static void checkPcLicense() {
        try {
            Object r = Api.call("GET", "/mobile/link", null, null);
            if (r instanceof JSONObject) { JSONObject j = (JSONObject) r; Lic.fromPc(j.optJSONObject("license")); if (!j.optString("link_key").isEmpty()) Prefs.set("link_key", j.optString("link_key")); if (!j.optString("store").isEmpty()) Prefs.set("store_name", j.optString("store")); if (j.optJSONObject("cloud") != null) Prefs.set("cloud_json", j.optJSONObject("cloud").toString()); }
        } catch (Api.ApiError e) { if (e.status == 402) Lic.pcLocked(e.getMessage()); }
        if (!Lic.allowed()) Api.ui(LockActivity::showIfNeeded);
    }

    /** Whole catalogue (no cursor) — used after local rows were replayed so temp ids vanish. */
    private static JSONObject fetchFull() {
        try {
            JSONObject body = new JSONObject(); body.put("push", new JSONArray()); body.put("pull", true); body.put("limit", 2000);
            JSONObject res = (JSONObject) Api.call("POST", "/mobile/sync", body.toString(), "application/json");
            return res.optJSONObject("pull");
        } catch (Exception e) { return new JSONObject(); }
    }

    /** temporary negative ids must not reach the PC — it resolves by barcode instead. */
    static JSONObject cleanLocalIds(JSONObject p) throws Exception {
        JSONObject c = new JSONObject(p.toString());
        if (c.has("product_id") && c.optLong("product_id") < 0) c.remove("product_id");
        if (c.has("customer_id") && c.optLong("customer_id") < 0) c.remove("customer_id");
        JSONArray items = c.optJSONArray("items");
        if (items != null) for (int i = 0; i < items.length(); i++) {
            JSONObject it = items.getJSONObject(i);
            if (it.optLong("product_id") < 0) it.remove("product_id");
            if (it.has("batch_id") && it.optLong("batch_id") <= 0) it.remove("batch_id");
        }
        return c;
    }

    /* ---- helpers used by screens: apply locally + queue + kick ---- */
    public static void queue(String type, JSONObject payload, String label, String localNo) { Db.opAdd(type, payload, label, localNo); kick(); }
}
