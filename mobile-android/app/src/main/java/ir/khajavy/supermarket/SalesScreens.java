package ir.khajavy.supermarket;

import android.app.Dialog;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** v2.0 — POS, held invoices, invoices/void/return, customers & ledger, marketing. */
public final class SalesScreens {
    private SalesScreens() {}

    /* =====================================================================
       POS — fixed viewport: search on top, cart list scrolls, totals + pay fixed.
       No profit anywhere on this screen (user rule).
       ===================================================================== */
    public static final class Pos extends Screens.Screen {
        static final int HELD_MAX = 10;
        final List<JSONObject> cart = new ArrayList<>();  // {product_id, name, barcode, batch_id, batch_number, quantity, price, discount, unit_decimal}
        JSONObject customer, campaign; String coupon; double invoiceDiscount = 0, couponDiscount = 0, campaignDiscount = 0; String heldId;
        String resolvedBenefitsKey = "", pendingBenefitsKey = "";
        boolean taxConfigured;
        LinearLayout lines, benefitsStrip; TextView tot, cnt, custTxt; EditText search; LinearLayout sugg; final Handler h = new Handler(Looper.getMainLooper()); Runnable pending;
        /** v4.7.0 — real-time POS suggestions (پیشنهاد پای صندوق) on the phone too:
         *  honest stock only, near-expiry first — same rules as the Windows POS. */
        LinearLayout nudgeBar; String nudgeKey = ""; Runnable nudgePend;
        Pos(AppActivity a) { super(a); taxConfigured = Api.standalone() || Local.hasSetting("pos.tax_rate"); }
        public String key() { return "pos"; } public String title() { return "صندوق فروش"; }
        public View view() {
            LinearLayout root = Ui.col(c); root.setPadding(Ui.dp(12), Ui.dp(10), Ui.dp(12), Ui.dp(10));
            // search row (mockup: rounded input + teal «اسکن» button)
            LinearLayout sr = Ui.row(c);
            search = Ui.input(c, "نام یا بارکد کالا…"); search.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG_LTR); search.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD | android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS); search.setLayoutParams(Ui.weight(1)); { Icons.Icon si = Icons.draw("search", Ui.MUTED, 2f); si.setBounds(0, 0, Ui.dp(18), Ui.dp(18)); search.setCompoundDrawables(null, null, si, null); search.setCompoundDrawablePadding(Ui.dp(8)); } sr.addView(search);
            android.widget.ImageView scanB = Icons.disc(c, "scan", Ui.PRIMARY, Color.WHITE, 46); scanB.setBackground(new android.graphics.drawable.RippleDrawable(android.content.res.ColorStateList.valueOf(0x33FFFFFF), Ui.gradient(Ui.PRIMARY2, Ui.PRIMARY, 0x88CBA75A, 14), null)); scanB.setOnClickListener(v -> a.scan("اسکن کالا برای فروش", this::onBarcode)); scanB.setLayoutParams(Ui.margin(Ui.lp(Ui.dp(50), Ui.dp(46)), 8, 0, 0, 6)); sr.addView(scanB);
            root.addView(sr);
            search.addTextChangedListener(new TextWatcher() { public void beforeTextChanged(CharSequence s, int i, int i1, int i2) {} public void onTextChanged(CharSequence s, int i, int i1, int i2) {} public void afterTextChanged(Editable e) { if (pending != null) h.removeCallbacks(pending); pending = () -> suggest(e.toString().trim()); h.postDelayed(pending, 220); } });
            search.setOnEditorActionListener((v, id, ev) -> { if (ev != null && ev.getAction() != android.view.KeyEvent.ACTION_DOWN) return true; String q = Ui.str(search); if (!q.isEmpty()) onBarcode(q); return true; });
            sugg = Ui.col(c); root.addView(sugg);
            // customer, coupon, campaign and invoice-discount controls
            benefitsStrip = Ui.row(c); benefitsStrip.setPadding(0, Ui.dp(4), 0, Ui.dp(2));
            renderBenefitsStrip(); root.addView(Ui.chips(c, benefitsStrip));
            custTxt = Ui.text(c, "مشتری آزاد", 12, Ui.MUTED, false); custTxt.setPadding(Ui.dp(4), 0, Ui.dp(4), Ui.dp(4)); custTxt.setOnClickListener(v -> pickCustomer()); root.addView(custTxt);
            nudgeBar = Ui.col(c); nudgeBar.setVisibility(View.GONE); root.addView(nudgeBar);   // v4.7.0
            applyDueDiscounts();                                                              // v4.8.0 — تخفیف‌های سررسیدشده، قبل از اولین قیمت
            // cart list (scrolls)
            lines = Ui.col(c); android.widget.ScrollView sv = new android.widget.ScrollView(c); sv.addView(lines); sv.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1)); root.addView(sv);
            // footer
            LinearLayout foot = Ui.col(c); foot.setBackground(Ui.luxe(22)); foot.setPadding(Ui.dp(16), Ui.dp(14), Ui.dp(16), Ui.dp(14)); foot.setElevation(Ui.dp(6));
            LinearLayout tr = Ui.row(c); LinearLayout tl = Ui.col(c); tl.setLayoutParams(Ui.weight(1)); tl.addView(Ui.text(c, "مبلغ قابل پرداخت", 12, 0xCCF3F0E8, false)); cnt = Ui.text(c, "", 12, 0x99F3F0E8, false); tl.addView(cnt); tr.addView(tl); tot = Ui.text(c, Ui.money(0), 24, Ui.GOLD, true); tr.addView(tot); foot.addView(tr);
            LinearLayout br = Ui.row(c); br.setPadding(0, Ui.dp(8), 0, 0);
            android.widget.Button hold = Ui.btn(c, "نگه‌داشتن", 0x1AFFFFFF, 0xFFF3F0E8, this::hold); hold.setBackground(Ui.rounded(0x1AFFFFFF, 0x33FFFFFF, 14)); hold.setLayoutParams(Ui.margin(Ui.weight(1), 0, 0, 3, 0)); br.addView(hold);
            android.widget.Button held = Ui.btn(c, "نگه‌داشته‌ها", 0x1AFFFFFF, 0xFFF3F0E8, () -> a.open(new Held(a), true)); held.setBackground(Ui.rounded(0x1AFFFFFF, 0x33FFFFFF, 14)); held.setLayoutParams(Ui.margin(Ui.weight(1), 3, 0, 0, 0)); br.addView(held);
            foot.addView(br);
            View pay = Ui.cta(c, "پرداخت", this::pay); pay.setLayoutParams(Ui.margin(Ui.match(), 0, 8, 0, 0)); foot.addView(pay);
            root.addView(foot);
            return root;
        }
        public void load() {
            String restore = Prefs.get("pos_restore", "");
            if (!restore.isEmpty()) { Prefs.set("pos_restore", ""); restoreHeld(restore); }
            renderCart(); loadPosTaxConfig();
        }
        void loadPosTaxConfig() {
            if (Api.standalone()) { taxConfigured = true; return; }
            taxConfigured = Local.hasSetting("pos.tax_rate");
            Api.get("/pos/kiosk/config", result -> {
                if (result instanceof JSONObject) {
                    JSONObject config = (JSONObject) result;
                    if (!config.isNull("tax_rate")) {
                        Local.setSetting("pos.tax_rate", config.optString("tax_rate", "0"));
                        taxConfigured = true; renderCart(); return;
                    }
                }
                if (!Local.hasSetting("pos.tax_rate")) {
                    taxConfigured = true;
                    Ui.toast("نرخ مالیات ذخیره نشده؛ صندوق با نرخ صفر ادامه می‌دهد");
                }
            }, error -> {
                if (!Local.hasSetting("pos.tax_rate")) {
                    taxConfigured = true;
                    Ui.toast("نرخ مالیات از رایانه دریافت نشد؛ صندوق با نرخ صفر ادامه می‌دهد");
                }
            });
        }
        @Override public void refresh() { renderCart(); if (search != null) suggest(Ui.str(search)); }

        /* ---- search / add ---- */
        void suggest(String q) {
            sugg.removeAllViews(); if (q.length() < 2) return;
            List<JSONObject> local = Db.searchProducts(q, 8); showSugg(local);
            if (Api.online && !Api.standalone()) Api.get("/pos/search?q=" + Api.q(q) + "&limit=8", r -> { if (!q.equals(Ui.str(search))) return; JSONArray it = ((JSONObject) r).optJSONArray("items"); List<JSONObject> l = new ArrayList<>(); for (int i = 0; it != null && i < it.length(); i++) l.add(it.optJSONObject(i)); if (!l.isEmpty()) showSugg(l); }, e -> {});
        }
        void showSugg(List<JSONObject> list) {
            sugg.removeAllViews();
            if (list.isEmpty() && !"0".equals(Prefs.get("install_starter", "1")) && Db.catalogPending()) {
                sugg.addView(Ui.muted(c, "فهرست پیش‌فرض هنوز در پس‌زمینه بارگذاری می‌شود؛ پس از آماده‌شدن دوباره جست‌وجو کنید."));
                return;
            }
            for (JSONObject p : list) { double avail = p.optDouble("available_qty", 0); JSONArray bs = p.optJSONArray("batches"); double price = bs != null && bs.length() > 0 ? bs.optJSONObject(0).optDouble("sell_price", 0) : 0; sugg.addView(Ui.pitem(c, p, p.optString("name"), Ui.fa(p.optString("barcode")) + " · موجودی " + Ui.num(avail), Ui.money(price), avail > 0 ? Ui.TEXT : Ui.RED, () -> { add(p, null); search.setText(""); sugg.removeAllViews(); })); }
        }
        void onBarcode(String code) {
            code = Db.norm(code); if (pending != null) h.removeCallbacks(pending); search.setText(""); sugg.removeAllViews(); if (code.isEmpty()) return;
            JSONObject p = Db.productByBarcode(code);
            if (p != null && p.optJSONArray("batches") != null && p.optJSONArray("batches").length() > 0) { add(p, null); return; }
            final String bc = code;
            if (Api.online && !Api.standalone()) Api.get("/pos/search?q=" + Api.q(bc) + "&limit=1", r -> { JSONArray it = ((JSONObject) r).optJSONArray("items"); if (it != null && it.length() > 0 && bc.equals(it.optJSONObject(0).optString("barcode"))) add(it.optJSONObject(0), null); else notFound(bc); }, e -> notFound(bc));
            else if (p != null) Ui.toast("موجودی این کالا صفر است"); else notFound(bc);
        }
        void notFound(String bc) {
            if (!"0".equals(Prefs.get("install_starter", "1")) && Db.catalogPending()) {
                Ui.toast("فهرست پیش‌فرض هنوز در پس‌زمینه بارگذاری می‌شود؛ چند لحظه دیگر دوباره اسکن کنید.");
                return;
            }
            Ui.toast("کالایی با بارکد " + Ui.fa(bc) + " نیست");
            Ui.confirm(c, "کالای " + Ui.fa(bc) + " تعریف نشده. اکنون تعریف و دریافت شود؟", () -> a.open(new StockScreens.Receive(a, bc), true));
        }
        void add(JSONObject p, JSONObject batch) {
            JSONArray bs = p.optJSONArray("batches");
            if (bs == null || bs.length() == 0) { Sfx.play("error"); Ui.toast("این کالا موجودی ندارد"); return; }
            if (batch == null && bs.length() > 1) { chooseBatch(p, bs); return; }
            JSONObject b = batch != null ? batch : bs.optJSONObject(0);
            long pid = p.optLong("product_id", p.optLong("id")), bid = b.optLong("batch_id", b.optLong("id"));
            Sfx.play("add");
            for (JSONObject l : cart) if (l.optLong("product_id") == pid && l.optLong("batch_id") == bid) { try { l.put("quantity", l.optDouble("quantity") + 1); } catch (Exception ignore) {} renderCart(); return; }
            try { JSONObject l = new JSONObject(); l.put("product_id", pid); l.put("name", p.optString("name")); l.put("barcode", p.optString("barcode")); l.put("batch_id", bid); l.put("batch_number", b.optString("batch_number")); l.put("quantity", 1); l.put("price", b.optDouble("sell_price", b.optDouble("unit_sell_price", 0))); l.put("discount", 0); l.put("avail", b.optDouble("current_qty", 0)); l.put("expiry", b.isNull("expiry_date") ? "" : b.optString("expiry_date")); cart.add(0, l); } catch (Exception ignore) {}
            renderCart();
        }
        void chooseBatch(JSONObject p, JSONArray bs) {
            LinearLayout l = Ui.col(c); l.addView(Ui.muted(c, "چند بچ با قیمت/انقضای متفاوت موجود است. بچ پیشنهادی (FEFO) بالاست.")); Dialog[] d = new Dialog[1];
            Ui.paged(l, bs, 50, b -> Ui.item(c, Ui.money(b.optDouble("sell_price", b.optDouble("unit_sell_price", 0))) + (b.optBoolean("is_recommended") ? "  ★ پیشنهادی" : ""), "بچ " + Ui.fa(b.optString("batch_number")) + " · موجودی " + Ui.num(b.optDouble("current_qty")) + (b.isNull("expiry_date") ? "" : " · انقضا " + Ui.jdate(b.optString("expiry_date"))), null, 0, () -> { d[0].dismiss(); add(p, b); }));
            d[0] = Ui.sheet(c, p.optString("name"), l);
        }
        /* ---- v4.7.0: POS suggestions (both platforms, owner's rule) ---- */
        void refreshNudges() {
            if (nudgeBar == null) return;
            StringBuilder sb = new StringBuilder();
            for (JSONObject l : cart) { long id = l.optLong("product_id"); if (sb.indexOf(":" + id + ":") < 0) sb.append(':').append(id).append(':'); }
            String key = sb.toString();
            if (key.equals(nudgeKey)) return;
            nudgeKey = key;
            if (nudgePend != null) h.removeCallbacks(nudgePend);
            if (key.isEmpty()) { nudgeBar.setVisibility(View.GONE); nudgeBar.removeAllViews(); return; }
            nudgePend = () -> {
                applyDueDiscounts();   // v4.8.0 — تخفیف پله‌ای سررسیدشده پیش از نمایش قیمت‌ها اعمال شود
                final JSONArray ids = new JSONArray();
                for (JSONObject l : cart) ids.put(l.optLong("product_id"));
                JSONObject body = new JSONObject();
                try { body.put("product_ids", ids); } catch (Exception ignore) {}
                Api.Cb<Object> show = r -> {
                    if (nudgeBar == null) return;
                    JSONArray ns = (JSONArray) r;
                    nudgeBar.removeAllViews();
                    if (ns == null || ns.length() == 0) { nudgeBar.setVisibility(View.GONE); return; }
                    // v4.8.0 — ظاهر کارت «نجوا»: یک کارت آرام با نوار رنگی، نه یک نوار چسبیده
                    LinearLayout card = Ui.col(c);
                    card.setPadding(Ui.dp(12), Ui.dp(10), Ui.dp(12), Ui.dp(10));
                    card.setBackground(Ui.rounded(Ui.dark ? 0x228950FF : 0x148950FF, Ui.VIOLET, 16));
                    LinearLayout head = Ui.row(c); head.setGravity(Gravity.CENTER_VERTICAL);
                    head.addView(Icons.view(c, "star", Ui.GOLD, 16));
                    TextView lbl = Ui.text(c, "پیشنهاد به مشتری", 12.5f, Ui.VIOLET, true);
                    lbl.setPadding(Ui.dp(6), 0, Ui.dp(6), 0); lbl.setLayoutParams(Ui.weight(1)); head.addView(lbl);
                    JSONObject first = ns.optJSONObject(0);
                    if (first != null && first.optBoolean("near_expiry")) head.addView(Ui.badge(c, "⏰ " + Ui.num(first.optInt("days_left")) + " روز به انقضا", Ui.AMBER));
                    card.addView(head);
                    for (int i = 0; i < ns.length(); i++) {
                        JSONObject n = ns.optJSONObject(i);
                        if (n == null) continue;
                        boolean near = n.optBoolean("near_expiry");
                        String label = n.optString("name") + (near ? "  ⏰ " + Ui.num(n.optInt("days_left")) + " روز" : "");
                        android.widget.Button chip = Ui.small(c, label, () -> addFromNudge(n.optLong("product_id")));
                        chip.setTextColor(near ? Ui.AMBER : Ui.TEAL);
                        chip.setMinHeight(Ui.dp(38));
                        chip.setLayoutParams(Ui.margin(Ui.match(), 0, dp4(), 0, 0));
                        card.addView(chip);
                        if (!n.optString("reason", "").isEmpty()) {
                            LinearLayout note = Ui.row(c); note.setLayoutParams(Ui.margin(Ui.match(), 0, 0, 0, 6));
                            TextView t = Ui.body(c, n.optString("reason")); t.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 11.5f); t.setTextColor(Ui.MUTED);
                            note.addView(t); card.addView(note);
                        }
                    }
                    nudgeBar.addView(card);
                    nudgeBar.setVisibility(View.VISIBLE);
                };
                // v4.8.0 — گزارش مالک: «پیشنهاد صندوق روی گوشی نمی‌آمد». دلیلش این بود که
                // مسیر آفلاین فقط برای GET به Local برمی‌گشت؛ روی گوشیِ مستقل (یا وقتی
                // رایانه در دسترس نیست) POST بی‌پاسخ می‌ماند. حالا همان موتور محلی گوشی
                // جواب می‌دهد، با همان قواعد و همان فیلدها.
                if (Api.standalone()) { try { show.ok(Insights.nudges(ids)); } catch (Exception ignore) {} return; }
                Api.post("/insights/nudges", body, show, e -> { try { show.ok(Insights.nudges(ids)); } catch (Exception ignore) { nudgeBar.setVisibility(View.GONE); } });
            };
            h.postDelayed(nudgePend, 350);
        }

        static int dp4() { return Ui.dp(6); }

        /** v4.8.0 — پله‌های تخفیفی که موعدشان رسیده، پیش از فروش اعمال می‌شوند (هم‌تای سرور). */
        void applyDueDiscounts() { try { Insights.applyMarkdownSteps(); } catch (Exception ignore) {} }

        /** fetch the suggested product + its honest batch options, then add to the cart. */
        void addFromNudge(long pid) {
            Api.get("/products/" + pid, r -> {
                JSONObject p = (JSONObject) r;
                Api.get("/pos/batch-options/" + pid, rr -> {
                    JSONArray opts = ((JSONObject) rr).optJSONArray("options");
                    if (opts == null || opts.length() == 0) { Ui.toast("این کالا اکنون موجودی قابل فروش ندارد"); return; }
                    try { p.put("batches", opts); } catch (Exception ignore) {}
                    add(p, null);
                }, e -> Ui.toast("موجودی پیشنهاد در دسترس نیست"));
            }, e -> Ui.toast("پیشنهاد در دسترس نیست"));
        }

        /* ---- cart ---- */
        void renderBenefitsStrip() {
            if (benefitsStrip == null) return;
            benefitsStrip.removeAllViews();
            benefitsStrip.addView(Ui.pill(c, "user", "مشتری", customer != null, this::pickCustomer));
            benefitsStrip.addView(Ui.pill(c, "gift", coupon == null ? "کوپن" : "کوپن · " + coupon, coupon != null, this::askCoupon));
            String campaignLabel = campaign == null ? "جشنواره" : "جشنواره · " + campaign.optString("name");
            benefitsStrip.addView(Ui.pill(c, "gift", campaignLabel, campaign != null, this::askCampaign));
            benefitsStrip.addView(Ui.pill(c, "percent", "تخفیف", invoiceDiscount > 0, this::askDiscount));
        }
        double amountBeforeBenefits() {
            double amount = 0;
            for (JSONObject line : cart) amount += line.optDouble("quantity") * line.optDouble("price") - line.optDouble("discount");
            return Math.max(0, amount - invoiceDiscount);
        }
        JSONObject campaignRequest() throws Exception {
            JSONObject request = new JSONObject(); JSONArray productIds = new JSONArray(); JSONObject lineAmounts = new JSONObject();
            for (JSONObject line : cart) {
                long productId = line.optLong("product_id");
                if (productId > 0) productIds.put(productId);
                String key = String.valueOf(productId);
                double lineAmount = line.optDouble("quantity") * line.optDouble("price") - line.optDouble("discount");
                lineAmounts.put(key, lineAmounts.optDouble(key) + lineAmount);
            }
            request.put("amount", amountBeforeBenefits()); request.put("product_ids", productIds);
            request.put("line_amounts", lineAmounts); request.put("include_auto_apply", true);
            if (customer != null) request.put("customer_id", customer.optLong("id"));
            return request;
        }
        String benefitsKey() {
            StringBuilder key = new StringBuilder();
            key.append(customer == null ? 0 : customer.optLong("id")).append('|').append(coupon == null ? "" : coupon).append('|')
                    .append(campaign == null ? 0 : campaign.optLong("campaign_id")).append('|').append(invoiceDiscount);
            for (JSONObject line : cart) key.append('|').append(line.optLong("product_id")).append(':').append(line.optLong("batch_id"))
                    .append(':').append(line.optDouble("quantity")).append(':').append(line.optDouble("price")).append(':').append(line.optDouble("discount"));
            return key.toString();
        }
        void requestBenefitData(String path, JSONObject request, Api.Cb<Object> ok, Api.ErrCb error) {
            boolean needsLocal = customer != null && customer.optLong("id") < 0;
            for (JSONObject line : cart) if (line.optLong("product_id") <= 0) needsLocal = true;
            if (needsLocal && !Api.standalone()) {
                Api.bg(() -> {
                    try { Object response = Local.handle("POST", path, request.toString()); Api.ui(() -> ok.ok(response)); }
                    catch (Api.ApiError e) { Api.ui(() -> error.err(e)); }
                });
            } else Api.post(path, request, ok, error);
        }
        /** build-501 — تخفیف مزایا هرگز NaN نمی‌شود (کلید غایب/NULL → صفر)؛ جلوی «Forbidden numeric value» گرفته می‌شود. */
        static double finBenefit(double v) { return Double.isFinite(v) && v > 0 ? v : 0; }
        void refreshBenefits() {
            if (cart.isEmpty()) return;
            String requestedKey = benefitsKey();
            if (requestedKey.equals(resolvedBenefitsKey) || requestedKey.equals(pendingBenefitsKey)) return;
            pendingBenefitsKey = requestedKey;
            final JSONObject campaignQuery;
            try { campaignQuery = campaignRequest(); }
            catch (Exception e) { pendingBenefitsKey = ""; return; }
            requestBenefitData("/pos/campaigns/eligible", campaignQuery, result -> {
                if (!requestedKey.equals(benefitsKey())) {
                    if (requestedKey.equals(pendingBenefitsKey)) pendingBenefitsKey = "";
                    refreshBenefits(); return;
                }
                JSONObject response = result instanceof JSONObject ? (JSONObject) result : new JSONObject();
                JSONArray offers = response.optJSONArray("campaigns");
                JSONObject selected = null, auto = null;
                for (int i = 0; offers != null && i < offers.length(); i++) {
                    JSONObject offer = offers.optJSONObject(i); if (offer == null) continue;
                    if (campaign != null && offer.optLong("campaign_id") == campaign.optLong("campaign_id")) selected = offer;
                    if (offer.optBoolean("auto_apply") && (auto == null
                            || offer.optInt("priority", 3) < auto.optInt("priority", 3)
                            || (offer.optInt("priority", 3) == auto.optInt("priority", 3)
                            && finBenefit(offer.optDouble("discount", 0)) > finBenefit(auto.optDouble("discount", 0))))) auto = offer;
                }
                if (campaign != null) {
                    if (selected == null) { campaign = null; campaignDiscount = 0; }
                    else { campaign = selected; campaignDiscount = finBenefit(selected.optDouble("discount", 0)); }
                }
                if (campaign == null && auto != null) {
                    if (couponDiscount > 0 && !auto.optBoolean("stackable")) {
                        coupon = null; couponDiscount = 0;
                        Ui.toast("جشنوارهٔ خودکار با کوپن قابل ترکیب نیست؛ کوپن حذف شد");
                    }
                    campaign = auto; campaignDiscount = finBenefit(auto.optDouble("discount", 0));
                }
                String[] expected = {benefitsKey()}; pendingBenefitsKey = expected[0];
                if (coupon == null) {
                    if (expected[0].equals(benefitsKey())) resolvedBenefitsKey = expected[0];
                    pendingBenefitsKey = ""; renderCart(); return;
                }
                JSONObject couponQuery = j("code", coupon); putNum(couponQuery, "amount", amountBeforeBenefits());
                if (customer != null) {
                    putNum(couponQuery, "customer_id", customer.optLong("id"));
                    try { couponQuery.put("customer_phone", customer.optString("phone")); }
                    catch (Exception e) { pendingBenefitsKey = ""; return; }
                }
                requestBenefitData("/marketing/coupons/validate", couponQuery, couponResult -> {
                    if (!expected[0].equals(benefitsKey())) {
                        if (expected[0].equals(pendingBenefitsKey)) pendingBenefitsKey = "";
                        refreshBenefits(); return;
                    }
                    JSONObject validation = couponResult instanceof JSONObject ? (JSONObject) couponResult : new JSONObject();
                    if (validation.optBoolean("valid", validation.optBoolean("ok", false)))
                        couponDiscount = finBenefit(validation.optDouble("discount", 0));
                    else { coupon = null; couponDiscount = 0; }
                    resolvedBenefitsKey = benefitsKey(); pendingBenefitsKey = ""; renderCart();
                }, error -> {
                    if (expected[0].equals(pendingBenefitsKey)) pendingBenefitsKey = "";
                    Ui.toast("بررسی کوپن انجام نشد: " + error.getMessage());
                });
            }, error -> {
                if (requestedKey.equals(pendingBenefitsKey)) pendingBenefitsKey = "";
                Ui.toast("بررسی جشنواره انجام نشد: " + error.getMessage());
            });
        }
        /* ---- cart ---- */
        void renderCart() {
            lines.removeAllViews(); double total = 0, n = 0;
            refreshNudges();   // v4.7.0 — suggestions follow the cart, on the phone like on Windows
            if (cart.isEmpty()) lines.addView(Ui.empty(c, "سبد خالی است — کالا را جست‌وجو یا اسکن کنید"));
            for (JSONObject l : cart) {
                double q = l.optDouble("quantity", 1), pr = l.optDouble("price", 0), disc = l.optDouble("discount", 0); double sub = q * pr - disc; total += sub; n += q;
                LinearLayout row = Ui.col(c); row.setBackground(Ui.surface(18)); row.setPadding(Ui.dp(12), Ui.dp(10), Ui.dp(12), Ui.dp(10)); row.setLayoutParams(Ui.margin(Ui.match(), 0, 0, 0, 8));
                LinearLayout r1 = Ui.row(c);
                android.widget.ImageView ic = Ui.thumb(c, Db.productById(l.optLong("product_id")) == null ? l : Db.productById(l.optLong("product_id")), 40); r1.addView(ic);
                LinearLayout nc = Ui.col(c); nc.setLayoutParams(Ui.weight(1)); nc.addView(Ui.text(c, l.optString("name"), 14, Ui.TEXT, true));
                nc.addView(Ui.muted(c, Ui.money(pr) + " × " + Ui.num(q) + (disc > 0 ? " − تخفیف " + Ui.money(disc) : "") + (l.optString("expiry").isEmpty() ? "" : " · انقضا " + Ui.jdate(l.optString("expiry"))))); r1.addView(nc);
                r1.addView(Ui.text(c, Ui.money(sub), 14, Ui.TEXT, true)); row.addView(r1);
                LinearLayout r2 = Ui.row(c); r2.setPadding(0, Ui.dp(4), 0, 0);
                r2.addView(qbtn("−", () -> { double nq = q - 1; if (nq <= 0) cart.remove(l); else set(l, "quantity", nq); renderCart(); }));
                TextView qt = Ui.text(c, Ui.num(q), 15, Ui.TEXT, true); qt.setGravity(Gravity.CENTER); qt.setMinWidth(Ui.dp(44)); qt.setOnClickListener(v -> Ui.prompt(c, "تعداد / مقدار", "مثلاً 2 یا 1.5 (کیلوگرم)", true, s -> { try { double nq = Double.parseDouble(Db.norm(s)); if (nq > 0) { set(l, "quantity", nq); renderCart(); } } catch (Exception ignore) {} })); r2.addView(qt);
                r2.addView(qbtn("+", () -> { if (q + 1 > l.optDouble("avail", 1e9) && l.optDouble("avail", 0) > 0) Ui.toast("بیش از موجودی بچ (" + Ui.num(l.optDouble("avail")) + ")"); set(l, "quantity", q + 1); renderCart(); }));
                View sp = new View(c); sp.setLayoutParams(Ui.weight(1)); r2.addView(sp);
                r2.addView(Ui.small(c, "تخفیف", () -> Ui.prompt(c, "تخفیف این ردیف (مبلغ)", "0", true, s -> { try { set(l, "discount", Math.max(0, Double.parseDouble(Db.norm(s).isEmpty() ? "0" : Db.norm(s)))); } catch (Exception ignore) {} renderCart(); })));
                r2.addView(Ui.small(c, "حذف", () -> { cart.remove(l); renderCart(); }));
                row.addView(r2); lines.addView(row);
            }
            total = Math.max(0, total - invoiceDiscount - couponDiscount - campaignDiscount);
            double tax = 0; String taxError = "";
            try { tax = taxAmount(total); }
            catch (NumberFormatException invalidRate) { taxError = " · نرخ مالیات صندوق نامعتبر است"; }
            tot.setText(Ui.money(total + tax));
            cnt.setText(Ui.num(cart.size()) + " قلم · " + Ui.num(n)
                    + (invoiceDiscount > 0 ? " · تخفیف فاکتور " + Ui.money(invoiceDiscount) : "")
                    + (couponDiscount > 0 ? " · کوپن −" + Ui.money(couponDiscount) : "")
                    + (campaignDiscount > 0 ? " · جشنواره −" + Ui.money(campaignDiscount) : "")
                    + (tax > 0 ? " · مالیات " + Ui.money(tax) : "") + taxError);
            custTxt.setText(customer == null ? "مشتری آزاد (بدون ثبت)" : "مشتری: " + customer.optString("name") + " " + Screens.Screen.s(customer, "last_name") + " · " + Ui.fa(customer.optString("phone")));
            renderBenefitsStrip(); refreshBenefits();
        }
        View qbtn(String s, Runnable r) { TextView t = Ui.text(c, s, 18, "+".equals(s) ? Color.WHITE : Ui.TEXT, true); t.setGravity(Gravity.CENTER); t.setBackground(Ui.rounded("+".equals(s) ? Ui.PRIMARY : Ui.CARD2, "+".equals(s) ? 0 : Ui.BORDER, 10)); t.setLayoutParams(Ui.lp(Ui.dp(36), Ui.dp(34))); t.setOnClickListener(v -> r.run()); return t; }
        static void set(JSONObject o, String k, double v) { try { o.put(k, v); } catch (Exception ignore) {} }
        double total() { return Math.max(0, amountBeforeBenefits() - couponDiscount - campaignDiscount); }
        double taxRate() {
            String raw = Db.norm(Local.setting("pos.tax_rate", "0"));
            double rate = raw.isEmpty() ? 0 : Double.parseDouble(raw);
            if (!Double.isFinite(rate) || rate < 0) throw new NumberFormatException("invalid POS tax rate");
            return rate;
        }
        double taxAmount(double taxable) {
            double tax = Math.floor((Math.max(0, taxable) * taxRate() / 100.0) * 100.0 + 0.5) / 100.0;
            if (!Double.isFinite(tax)) throw new NumberFormatException("invalid POS tax amount");
            return tax;
        }
        double payableTotal() { double base = total(); return base + taxAmount(base); }

        /* ---- customer / coupon / discount ---- */
        void pickCustomer() {
            LinearLayout l = Ui.col(c); EditText q = Ui.input(c, "نام یا شماره موبایل…"); l.addView(q); LinearLayout res = Ui.col(c); l.addView(res); Dialog[] d = new Dialog[1];
            l.addView(Ui.ghost(c, "مشتری آزاد (بدون ثبت)", () -> { customer = null; d[0].dismiss(); renderCart(); }));
            l.addView(Ui.primary(c, "ثبت مشتری جدید", () -> { d[0].dismiss(); newCustomer(Ui.str(q), cu -> { customer = cu; renderCart(); }); }));
            // build-501 — بازسازی ۲۰۰ ردیف در هر حرف تایپ، حافظه را می‌خورد (OOM در pickCustomer)؛
            // اکنون: debounce ۲۵۰ms + سقف ۳۰ ردیف + آزادسازی کش تصاویر در صورت فشار حافظه.
            final android.os.Handler debounce = new android.os.Handler(android.os.Looper.getMainLooper());
            final Runnable[] pending = {null};
            Runnable fill = () -> {
                try {
                    res.removeAllViews();
                    java.util.List<JSONObject> found = Db.customers(Ui.str(q));
                    int n = Math.min(30, found.size());
                    for (int i = 0; i < n; i++) { JSONObject cu = found.get(i); res.addView(Ui.item(c, cu.optString("name") + " " + s(cu, "last_name"), Ui.fa(cu.optString("phone")), null, 0, () -> { customer = cu; d[0].dismiss(); renderCart(); })); }
                    if (found.size() > n) res.addView(Ui.muted(c, "برای یافتن مشتری دقیق‌تر، جست‌وجو را کامل‌تر کنید (" + Ui.fa(String.valueOf(found.size())) + " نتیجه)"));
                    if (found.isEmpty()) res.addView(Ui.muted(c, "مشتری‌ای یافت نشد — «ثبت مشتری جدید» را بزنید"));
                } catch (OutOfMemoryError mem) {
                    Images.MEM.evictAll(); Ui.tileCacheClear();
                    res.removeAllViews(); res.addView(Ui.muted(c, "حافظهٔ گوشی پر شد — عبارت کوتاه‌تری جست‌وجو کنید"));
                }
            };
            Runnable debounced = () -> { if (pending[0] != null) debounce.removeCallbacks(pending[0]); pending[0] = fill; debounce.postDelayed(fill, 250); };
            q.addTextChangedListener(new TextWatcher() { public void beforeTextChanged(CharSequence s, int i, int i1, int i2) {} public void onTextChanged(CharSequence s, int i, int i1, int i2) {} public void afterTextChanged(Editable e) { debounced.run(); } });
            try { fill.run(); } catch (Throwable firstPaint) { /* اولین پرکردن هم محافظت می‌شود */ }
            d[0] = Ui.sheet(c, "انتخاب مشتری", l);
        }
        void newCustomer(String prefill, java.util.function.Consumer<JSONObject> cb) { Customers.newCustomer(a, prefill, cb); }
        void askCoupon() {
            Ui.prompt(c, "کد کوپن", "مثلاً WELCOME10", false, code -> {
                if (code.isEmpty()) { coupon = null; couponDiscount = 0; renderCart(); return; }
                if (campaign != null && !campaign.optBoolean("stackable")) {
                    Ui.toast("این جشنواره با کوپن قابل ترکیب نیست؛ ابتدا جشنواره را حذف کنید"); return;
                }
                JSONObject request = j("code", code); putNum(request, "amount", amountBeforeBenefits());
                if (customer != null) {
                    putNum(request, "customer_id", customer.optLong("id"));
                    try { request.put("customer_phone", customer.optString("phone")); } catch (Exception e) { Ui.toast("اطلاعات مشتری خوانده نشد"); return; }
                }
                requestBenefitData("/marketing/coupons/validate", request, result -> {
                    JSONObject validation = (JSONObject) result;
                    if (validation.optBoolean("valid", validation.optBoolean("ok", false))) {
                        coupon = validation.optString("code", code).toUpperCase(java.util.Locale.ROOT);
                        couponDiscount = validation.optDouble("discount", 0);
                        Ui.toast("کوپن معتبر: " + Ui.money(couponDiscount));
                    } else {
                        coupon = null; couponDiscount = 0;
                        Ui.toast(s(validation, "reason", s(validation, "message", "کوپن معتبر نیست")));
                    }
                    renderCart();
                }, error -> Ui.toast(error.getMessage()));
            });
        }
        void askCampaign() {
            if (cart.isEmpty()) { Ui.toast("سبد خالی است؛ ابتدا کالا اضافه کنید"); return; }
            final JSONObject request;
            try { request = campaignRequest(); request.put("include_auto_apply", false); }
            catch (Exception e) { Ui.toast("اطلاعات سبد برای بررسی جشنواره آماده نشد"); return; }
            requestBenefitData("/pos/campaigns/eligible", request, result -> {
                JSONObject response = result instanceof JSONObject ? (JSONObject) result : new JSONObject();
                JSONArray offers = response.optJSONArray("campaigns");
                if (offers == null || offers.length() == 0) { Ui.toast("جشنوارهٔ واجد شرایطی برای این سبد فعال نیست"); return; }
                LinearLayout content = Ui.col(c); content.addView(Ui.muted(c, "فقط جشنواره‌های سازگار با همین سبد نمایش داده می‌شوند؛ شرایط هنگام ثبت فروش دوباره بررسی می‌شود."));
                Dialog[] sheet = new Dialog[1];
                for (int i = 0; i < offers.length(); i++) {
                    JSONObject offer = offers.optJSONObject(i); if (offer == null) continue;
                    String title = offer.optString("name") + (offer.optBoolean("auto_apply") ? " · خودکار" : "");
                    String detail = ("PERCENT".equalsIgnoreCase(offer.optString("discount_type"))
                            ? Ui.num(offer.optDouble("discount_value")) + "٪ تخفیف" : "تخفیف ثابت")
                            + " · حداقل خرید " + Ui.money(offer.optDouble("min_purchase"));
                    content.addView(Ui.item(c, title, detail, "−" + Ui.money(offer.optDouble("discount")), Ui.GREEN, () -> {
                        Runnable apply = () -> {
                            campaign = offer; campaignDiscount = offer.optDouble("discount");
                            if (sheet[0] != null) sheet[0].dismiss(); renderCart();
                        };
                        if (couponDiscount > 0 && !offer.optBoolean("stackable"))
                            Ui.confirm(c, "این جشنواره با کوپن قابل ترکیب نیست. کوپن حذف و جشنواره اعمال شود؟", () -> {
                                coupon = null; couponDiscount = 0; apply.run();
                            });
                        else apply.run();
                    }));
                }
                if (campaign != null && !campaign.optBoolean("auto_apply")) content.addView(Ui.ghost(c, "حذف جشنوارهٔ انتخاب‌شده", () -> {
                    campaign = null; campaignDiscount = 0;
                    if (sheet[0] != null) sheet[0].dismiss(); renderCart();
                }));
                sheet[0] = Ui.sheet(c, "جشنواره‌های قابل اعمال", content);
            }, error -> Ui.toast(error.getMessage()));
        }
        void askDiscount() { Ui.prompt(c, "تخفیف کل فاکتور (مبلغ)", "0", true, s -> { try { invoiceDiscount = Math.max(0, Double.parseDouble(Db.norm(s).isEmpty() ? "0" : Db.norm(s))); } catch (Exception e) { invoiceDiscount = 0; } renderCart(); }); }

        /* ---- hold / restore (up to 10, listed with time, re-openable) ---- */
        void hold() {
            if (cart.isEmpty()) { Ui.toast("سبد خالی است"); return; }
            try { JSONArray held = new JSONArray(Prefs.get("pos_held", "[]")); JSONArray keep = new JSONArray(); for (int i = 0; i < held.length(); i++) if (!held.optJSONObject(i).optString("id").equals(heldId)) keep.put(held.optJSONObject(i));
                if (keep.length() >= HELD_MAX) { Ui.toast("حداکثر " + Ui.fa("10") + " فاکتور نگه‌داشته"); return; }
                JSONObject hjson = new JSONObject(); hjson.put("id", heldId != null ? heldId : "h" + System.currentTimeMillis()); hjson.put("at", Db.now()); hjson.put("cart", new JSONArray(cart)); hjson.put("customer", customer == null ? JSONObject.NULL : customer); hjson.put("coupon", coupon == null ? JSONObject.NULL : coupon); hjson.put("coupon_discount", couponDiscount); hjson.put("campaign", campaign == null ? JSONObject.NULL : campaign); hjson.put("campaign_discount", campaignDiscount); hjson.put("invoice_discount", invoiceDiscount); hjson.put("total", total()); hjson.put("label", cart.get(0).optString("name") + (cart.size() > 1 ? " و " + Ui.num(cart.size() - 1) + " قلم دیگر" : "")); keep.put(hjson);
                Prefs.set("pos_held", keep.toString()); cart.clear(); customer = null; coupon = null; couponDiscount = 0; campaign = null; campaignDiscount = 0; invoiceDiscount = 0; resolvedBenefitsKey = ""; pendingBenefitsKey = ""; heldId = null; renderCart(); Sfx.play("hold"); Ui.toast("فاکتور نگه داشته شد (" + Ui.num(keep.length()) + ")");
            } catch (Exception e) { Ui.toast("خطا در نگه‌داشتن"); }
        }
        void restoreHeld(String id) {
            Sfx.play("resume"); try { JSONArray held = new JSONArray(Prefs.get("pos_held", "[]")); for (int i = 0; i < held.length(); i++) { JSONObject hj = held.optJSONObject(i); if (hj.optString("id").equals(id)) { cart.clear(); JSONArray ca = hj.optJSONArray("cart"); for (int k = 0; ca != null && k < ca.length(); k++) cart.add(ca.optJSONObject(k)); customer = hj.optJSONObject("customer"); coupon = hj.isNull("coupon") ? null : hj.optString("coupon"); couponDiscount = hj.optDouble("coupon_discount", 0); campaign = hj.optJSONObject("campaign"); campaignDiscount = hj.optDouble("campaign_discount", 0); invoiceDiscount = hj.optDouble("invoice_discount", 0); resolvedBenefitsKey = ""; pendingBenefitsKey = ""; heldId = id; } } } catch (Exception ignore) {}
        }
        static void removeHeld(String id) { try { JSONArray held = new JSONArray(Prefs.get("pos_held", "[]")); JSONArray keep = new JSONArray(); for (int i = 0; i < held.length(); i++) if (!held.optJSONObject(i).optString("id").equals(id)) keep.put(held.optJSONObject(i)); Prefs.set("pos_held", keep.toString()); } catch (Exception ignore) {} }

        String smsPhone = null;
        /* ---- payment ---- */
        void pay() {
            if (cart.isEmpty()) { Ui.toast("سبد خالی است"); return; }
            if (!taxConfigured) { Ui.toast("در حال دریافت نرخ مالیات صندوق؛ چند لحظه دیگر دوباره پرداخت را بزنید"); loadPosTaxConfig(); return; }
            String key = benefitsKey();
            if (!key.equals(resolvedBenefitsKey)) {
                if (key.equals(pendingBenefitsKey)) { Ui.toast("در حال بررسی کوپن و جشنواره؛ لحظه‌ای صبر کنید"); return; }
                // build-500 — خطای بررسی مزایا هرگز نباید فروش را ببندد: سرور همان
                // لحظه در /pos/checkout کوپن و جشنواره را دوباره راستی‌آزمایی می‌کند؛
                // جدول پرداخت بی‌درنگ باز می‌شود و بررسی در پس‌زمینه ادامه می‌یابد.
                refreshBenefits();
            }
            double total;
            try { total = payableTotal(); }
            catch (NumberFormatException invalidRate) { Ui.toast("نرخ مالیات صندوق در تنظیمات نامعتبر است"); return; }
            LinearLayout l = Ui.col(c); Dialog[] d = new Dialog[1];
            TextView tt = Ui.text(c, Ui.money(total), 24, Ui.TEXT, true); tt.setGravity(Gravity.CENTER); l.addView(tt);
            l.addView(Ui.muted(c, customer == null ? "مشتری آزاد" : "مشتری: " + customer.optString("name")));
            String[] methods = {"CASH", "CARD", "TRANSFER"}; String[] labels = {"نقدی", "کارت‌خوان", "کارت‌به‌کارت"}; final String[] chosen = {"CASH"}; Ui.Flow chips = Ui.wrap(c); chips.setPadding(0, Ui.dp(8), 0, Ui.dp(8));
            Runnable[] redraw = new Runnable[1]; redraw[0] = () -> { chips.removeAllViews(); for (int i = 0; i < methods.length; i++) { final String m = methods[i]; chips.addView(Ui.chip(c, labels[i], m.equals(chosen[0]), () -> { chosen[0] = m; redraw[0].run(); })); } if (customer != null) chips.addView(Ui.chip(c, "نسیه (دفتر حساب)", "CREDIT".equals(chosen[0]), () -> { chosen[0] = "CREDIT"; redraw[0].run(); })); }; redraw[0].run(); l.addView(chips);
            l.addView(Ui.label(c, "مبلغ دریافتی (برای محاسبهٔ باقی‌مانده)")); EditText paid = Ui.input(c, Ui.num(total), true); l.addView(paid); TextView change = Ui.muted(c, ""); l.addView(change);
            paid.addTextChangedListener(new TextWatcher() { public void beforeTextChanged(CharSequence s, int i, int i1, int i2) {} public void onTextChanged(CharSequence s, int i, int i1, int i2) {} public void afterTextChanged(Editable e) { double p = Ui.numVal(paid, total); change.setText(p >= total ? "باقی‌مانده به مشتری: " + Ui.money(p - total) : "کسری: " + Ui.money(total - p) + (customer == null ? " (برای نسیه، مشتری انتخاب کنید)" : " → در دفتر حساب ثبت می‌شود")); } });
            // v2.4: SMS phone is asked on EVERY checkout — pre-filled from the chosen customer; empty = no SMS
            l.addView(Ui.label(c, "موبایل مشتری برای پیامک فاکتور" + (SmsLocal.configured() || !Api.standalone() ? "" : " (سرویس پیامک تنظیم نشده)")));
            EditText phone = Ui.input(c, "09xxxxxxxxx — خالی = بدون پیامک", true); if (customer != null) phone.setText(customer.optString("phone")); else phone.setText(Prefs.get("pos_last_phone", "")); l.addView(phone);
            l.addView(Ui.success(c, "ثبت فاکتور", () -> { d[0].dismiss(); smsPhone = Db.norm(Ui.str(phone)); Prefs.set("pos_last_phone", ""); checkout(chosen[0], Math.min(total, Ui.numVal(paid, total)), total); }));
            d[0] = Ui.sheet(c, "پرداخت", l);
        }
        void checkout(String method, double paidAmt, double total) {
            try {
                // build-501 — هیچ عدد NaN/منفی به موتور فروش محلی یا رایانه نمی‌رود
                if (!Double.isFinite(total) || total < 0) { Ui.toast("مبلغ فاکتور نامعتبر است؛ سبد را بازبینی کنید"); return; }
                if (!Double.isFinite(paidAmt) || paidAmt < 0) paidAmt = 0;
                JSONObject body = new JSONObject(); JSONArray items = new JSONArray();
                for (JSONObject l : cart) { JSONObject it = new JSONObject(); it.put("product_id", l.optLong("product_id")); it.put("barcode", l.optString("barcode")); it.put("quantity", Math.max(0, l.optDouble("quantity", 1))); it.put("price", Math.max(0, l.optDouble("price", 0))); if (l.optLong("batch_id") > 0) it.put("batch_id", l.optLong("batch_id")); it.put("discount", Math.max(0, l.optDouble("discount", 0))); items.put(it); }
                body.put("items", items); JSONArray pays = new JSONArray(); JSONObject p = new JSONObject();
                boolean credit = "CREDIT".equals(method) || (paidAmt < total && customer != null);
                if (credit) { if (paidAmt > 0) { p.put("method", "CASH"); p.put("amount", paidAmt); pays.put(p); } JSONObject cr = new JSONObject(); cr.put("method", "CREDIT"); cr.put("amount", total - paidAmt); pays.put(cr); } else { p.put("method", method); p.put("amount", total); pays.put(p); }
                body.put("payments", pays); if (customer != null) { body.put("customer_id", customer.optLong("id")); body.put("customer_phone", customer.optString("phone")); body.put("customer_name", customer.optString("name")); }
                if (coupon != null) body.put("coupon_code", coupon);
                body.put("coupon_discount", couponDiscount);
                if (campaign != null) {
                    body.put("campaign_id", campaign.optLong("campaign_id"));
                    body.put("campaign_name", campaign.optString("name"));
                    body.put("campaign_discount", campaignDiscount);
                    body.put("campaign_local", campaign.optBoolean("_local"));
                }
                if (invoiceDiscount > 0) body.put("invoice_discount", invoiceDiscount);
                double taxRate = taxRate(); body.put("tax_rate", taxRate); body.put("tax", taxAmount(total()));
                body.put("open_drawer", false);
                String ph = smsPhone != null && !smsPhone.isEmpty() ? smsPhone : (customer == null ? "" : customer.optString("phone"));
                if (!ph.isEmpty()) { body.put("customer_phone", ph); if (customer == null) { body.put("customer_name", "مشتری " + ph); { JSONObject cu = Db.customerByPhone(ph); if (cu == null) cu = Db.localCustomer("مشتری " + ph, ph); body.put("customer_id", cu.optLong("id")); } } }   // v3.1: always file the number in the customer book (phone + PC) so the next visit is recognised
                // local-first: apply on the phone immediately (with the phone-book customer attached), then push
                String no;
                if (Api.standalone() || !Api.online) {
                    JSONObject stored = (JSONObject) Local.handle("POST", "/pos/checkout", body.toString());
                    no = stored.optString("local_no", stored.optString("invoice_number"));
                } else no = Db.localSale(body, total);
                if (no.isEmpty()) throw new IllegalStateException("شمارهٔ فاکتور محلی ساخته نشد");
                if (heldId != null) removeHeld(heldId);
                String issuedCouponCodes = Local.issuedCouponCodesForInvoice(no);
                // v2.3: invoice SMS the moment the sale is confirmed — from the phone itself when there is no PC
                try {
                if (!ph.isEmpty() && SmsLocal.sendInvoiceOn() && SmsLocal.phoneShouldSend()) { if (SmsLocal.configured()) { String text = SmsLocal.patternMode() ? SmsLocal.renderInvoiceShort(no, total) : SmsLocal.renderInvoice(no, total); if (!issuedCouponCodes.isEmpty()) text += "\nکد تخفیف خرید بعدی: " + issuedCouponCodes; SmsLocal.enqueueAndSend(ph, text, no); } else Ui.toast("پیامک ارسال نشد: سرویس پیامک را در تنظیمات → پیامک تنظیم کنید"); }
                } catch (Exception smsError) { Ui.toast("فروش ثبت شد؛ ساخت پیامک ناموفق بود: " + smsError.getMessage()); }
                smsPhone = null;
                Sync.queue("POS_CHECKOUT", Db.localInvoicePayload(no), "فاکتور " + no + " · " + Ui.money(total), no);
                cart.clear(); customer = null; coupon = null; couponDiscount = 0; campaign = null; campaignDiscount = 0; invoiceDiscount = 0; resolvedBenefitsKey = ""; pendingBenefitsKey = ""; heldId = null; renderCart();
                Ui.done(a, "فروش ثبت شد", "فاکتور " + Ui.fa(no) + " · " + Ui.money(total)
                        + (issuedCouponCodes.isEmpty() ? "" : "\nکد تخفیف خرید بعدی: " + issuedCouponCodes), null);
            } catch (Exception e) {
                // build-501 — پیام خام org.json («Forbidden numeric value») به کاربر نمایش داده نمی‌شود
                String m = String.valueOf(e.getMessage());
                if (m.contains("Forbidden numeric") || m.contains("NaN")) Ui.toast("ثبت فروش ناموفق: مبلغی در سبد نامعتبر است — سطرها را بازبینی کنید");
                else Ui.toast("خطا: " + m);
            }
        }
    }

    /* ---------------- Held invoices ---------------- */
    public static final class Held extends Screens.Screen {
        Held(AppActivity a) { super(a); }
        public String key() { return "held"; } public String title() { return "فاکتورهای نگه‌داشته"; }
        public void load() {
            clear(); try { JSONArray held = new JSONArray(Prefs.get("pos_held", "[]")); if (held.length() == 0) { body.addView(Ui.empty(c, "فاکتور نگه‌داشته‌ای نیست. در صندوق «نگه‌داشتن» را بزنید.")); return; }
                body.addView(Ui.muted(c, Ui.num(held.length()) + " از " + Ui.fa("10") + " — برای بازگردانی ضربه بزنید"));
                for (int i = held.length() - 1; i >= 0; i--) { JSONObject hj = held.optJSONObject(i); JSONObject cu = hj.optJSONObject("customer"); String id = hj.optString("id");
                    LinearLayout it = Ui.item(c, hj.optString("label"), Ui.jdate(hj.optString("at")) + (cu == null ? " · مشتری آزاد" : " · " + cu.optString("name")) + " · " + Ui.num(hj.optJSONArray("cart").length()) + " قلم", Ui.money(hj.optDouble("total")), Ui.PRIMARY, () -> { Prefs.set("pos_restore", id); a.route("pos"); });
                    it.setOnLongClickListener(v -> { Ui.confirm(c, "این فاکتور نگه‌داشته حذف شود؟", () -> { Pos.removeHeld(id); load(); }); return true; }); body.addView(it); }
                body.addView(Ui.muted(c, "نگه‌داشتن طولانی روی هر مورد → حذف"));
            } catch (Exception e) { body.addView(Ui.empty(c, "—")); }
        }
    }

    /* ---------------- Invoices: list, detail, void, return, receipt ---------------- */
    public static final class Invoices extends Screens.Screen {
        int tab = 0;
        Invoices(AppActivity a) { super(a); }
        public String key() { return "invoices"; } public String title() { return "فاکتورها"; }
        public boolean autoRefresh() { return tab == 0; }
        public void load() {
            clear(); body.addView(tabs(new String[]{Api.standalone() ? "همهٔ فاکتورها (ابطال / مرجوعی)" : "فاکتورهای رایانه", "فاکتورهای این گوشی"}, tab, t -> { tab = t; load(); }));
            if (tab == 1) { java.util.List<JSONObject> li = Db.localInvoices(); LinearLayout ll = Ui.col(c); body.addView(ll); Ui.paged(ll, li.size(), 40, ix -> { JSONObject o = li.get(ix); return Ui.item(c, Ui.fa(o.optString("local_no")) + (o.optInt("synced") == 1 ? " ← " + Ui.fa(s(o, "invoice_number")) : ""), Ui.jdate(o.optString("at")) + " · " + Ui.num(o.optInt("items")) + " قلم · " + label(o.optString("payment"), PAY), Ui.money(o.optDouble("total")), o.optInt("synced") == 1 ? Ui.GREEN : Ui.AMBER, () -> a.open(new LocalInvoiceDetail(a, o.optLong("id")), true)); }); if (li.isEmpty()) body.addView(Ui.empty(c, "هنوز فاکتوری روی این گوشی ثبت نشده")); return; }
            body.addView(Ui.empty(c, "…")); get("/invoices?limit=400", r -> { body.removeViewAt(body.getChildCount() - 1); JSONArray ar = arr(r); if (ar.length() == 0) body.addView(Ui.empty(c, "فاکتوری نیست")); LinearLayout list = Ui.col(c); body.addView(list);
                // v3.5 — staged: 40 rows per page, next page on demand (no ANR with thousands of invoices)
                Ui.paged(list, ar, 40, inv -> Ui.item(c, Ui.fa(inv.optString("invoice_number")), Ui.jdate(inv.optString("created_at")) + " · " + label(inv.optString("payment_method"), PAY) + " · " + label(inv.optString("status"), INV_ST), Ui.money(inv.optDouble("total_amount")), stColor(inv.optString("status")), () -> a.open(new InvoiceDetail(a, inv.optLong("id")), true))); });
        }
    }
    public static final class LocalInvoiceDetail extends Screens.Screen {
        final long id; JSONObject invoice;
        LocalInvoiceDetail(AppActivity a, long id) { super(a); this.id = id; }
        public String key() { return "invoices"; } public String title() { return "جزئیات فاکتور گوشی"; }
        public void load() {
            loading();
            Api.bg(() -> {
                try {
                    JSONObject result = (JSONObject) Local.handle("GET", "/invoices/" + id, null);
                    Api.ui(() -> render(result));
                } catch (Api.ApiError error) {
                    Api.ui(() -> { clear(); body.addView(Ui.empty(c, error.getMessage())); });
                }
            });
        }
        void render(JSONObject data) {
            invoice = data; clear();
            String status = invoice.optString("status", "PAID");
            LinearLayout summary = Ui.card(c, Ui.fa(invoice.optString("invoice_number", invoice.optString("local_no"))));
            summary.addView(Ui.kv(c, "تاریخ", Ui.jdate(invoice.optString("created_at")), 0));
            summary.addView(Ui.kv(c, "وضعیت", "PAID".equals(status) ? "پرداخت‌شده" : "PARTIALLY_REFUNDED".equals(status) ? "مرجوعی جزئی" : status, stColor(status)));
            summary.addView(Ui.kv(c, "پرداخت", Screens.Screen.label(invoice.optString("payment_method"), Screens.Screen.PAY), 0));
            summary.addView(Ui.kv(c, "جمع کالاها", Ui.money(invoice.optDouble("subtotal")), 0));
            summary.addView(Ui.kv(c, "تخفیف کل", Ui.money(invoice.optDouble("discount")), Ui.GREEN));
            if (invoice.optDouble("invoice_discount") > 0) summary.addView(Ui.kv(c, "تخفیف فاکتور", Ui.money(invoice.optDouble("invoice_discount")), Ui.GREEN));
            if (invoice.optDouble("coupon_discount") > 0) summary.addView(Ui.kv(c, "تخفیف کوپن " + invoice.optString("coupon"), Ui.money(invoice.optDouble("coupon_discount")), Ui.GREEN));
            if (invoice.optDouble("campaign_discount") > 0) summary.addView(Ui.kv(c, "تخفیف جشنواره " + invoice.optString("campaign_name"), Ui.money(invoice.optDouble("campaign_discount")), Ui.GREEN));
            if (invoice.optDouble("tax") > 0) summary.addView(Ui.kv(c, "مالیات", Ui.money(invoice.optDouble("tax")), 0));
            summary.addView(Ui.kv(c, "مبلغ نهایی", Ui.money(invoice.optDouble("total_amount")), Ui.GREEN));
            String issued = invoice.optString("auto_issued_coupon_codes", "");
            if (!issued.isEmpty()) summary.addView(Ui.kv(c, "کد خرید بعدی", issued, Ui.VIOLET));
            body.addView(summary);

            LinearLayout items = Ui.card(c, "اقلام");
            JSONArray lines = invoice.optJSONArray("items"); boolean hasReturnableLine = false;
            for (int i = 0; lines != null && i < lines.length(); i++) {
                JSONObject line = lines.optJSONObject(i); if (line == null) continue;
                double remaining = Math.max(0, line.optDouble("qty") - line.optDouble("returned_qty"));
                String sub = Ui.num(line.optDouble("qty")) + " × " + Ui.money(line.optDouble("unit_sell_price"));
                if (line.optDouble("discount") > 0) sub += " · تخفیف " + Ui.money(line.optDouble("discount"));
                if (remaining < line.optDouble("qty")) sub += " · مرجوع‌شده " + Ui.num(line.optDouble("returned_qty"));
                LinearLayout row = Ui.item(c, line.optString("name", "کالا"), sub, Ui.money(line.optDouble("subtotal")), 0, null);
                boolean returnable = "PAID".equals(status) || "PARTIALLY_REFUNDED".equals(status);
                if (Screens.can("pos.return") && returnable && remaining > 0) {
                    hasReturnableLine = true; row.setOnClickListener(v -> returnItem(line, remaining));
                }
                items.addView(row);
            }
            if (lines == null || lines.length() == 0) items.addView(Ui.muted(c, "قلمی ثبت نشده است."));
            if (hasReturnableLine) items.addView(Ui.muted(c, "برای مرجوعی، قلم موردنظر را انتخاب کنید."));
            body.addView(items);

            LinearLayout actions = Ui.card(c, "رسید و عملیات");
            if (Screens.can("pos.sell")) {
                actions.addView(Ui.ghost(c, "نمایش رسید", () -> showReceipt(false)));
                actions.addView(Ui.ghost(c, "چاپ / اشتراک رسید", () -> showReceipt(true)));
            }
            if (!"VOID".equals(status) && (Screens.can("pos.void_paid") || Screens.can("pos.void_unpaid")))
                actions.addView(Ui.danger(c, "ابطال فاکتور", this::voidInvoice));
            if (actions.getChildCount() == 0) actions.addView(Ui.muted(c, "برای رسید یا ابطال، دسترسی متناظر لازم است."));
            body.addView(actions);
        }
        void showReceipt(boolean share) {
            Api.bg(() -> {
                try {
                    String suffix = share ? "/print" : "/receipt";
                    JSONObject result = (JSONObject) Local.handle("GET", "/invoices/" + id + suffix, null);
                    Api.ui(() -> {
                        if (share) Ui.toast(result.optString("message", "رسید برای اشتراک آماده شد"));
                        else {
                            TextView receipt = Ui.text(c, result.optString("receipt_text"), 12, Ui.TEXT, false);
                            receipt.setTypeface(android.graphics.Typeface.MONOSPACE); receipt.setTextDirection(View.TEXT_DIRECTION_LTR);
                            receipt.setGravity(Gravity.START); Ui.sheet(c, "رسید", receipt);
                        }
                    });
                } catch (Api.ApiError error) { Api.ui(() -> Ui.toast(error.getMessage())); }
            });
        }
        void returnItem(JSONObject line, double remaining) {
            if (remaining <= 0) { Ui.toast("مقدار قابل مرجوعی باقی نمانده است"); return; }
            LinearLayout form = Ui.col(c);
            form.addView(Ui.body(c, line.optString("name", "کالا") + " — ماندهٔ قابل مرجوعی: " + Ui.num(remaining)));
            EditText quantity = Ui.input(c, "مقدار مرجوعی", true); quantity.setText(Ui.num(remaining)); form.addView(quantity);
            EditText reason = Ui.input(c, "دلیل"); form.addView(reason);
            EditText refund = Ui.input(c, "مبلغ بازپرداخت (خالی = خودکار)", true); form.addView(refund);
            Dialog[] dialog = new Dialog[1];
            form.addView(Ui.primary(c, "ثبت مرجوعی", () -> {
                double qty = Ui.numVal(quantity, remaining);
                if (qty <= 0 || qty > remaining) { Ui.toast("مقدار باید بین صفر و " + Ui.num(remaining) + " باشد"); return; }
                dialog[0].dismiss(); JSONObject request = j("reason", Ui.str(reason));
                putNum(request, "invoice_id", id); putNum(request, "invoice_item_id", line.optLong("id")); putNum(request, "qty", qty);
                if (!Ui.str(refund).isEmpty()) putNum(request, "refund_amount", Ui.numVal(refund, 0));
                Api.bg(() -> {
                    try { Local.handle("POST", "/returns", request.toString()); Api.ui(() -> { Ui.toast("مرجوعی ثبت شد"); load(); }); }
                    catch (Api.ApiError error) { Api.ui(() -> Ui.toast(error.getMessage())); }
                });
            }));
            dialog[0] = Ui.sheet(c, "مرجوعی", form);
        }
        void voidInvoice() {
            LinearLayout form = Ui.col(c); EditText reason = Ui.input(c, "دلیل ابطال"); form.addView(reason);
            EditText password = Ui.input(c, "رمز مدیر (برای فاکتور پرداخت‌شده)");
            password.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD); form.addView(password);
            Dialog[] dialog = new Dialog[1];
            form.addView(Ui.danger(c, "تأیید ابطال", () -> {
                dialog[0].dismiss(); JSONObject request = j("reason", Ui.str(reason)); putIf(request, "admin_password", Ui.str(password));
                Api.bg(() -> {
                    try { Local.handle("POST", "/invoices/" + id + "/void", request.toString()); Api.ui(() -> { Ui.toast("فاکتور باطل شد"); load(); }); }
                    catch (Api.ApiError error) { Api.ui(() -> Ui.toast(error.getMessage())); }
                });
            }));
            dialog[0] = Ui.sheet(c, "ابطال فاکتور", form);
        }
    }

    public static final class InvoiceDetail extends Screens.Screen {
        final long id; JSONObject inv;
        InvoiceDetail(AppActivity a, long id) { super(a); this.id = id; }
        public String key() { return "invoices"; } public String title() { return "جزئیات فاکتور"; }
        public void load() { loading(); get("/invoices/" + id, r -> { inv = (JSONObject) r; render(); }); }
        void render() {
            clear(); LinearLayout hd = Ui.card(c, Ui.fa(inv.optString("invoice_number")));
            hd.addView(Ui.kv(c, "تاریخ", Ui.jdate(inv.optString("created_at")), 0)); hd.addView(Ui.kv(c, "وضعیت", label(inv.optString("status"), INV_ST), stColor(inv.optString("status")))); hd.addView(Ui.kv(c, "پرداخت", label(inv.optString("payment_method"), PAY) + " · " + label(inv.optString("payment_status"), INV_ST), 0));
            hd.addView(Ui.kv(c, "جمع", Ui.money(inv.optDouble("subtotal")), 0)); hd.addView(Ui.kv(c, "تخفیف", Ui.money(inv.optDouble("discount")), 0)); hd.addView(Ui.kv(c, "مالیات", Ui.money(inv.optDouble("tax")), 0)); hd.addView(Ui.kv(c, "مبلغ نهایی", Ui.money(inv.optDouble("total_amount")), Ui.GREEN)); body.addView(hd);
            LinearLayout its = Ui.card(c, "اقلام"); JSONArray ar = inv.optJSONArray("items");
            for (int i = 0; ar != null && i < ar.length(); i++) { JSONObject it = ar.optJSONObject(i); JSONObject p = Db.productById(it.optLong("product_id")); String name = p == null ? "کالا #" + it.optLong("product_id") : p.optString("name"); LinearLayout row = Ui.item(c, name, Ui.num(it.optDouble("qty")) + " × " + Ui.money(it.optDouble("unit_sell_price")) + (it.optDouble("discount") > 0 ? " − " + Ui.money(it.optDouble("discount")) : ""), Ui.money(it.optDouble("subtotal")), 0, null);
                boolean returnable = "PAID".equals(inv.optString("status")) || "PARTIALLY_REFUNDED".equals(inv.optString("status"));
                double remainingQty = Math.max(0, it.optDouble("qty") - it.optDouble("returned_qty"));
                if (Screens.can("pos.return") && returnable && remainingQty > 0) { row.setOnClickListener(v -> returnItem(it, name)); }
                its.addView(row); }
            boolean returnable = "PAID".equals(inv.optString("status")) || "PARTIALLY_REFUNDED".equals(inv.optString("status"));
            if (Screens.can("pos.return") && returnable) its.addView(Ui.muted(c, "برای مرجوعی روی قلم ضربه بزنید")); body.addView(its);
            LinearLayout act = Ui.card(c, "عملیات");
            act.addView(Ui.ghost(c, "نمایش رسید", () -> get("/invoices/" + id + "/receipt", r -> { TextView t = Ui.text(c, ((JSONObject) r).optString("receipt_text"), 12, Ui.TEXT, false); t.setTypeface(android.graphics.Typeface.MONOSPACE); t.setTextDirection(View.TEXT_DIRECTION_LTR); t.setGravity(Gravity.START); Ui.sheet(c, "رسید", t); })));
            act.addView(Ui.ghost(c, Api.standalone() ? "چاپ / اشتراک رسید" : "چاپ روی چاپگر رایانه", () -> post("/invoices/" + id + "/print", null, r -> Ui.toast("به صف چاپ رایانه رفت"))));
            if (!"VOID".equals(inv.optString("status")) && (Screens.can("pos.void_paid") || Screens.can("pos.void_unpaid"))) act.addView(Ui.danger(c, "ابطال فاکتور", this::voidInvoice));
            body.addView(act);
        }
        void voidInvoice() { LinearLayout l = Ui.col(c); EditText reason = Ui.input(c, "دلیل ابطال"); l.addView(reason); EditText pw = Ui.input(c, "رمز مدیر (برای فاکتور پرداخت‌شده)"); pw.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD); l.addView(pw); Dialog[] d = new Dialog[1]; l.addView(Ui.danger(c, "تأیید ابطال", () -> { d[0].dismiss(); JSONObject b = j("reason", Ui.str(reason)); putIf(b, "admin_password", Ui.str(pw)); post("/invoices/" + id + "/void", b, r -> { Sfx.play("void"); Ui.toast("فاکتور باطل شد"); Sync.kick(); load(); }); })); d[0] = Ui.sheet(c, "ابطال " + Ui.fa(inv.optString("invoice_number")), l); }
        void returnItem(JSONObject it, String name) {
            double remaining = Math.max(0, it.optDouble("qty") - it.optDouble("returned_qty"));
            if (remaining <= 0) { Ui.toast("مقدار قابل مرجوعی باقی نمانده است"); return; }
            LinearLayout content = Ui.col(c);
            content.addView(Ui.body(c, name + " — ماندهٔ قابل مرجوعی: " + Ui.num(remaining)));
            EditText qty = Ui.input(c, "مقدار مرجوعی", true); qty.setText(Ui.num(remaining)); content.addView(qty);
            EditText reason = Ui.input(c, "دلیل"); content.addView(reason);
            EditText refund = Ui.input(c, "مبلغ بازپرداخت (خالی = خودکار)", true); content.addView(refund);
            Dialog[] dialog = new Dialog[1];
            content.addView(Ui.primary(c, "ثبت مرجوعی", () -> {
                double quantity = Ui.numVal(qty, remaining);
                if (quantity <= 0 || quantity > remaining) { Ui.toast("مقدار باید بین صفر و " + Ui.num(remaining) + " باشد"); return; }
                dialog[0].dismiss(); JSONObject request = j("reason", Ui.str(reason));
                putNum(request, "invoice_id", id); putNum(request, "invoice_item_id", it.optLong("id")); putNum(request, "qty", quantity);
                if (!Ui.str(refund).isEmpty()) putNum(request, "refund_amount", Ui.numVal(refund, 0));
                post("/returns", request, result -> { Ui.done(Ui.ctx, "مرجوعی ثبت شد", null, null); Sync.kick(); load(); });
            }));
            dialog[0] = Ui.sheet(c, "مرجوعی", content);
        }
    }

    /* ---------------- Customers + ledger ---------------- */
    public static final class Customers extends Screens.Screen {
        int tab = 0; EditText q;
        Customers(AppActivity a) { super(a); }
        public String key() { return "customers"; } public String title() { return "مشتریان"; }
        public void load() {
            clear(); body.addView(tabs(new String[]{"همه", "بدهکاران"}, tab, t -> { tab = t; load(); }));
            if (tab == 1) { body.addView(Ui.empty(c, "…")); get("/customers/debtors", r -> { body.removeViewAt(body.getChildCount() - 1); JSONArray ar = arr(r); if (ar.length() == 0) body.addView(Ui.empty(c, "بدهکاری نیست")); Ui.paged(body, ar, 50, cu -> Ui.item(c, cu.optString("name") + " " + s(cu, "last_name"), Ui.fa(s(cu, "phone")), Ui.money(cu.optDouble("balance", cu.optDouble("debt", 0))), Ui.RED, () -> a.open(new CustomerDetail(a, cu), true))); }); return; }
            LinearLayout sr = Ui.row(c); q = Ui.input(c, "جست‌وجو نام / موبایل"); q.setLayoutParams(Ui.weight(1)); sr.addView(q); View add = Ui.primary(c, "+ جدید", () -> newCustomer(a, Ui.str(q), cu -> load())); add.setLayoutParams(Ui.margin(Ui.lp(ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(44)), 6, 0, 0, 6)); sr.addView(add); body.addView(sr);
            LinearLayout list = Ui.col(c); body.addView(list);
            Runnable fill = () -> { list.removeAllViews(); List<JSONObject> cs = Db.customers(Ui.str(q)); if (cs.isEmpty()) list.addView(Ui.empty(c, "مشتری‌ای نیست")); for (JSONObject cu : cs) list.addView(Ui.item(c, cu.optString("name") + " " + s(cu, "last_name"), Ui.fa(s(cu, "phone")) + (cu.optBoolean("_local") ? " · در انتظار ارسال" : ""), cu.optDouble("credit_limit") > 0 ? "سقف " + Ui.money(cu.optDouble("credit_limit")) : null, Ui.MUTED, () -> a.open(new CustomerDetail(a, cu), true))); };
            q.addTextChangedListener(new TextWatcher() { public void beforeTextChanged(CharSequence s, int i, int i1, int i2) {} public void onTextChanged(CharSequence s, int i, int i1, int i2) {} public void afterTextChanged(Editable e) { fill.run(); } }); fill.run();
        }
        static void newCustomer(AppActivity a, String prefill, java.util.function.Consumer<JSONObject> cb) {
            LinearLayout l = Ui.col(a); EditText name = Ui.input(a, "نام *"); EditText last = Ui.input(a, "نام خانوادگی"); EditText phone = Ui.input(a, "موبایل", true); phone.setInputType(android.text.InputType.TYPE_CLASS_PHONE); EditText addr = Ui.input(a, "آدرس"); EditText limit = Ui.input(a, "سقف اعتبار (۰ = بدون سقف)", true);
            if (prefill.matches("[0-9۰-۹]+")) phone.setText(prefill); else name.setText(prefill);
            l.addView(name); l.addView(last); l.addView(phone); l.addView(addr); l.addView(limit); Dialog[] d = new Dialog[1];
            l.addView(Ui.primary(a, "ثبت مشتری", () -> { if (Ui.str(name).isEmpty() && Db.norm(Ui.str(phone)).isEmpty()) { Ui.toast("نام یا شماره موبایل لازم است"); return; } d[0].dismiss(); JSONObject b = Api.obj("name", Ui.str(name).isEmpty() ? "مشتری " + Db.norm(Ui.str(phone)) : Ui.str(name), "last_name", Ui.str(last), "phone", Db.norm(Ui.str(phone)), "address", Ui.str(addr)); try { b.put("credit_enabled", true); b.put("credit_limit", Ui.numVal(limit, 0)); } catch (Exception ignore) {} JSONObject local = Db.localCustomer(Ui.str(name), Db.norm(Ui.str(phone))); Sync.queue("CUSTOMER_CREATE", b, "مشتری " + Ui.str(name), null); Ui.done(Ui.ctx, "مشتری ثبت شد", null, null); cb.accept(local); }));
            d[0] = Ui.sheet(a, "مشتری جدید", l);
        }
    }
    public static final class CustomerDetail extends Screens.Screen {
        JSONObject cu; final long id;
        CustomerDetail(AppActivity a, JSONObject cu) { super(a); this.cu = cu; id = cu.optLong("id"); }
        public String key() { return "customers"; } public String title() { return "پروندهٔ مشتری"; }
        public void load() {
            clear(); LinearLayout hd = Ui.card(c, cu.optString("name") + " " + s(cu, "last_name")); hd.addView(Ui.kv(c, "موبایل", Ui.fa(s(cu, "phone", "—")), 0)); if (!s(cu, "address").isEmpty()) hd.addView(Ui.kv(c, "آدرس", s(cu, "address"), 0)); hd.addView(Ui.kv(c, "سقف اعتبار", cu.optDouble("credit_limit") > 0 ? Ui.money(cu.optDouble("credit_limit")) : "بدون سقف", 0)); body.addView(hd);
            if (id < 0 && !Api.standalone()) { body.addView(Ui.note(c, null, "این مشتری هنوز به رایانه ارسال نشده؛ دفتر حساب پس از همگام‌سازی در دسترس است.")); return; }
            LinearLayout act = Ui.row(c); act.addView(Ui.small(c, "فروش به این مشتری", () -> { Prefs.set("pos_restore", ""); a.route("pos"); ((Pos) a.current()).customer = cu; ((Pos) a.current()).renderCart(); })); act.addView(Ui.small(c, "ویرایش", this::edit)); body.addView(act);
            LinearLayout led = Ui.card(c, "دفتر حساب"); body.addView(led); LinearLayout invs = Ui.card(c, "فاکتورها"); body.addView(invs);
            getQuiet("/customers/" + id + "/ledger", r -> { JSONObject lg = (JSONObject) r; double bal = lg.optDouble("balance"); led.addView(Ui.kv(c, "ماندهٔ بدهی", Ui.money(bal), bal > 0 ? Ui.RED : Ui.GREEN)); led.addView(Ui.kv(c, "کل نسیه / کل پرداخت", Ui.money(lg.optDouble("total_charged")) + " / " + Ui.money(lg.optDouble("total_paid")), 0));
                LinearLayout br = Ui.row(c); if (Screens.can("customers.settle")) { br.addView(Ui.small(c, "تسویه", () -> settle(bal))); br.addView(Ui.small(c, "اصلاح دستی", this::adjust)); } br.addView(Ui.small(c, "پیامک یادآوری", () -> post("/customers/" + id + "/debt-reminder", j(), x -> Ui.toast("پیامک در صف ارسال قرار گرفت")))); led.addView(br);
                JSONArray en = lg.optJSONArray("entries"); for (int i = 0; en != null && i < Math.min(30, en.length()); i++) { JSONObject e = en.optJSONObject(i); String ty = s(e, "entry_type", s(e, "type")); led.addView(Ui.kv(c, Ui.jdate(s(e, "created_at")) + " · " + label(ty, new String[][]{{"SALE", "خرید نسیه"}, {"CHARGE", "خرید نسیه"}, {"PAYMENT", "پرداخت"}, {"SETTLEMENT", "تسویه"}, {"ADJUSTMENT_DEBIT", "اصلاح بدهکار"}, {"ADJUSTMENT_CREDIT", "اصلاح بستانکار"}}), Ui.money(e.optDouble("amount")), ty.contains("PAY") || ty.contains("SETTLE") || ty.contains("CREDIT") ? Ui.GREEN : Ui.AMBER)); } if (en == null || en.length() == 0) led.addView(Ui.muted(c, "گردشی ندارد")); });
            getQuiet("/customers/" + id + "/invoices", r -> { JSONArray ar = arr(r); if (ar.length() == 0) invs.addView(Ui.muted(c, "—")); for (int i = 0; i < Math.min(20, ar.length()); i++) { JSONObject inv = ar.optJSONObject(i); invs.addView(Ui.item(c, Ui.fa(inv.optString("invoice_number")), Ui.jdate(inv.optString("created_at")) + " · " + label(inv.optString("status"), INV_ST), Ui.money(inv.optDouble("total_amount")), stColor(inv.optString("status")), () -> a.open(new InvoiceDetail(a, inv.optLong("id")), true))); } });
        }
        void settle(double bal) { LinearLayout l = Ui.col(c); l.addView(Ui.body(c, "ماندهٔ فعلی: " + Ui.money(bal))); EditText amt = Ui.input(c, "مبلغ (خالی = تسویهٔ کامل)", true); l.addView(amt); final String[] m = {"CASH"}; LinearLayout ch = Ui.row(c); Runnable[] rd = new Runnable[1]; rd[0] = () -> { ch.removeAllViews(); for (String[] p : new String[][]{{"CASH", "نقدی"}, {"CARD", "کارت"}, {"TRANSFER", "کارت‌به‌کارت"}}) ch.addView(Ui.chip(c, p[1], p[0].equals(m[0]), () -> { m[0] = p[0]; rd[0].run(); })); }; rd[0].run(); l.addView(ch); EditText note = Ui.input(c, "توضیح"); l.addView(note); Dialog[] d = new Dialog[1]; l.addView(Ui.success(c, "ثبت تسویه", () -> { d[0].dismiss(); JSONObject b = j("method", m[0], "note", Ui.str(note)); if (!Ui.str(amt).isEmpty()) putNum(b, "amount", Ui.numVal(amt, 0)); post("/customers/" + id + "/settle", b, r -> { Ui.done(Ui.ctx, "تسویه ثبت شد", null, null); load(); }); })); d[0] = Ui.sheet(c, "تسویهٔ بدهی", l); }
        void adjust() { LinearLayout l = Ui.col(c); final String[] t = {"ADJUSTMENT_DEBIT"}; LinearLayout ch = Ui.row(c); Runnable[] rd = new Runnable[1]; rd[0] = () -> { ch.removeAllViews(); ch.addView(Ui.chip(c, "افزایش بدهی", t[0].endsWith("DEBIT"), () -> { t[0] = "ADJUSTMENT_DEBIT"; rd[0].run(); })); ch.addView(Ui.chip(c, "کاهش بدهی", t[0].endsWith("CREDIT"), () -> { t[0] = "ADJUSTMENT_CREDIT"; rd[0].run(); })); }; rd[0].run(); l.addView(ch); EditText amt = Ui.input(c, "مبلغ", true); l.addView(amt); EditText note = Ui.input(c, "توضیح *"); l.addView(note); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ثبت", () -> { if (Ui.str(note).isEmpty()) { Ui.toast("توضیح لازم است"); return; } d[0].dismiss(); JSONObject b = j("entry_type", t[0], "note", Ui.str(note)); putNum(b, "amount", Ui.numVal(amt, 0)); post("/customers/" + id + "/ledger/adjust", b, r -> { Ui.done(Ui.ctx, "ثبت شد", null, null); load(); }); })); d[0] = Ui.sheet(c, "اصلاح دستی دفتر حساب", l); }
        void edit() { LinearLayout l = Ui.col(c); EditText name = Ui.input(c, "نام"); name.setText(s(cu, "name")); EditText last = Ui.input(c, "نام خانوادگی"); last.setText(s(cu, "last_name")); EditText phone = Ui.input(c, "موبایل", true); phone.setText(s(cu, "phone")); EditText addr = Ui.input(c, "آدرس"); addr.setText(s(cu, "address")); EditText limit = Ui.input(c, "سقف اعتبار", true); limit.setText(Ui.num(cu.optDouble("credit_limit"))); l.addView(name); l.addView(last); l.addView(phone); l.addView(addr); l.addView(limit); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ذخیره", () -> { d[0].dismiss(); JSONObject b = j("name", Ui.str(name), "last_name", Ui.str(last), "phone", Db.norm(Ui.str(phone)), "address", Ui.str(addr)); putNum(b, "credit_limit", Ui.numVal(limit, 0)); patch("/customers/" + id, b, r -> { cu = (JSONObject) r; Db.putCustomer(cu, false); Ui.done(Ui.ctx, "ذخیره شد", null, null); load(); }); })); d[0] = Ui.sheet(c, "ویرایش مشتری", l); }
    }

    /* ---------------- Marketing: campaigns + coupons ---------------- */
    public static final class Marketing extends Screens.Screen {
        int tab = 0;
        Marketing(AppActivity a) { super(a); }
        public String key() { return "marketing"; } public String title() { return "جشنواره و کوپن"; }
        public void load() {
            clear(); body.addView(tabs(new String[]{"جشنواره‌ها", "کوپن‌ها", "آمار"}, tab, t -> { tab = t; load(); })); LinearLayout list = Ui.col(c); body.addView(list);
            if (tab == 0) { body.addView(Ui.primary(c, "+ جشنوارهٔ جدید", this::newCampaign)); get("/marketing/campaigns", r -> { JSONArray ar = arr(r); if (ar.length() == 0) list.addView(Ui.empty(c, "جشنواره‌ای تعریف نشده")); for (int i = 0; i < ar.length(); i++) { JSONObject cp = ar.optJSONObject(i); LinearLayout it = Ui.item(c, cp.optString("name"), ("PERCENT".equals(cp.optString("discount_type")) ? Ui.num(cp.optDouble("discount_value")) + "٪" : Ui.money(cp.optDouble("discount_value"))) + " · حداقل خرید " + Ui.money(cp.optDouble("min_purchase")) + (Local.offerFlag(cp, "auto_apply") ? " · اعمال خودکار" : "") + (Local.offerFlag(cp, "stackable") ? " · ترکیب با کوپن" : "") + (cp.isNull("valid_until") ? "" : " · تا " + Ui.jdate(cp.optString("valid_until"))), label(cp.optString("status"), new String[][]{{"ACTIVE", "فعال"}, {"PAUSED", "متوقف"}, {"ENDED", "پایان‌یافته"}}), stColor(cp.optString("status")), () -> { String next = "ACTIVE".equals(cp.optString("status")) ? "PAUSED" : "ACTIVE"; Ui.confirm(c, "وضعیت به «" + ("ACTIVE".equals(next) ? "فعال" : "متوقف") + "» تغییر کند؟", () -> patch("/marketing/campaigns/" + cp.optLong("id"), j("status", next), x -> load())); }); list.addView(it); } }); }
            else if (tab == 1) { body.addView(Ui.primary(c, "+ صدور کوپن", this::newCoupon)); get("/marketing/coupons", r -> { JSONArray ar = arr(r); if (ar.length() == 0) list.addView(Ui.empty(c, "کوپنی نیست")); Ui.paged(list, ar, 50, cp -> Ui.item(c, cp.optString("code"), ("PERCENT".equals(cp.optString("discount_type")) ? Ui.num(cp.optDouble("discount_value")) + "٪" : Ui.money(cp.optDouble("discount_value"))) + (s(cp, "customer_phone").isEmpty() ? "" : " · " + Ui.fa(s(cp, "customer_phone"))) + " · استفاده " + Ui.fa(cp.optInt("used_count") + "/" + cp.optInt("usage_limit", 1)), label(cp.optString("status"), new String[][]{{"ACTIVE", "فعال"}, {"USED", "مصرف‌شده"}, {"BLOCKED", "مسدود"}, {"EXPIRED", "منقضی"}}), stColor(cp.optString("status")), () -> { if ("ACTIVE".equals(cp.optString("status"))) Ui.confirm(c, "کوپن " + cp.optString("code") + " مسدود شود؟", () -> post("/marketing/coupons/" + cp.optLong("id") + "/block", null, x -> load())); })); }); }
            else get("/marketing/stats", r -> { JSONObject st = (JSONObject) r; LinearLayout cd = Ui.card(c, "آمار"); cd.addView(Ui.kv(c, "جشنواره‌ها", Ui.num(st.optDouble("campaigns")), 0)); cd.addView(Ui.kv(c, "کل کوپن‌ها", Ui.num(st.optDouble("total_coupons")), 0)); cd.addView(Ui.kv(c, "ارزش تخفیف مصرف‌شده", Ui.money(st.optDouble("redeemed_value")), Ui.GREEN)); JSONObject bs = st.optJSONObject("by_status"); if (bs != null) { java.util.Iterator<String> it = bs.keys(); while (it.hasNext()) { String k = it.next(); cd.addView(Ui.kv(c, k, Ui.num(bs.optDouble(k)), 0)); } } list.addView(cd); });
        }
        void newCampaign() {
            LinearLayout form = Ui.col(c);
            EditText name = Ui.input(c, "نام جشنواره *");
            EditText value = Ui.input(c, "مقدار تخفیف", true);
            EditText minimum = Ui.input(c, "حداقل خرید", true);
            EditText maximumPurchase = Ui.input(c, "سقف خرید (اختیاری)", true);
            EditText maximumDiscount = Ui.input(c, "سقف تخفیف (اختیاری)", true);
            EditText usageLimit = Ui.input(c, "سقف استفادهٔ کل (خالی = نامحدود)", true);
            EditText until = DatePicker.field(c, "پایان (اختیاری)");
            EditText issueThreshold = Ui.input(c, "صدور کوپن خرید بعدی از مبلغ (اختیاری)", true);
            EditText issueDays = Ui.input(c, "اعتبار کوپن بعدی (روز)", true); issueDays.setText("30");
            final String[] type = {"PERCENT"};
            final boolean[] autoApply = {false}, stackable = {false};
            LinearLayout typeRow = Ui.row(c), applyRow = Ui.row(c), stackRow = Ui.row(c);
            Runnable[] renderType = new Runnable[1];
            renderType[0] = () -> {
                typeRow.removeAllViews();
                typeRow.addView(Ui.chip(c, "درصدی", type[0].equals("PERCENT"), () -> { type[0] = "PERCENT"; renderType[0].run(); }));
                typeRow.addView(Ui.chip(c, "مبلغ ثابت", type[0].equals("FIXED"), () -> { type[0] = "FIXED"; renderType[0].run(); }));
            };
            Runnable[] renderRules = new Runnable[1];
            renderRules[0] = () -> {
                applyRow.removeAllViews();
                applyRow.addView(Ui.chip(c, "انتخاب صندوق‌دار", !autoApply[0], () -> { autoApply[0] = false; renderRules[0].run(); }));
                applyRow.addView(Ui.chip(c, "اعمال خودکار", autoApply[0], () -> { autoApply[0] = true; renderRules[0].run(); }));
                stackRow.removeAllViews();
                stackRow.addView(Ui.chip(c, "بدون ترکیب با کوپن", !stackable[0], () -> { stackable[0] = false; renderRules[0].run(); }));
                stackRow.addView(Ui.chip(c, "ترکیب با کوپن", stackable[0], () -> { stackable[0] = true; renderRules[0].run(); }));
            };
            renderType[0].run(); renderRules[0].run();
            form.addView(name); form.addView(Ui.muted(c, "نوع تخفیف")); form.addView(typeRow);
            form.addView(value); form.addView(minimum); form.addView(maximumPurchase); form.addView(maximumDiscount); form.addView(usageLimit);
            form.addView(until); form.addView(issueThreshold); form.addView(issueDays);
            form.addView(Ui.muted(c, "اعمال در صندوق")); form.addView(applyRow);
            form.addView(Ui.muted(c, "ترکیب با کوپن")); form.addView(stackRow);
            form.addView(Ui.muted(c, "صدور کوپن خرید بعدی پس از رسیدن فروش به آستانه؛ کد در رسید/پیامک فاکتور ثبت می‌شود."));
            Dialog[] dialog = new Dialog[1];
            form.addView(Ui.primary(c, "ایجاد جشنواره", () -> {
                try {
                    JSONObject request = j("name", Ui.str(name), "discount_type", type[0]);
                    request.put("auto_apply", autoApply[0]); request.put("stackable", stackable[0]); request.put("auto_issue_sms", true);
                    putNum(request, "discount_value", Ui.numVal(value, 0));
                    putNum(request, "min_purchase", Ui.numVal(minimum, 0));
                    if (!Ui.str(maximumPurchase).isEmpty() && Ui.numVal(maximumPurchase, 0) > 0)
                        putNum(request, "max_purchase", Ui.numVal(maximumPurchase, 0));
                    if (!Ui.str(maximumDiscount).isEmpty() && Ui.numVal(maximumDiscount, 0) > 0)
                        putNum(request, "max_discount", Ui.numVal(maximumDiscount, 0));
                    if (!Ui.str(usageLimit).isEmpty()) putNum(request, "usage_limit", (int) Ui.numVal(usageLimit, 0));
                    String endDate = dateIn(until);
                    if (endDate != null) request.put("valid_until", endDate + "T23:59:59");
                    if (!Ui.str(issueThreshold).isEmpty() && Ui.numVal(issueThreshold, 0) > 0)
                        putNum(request, "auto_issue_threshold", Ui.numVal(issueThreshold, 0));
                    putNum(request, "auto_issue_validity_days", Math.max(1, Math.min(3650, (int) Ui.numVal(issueDays, 30))));
                    dialog[0].dismiss();
                    post("/marketing/campaigns", request, result -> { Ui.toast("جشنواره ایجاد شد"); load(); });
                } catch (IllegalArgumentException invalid) { /* dateIn already shows a precise date error */ }
                catch (org.json.JSONException error) { Ui.toast("اطلاعات جشنواره ذخیره نشد: " + error.getMessage()); }
            }));
            dialog[0] = Ui.sheet(c, "جشنوارهٔ جدید", form);
        }
        void newCoupon() {
            LinearLayout form = Ui.col(c);
            EditText code = Ui.input(c, "کد (خالی = خودکار)");
            EditText value = Ui.input(c, "مقدار تخفیف", true);
            EditText maximumDiscount = Ui.input(c, "سقف تخفیف (اختیاری)", true);
            EditText minimum = Ui.input(c, "حداقل خرید", true);
            EditText phone = Ui.input(c, "موبایل مشتری (اختیاری)", true);
            EditText until = DatePicker.field(c, "انقضا (اختیاری)");
            EditText limit = Ui.input(c, "تعداد دفعات استفاده", true); limit.setText("1");
            final String[] type = {"PERCENT"};
            LinearLayout typeRow = Ui.row(c); Runnable[] renderType = new Runnable[1];
            renderType[0] = () -> {
                typeRow.removeAllViews();
                typeRow.addView(Ui.chip(c, "درصدی", type[0].equals("PERCENT"), () -> { type[0] = "PERCENT"; renderType[0].run(); }));
                typeRow.addView(Ui.chip(c, "مبلغ ثابت", type[0].equals("FIXED"), () -> { type[0] = "FIXED"; renderType[0].run(); }));
            };
            renderType[0].run();
            form.addView(code); form.addView(Ui.muted(c, "نوع تخفیف")); form.addView(typeRow);
            form.addView(value); form.addView(maximumDiscount); form.addView(minimum); form.addView(phone); form.addView(until); form.addView(limit);
            Dialog[] dialog = new Dialog[1];
            form.addView(Ui.primary(c, "صدور کوپن", () -> {
                double discountValue = Ui.numVal(value, 0), usageCount = Ui.numVal(limit, 1);
                if (discountValue <= 0) { Ui.toast("مقدار تخفیف باید بیشتر از صفر باشد"); return; }
                if (usageCount < 1 || usageCount > 100000) { Ui.toast("تعداد دفعات استفاده باید بین ۱ و ۱۰۰٬۰۰۰ باشد"); return; }
                try {
                    JSONObject request = j("discount_type", type[0]);
                    putIf(request, "code", Ui.str(code)); putIf(request, "customer_phone", Db.norm(Ui.str(phone)));
                    putNum(request, "discount_value", discountValue); putNum(request, "min_purchase", Ui.numVal(minimum, 0));
                    putNum(request, "usage_limit", (int) usageCount);
                    if (!Ui.str(maximumDiscount).isEmpty() && Ui.numVal(maximumDiscount, 0) > 0)
                        putNum(request, "max_discount", Ui.numVal(maximumDiscount, 0));
                    String endDate = dateIn(until);
                    if (endDate != null) request.put("valid_until", endDate + "T23:59:59");
                    dialog[0].dismiss();
                    post("/marketing/coupons", request, result -> { Ui.toast("کوپن " + ((JSONObject) result).optString("code") + " صادر شد"); load(); });
                } catch (IllegalArgumentException invalid) { /* dateIn already shows a precise date error */ }
                catch (org.json.JSONException error) { Ui.toast("کوپن ذخیره نشد: " + error.getMessage()); }
            }));
            dialog[0] = Ui.sheet(c, "صدور کوپن", form);
        }
    }
}
