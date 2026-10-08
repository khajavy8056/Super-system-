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

    private static boolean netWatching;
    /** v2.3: re-run the route ladder (LAN → relay beacon → relay) as soon as the phone changes network
     *  (new Wi‑Fi, mobile data, back home) so a changed PC address never needs a manual re-pair. */
    public static void watchNetwork(android.content.Context ctx) {
        if (netWatching || android.os.Build.VERSION.SDK_INT < 24) return;
        try {
            android.net.ConnectivityManager cm = (android.net.ConnectivityManager) ctx.getApplicationContext().getSystemService(android.content.Context.CONNECTIVITY_SERVICE);
            if (cm == null) return;
            cm.registerDefaultNetworkCallback(new android.net.ConnectivityManager.NetworkCallback() {
                @Override public void onAvailable(android.net.Network n) { lastRun = 0; Api.ui(Sync::kick, 1200); Api.ui(Images::kick, 2500); }
                @Override public void onLost(android.net.Network n) { lastRun = 0; }
            });
            netWatching = true;
        } catch (Exception ignore) {}
    }
    public static void kickIfStale(long ms) { if (System.currentTimeMillis() - lastRun > ms) kick(); }

    /** Full cycle on a worker thread. */
    public static synchronized void runBlocking() {
        running = true;
        try {
            final long ownerUserId = Db.localUserId();
            final long remoteUserId = currentRemoteUserId();
            final String sessionToken = Api.token;
            boolean up = Api.health();
            // v2.1: the PC's IP may have changed — ask the LAN who holds our link key
            if (!up && !Api.standalone()) { String found = Discovery.find(Prefs.get("link_key", ""), 1500); if (found != null && !found.equals(Api.base)) { Api.base = found; Prefs.set("server_url", found); up = Api.health(); } }
            if (ownerUserId <= 0 || remoteUserId <= 0 || sessionToken == null || sessionToken.isEmpty()) up = false;
            Api.online = up;
            if (up && "pc".equals(Lic.mode())) checkPcLicense();
            int applied = 0, rejected = 0;
            if (up) {
                List<JSONObject> ops = Db.opsForUser(ownerUserId);
                JSONArray push = new JSONArray();
                for (JSONObject o : ops) {
                    JSONObject op = new JSONObject();
                    op.put("id", o.getString("id")); op.put("type", o.getString("type")); op.put("payload", cleanLocalIds(o.getJSONObject("payload"))); op.put("created_at", o.optString("created_at"));
                    push.put(op);
                }
                String cursorKey = "cursor_user_" + ownerUserId;
                String cursor = ownerUserId > 0 ? Db.kv(cursorKey) : null;
                JSONObject body = new JSONObject();
                body.put("device_id", Prefs.deviceIdStatic()); body.put("cursor", cursor == null ? JSONObject.NULL : cursor); body.put("push", push); body.put("pull", true); body.put("limit", 2000);
                Object r = Api.callWithToken(sessionToken, "POST", "/mobile/sync", body.toString(), "application/json");
                if (Db.localUserId() != ownerUserId || currentRemoteUserId() != remoteUserId || !sessionToken.equals(Api.token)) {
                    Api.online = false; lastRun = System.currentTimeMillis(); return;
                }
                JSONObject res = (JSONObject) r;
                // build-497 — تشخیص «بازنشانی کارخانه» روی رایانه: اگر epoch داده
                // عوض شده باشد، دادهٔ دورهٔ قبل روی گوشی معتبر نیست؛ پاک و از نو همگام می‌شود.
                String epoch = res.optString("data_epoch", "");
                if (!epoch.isEmpty()) {
                    String epochKey = "data_epoch_user_" + ownerUserId;
                    String epochBefore = Db.kv(epochKey);
                    if (epochBefore != null && !epochBefore.isEmpty() && !epochBefore.equals(epoch)) {
                        final int dropped = Db.wipeOperational();
                        Db.kv(cursorKey, null);
                        Api.ui(() -> Ui.toast(dropped > 0
                                ? "رایانه بازنشانی شد؛ " + Ui.num(dropped) + " فروش همگام‌نشدهٔ دورهٔ قبل حذف شد"
                                : "رایانه بازنشانی شد؛ همگام‌سازی از نو انجام می‌شود"));
                    }
                    Db.kv(epochKey, epoch);
                }
                JSONArray ap = res.optJSONArray("applied");
                for (int i = 0; ap != null && i < ap.length(); i++) {
                    JSONObject a = ap.getJSONObject(i); String id = a.optString("id"); String st = a.optString("status");
                    JSONObject src = null; for (JSONObject o : ops) if (o.optString("id").equals(id)) src = o;
                    if ("APPLIED".equals(st) || "DUPLICATE".equals(st)) {
                        applied++;
                        JSONObject result = a.optJSONObject("result");
                        if (src != null && result != null) {
                            JSONObject original = src.optJSONObject("payload"); String opType = src.optString("type", "").toUpperCase();
                            if (original != null) {
                                long localId = 0, remoteId = 0;
                                if ("SHIFT_CREATE".equals(opType) || "SHIFT_UPDATE".equals(opType)) {
                                    localId = original.optLong("local_shift_id"); remoteId = result.optLong("shift_id", result.optLong("id"));
                                    if (localId != 0 && remoteId > 0) Db.markShiftSynced(localId, remoteId);
                                } else if ("SHIFT_ASSIGN".equals(opType) || "SHIFT_MOVE".equals(opType)) {
                                    localId = original.optLong("local_assignment_id"); remoteId = result.optLong("assignment_id");
                                    if (localId != 0 && remoteId > 0) Db.markAssignmentSynced(localId, remoteId);
                                } else if ("ATTENDANCE_CLOCK_IN".equals(opType) || "ATTENDANCE_CLOCK_OUT".equals(opType)) {
                                    localId = original.optLong("attendance_id"); remoteId = result.optLong("attendance_id", result.optLong("id"));
                                    if (localId != 0 && remoteId > 0) Db.markAttendanceSynced(localId, remoteId);
                                } else if ("ANNOUNCEMENT_CREATE".equals(opType)) {
                                    localId = original.optLong("local_announcement_id"); remoteId = result.optLong("announcement_id", result.optLong("id"));
                                    if (localId != 0 && remoteId > 0) Db.markAnnouncementSynced(localId, remoteId);
                                } else if (opType.startsWith("PAYROLL_")) {
                                    localId = original.optLong("local_payroll_id"); remoteId = result.optLong("payroll_id", result.optLong("id"));
                                    if (localId != 0 && remoteId > 0) Db.markPayrollSynced(localId, remoteId);
                                }
                            }
                            if (result.has("invoice_number") && !src.isNull("local_no")) Db.markInvoiceSynced(src.optString("local_no"), result.optString("invoice_number"));
                        }
                        JSONObject adj = result == null ? null : result.optJSONObject("adjusted");
                        if (adj != null) Db.conflictAdd(id, src == null ? id : src.optString("label"), "قیمت روی رایانه متفاوت بود: گوشی " + Ui.money(adj.optDouble("phone_total")) + " ← رایانه " + Ui.money(adj.optDouble("pc_total")) + " (فاکتور با مبلغ رایانه ثبت شد)", ownerUserId);
                        Db.opDelete(id);
                    } else {
                        rejected++;
                        Db.conflictAdd(id, src == null ? id : src.optString("label"), a.optString("error", "رد شد"), ownerUserId);
                        Db.opDelete(id);
                    }
                }
                JSONObject pull = res.optJSONObject("pull");
                if (pull != null) Db.applyPull(pull, cursor == null);
                boolean accessChanged = false;
                JSONObject cu = res.optJSONObject("current_user");
                if (cu != null && cu.optLong("id") == remoteUserId && ownerUserId > 0) {
                    JSONObject prior = Screens.user;
                    String priorPermissions = prior == null || prior.optJSONArray("permissions") == null ? "[]" : prior.optJSONArray("permissions").toString();
                    String nextPermissions = cu.optJSONArray("permissions") == null ? "[]" : cu.optJSONArray("permissions").toString();
                    String priorRoles = prior == null || prior.optJSONArray("roles") == null ? "[]" : prior.optJSONArray("roles").toString();
                    String nextRoles = cu.optJSONArray("roles") == null ? "[]" : cu.optJSONArray("roles").toString();
                    String priorViews = prior == null || prior.optJSONArray("allowed_views") == null ? "[]" : prior.optJSONArray("allowed_views").toString();
                    String nextViews = cu.optJSONArray("allowed_views") == null ? "[]" : cu.optJSONArray("allowed_views").toString();
                    accessChanged = !priorPermissions.equals(nextPermissions) || !priorRoles.equals(nextRoles) || !priorViews.equals(nextViews);
                    if (accessChanged) Db.cacheClearForUser(ownerUserId);
                    Db.putUserMeta(cu);
                    Screens.user = cu;
                    Prefs.set("user_json", cu.toString());
                }
                JSONObject shift = res.optJSONObject("shift_status");
                if (shift != null && ownerUserId > 0) {
                    String key = "shift_status_" + ownerUserId, before = Db.kv(key);
                    Db.kv(key, shift.toString());
                    if (before == null || !before.equals(shift.toString())) {
                        Api.ui(() -> { if (Ui.ctx instanceof AppActivity) ((AppActivity) Ui.ctx).refreshCurrent(); });
                    }
                }
                if (res.has("cursor") && ownerUserId > 0) Db.kv(cursorKey, res.optString("cursor"));
                // Re-fetch every table after a grant/revocation change. The previous
                // cursor may have advanced while a table was outside this user's scope.
                if (accessChanged && ownerUserId > 0) Db.kv(cursorKey, null);
                Db.kv("last_sync", Db.now()); SmsLocal.relayPcOutbox();   // v2.8: PC queue → this SIM
                autoCatalog();   // v3.4: pull the PC's catalog.pack when it is newer than ours (max once an hour)
                // after the first successful sync the local (negative-id) rows have been replaced by the PC's truth
                if (applied > 0) Db.applyPull(fetchFull(sessionToken), true);
            }
            // v2.1: PC not reachable on this network → exchange through the shared Drive folder (if the owner connected one)
            if (!up && !Api.standalone() && CloudSync.available() && System.currentTimeMillis() - lastCloud > 60000) { lastCloud = System.currentTimeMillis(); int n = CloudSync.run(); if (n >= 0) { applied += n; Db.kv("last_sync", Db.now()); } }
            lastRun = System.currentTimeMillis();
            long activeUser = Db.localUserId();
            final int a = applied, rj = rejected, p = Db.opCountForUser(activeUser); final boolean on = up;
            Listener l = listener; if (l != null) Api.ui(() -> l.onSync(on, a, rj, p));
        } catch (Exception e) {
            android.util.Log.w("Sync", "background sync failed; local app remains available: " + e);
            Api.online = false; lastRun = System.currentTimeMillis();
            long activeUser = Db.localUserId();
            Listener l = listener; if (l != null) Api.ui(() -> l.onSync(false, 0, 0, Db.opCountForUser(activeUser)));
        } finally { running = false; }
    }

    /** Resolve the authenticated PC principal while local tables keep their own stable row IDs. */
    static long currentRemoteUserId() {
        JSONObject user = Screens.user;
        if (user == null || user.optString("username", "").isEmpty()) {
            try { user = new JSONObject(Prefs.get("user_json", "{}")); } catch (Exception e) { return 0; }
        }
        long pcId = user.optLong("pc_id", 0);
        return pcId > 0 ? pcId : user.optLong("id", 0);
    }

    /** PC mode: the phone's licence IS the PC's licence. */
    static void checkPcLicense() {
        try {
            Object r = Api.call("GET", "/mobile/link", null, null);
            if (r instanceof JSONObject) { JSONObject j = (JSONObject) r; Lic.fromPc(j.optJSONObject("license")); if (j.optJSONObject("relay") != null) Prefs.set("relay_json", j.optJSONObject("relay").toString()); if (j.optJSONArray("lan") != null) Prefs.set("pc_lan_json", j.optJSONArray("lan").toString() + "|0"); if (!j.optString("link_key").isEmpty()) Prefs.set("link_key", j.optString("link_key")); if (!j.optString("store").isEmpty()) Prefs.set("store_name", j.optString("store")); if (j.optJSONObject("cloud") != null) Prefs.set("cloud_json", j.optJSONObject("cloud").toString()); }
        } catch (Api.ApiError e) { if (e.status == 402) Lic.pcLocked(e.getMessage()); }
        if (!Lic.allowed()) Api.ui(LockActivity::showIfNeeded);
    }

    /** Whole catalogue (no cursor) — used after local rows were replayed so temp ids vanish. */
    static long lastCatalogCheck = 0;
    static void autoCatalog() {
        if (Api.standalone() || Ui.ctx == null || System.currentTimeMillis() - lastCatalogCheck < 3600_000L) return;
        lastCatalogCheck = System.currentTimeMillis();
        try {
            Object r = Api.call("GET", "/catalog/pack/info", null, null); if (!(r instanceof JSONObject)) return; JSONObject j = (JSONObject) r;
            if (!j.optBoolean("exists")) return;
            String v = j.optString("version", ""); if (v.isEmpty() || v.equals(Db.kv("catalog_version"))) return;
            Catalog.fetchFromPc(Ui.ctx, null); Notify.progressDone(Ui.ctx, "بانک محصولات به‌روز شد", Ui.fa(j.optString("items", "")) + " کالا از رایانه دریافت شد");
        } catch (Throwable e) { android.util.Log.w("Sync", "catalog: " + e); }
    }
    private static JSONObject fetchFull(String sessionToken) {
        try {
            JSONObject body = new JSONObject(); body.put("push", new JSONArray()); body.put("pull", true); body.put("limit", 2000);
            JSONObject res = (JSONObject) Api.callWithToken(sessionToken, "POST", "/mobile/sync", body.toString(), "application/json");
            return res.optJSONObject("pull");
        } catch (Exception e) { return new JSONObject(); }
    }

    /** Resolve phone-side identifiers to their PC identity; unresolved temporary IDs never cross the wire. */
    static JSONObject cleanLocalIds(JSONObject p) throws Exception {
        JSONObject c = new JSONObject(p.toString());
        if (c.has("product_id") && c.optLong("product_id") < 0) c.remove("product_id");
        if (c.has("customer_id") && c.optLong("customer_id") < 0) c.remove("customer_id");
        if (c.optBoolean("campaign_local")) c.remove("campaign_id");
        c.remove("campaign_local");
        if (c.has("user_id")) {
            long localOrPc = c.optLong("user_id");
            if (Db.localUserIdForPc(localOrPc) > 0) {
                // Values already expressed in the PC namespace take precedence over
                // an unrelated phone-local primary key with the same number.
            } else {
                long pcId = Db.pcUserIdForLocal(localOrPc);
                if (pcId > 0) c.put("user_id", pcId);
                else c.remove("user_id");
            }
        }
        if (c.has("shift_id")) {
            long remoteId = Db.remoteShiftId(c.optLong("shift_id"));
            if (remoteId > 0) c.put("shift_id", remoteId); else c.remove("shift_id");
        }
        if (c.has("assignment_id")) {
            long remoteId = Db.remoteAssignmentId(c.optLong("assignment_id"));
            if (remoteId > 0) c.put("assignment_id", remoteId); else c.remove("assignment_id");
        }
        if (c.has("payroll_id")) {
            long remoteId = Db.remotePayrollId(c.optLong("payroll_id"));
            if (remoteId > 0) c.put("payroll_id", remoteId); else c.remove("payroll_id");
        }
        if (c.has("announcement_id")) {
            long remoteId = Db.remoteAnnouncementId(c.optLong("announcement_id"));
            if (remoteId > 0) c.put("announcement_id", remoteId); else c.remove("announcement_id");
        }
        JSONArray targetUsers = c.optJSONArray("target_users");
        if (targetUsers != null) {
            JSONArray mapped = new JSONArray();
            for (int i = 0; i < targetUsers.length(); i++) {
                long id = targetUsers.optLong(i);
                if (id > 0 && Db.localUserIdForPc(id) > 0) mapped.put(id);
                else {
                    long pcId = Db.pcUserIdForLocal(id);
                    if (pcId > 0) mapped.put(pcId);
                }
            }
            c.put("target_users", mapped);
        }
        JSONArray items = c.optJSONArray("items");
        if (items != null) for (int i = 0; i < items.length(); i++) {
            JSONObject it = items.getJSONObject(i);
            if (it.optLong("product_id") < 0) it.remove("product_id");
            if (it.has("batch_id") && it.optLong("batch_id") <= 0) it.remove("batch_id");
        }
        for (String local : new String[]{"local_shift_id", "local_assignment_id", "local_payroll_id", "local_announcement_id", "attendance_id"}) c.remove(local);
        return c;
    }

    /* ---- helpers used by screens: apply locally + queue + kick ---- */
    public static void queue(String type, JSONObject payload, String label, String localNo) { Db.opAdd(type, payload, label, localNo); kick(); }
}
