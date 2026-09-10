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
        JSONObject customer; String coupon; double invoiceDiscount = 0; String heldId;
        LinearLayout lines; TextView tot, cnt, custTxt; EditText search; LinearLayout sugg; final Handler h = new Handler(Looper.getMainLooper()); Runnable pending;
        Pos(AppActivity a) { super(a); }
        public String key() { return "pos"; } public String title() { return "صندوق فروش"; }
        public View view() {
            LinearLayout root = Ui.col(c); root.setPadding(Ui.dp(12), Ui.dp(10), Ui.dp(12), Ui.dp(10));
            // search row (mockup: rounded input + teal «اسکن» button)
            LinearLayout sr = Ui.row(c);
            search = Ui.input(c, "🔍  نام یا بارکد کالا…"); search.setLayoutParams(Ui.weight(1)); sr.addView(search);
            View scanB = Ui.btn(c, "▣ اسکن", Ui.PRIMARY, Color.WHITE, () -> a.scan("اسکن کالا برای فروش", this::onBarcode)); scanB.setLayoutParams(Ui.margin(Ui.lp(ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(46)), 8, 0, 0, 6)); sr.addView(scanB);
            root.addView(sr);
            search.addTextChangedListener(new TextWatcher() { public void beforeTextChanged(CharSequence s, int i, int i1, int i2) {} public void onTextChanged(CharSequence s, int i, int i1, int i2) {} public void afterTextChanged(Editable e) { if (pending != null) h.removeCallbacks(pending); pending = () -> suggest(e.toString().trim()); h.postDelayed(pending, 220); } });
            search.setOnEditorActionListener((v, id, ev) -> { String q = Ui.str(search); if (!q.isEmpty()) onBarcode(q); return true; });
            sugg = Ui.col(c); root.addView(sugg);
            // customer + coupon strip
            LinearLayout cs = Ui.row(c); cs.setPadding(0, Ui.dp(4), 0, Ui.dp(2));
            cs.addView(Ui.pill(c, "👤", "مشتری", customer != null, this::pickCustomer)); cs.addView(Ui.pill(c, "🎟", "کوپن", coupon != null, this::askCoupon)); cs.addView(Ui.pill(c, "％", "تخفیف", invoiceDiscount > 0, this::askDiscount));
            root.addView(Ui.chips(c, cs));
            custTxt = Ui.text(c, "مشتری آزاد", 12, Ui.MUTED, false); custTxt.setPadding(Ui.dp(4), 0, Ui.dp(4), Ui.dp(4)); custTxt.setOnClickListener(v -> pickCustomer()); root.addView(custTxt);
            // cart list (scrolls)
            lines = Ui.col(c); android.widget.ScrollView sv = new android.widget.ScrollView(c); sv.addView(lines); sv.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1)); root.addView(sv);
            // footer
            LinearLayout foot = Ui.col(c); foot.setBackground(Ui.surface(20)); foot.setPadding(Ui.dp(14), Ui.dp(12), Ui.dp(14), Ui.dp(12)); foot.setElevation(Ui.dp(4));
            LinearLayout tr = Ui.row(c); LinearLayout tl = Ui.col(c); tl.setLayoutParams(Ui.weight(1)); tl.addView(Ui.muted(c, "مبلغ قابل پرداخت")); cnt = Ui.muted(c, ""); tl.addView(cnt); tr.addView(tl); tot = Ui.text(c, Ui.money(0), 22, Ui.PRIMARY, true); tr.addView(tot); foot.addView(tr);
            LinearLayout br = Ui.row(c); br.setPadding(0, Ui.dp(8), 0, 0);
            View hold = Ui.ghost(c, "⏸ نگه‌داشتن", this::hold); hold.setLayoutParams(Ui.margin(Ui.weight(1), 0, 0, 3, 0)); br.addView(hold);
            View held = Ui.ghost(c, "نگه‌داشته‌ها", () -> a.open(new Held(a), true)); held.setLayoutParams(Ui.margin(Ui.weight(1), 3, 0, 0, 0)); br.addView(held);
            foot.addView(br);
            View pay = Ui.cta(c, "پرداخت  ←", this::pay); pay.setLayoutParams(Ui.margin(Ui.match(), 0, 8, 0, 0)); foot.addView(pay);
            root.addView(foot);
            return root;
        }
        public void load() { String restore = Prefs.get("pos_restore", ""); if (!restore.isEmpty()) { Prefs.set("pos_restore", ""); restoreHeld(restore); } renderCart(); }

        /* ---- search / add ---- */
        void suggest(String q) {
            sugg.removeAllViews(); if (q.length() < 2) return;
            List<JSONObject> local = Db.searchProducts(q, 8); showSugg(local);
            if (Api.online && !Api.standalone()) Api.get("/pos/search?q=" + Api.q(q) + "&limit=8", r -> { if (!q.equals(Ui.str(search))) return; JSONArray it = ((JSONObject) r).optJSONArray("items"); List<JSONObject> l = new ArrayList<>(); for (int i = 0; it != null && i < it.length(); i++) l.add(it.optJSONObject(i)); if (!l.isEmpty()) showSugg(l); }, e -> {});
        }
        void showSugg(List<JSONObject> list) {
            sugg.removeAllViews();
            for (JSONObject p : list) { double avail = p.optDouble("available_qty", 0); JSONArray bs = p.optJSONArray("batches"); double price = bs != null && bs.length() > 0 ? bs.optJSONObject(0).optDouble("sell_price", 0) : 0; sugg.addView(Ui.item(c, p.optString("name"), Ui.fa(p.optString("barcode")) + " · موجودی " + Ui.num(avail), Ui.money(price), avail > 0 ? Ui.TEXT : Ui.RED, () -> { add(p, null); search.setText(""); sugg.removeAllViews(); })); }
        }
        void onBarcode(String code) {
            code = Db.norm(code); search.setText(""); sugg.removeAllViews();
            JSONObject p = Db.productByBarcode(code);
            if (p != null && p.optJSONArray("batches") != null && p.optJSONArray("batches").length() > 0) { add(p, null); return; }
            final String bc = code;
            if (Api.online && !Api.standalone()) Api.get("/pos/search?q=" + Api.q(bc) + "&limit=1", r -> { JSONArray it = ((JSONObject) r).optJSONArray("items"); if (it != null && it.length() > 0 && bc.equals(it.optJSONObject(0).optString("barcode"))) add(it.optJSONObject(0), null); else notFound(bc); }, e -> notFound(bc));
            else if (p != null) Ui.toast("موجودی این کالا صفر است"); else notFound(bc);
        }
        void notFound(String bc) { Ui.toast("کالایی با بارکد " + Ui.fa(bc) + " نیست"); Ui.confirm(c, "کالای " + Ui.fa(bc) + " تعریف نشده. اکنون تعریف و دریافت شود؟", () -> a.open(new StockScreens.Receive(a, bc), true)); }
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
            for (int i = 0; i < bs.length(); i++) { JSONObject b = bs.optJSONObject(i); l.addView(Ui.item(c, Ui.money(b.optDouble("sell_price", b.optDouble("unit_sell_price", 0))) + (b.optBoolean("is_recommended") ? "  ★ پیشنهادی" : ""), "بچ " + Ui.fa(b.optString("batch_number")) + " · موجودی " + Ui.num(b.optDouble("current_qty")) + (b.isNull("expiry_date") ? "" : " · انقضا " + Ui.jdate(b.optString("expiry_date"))), null, 0, () -> { d[0].dismiss(); add(p, b); })); }
            d[0] = Ui.sheet(c, p.optString("name"), l);
        }
        /* ---- cart ---- */
        void renderCart() {
            lines.removeAllViews(); double total = 0, n = 0;
            if (cart.isEmpty()) lines.addView(Ui.empty(c, "سبد خالی است — کالا را جست‌وجو یا اسکن کنید"));
            for (JSONObject l : cart) {
                double q = l.optDouble("quantity"), pr = l.optDouble("price"), disc = l.optDouble("discount"); double sub = q * pr - disc; total += sub; n += q;
                LinearLayout row = Ui.col(c); row.setBackground(Ui.surface(18)); row.setPadding(Ui.dp(12), Ui.dp(10), Ui.dp(12), Ui.dp(10)); row.setLayoutParams(Ui.margin(Ui.match(), 0, 0, 0, 8));
                LinearLayout r1 = Ui.row(c);
                TextView ic = Ui.text(c, l.optString("name").isEmpty() ? "🛍" : l.optString("name").substring(0, 1), 16, Ui.PRIMARY, true); ic.setGravity(Gravity.CENTER); ic.setBackground(Ui.rounded((Ui.PRIMARY & 0x00FFFFFF) | 0x22000000, 0, 12)); ic.setLayoutParams(Ui.margin(Ui.lp(Ui.dp(40), Ui.dp(40)), 0, 0, 10, 0)); r1.addView(ic);
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
            total -= invoiceDiscount; if (total < 0) total = 0;
            tot.setText(Ui.money(total)); cnt.setText(Ui.num(cart.size()) + " قلم · " + Ui.num(n) + " واحد" + (invoiceDiscount > 0 ? " · تخفیف فاکتور " + Ui.money(invoiceDiscount) : "") + (coupon != null ? " · کوپن " + coupon : ""));
            custTxt.setText(customer == null ? "مشتری آزاد (بدون ثبت)" : "مشتری: " + customer.optString("name") + " " + Screens.Screen.s(customer, "last_name") + " · " + Ui.fa(customer.optString("phone")));
        }
        View qbtn(String s, Runnable r) { TextView t = Ui.text(c, s, 18, "+".equals(s) ? Color.WHITE : Ui.TEXT, true); t.setGravity(Gravity.CENTER); t.setBackground(Ui.rounded("+".equals(s) ? Ui.PRIMARY : Ui.CARD2, "+".equals(s) ? 0 : Ui.BORDER, 10)); t.setLayoutParams(Ui.lp(Ui.dp(36), Ui.dp(34))); t.setOnClickListener(v -> r.run()); return t; }
        static void set(JSONObject o, String k, double v) { try { o.put(k, v); } catch (Exception ignore) {} }
        double total() { double t = 0; for (JSONObject l : cart) t += l.optDouble("quantity") * l.optDouble("price") - l.optDouble("discount"); return Math.max(0, t - invoiceDiscount); }

        /* ---- customer / coupon / discount ---- */
        void pickCustomer() {
            LinearLayout l = Ui.col(c); EditText q = Ui.input(c, "نام یا شماره موبایل…"); l.addView(q); LinearLayout res = Ui.col(c); l.addView(res); Dialog[] d = new Dialog[1];
            l.addView(Ui.ghost(c, "مشتری آزاد (بدون ثبت)", () -> { customer = null; d[0].dismiss(); renderCart(); }));
            l.addView(Ui.primary(c, "ثبت مشتری جدید", () -> { d[0].dismiss(); newCustomer(Ui.str(q), cu -> { customer = cu; renderCart(); }); }));
            Runnable fill = () -> { res.removeAllViews(); for (JSONObject cu : Db.customers(Ui.str(q))) res.addView(Ui.item(c, cu.optString("name") + " " + s(cu, "last_name"), Ui.fa(cu.optString("phone")), null, 0, () -> { customer = cu; d[0].dismiss(); renderCart(); })); };
            q.addTextChangedListener(new TextWatcher() { public void beforeTextChanged(CharSequence s, int i, int i1, int i2) {} public void onTextChanged(CharSequence s, int i, int i1, int i2) {} public void afterTextChanged(Editable e) { fill.run(); } }); fill.run();
            d[0] = Ui.sheet(c, "انتخاب مشتری", l);
        }
        void newCustomer(String prefill, java.util.function.Consumer<JSONObject> cb) { Customers.newCustomer(a, prefill, cb); }
        void askCoupon() { Ui.prompt(c, "کد کوپن", "مثلاً WELCOME10", false, code -> { if (code.isEmpty()) { coupon = null; renderCart(); return; } JSONObject b = j("code", code); putNum(b, "amount", total()); if (customer != null) putNum(b, "customer_id", customer.optLong("id")); Api.post("/marketing/coupons/validate", b, r -> { JSONObject v = (JSONObject) r; if (v.optBoolean("valid", v.optBoolean("ok", false))) { coupon = code; Ui.toast("کوپن معتبر: " + Ui.money(v.optDouble("discount", 0))); } else { coupon = null; Ui.toast(s(v, "reason", s(v, "message", "کوپن معتبر نیست"))); } renderCart(); }, e -> Ui.toast(e.getMessage())); }); }
        void askDiscount() { Ui.prompt(c, "تخفیف کل فاکتور (مبلغ)", "0", true, s -> { try { invoiceDiscount = Math.max(0, Double.parseDouble(Db.norm(s).isEmpty() ? "0" : Db.norm(s))); } catch (Exception e) { invoiceDiscount = 0; } renderCart(); }); }

        /* ---- hold / restore (up to 10, listed with time, re-openable) ---- */
        void hold() {
            if (cart.isEmpty()) { Ui.toast("سبد خالی است"); return; }
            try { JSONArray held = new JSONArray(Prefs.get("pos_held", "[]")); JSONArray keep = new JSONArray(); for (int i = 0; i < held.length(); i++) if (!held.optJSONObject(i).optString("id").equals(heldId)) keep.put(held.optJSONObject(i));
                if (keep.length() >= HELD_MAX) { Ui.toast("حداکثر " + Ui.fa("10") + " فاکتور نگه‌داشته"); return; }
                JSONObject hjson = new JSONObject(); hjson.put("id", heldId != null ? heldId : "h" + System.currentTimeMillis()); hjson.put("at", Db.now()); hjson.put("cart", new JSONArray(cart)); hjson.put("customer", customer); hjson.put("coupon", coupon); hjson.put("invoice_discount", invoiceDiscount); hjson.put("total", total()); hjson.put("label", cart.get(0).optString("name") + (cart.size() > 1 ? " و " + Ui.num(cart.size() - 1) + " قلم دیگر" : "")); keep.put(hjson);
                Prefs.set("pos_held", keep.toString()); cart.clear(); customer = null; coupon = null; invoiceDiscount = 0; heldId = null; renderCart(); Sfx.play("hold"); Ui.toast("فاکتور نگه داشته شد (" + Ui.num(keep.length()) + ")");
            } catch (Exception e) { Ui.toast("خطا در نگه‌داشتن"); }
        }
        void restoreHeld(String id) {
            Sfx.play("resume"); try { JSONArray held = new JSONArray(Prefs.get("pos_held", "[]")); for (int i = 0; i < held.length(); i++) { JSONObject hj = held.optJSONObject(i); if (hj.optString("id").equals(id)) { cart.clear(); JSONArray ca = hj.optJSONArray("cart"); for (int k = 0; ca != null && k < ca.length(); k++) cart.add(ca.optJSONObject(k)); customer = hj.optJSONObject("customer"); coupon = hj.isNull("coupon") ? null : hj.optString("coupon"); invoiceDiscount = hj.optDouble("invoice_discount", 0); heldId = id; } } } catch (Exception ignore) {}
        }
        static void removeHeld(String id) { try { JSONArray held = new JSONArray(Prefs.get("pos_held", "[]")); JSONArray keep = new JSONArray(); for (int i = 0; i < held.length(); i++) if (!held.optJSONObject(i).optString("id").equals(id)) keep.put(held.optJSONObject(i)); Prefs.set("pos_held", keep.toString()); } catch (Exception ignore) {} }

        String smsPhone = null;
        /* ---- payment ---- */
        void pay() {
            if (cart.isEmpty()) { Ui.toast("سبد خالی است"); return; }
            double total = total(); LinearLayout l = Ui.col(c); Dialog[] d = new Dialog[1];
            TextView tt = Ui.text(c, Ui.money(total), 24, Ui.TEXT, true); tt.setGravity(Gravity.CENTER); l.addView(tt);
            l.addView(Ui.muted(c, customer == null ? "مشتری آزاد" : "مشتری: " + customer.optString("name")));
            String[] methods = {"CASH", "CARD", "TRANSFER"}; String[] labels = {"نقدی", "کارت‌خوان", "کارت‌به‌کارت"}; final String[] chosen = {"CASH"}; LinearLayout chips = Ui.row(c); chips.setPadding(0, Ui.dp(8), 0, Ui.dp(8));
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
                JSONObject body = new JSONObject(); JSONArray items = new JSONArray();
                for (JSONObject l : cart) { JSONObject it = new JSONObject(); it.put("product_id", l.optLong("product_id")); it.put("barcode", l.optString("barcode")); it.put("quantity", l.optDouble("quantity")); if (l.optLong("batch_id") > 0) it.put("batch_id", l.optLong("batch_id")); it.put("discount", l.optDouble("discount")); items.put(it); }
                body.put("items", items); JSONArray pays = new JSONArray(); JSONObject p = new JSONObject();
                boolean credit = "CREDIT".equals(method) || (paidAmt < total && customer != null);
                if (credit) { if (paidAmt > 0) { p.put("method", "CASH"); p.put("amount", paidAmt); pays.put(p); } JSONObject cr = new JSONObject(); cr.put("method", "CREDIT"); cr.put("amount", total - paidAmt); pays.put(cr); } else { p.put("method", method); p.put("amount", total); pays.put(p); }
                body.put("payments", pays); if (customer != null) { body.put("customer_id", customer.optLong("id")); body.put("customer_phone", customer.optString("phone")); body.put("customer_name", customer.optString("name")); }
                if (coupon != null) body.put("coupon_code", coupon); if (invoiceDiscount > 0) body.put("invoice_discount", invoiceDiscount); body.put("open_drawer", false);
                // local-first: apply on the phone immediately, then push
                String no = Db.localSale(body, total); if (heldId != null) removeHeld(heldId);
                // v2.3: invoice SMS the moment the sale is confirmed — from the phone itself when there is no PC
                String ph = smsPhone != null && !smsPhone.isEmpty() ? smsPhone : (customer == null ? "" : customer.optString("phone"));
                if (!ph.isEmpty()) { body.put("customer_phone", ph); if (customer == null) { body.put("customer_name", "مشتری " + ph); if (Api.standalone()) { JSONObject cu = Db.customerByPhone(ph); if (cu == null) cu = Db.localCustomer("مشتری " + ph, ph); body.put("customer_id", cu.optLong("id")); } } }
                if (!ph.isEmpty() && SmsLocal.sendInvoiceOn() && SmsLocal.phoneShouldSend()) { if (SmsLocal.configured()) SmsLocal.enqueueAndSend(ph, SmsLocal.renderInvoice(no, total), no); else Ui.toast("پیامک ارسال نشد: سرویس پیامک را در تنظیمات → پیامک تنظیم کنید"); }
                smsPhone = null;
                Sync.queue("POS_CHECKOUT", body, "فاکتور " + no + " · " + Ui.money(total), no);
                cart.clear(); customer = null; coupon = null; invoiceDiscount = 0; heldId = null; renderCart();
                Sfx.play("success"); Ui.toast("فاکتور " + Ui.fa(no) + " ثبت شد" + (Api.online ? " — در حال ارسال به رایانه" : " — پس از اتصال ارسال می‌شود"));
            } catch (Exception e) { Ui.toast("خطا: " + e.getMessage()); }
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
            if (tab == 1) { for (JSONObject o : Db.localInvoices()) body.addView(Ui.item(c, Ui.fa(o.optString("local_no")) + (o.optInt("synced") == 1 ? " ← " + Ui.fa(s(o, "invoice_number")) : ""), Ui.jdate(o.optString("at")) + " · " + Ui.num(o.optInt("items")) + " قلم · " + label(o.optString("payment"), PAY), Ui.money(o.optDouble("total")), o.optInt("synced") == 1 ? Ui.GREEN : Ui.AMBER, null)); if (Db.localInvoices().isEmpty()) body.addView(Ui.empty(c, "هنوز فاکتوری روی این گوشی ثبت نشده")); return; }
            body.addView(Ui.empty(c, "…")); get("/invoices?limit=100", r -> { body.removeViewAt(body.getChildCount() - 1); JSONArray ar = arr(r); if (ar.length() == 0) body.addView(Ui.empty(c, "فاکتوری نیست")); for (int i = 0; i < ar.length(); i++) { JSONObject inv = ar.optJSONObject(i); body.addView(Ui.item(c, Ui.fa(inv.optString("invoice_number")), Ui.jdate(inv.optString("created_at")) + " · " + label(inv.optString("payment_method"), PAY) + " · " + label(inv.optString("status"), INV_ST), Ui.money(inv.optDouble("total_amount")), stColor(inv.optString("status")), () -> a.open(new InvoiceDetail(a, inv.optLong("id")), true))); } });
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
                if (Screens.can("pos.return") && "PAID".equals(inv.optString("status"))) { row.setOnClickListener(v -> returnItem(it, name)); }
                its.addView(row); }
            if (Screens.can("pos.return") && "PAID".equals(inv.optString("status"))) its.addView(Ui.muted(c, "برای مرجوعی روی قلم ضربه بزنید")); body.addView(its);
            LinearLayout act = Ui.card(c, "عملیات");
            act.addView(Ui.ghost(c, "نمایش رسید", () -> get("/invoices/" + id + "/receipt", r -> { TextView t = Ui.text(c, ((JSONObject) r).optString("receipt_text"), 12, Ui.TEXT, false); t.setTypeface(android.graphics.Typeface.MONOSPACE); t.setTextDirection(View.TEXT_DIRECTION_LTR); t.setGravity(Gravity.START); Ui.sheet(c, "رسید", t); })));
            act.addView(Ui.ghost(c, Api.standalone() ? "چاپ / اشتراک رسید" : "چاپ روی چاپگر رایانه", () -> post("/invoices/" + id + "/print", null, r -> Ui.toast("به صف چاپ رایانه رفت"))));
            if (!"VOID".equals(inv.optString("status")) && (Screens.can("pos.void_paid") || Screens.can("pos.void_unpaid"))) act.addView(Ui.danger(c, "ابطال فاکتور", this::voidInvoice));
            body.addView(act);
        }
        void voidInvoice() { LinearLayout l = Ui.col(c); EditText reason = Ui.input(c, "دلیل ابطال"); l.addView(reason); EditText pw = Ui.input(c, "رمز مدیر (برای فاکتور پرداخت‌شده)"); pw.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD); l.addView(pw); Dialog[] d = new Dialog[1]; l.addView(Ui.danger(c, "تأیید ابطال", () -> { d[0].dismiss(); JSONObject b = j("reason", Ui.str(reason)); putIf(b, "admin_password", Ui.str(pw)); post("/invoices/" + id + "/void", b, r -> { Sfx.play("void"); Ui.toast("فاکتور باطل شد"); Sync.kick(); load(); }); })); d[0] = Ui.sheet(c, "ابطال " + Ui.fa(inv.optString("invoice_number")), l); }
        void returnItem(JSONObject it, String name) { LinearLayout l = Ui.col(c); l.addView(Ui.body(c, name + " — فروخته‌شده: " + Ui.num(it.optDouble("qty")))); EditText qty = Ui.input(c, "تعداد مرجوعی", true); l.addView(qty); EditText reason = Ui.input(c, "دلیل"); l.addView(reason); EditText refund = Ui.input(c, "مبلغ بازپرداخت (خالی = خودکار)", true); l.addView(refund); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ثبت مرجوعی", () -> { d[0].dismiss(); JSONObject b = j("reason", Ui.str(reason)); putNum(b, "invoice_id", id); putNum(b, "invoice_item_id", it.optLong("id")); putNum(b, "qty", (int) Ui.numVal(qty, 1)); if (!Ui.str(refund).isEmpty()) putNum(b, "refund_amount", Ui.numVal(refund, 0)); post("/returns", b, r -> { Ui.toast("مرجوعی ثبت شد (RETURN_IN)"); Sync.kick(); load(); }); })); d[0] = Ui.sheet(c, "مرجوعی", l); }
    }

    /* ---------------- Customers + ledger ---------------- */
    public static final class Customers extends Screens.Screen {
        int tab = 0; EditText q;
        Customers(AppActivity a) { super(a); }
        public String key() { return "customers"; } public String title() { return "مشتریان"; }
        public void load() {
            clear(); body.addView(tabs(new String[]{"همه", "بدهکاران"}, tab, t -> { tab = t; load(); }));
            if (tab == 1) { body.addView(Ui.empty(c, "…")); get("/customers/debtors", r -> { body.removeViewAt(body.getChildCount() - 1); JSONArray ar = arr(r); if (ar.length() == 0) body.addView(Ui.empty(c, "بدهکاری نیست")); for (int i = 0; i < ar.length(); i++) { JSONObject cu = ar.optJSONObject(i); body.addView(Ui.item(c, cu.optString("name") + " " + s(cu, "last_name"), Ui.fa(s(cu, "phone")), Ui.money(cu.optDouble("balance", cu.optDouble("debt", 0))), Ui.RED, () -> a.open(new CustomerDetail(a, cu), true))); } }); return; }
            LinearLayout sr = Ui.row(c); q = Ui.input(c, "جست‌وجو نام / موبایل"); q.setLayoutParams(Ui.weight(1)); sr.addView(q); View add = Ui.primary(c, "+ جدید", () -> newCustomer(a, Ui.str(q), cu -> load())); add.setLayoutParams(Ui.margin(Ui.lp(ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(44)), 6, 0, 0, 6)); sr.addView(add); body.addView(sr);
            LinearLayout list = Ui.col(c); body.addView(list);
            Runnable fill = () -> { list.removeAllViews(); List<JSONObject> cs = Db.customers(Ui.str(q)); if (cs.isEmpty()) list.addView(Ui.empty(c, "مشتری‌ای نیست")); for (JSONObject cu : cs) list.addView(Ui.item(c, cu.optString("name") + " " + s(cu, "last_name"), Ui.fa(s(cu, "phone")) + (cu.optBoolean("_local") ? " · در انتظار ارسال" : ""), cu.optDouble("credit_limit") > 0 ? "سقف " + Ui.money(cu.optDouble("credit_limit")) : null, Ui.MUTED, () -> a.open(new CustomerDetail(a, cu), true))); };
            q.addTextChangedListener(new TextWatcher() { public void beforeTextChanged(CharSequence s, int i, int i1, int i2) {} public void onTextChanged(CharSequence s, int i, int i1, int i2) {} public void afterTextChanged(Editable e) { fill.run(); } }); fill.run();
        }
        static void newCustomer(AppActivity a, String prefill, java.util.function.Consumer<JSONObject> cb) {
            LinearLayout l = Ui.col(a); EditText name = Ui.input(a, "نام *"); EditText last = Ui.input(a, "نام خانوادگی"); EditText phone = Ui.input(a, "موبایل", true); phone.setInputType(android.text.InputType.TYPE_CLASS_PHONE); EditText addr = Ui.input(a, "آدرس"); EditText limit = Ui.input(a, "سقف اعتبار (۰ = بدون سقف)", true);
            if (prefill.matches("[0-9۰-۹]+")) phone.setText(prefill); else name.setText(prefill);
            l.addView(name); l.addView(last); l.addView(phone); l.addView(addr); l.addView(limit); Dialog[] d = new Dialog[1];
            l.addView(Ui.primary(a, "ثبت مشتری", () -> { if (Ui.str(name).isEmpty()) { Ui.toast("نام لازم است"); return; } d[0].dismiss(); JSONObject b = Api.obj("name", Ui.str(name), "last_name", Ui.str(last), "phone", Db.norm(Ui.str(phone)), "address", Ui.str(addr)); try { b.put("credit_enabled", true); b.put("credit_limit", Ui.numVal(limit, 0)); } catch (Exception ignore) {} JSONObject local = Db.localCustomer(Ui.str(name), Db.norm(Ui.str(phone))); Sync.queue("CUSTOMER_CREATE", b, "مشتری " + Ui.str(name), null); Ui.toast("مشتری ثبت شد"); cb.accept(local); }));
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
        void settle(double bal) { LinearLayout l = Ui.col(c); l.addView(Ui.body(c, "ماندهٔ فعلی: " + Ui.money(bal))); EditText amt = Ui.input(c, "مبلغ (خالی = تسویهٔ کامل)", true); l.addView(amt); final String[] m = {"CASH"}; LinearLayout ch = Ui.row(c); Runnable[] rd = new Runnable[1]; rd[0] = () -> { ch.removeAllViews(); for (String[] p : new String[][]{{"CASH", "نقدی"}, {"CARD", "کارت"}, {"TRANSFER", "کارت‌به‌کارت"}}) ch.addView(Ui.chip(c, p[1], p[0].equals(m[0]), () -> { m[0] = p[0]; rd[0].run(); })); }; rd[0].run(); l.addView(ch); EditText note = Ui.input(c, "توضیح"); l.addView(note); Dialog[] d = new Dialog[1]; l.addView(Ui.success(c, "ثبت تسویه", () -> { d[0].dismiss(); JSONObject b = j("method", m[0], "note", Ui.str(note)); if (!Ui.str(amt).isEmpty()) putNum(b, "amount", Ui.numVal(amt, 0)); post("/customers/" + id + "/settle", b, r -> { Ui.toast("تسویه ثبت شد"); load(); }); })); d[0] = Ui.sheet(c, "تسویهٔ بدهی", l); }
        void adjust() { LinearLayout l = Ui.col(c); final String[] t = {"ADJUSTMENT_DEBIT"}; LinearLayout ch = Ui.row(c); Runnable[] rd = new Runnable[1]; rd[0] = () -> { ch.removeAllViews(); ch.addView(Ui.chip(c, "افزایش بدهی", t[0].endsWith("DEBIT"), () -> { t[0] = "ADJUSTMENT_DEBIT"; rd[0].run(); })); ch.addView(Ui.chip(c, "کاهش بدهی", t[0].endsWith("CREDIT"), () -> { t[0] = "ADJUSTMENT_CREDIT"; rd[0].run(); })); }; rd[0].run(); l.addView(ch); EditText amt = Ui.input(c, "مبلغ", true); l.addView(amt); EditText note = Ui.input(c, "توضیح *"); l.addView(note); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ثبت", () -> { if (Ui.str(note).isEmpty()) { Ui.toast("توضیح لازم است"); return; } d[0].dismiss(); JSONObject b = j("entry_type", t[0], "note", Ui.str(note)); putNum(b, "amount", Ui.numVal(amt, 0)); post("/customers/" + id + "/ledger/adjust", b, r -> { Ui.toast("ثبت شد"); load(); }); })); d[0] = Ui.sheet(c, "اصلاح دستی دفتر حساب", l); }
        void edit() { LinearLayout l = Ui.col(c); EditText name = Ui.input(c, "نام"); name.setText(s(cu, "name")); EditText last = Ui.input(c, "نام خانوادگی"); last.setText(s(cu, "last_name")); EditText phone = Ui.input(c, "موبایل", true); phone.setText(s(cu, "phone")); EditText addr = Ui.input(c, "آدرس"); addr.setText(s(cu, "address")); EditText limit = Ui.input(c, "سقف اعتبار", true); limit.setText(Ui.num(cu.optDouble("credit_limit"))); l.addView(name); l.addView(last); l.addView(phone); l.addView(addr); l.addView(limit); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ذخیره", () -> { d[0].dismiss(); JSONObject b = j("name", Ui.str(name), "last_name", Ui.str(last), "phone", Db.norm(Ui.str(phone)), "address", Ui.str(addr)); putNum(b, "credit_limit", Ui.numVal(limit, 0)); patch("/customers/" + id, b, r -> { cu = (JSONObject) r; Db.putCustomer(cu, false); Ui.toast("ذخیره شد"); load(); }); })); d[0] = Ui.sheet(c, "ویرایش مشتری", l); }
    }

    /* ---------------- Marketing: campaigns + coupons ---------------- */
    public static final class Marketing extends Screens.Screen {
        int tab = 0;
        Marketing(AppActivity a) { super(a); }
        public String key() { return "marketing"; } public String title() { return "جشنواره و کوپن"; }
        public void load() {
            clear(); body.addView(tabs(new String[]{"جشنواره‌ها", "کوپن‌ها", "آمار"}, tab, t -> { tab = t; load(); })); LinearLayout list = Ui.col(c); body.addView(list);
            if (tab == 0) { body.addView(Ui.primary(c, "+ جشنوارهٔ جدید", this::newCampaign)); get("/marketing/campaigns", r -> { JSONArray ar = arr(r); if (ar.length() == 0) list.addView(Ui.empty(c, "جشنواره‌ای تعریف نشده")); for (int i = 0; i < ar.length(); i++) { JSONObject cp = ar.optJSONObject(i); LinearLayout it = Ui.item(c, cp.optString("name"), ("PERCENT".equals(cp.optString("discount_type")) ? Ui.num(cp.optDouble("discount_value")) + "٪" : Ui.money(cp.optDouble("discount_value"))) + " · حداقل خرید " + Ui.money(cp.optDouble("min_purchase")) + (cp.isNull("valid_until") ? "" : " · تا " + Ui.jdate(cp.optString("valid_until"))), label(cp.optString("status"), new String[][]{{"ACTIVE", "فعال"}, {"PAUSED", "متوقف"}, {"ENDED", "پایان‌یافته"}}), stColor(cp.optString("status")), () -> { String next = "ACTIVE".equals(cp.optString("status")) ? "PAUSED" : "ACTIVE"; Ui.confirm(c, "وضعیت به «" + ("ACTIVE".equals(next) ? "فعال" : "متوقف") + "» تغییر کند؟", () -> patch("/marketing/campaigns/" + cp.optLong("id"), j("status", next), x -> load())); }); list.addView(it); } }); }
            else if (tab == 1) { body.addView(Ui.primary(c, "+ صدور کوپن", this::newCoupon)); get("/marketing/coupons", r -> { JSONArray ar = arr(r); if (ar.length() == 0) list.addView(Ui.empty(c, "کوپنی نیست")); for (int i = 0; i < ar.length(); i++) { JSONObject cp = ar.optJSONObject(i); list.addView(Ui.item(c, cp.optString("code"), ("PERCENT".equals(cp.optString("discount_type")) ? Ui.num(cp.optDouble("discount_value")) + "٪" : Ui.money(cp.optDouble("discount_value"))) + (s(cp, "customer_phone").isEmpty() ? "" : " · " + Ui.fa(s(cp, "customer_phone"))) + " · استفاده " + Ui.fa(cp.optInt("used_count") + "/" + cp.optInt("usage_limit", 1)), label(cp.optString("status"), new String[][]{{"ACTIVE", "فعال"}, {"USED", "مصرف‌شده"}, {"BLOCKED", "مسدود"}, {"EXPIRED", "منقضی"}}), stColor(cp.optString("status")), () -> { if ("ACTIVE".equals(cp.optString("status"))) Ui.confirm(c, "کوپن " + cp.optString("code") + " مسدود شود؟", () -> post("/marketing/coupons/" + cp.optLong("id") + "/block", null, x -> load())); })); } }); }
            else get("/marketing/stats", r -> { JSONObject st = (JSONObject) r; LinearLayout cd = Ui.card(c, "آمار"); cd.addView(Ui.kv(c, "جشنواره‌ها", Ui.num(st.optDouble("campaigns")), 0)); cd.addView(Ui.kv(c, "کل کوپن‌ها", Ui.num(st.optDouble("total_coupons")), 0)); cd.addView(Ui.kv(c, "ارزش تخفیف مصرف‌شده", Ui.money(st.optDouble("redeemed_value")), Ui.GREEN)); JSONObject bs = st.optJSONObject("by_status"); if (bs != null) { java.util.Iterator<String> it = bs.keys(); while (it.hasNext()) { String k = it.next(); cd.addView(Ui.kv(c, k, Ui.num(bs.optDouble(k)), 0)); } } list.addView(cd); });
        }
        void newCampaign() { LinearLayout l = Ui.col(c); EditText name = Ui.input(c, "نام جشنواره *"); EditText val = Ui.input(c, "مقدار تخفیف", true); EditText min = Ui.input(c, "حداقل خرید", true); EditText max = Ui.input(c, "سقف تخفیف (اختیاری)", true); EditText until = DatePicker.field(c, "پایان (اختیاری)"); EditText thr = Ui.input(c, "صدور خودکار کوپن بعد از خرید بالای (اختیاری)", true); final String[] ty = {"PERCENT"}; LinearLayout ch = Ui.row(c); Runnable[] rd = new Runnable[1]; rd[0] = () -> { ch.removeAllViews(); ch.addView(Ui.chip(c, "درصدی", ty[0].equals("PERCENT"), () -> { ty[0] = "PERCENT"; rd[0].run(); })); ch.addView(Ui.chip(c, "مبلغ ثابت", ty[0].equals("FIXED"), () -> { ty[0] = "FIXED"; rd[0].run(); })); }; rd[0].run(); l.addView(name); l.addView(ch); l.addView(val); l.addView(min); l.addView(max); l.addView(until); l.addView(thr); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ایجاد", () -> { try { JSONObject b = j("name", Ui.str(name), "discount_type", ty[0]); putNum(b, "discount_value", Ui.numVal(val, 0)); putNum(b, "min_purchase", Ui.numVal(min, 0)); if (!Ui.str(max).isEmpty()) putNum(b, "max_discount", Ui.numVal(max, 0)); String u = dateIn(until); if (u != null) b.put("valid_until", u + "T23:59:59"); if (!Ui.str(thr).isEmpty()) putNum(b, "auto_issue_threshold", Ui.numVal(thr, 0)); d[0].dismiss(); post("/marketing/campaigns", b, r -> { Ui.toast("جشنواره ایجاد شد"); load(); }); } catch (Exception ignore) {} })); d[0] = Ui.sheet(c, "جشنوارهٔ جدید", l); }
        void newCoupon() { LinearLayout l = Ui.col(c); EditText code = Ui.input(c, "کد (خالی = خودکار)"); EditText val = Ui.input(c, "مقدار تخفیف", true); EditText min = Ui.input(c, "حداقل خرید", true); EditText phone = Ui.input(c, "موبایل مشتری (اختیاری)", true); EditText until = DatePicker.field(c, "انقضا (اختیاری)"); EditText lim = Ui.input(c, "تعداد دفعات استفاده", true); lim.setText("1"); final String[] ty = {"PERCENT"}; LinearLayout ch = Ui.row(c); Runnable[] rd = new Runnable[1]; rd[0] = () -> { ch.removeAllViews(); ch.addView(Ui.chip(c, "درصدی", ty[0].equals("PERCENT"), () -> { ty[0] = "PERCENT"; rd[0].run(); })); ch.addView(Ui.chip(c, "مبلغ ثابت", ty[0].equals("FIXED"), () -> { ty[0] = "FIXED"; rd[0].run(); })); }; rd[0].run(); l.addView(code); l.addView(ch); l.addView(val); l.addView(min); l.addView(phone); l.addView(until); l.addView(lim); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "صدور", () -> { try { JSONObject b = j("discount_type", ty[0]); putIf(b, "code", Ui.str(code)); putIf(b, "customer_phone", Db.norm(Ui.str(phone))); putNum(b, "discount_value", Ui.numVal(val, 0)); putNum(b, "min_purchase", Ui.numVal(min, 0)); putNum(b, "usage_limit", (int) Ui.numVal(lim, 1)); String u = dateIn(until); if (u != null) b.put("valid_until", u + "T23:59:59"); d[0].dismiss(); post("/marketing/coupons", b, r -> { Ui.toast("کوپن " + ((JSONObject) r).optString("code") + " صادر شد"); load(); }); } catch (Exception ignore) {} })); d[0] = Ui.sheet(c, "صدور کوپن", l); }
    }
}
