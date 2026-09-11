package ir.khajavy.supermarket;

import android.app.Dialog;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;

/** v2.0 — products, receive (batches), inventory, stocktake, waste/adjust/transfer, warehouses, movements. */
public final class StockScreens {
    private StockScreens() {}
    static JSONArray units = new JSONArray(), categories = new JSONArray(), brands = new JSONArray();
    static void loadLocalUnits() { if (units.length() == 0) { try { String u = Db.kv("local_units"); if (u != null) units = new JSONArray(u); } catch (Exception ignore) {} if (units.length() == 0) { try { units = new JSONArray("[{\"id\":1,\"name\":\"عدد\",\"allow_decimal\":false},{\"id\":2,\"name\":\"کیلوگرم\",\"allow_decimal\":true},{\"id\":3,\"name\":\"بسته\",\"allow_decimal\":false},{\"id\":4,\"name\":\"لیتر\",\"allow_decimal\":true}]"); } catch (Exception ignore) {} } } }
    static void loadTaxonomy() { if (Api.standalone()) loadLocalUnits(); Api.get("/units", r -> units = (JSONArray) r, e -> {}); Api.get("/products/categories", r -> categories = (JSONArray) r, e -> {}); Api.get("/products/brands", r -> brands = (JSONArray) r, e -> {}); }
    static String unitName(long id) { for (int i = 0; i < units.length(); i++) if (units.optJSONObject(i).optLong("id") == id) return units.optJSONObject(i).optString("name"); return ""; }
    static boolean unitDecimal(long id) { for (int i = 0; i < units.length(); i++) if (units.optJSONObject(i).optLong("id") == id) return units.optJSONObject(i).optBoolean("allow_decimal"); return false; }

    /* ---------------- Products ---------------- */
    public static final class Products extends Screens.Screen {
        EditText q; LinearLayout list;
        Products(AppActivity a) { super(a); }
        public String key() { return "products"; } public String title() { return "کالاها"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            clear(); if (units.length() == 0) loadTaxonomy();
            LinearLayout sr = Ui.row(c); q = Ui.input(c, "نام / بارکد / SKU"); q.setLayoutParams(Ui.weight(1)); sr.addView(q);
            View sc = Ui.btn(c, "اسکن", Ui.PRIMARY, 0xFFFFFFFF, () -> a.scan("اسکن کالا", code -> a.open(new ProductDetail(a, code), true))); sc.setLayoutParams(Ui.margin(Ui.lp(ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(44)), 6, 0, 0, 6)); sr.addView(sc); body.addView(sr);
            LinearLayout act = Ui.row(c); if (Screens.can("products.manage")) act.addView(Ui.small(c, "+ کالای جدید", () -> newProduct(a, null, p -> load()))); act.addView(Ui.small(c, "واحدها", () -> a.open(new Units(a), true))); act.addView(Ui.small(c, "دسته / برند", () -> a.open(new Taxonomy(a), true))); body.addView(act);
            TextView cnt = Ui.muted(c, Ui.num(Db.count("products")) + " کالا روی گوشی"); body.addView(cnt);
            list = Ui.col(c); body.addView(list);
            Runnable fill = () -> { list.removeAllViews(); List<JSONObject> ps = Db.searchProducts(Ui.str(q), 60); if (ps.isEmpty()) list.addView(Ui.empty(c, Db.count("products") == 0 ? "کاتالوگ هنوز از رایانه دریافت نشده — به رایانه وصل شوید" : "کالایی یافت نشد")); for (JSONObject p : ps) { double av = p.optDouble("available_qty"); JSONArray bs = p.optJSONArray("batches"); double price = bs != null && bs.length() > 0 ? bs.optJSONObject(0).optDouble("sell_price") : 0; list.addView(Ui.pitem(c, p, p.optString("name"), Ui.fa(p.optString("barcode")) + (p.optLong("unit_id") > 0 ? " · " + unitName(p.optLong("unit_id")) : "") + (p.optBoolean("_local") ? " · در انتظار ارسال" : ""), Ui.money(price) + "\n" + "موجودی " + Ui.num(av), av <= p.optDouble("min_stock_alert", 0) ? Ui.RED : Ui.TEXT, () -> a.open(new ProductDetail(a, p.optString("barcode")), true))); } };
            q.addTextChangedListener(new TextWatcher() { public void beforeTextChanged(CharSequence s, int i, int i1, int i2) {} public void onTextChanged(CharSequence s, int i, int i1, int i2) {} public void afterTextChanged(Editable e) { fill.run(); } }); fill.run();
        }
        static void newProduct(AppActivity a, String barcode, java.util.function.Consumer<JSONObject> cb) {
            LinearLayout l = Ui.col(a); EditText bc = Ui.input(a, "بارکد (خالی = کد داخلی INT-)", true); if (barcode != null) bc.setText(barcode); EditText name = Ui.input(a, "نام کالا *"); EditText sku = Ui.input(a, "SKU (اختیاری)"); EditText min = Ui.input(a, "حداقل موجودی هشدار", true);
            final long[] unit = {units.length() > 0 ? units.optJSONObject(0).optLong("id") : 0}; LinearLayout uc = Ui.row(a); Runnable[] rd = new Runnable[1]; rd[0] = () -> { uc.removeAllViews(); for (int i = 0; i < units.length(); i++) { JSONObject u = units.optJSONObject(i); uc.addView(Ui.chip(a, u.optString("name"), u.optLong("id") == unit[0], () -> { unit[0] = u.optLong("id"); rd[0].run(); })); } }; rd[0].run();
            LinearLayout br = Ui.row(a); bc.setLayoutParams(Ui.weight(1)); br.addView(bc);
            TextView hint = Ui.muted(a, ""); hint.setVisibility(View.GONE);
            // v2.6 — the scanned GTIN is looked up in Iranian marketplaces (exact barcode-in-title only); name/unit are proposed, never forced
            Runnable[] auto = new Runnable[1]; auto[0] = () -> { final String code = Db.norm(Ui.str(bc)); if (code.length() < 8 || !code.matches("[0-9]+") || Db.productByBarcode(code) != null) return; hint.setText("در حال شناسایی کالا از روی بارکد…"); hint.setVisibility(View.VISIBLE); Api.bg(() -> { JSONObject h = Images.lookupBarcode(code); a.runOnUiThread(() -> { if (!code.equals(Db.norm(Ui.str(bc)))) return; if (h == null) { hint.setText("این بارکد در منابع آنلاین پیدا نشد — نام را دستی وارد کنید"); return; } if (Ui.str(name).isEmpty()) name.setText(h.optString("name")); String u = h.optString("unit"); hint.setText("شناسایی شد (" + ("basalam".equals(h.optString("shop")) ? "باسلام" : "ترب") + ")" + (u.isEmpty() ? "" : " · " + u) + " — در صورت نیاز نام را اصلاح کنید"); }); }); };
            br.addView(Ui.small(a, "اسکن", () -> a.scan("اسکن بارکد کالا", code -> { bc.setText(code); auto[0].run(); })));
            bc.setOnFocusChangeListener((v, f) -> { if (!f) auto[0].run(); });
            l.addView(br); l.addView(hint); l.addView(name); l.addView(sku);
            if (barcode != null && !barcode.isEmpty()) auto[0].run(); l.addView(Ui.label(a, "واحد")); l.addView(Ui.chips(a, uc)); l.addView(min);
            l.addView(Ui.muted(a, "قیمت به بچ تعلق دارد نه کالا؛ پس از تعریف، از «ورود کالا» بچ اول را با قیمت‌ها ثبت کنید."));
            Dialog[] d = new Dialog[1];
            l.addView(Ui.primary(a, "ثبت کالا", () -> { if (Ui.str(name).isEmpty()) { Ui.toast("نام لازم است"); return; } String code = Db.norm(Ui.str(bc)); if (!code.isEmpty() && Db.productByBarcode(code) != null) { Ui.toast("این بارکد قبلاً ثبت شده"); return; } d[0].dismiss(); JSONObject b = Api.obj("name", Ui.str(name), "sku", Ui.str(sku)); try { if (!code.isEmpty()) b.put("barcode", code); if (unit[0] > 0) b.put("unit_id", unit[0]); b.put("min_stock_alert", (int) Ui.numVal(min, 0)); b.put("has_own_barcode", !code.isEmpty()); } catch (Exception ignore) {} JSONObject local = Db.localProduct(code, Ui.str(name), unit[0] > 0 ? unit[0] : null); if (code.isEmpty()) putIf(b, "barcode", local.optString("barcode")); Sync.queue("PRODUCT_CREATE", b, "کالای " + Ui.str(name), null); Images.findLater(local.optLong("id")); Ui.done(a, "کالا ثبت شد", Ui.str(name) + "\nتصویر کالا خودکار پیدا می‌شود", () -> cb.accept(local)); }));
            d[0] = Ui.sheet(a, "کالای جدید", l);
        }
    }

    public static final class ProductDetail extends Screens.Screen {
        final String barcode; JSONObject p;
        ProductDetail(AppActivity a, String barcode) { super(a); this.barcode = Db.norm(barcode); }
        public String key() { return "products"; } public String title() { return "کالا"; }
        public void load() {
            p = Db.productByBarcode(barcode); clear();
            if (p == null) { LinearLayout cd = Ui.card(c, "کالا یافت نشد"); cd.addView(Ui.body(c, "بارکد " + Ui.fa(barcode) + " در کاتالوگ نیست.")); if (Screens.can("products.manage")) cd.addView(Ui.primary(c, "تعریف همین کالا", () -> Products.newProduct(a, barcode, np -> load()))); cd.addView(Ui.ghost(c, "شناسایی کالا از روی بارکد (آنلاین)", () -> { Ui.toast("در حال جست‌وجو…"); Api.bg(() -> { JSONObject h = Images.lookupBarcode(barcode); a.runOnUiThread(() -> { if (h == null) { Ui.toast("این بارکد در فروشگاه‌های آنلاین پیدا نشد"); return; } Ui.confirm(c, "شناسایی شد: " + h.optString("name") + (h.optString("unit").isEmpty() ? "" : " · " + h.optString("unit")) + "\nبا همین نام تعریف شود؟", () -> { if (Screens.can("products.manage")) Products.newProduct(a, barcode, np -> load()); }); }); }); })); body.addView(cd); return; }
            long pid = p.optLong("id"); LinearLayout hd = Ui.card(c, p.optString("name"));
            LinearLayout pr = Ui.row(c); pr.addView(Ui.thumb(c, p, 96)); LinearLayout pc = Ui.col(c); pc.setLayoutParams(Ui.weight(1));
            pc.addView(Ui.muted(c, Images.urlOf(p) == null ? "تصویری ندارد — جست‌وجوی خودکار در پس‌زمینه انجام می‌شود" : "تصویر کالا")); if (Screens.can("products.manage")) pc.addView(Ui.small(c, Images.urlOf(p) == null ? "انتخاب تصویر" : "تغییر تصویر", () -> pickImage((AppActivity) c, pid, () -> load())));
            pr.addView(pc); hd.addView(pr);
            hd.addView(Ui.kv(c, "بارکد", Ui.fa(barcode), 0)); if (!s(p, "sku").isEmpty()) hd.addView(Ui.kv(c, "SKU", s(p, "sku"), 0)); hd.addView(Ui.kv(c, "واحد", unitName(p.optLong("unit_id")).isEmpty() ? "عدد" : unitName(p.optLong("unit_id")), 0)); hd.addView(Ui.kv(c, "موجودی کل", Ui.num(p.optDouble("available_qty")), p.optDouble("available_qty") <= p.optDouble("min_stock_alert") ? Ui.RED : Ui.GREEN)); hd.addView(Ui.kv(c, "حداقل هشدار", Ui.num(p.optDouble("min_stock_alert")), 0)); body.addView(hd);
            LinearLayout act = Ui.row(c); act.addView(Ui.small(c, "فروش", () -> { a.route("pos"); ((SalesScreens.Pos) a.current()).add(p, null); })); if (Screens.can("batches.manage")) act.addView(Ui.small(c, "ورود کالا", () -> a.open(new Receive(a, barcode), true))); if (Screens.can("products.manage") && pid > 0) { act.addView(Ui.small(c, "ویرایش", this::edit)); act.addView(Ui.small(c, "قیمت سریع", this::quickPrice)); } body.addView(act);
            LinearLayout bs = Ui.card(c, "بچ‌های فعال (FEFO)"); JSONArray ar = p.optJSONArray("batches"); if (ar == null || ar.length() == 0) bs.addView(Ui.muted(c, "بچ فعالی ندارد")); for (int i = 0; ar != null && i < ar.length(); i++) { JSONObject b = ar.optJSONObject(i); bs.addView(Ui.item(c, "بچ " + Ui.fa(b.optString("batch_number")), "موجودی " + Ui.num(b.optDouble("current_qty")) + (b.isNull("expiry_date") ? "" : " · انقضا " + Ui.jdate(b.optString("expiry_date"))) + (Screens.can("pricing.view_cost") ? " · خرید " + Ui.money(b.optDouble("buy_price")) : ""), "فروش " + Ui.money(b.optDouble("sell_price")) + "\nمصرف‌کننده " + Ui.money(b.optDouble("consumer_price")), 0, null)); } body.addView(bs);
            if (pid != 0) { LinearLayout ph = Ui.card(c, "تاریخچهٔ قیمت (غیرقابل ویرایش)"); body.addView(ph); getQuiet("/prices/history/" + pid, r -> { JSONArray h = arr(r); if (h.length() == 0) ph.addView(Ui.muted(c, "—")); for (int i = 0; i < Math.min(10, h.length()); i++) { JSONObject e = h.optJSONObject(i); ph.addView(Ui.kv(c, Ui.jdate(e.optString("effective_from")) + " · " + label(e.optString("price_type"), new String[][]{{"SELL", "فروش"}, {"CONSUMER", "مصرف‌کننده"}, {"BUY", "خرید"}}) + (e.optBoolean("is_active") ? " (فعال)" : ""), Ui.money(e.optDouble("price")), 0)); } });
                LinearLayout dp = Ui.card(c, "بچ‌های تمام‌شده"); body.addView(dp); getQuiet("/products/" + pid + "/detail", r -> { JSONArray dd = ((JSONObject) r).optJSONArray("depleted_batches"); if (dd == null || dd.length() == 0) dp.addView(Ui.muted(c, "—")); for (int i = 0; dd != null && i < Math.min(8, dd.length()); i++) { JSONObject b = dd.optJSONObject(i); dp.addView(Ui.kv(c, Ui.fa(b.optString("batch_number")) + " · " + Ui.jdate(b.optString("received_at")), "دریافت " + Ui.num(b.optDouble("quantity_received")), 0)); } }); }
        }
        void edit() { LinearLayout l = Ui.col(c); EditText name = Ui.input(c, "نام"); name.setText(p.optString("name")); EditText sku = Ui.input(c, "SKU"); sku.setText(s(p, "sku")); EditText min = Ui.input(c, "حداقل هشدار", true); min.setText(Ui.num(p.optDouble("min_stock_alert"))); final long[] unit = {p.optLong("unit_id")}; LinearLayout uc = Ui.row(c); Runnable[] rd = new Runnable[1]; rd[0] = () -> { uc.removeAllViews(); for (int i = 0; i < units.length(); i++) { JSONObject u = units.optJSONObject(i); uc.addView(Ui.chip(c, u.optString("name"), u.optLong("id") == unit[0], () -> { unit[0] = u.optLong("id"); rd[0].run(); })); } }; rd[0].run(); l.addView(name); l.addView(sku); l.addView(Ui.chips(c, uc)); l.addView(min); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ذخیره", () -> { d[0].dismiss(); JSONObject b = j("name", Ui.str(name), "sku", Ui.str(sku)); putNum(b, "min_stock_alert", (int) Ui.numVal(min, 0)); if (unit[0] > 0) putNum(b, "unit_id", unit[0]); patch("/products/" + p.optLong("id"), b, r -> { Db.putProduct((JSONObject) r, false); Ui.done(Ui.ctx, "ذخیره شد", null, null); load(); }); })); l.addView(Ui.danger(c, "حذف کالا", () -> Ui.confirm(c, "کالا حذف (غیرفعال) شود؟", () -> { d[0].dismiss(); Api.delete("/products/" + p.optLong("id"), r -> { Ui.toast("حذف شد"); Db.kv("cursor", null); Sync.kick(); a.back(); }, e -> Ui.toast(e.getMessage())); }))); d[0] = Ui.sheet(c, "ویرایش کالا", l); }
        void quickPrice() { LinearLayout l = Ui.col(c); l.addView(Ui.muted(c, "قیمت جدید روی بچ‌های فعال اعمال و در تاریخچهٔ قیمت ثبت می‌شود.")); EditText sell = Ui.input(c, "قیمت فروش", true); EditText cons = Ui.input(c, "قیمت مصرف‌کننده", true); l.addView(sell); l.addView(cons); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "اعمال روی همهٔ بچ‌ها", () -> { d[0].dismiss(); JSONObject b = j(); if (!Ui.str(sell).isEmpty()) putNum(b, "sell_price", Ui.numVal(sell, 0)); if (!Ui.str(cons).isEmpty()) putNum(b, "consumer_price", Ui.numVal(cons, 0)); try { b.put("apply_to_all_batches", true); } catch (Exception ignore) {} post("/products/" + p.optLong("id") + "/quick-price", b, r -> { Ui.toast("قیمت به‌روز شد"); Sync.kick(); Api.ui(this::load, 1200); }); })); d[0] = Ui.sheet(c, "تغییر سریع قیمت", l); }
    }

    public static final class Units extends Screens.Screen {
        Units(AppActivity a) { super(a); }
        public String key() { return "products"; } public String title() { return "واحدهای شمارش"; }
        public void load() { loading(); get("/units", r -> { units = (JSONArray) r; clear(); body.addView(Ui.muted(c, "واحدهای اعشاری (گرم، کیلوگرم، لیتر…) فروش با مقدار کسری را ممکن می‌کنند.")); for (int i = 0; i < units.length(); i++) { JSONObject u = units.optJSONObject(i); body.addView(Ui.item(c, u.optString("name"), u.optString("symbol") + (u.optBoolean("allow_decimal") ? " · اعشاری (" + Ui.num(u.optInt("decimals")) + " رقم)" : " · صحیح"), u.optBoolean("is_active") ? "فعال" : "غیرفعال", u.optBoolean("is_active") ? Ui.GREEN : Ui.MUTED, null)); } if (Screens.can("products.manage")) body.addView(Ui.primary(c, "+ واحد جدید", () -> { LinearLayout l = Ui.col(c); EditText n = Ui.input(c, "نام (مثلاً بسته)"); EditText sy = Ui.input(c, "نماد"); EditText dec = Ui.input(c, "تعداد رقم اعشار (۰ = صحیح)", true); l.addView(n); l.addView(sy); l.addView(dec); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ثبت", () -> { d[0].dismiss(); int dc = (int) Ui.numVal(dec, 0); JSONObject b = j("name", Ui.str(n), "symbol", Ui.str(sy)); try { b.put("allow_decimal", dc > 0); b.put("decimals", dc); } catch (Exception ignore) {} post("/units", b, x -> load()); })); d[0] = Ui.sheet(c, "واحد جدید", l); })); }); }
    }
    public static final class Taxonomy extends Screens.Screen {
        Taxonomy(AppActivity a) { super(a); }
        public String key() { return "products"; } public String title() { return "دسته‌بندی و برند"; }
        public void load() { clear(); LinearLayout cc = Ui.card(c, "دسته‌بندی‌ها"); body.addView(cc); LinearLayout bc = Ui.card(c, "برندها"); body.addView(bc);
            get("/products/categories", r -> { categories = (JSONArray) r; if (categories.length() == 0) cc.addView(Ui.muted(c, "—")); for (int i = 0; i < categories.length(); i++) cc.addView(Ui.kv(c, categories.optJSONObject(i).optString("name"), "", 0)); if (Screens.can("products.manage")) cc.addView(Ui.small(c, "+ دسته", () -> Ui.prompt(c, "نام دسته", "", false, n -> { if (!n.isEmpty()) post("/products/categories", j("name", n), x -> load()); }))); });
            getQuiet("/products/brands", r -> { brands = (JSONArray) r; if (brands.length() == 0) bc.addView(Ui.muted(c, "—")); for (int i = 0; i < brands.length(); i++) bc.addView(Ui.kv(c, brands.optJSONObject(i).optString("name"), "", 0)); if (Screens.can("products.manage")) bc.addView(Ui.small(c, "+ برند", () -> Ui.prompt(c, "نام برند", "", false, n -> { if (!n.isEmpty()) post("/products/brands", j("name", n), x -> load()); }))); }); }
    }

    /* ---------------- Receive (batch) ---------------- */
    public static final class Receive extends Screens.Screen {
        String barcode; JSONObject p; EditText bc, qty, buy, sell, cons, exp, note; TextView pname;
        Receive(AppActivity a) { super(a); } Receive(AppActivity a, String bc) { super(a); barcode = bc; }
        public String key() { return "receive"; } public String title() { return "ورود کالا"; }
        public void load() {
            clear(); if (units.length() == 0) loadTaxonomy();
            LinearLayout cd = Ui.card(c, "کالا"); LinearLayout br = Ui.row(c); bc = Ui.input(c, "بارکد", true); bc.setLayoutParams(Ui.weight(1)); br.addView(bc); br.addView(Ui.small(c, "اسکن", () -> a.scan("اسکن کالای ورودی", code -> { bc.setText(code); resolve(code); }))); cd.addView(br);
            pname = Ui.text(c, "—", 15, Ui.TEXT, true); cd.addView(pname); body.addView(cd);
            bc.setOnEditorActionListener((v, i, e) -> { resolve(Ui.str(bc)); return true; });
            bc.addTextChangedListener(new TextWatcher() { public void beforeTextChanged(CharSequence s, int i, int i1, int i2) {} public void onTextChanged(CharSequence s, int i, int i1, int i2) {} public void afterTextChanged(Editable e) { if (e.length() >= 8) resolve(e.toString()); } });
            LinearLayout f = Ui.card(c, "بچ جدید"); qty = Ui.input(c, "تعداد / مقدار دریافتی *", true); buy = Ui.input(c, "قیمت خرید *", true); cons = Ui.input(c, "قیمت مصرف‌کننده", true); sell = Ui.input(c, "قیمت فروش (خالی = مصرف‌کننده)", true); exp = DatePicker.field(c, "تاریخ انقضا (اختیاری)"); note = Ui.input(c, "توضیح / تأمین‌کننده");
            f.addView(qty); f.addView(buy); f.addView(cons); f.addView(sell); f.addView(exp); f.addView(note); f.addView(Ui.success(c, "ثبت ورود (IN)", this::submit)); body.addView(f);
            body.addView(Ui.note(c, null, "هر ورود یک «بچ» جدا با قیمت و انقضای خودش می‌سازد (کالا ≠ بچ). فروش به‌صورت FEFO از بچ نزدیک‌تر به انقضا برداشت می‌کند."));
            if (barcode != null) { bc.setText(barcode); resolve(barcode); }
        }
        void resolve(String code) { code = Db.norm(code); p = Db.productByBarcode(code); if (p != null) { pname.setText(p.optString("name") + " · موجودی فعلی " + Ui.num(p.optDouble("available_qty"))); JSONArray bs = p.optJSONArray("batches"); if (bs != null && bs.length() > 0 && Ui.str(buy).isEmpty()) { JSONObject lb = bs.optJSONObject(0); buy.setText(Ui.num(lb.optDouble("buy_price"))); cons.setText(Ui.num(lb.optDouble("consumer_price"))); sell.setText(Ui.num(lb.optDouble("sell_price"))); } } else { pname.setText("تعریف‌نشده — ابتدا کالا را تعریف کنید"); final String cc = code; if (Screens.can("products.manage") && !cc.isEmpty()) Ui.confirm(c, "کالای " + Ui.fa(cc) + " تعریف نشده. اکنون تعریف شود؟", () -> Products.newProduct(a, cc, np -> resolve(cc))); } }
        void submit() {
            if (p == null) { resolve(Ui.str(bc)); if (p == null) { Ui.toast("کالا را مشخص کنید"); return; } }
            double q = Ui.numVal(qty, 0), b = Ui.numVal(buy, -1), cs = Ui.numVal(cons, 0), sl = Ui.str(sell).isEmpty() ? cs : Ui.numVal(sell, 0);
            if (q <= 0) { Ui.toast("مقدار باید بیشتر از صفر باشد"); return; } if (b < 0) { Ui.toast("قیمت خرید لازم است"); return; } if (sl < b) { Ui.toast("قیمت فروش کمتر از خرید است"); }
            if (!unitDecimal(p.optLong("unit_id")) && q != Math.floor(q)) { Ui.toast("واحد این کالا اعشار نمی‌پذیرد"); return; }
            try { String ex = dateIn(exp); JSONObject body = j("barcode", p.optString("barcode"), "note", Ui.str(note)); if (p.optLong("id") > 0) putNum(body, "product_id", p.optLong("id")); putNum(body, "quantity_received", q); putNum(body, "buy_price", b); putNum(body, "consumer_price", cs); putNum(body, "sell_price", sl); if (ex != null) body.put("expiry_date", ex);
                Db.localBatch(p.optLong("id"), q, sl, cs, b, ex); Sync.queue("STOCK_RECEIVE", body, "ورود " + Ui.num(q) + " × " + p.optString("name"), null); qty.setText(""); exp.setText(""); note.setText(""); Ui.done(a, "ورود کالا ثبت شد", Ui.num(q) + " × " + p.optString("name") + "\nموجودی به‌روز شد", () -> { if (!a.back()) resolve(p.optString("barcode")); }); } catch (IllegalArgumentException ignore) {} catch (Exception e) { Ui.toast(e.getMessage()); }
        }
    }

    /* ---------------- Inventory ---------------- */
    public static final class Inventory extends Screens.Screen {
        int tab = 0;
        Inventory(AppActivity a) { super(a); }
        public String key() { return "inventory"; } public String title() { return "انبار و موجودی"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            clear(); body.addView(tabs(new String[]{"همه", "کمبود", "انقضا"}, tab, t -> { tab = t; load(); }));
            if (tab == 2) { body.addView(Ui.empty(c, "…")); get("/reports/expiry", r -> { body.removeViewAt(body.getChildCount() - 1); JSONObject ex = (JSONObject) r; String[][] EK = {{"EXPIRED", "منقضی‌شده"}, {"EXPIRING_TODAY", "امروز منقضی می‌شود"}, {"EXPIRING_3_DAYS", "تا ۳ روز"}, {"EXPIRING_7_DAYS", "تا ۷ روز"}, {"EXPIRING_30_DAYS", "تا ۳۰ روز"}}; boolean any = false; for (String[] k : EK) { JSONArray ar = ex.optJSONArray(k[0]); if (ar == null || ar.length() == 0) continue; any = true; LinearLayout cd = Ui.card(c, k[1] + " (" + Ui.num(ar.length()) + ")"); for (int i = 0; i < ar.length(); i++) { JSONObject b = ar.optJSONObject(i); cd.addView(Ui.kv(c, s(b, "product_name", s(b, "name")) + " · " + Ui.fa(s(b, "batch_number")), Ui.num(b.optDouble("current_qty")) + " · " + Ui.jdate(s(b, "expiry_date")), "EXPIRED".equals(k[0]) ? Ui.RED : Ui.AMBER)); } body.addView(cd); } if (!any) body.addView(Ui.empty(c, "کالای نزدیک انقضا نیست")); }); return; }
            List<JSONObject> rows = Db.stockRows(); double value = 0; int shown = 0; LinearLayout list = Ui.col(c);
            for (JSONObject r : rows) { double st = r.optDouble("total_stock"), mn = r.optDouble("min_stock_alert"); if (tab == 1 && st > mn) continue; shown++; list.addView(Ui.item(c, r.optString("name"), Ui.fa(r.optString("barcode")), Ui.num(st), st <= 0 ? Ui.RED : st <= mn ? Ui.AMBER : Ui.GREEN, () -> a.open(new ProductDetail(a, r.optString("barcode")), true))); }
            body.addView(Ui.muted(c, Ui.num(shown) + " کالا" + (tab == 1 ? " زیر حد هشدار" : ""))); body.addView(list); if (shown == 0) body.addView(Ui.empty(c, tab == 1 ? "کمبودی نیست" : "کاتالوگ خالی است"));
        }
    }

    /* ---------------- Stocktake (resumable, barcode-driven) ---------------- */
    public static final class Stocktake extends Screens.Screen {
        Stocktake(AppActivity a) { super(a); }
        public String key() { return "stocktake"; } public String title() { return "انبارگردانی"; }
        public void load() { loading(); get("/inventory/stocktakes", r -> { JSONArray ar = arr(r); clear(); body.addView(Ui.primary(c, "+ انبارگردانی جدید", this::create)); if (ar.length() == 0) body.addView(Ui.empty(c, "انبارگردانی‌ای ثبت نشده")); for (int i = ar.length() - 1; i >= 0; i--) { JSONObject st = ar.optJSONObject(i); body.addView(Ui.item(c, st.optString("name"), Ui.jdate(s(st, "created_at", s(st, "started_at"))) + (st.isNull("scheduled_for") ? "" : " · زمان‌بندی " + Ui.jdate(st.optString("scheduled_for"))), label(st.optString("status"), new String[][]{{"DRAFT", "پیش‌نویس"}, {"IN_PROGRESS", "در حال شمارش"}, {"COMPLETED", "شمارش تمام"}, {"APPROVED", "تأیید‌شده"}, {"CANCELLED", "لغو"}}), stColor(st.optString("status")), () -> a.open(new StocktakeSession(a, st.optLong("id")), true))); } }); }
        void create() { LinearLayout l = Ui.col(c); EditText n = Ui.input(c, "نام (مثلاً شمارش قفسهٔ لبنیات)"); EditText area = Ui.input(c, "محدوده / قفسه (اختیاری)"); EditText sch = DatePicker.field(c, "زمان‌بندی (اختیاری)"); l.addView(n); l.addView(area); l.addView(sch); l.addView(Ui.muted(c, "همهٔ بچ‌های فعال (حتی صفر) عکس‌برداری می‌شود؛ شمارش قابل توقف و ادامه است.")); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ایجاد", () -> { try { String sc = dateIn(sch); d[0].dismiss(); JSONObject b = j("name", Ui.str(n).isEmpty() ? "انبارگردانی " + Jalali.todayLong() : Ui.str(n), "area", Ui.str(area)); try { b.put("include_zero", true); if (sc != null) b.put("scheduled_for", sc); } catch (Exception ignore) {} post("/inventory/stocktakes", b, r -> a.open(new StocktakeSession(a, ((JSONObject) r).optLong("id")), true)); } catch (IllegalArgumentException ignore) {} })); d[0] = Ui.sheet(c, "انبارگردانی جدید", l); }
    }
    public static final class StocktakeSession extends Screens.Screen {
        final long id; JSONObject prog; JSONArray items;
        StocktakeSession(AppActivity a, long id) { super(a); this.id = id; }
        public String key() { return "stocktake"; } public String title() { return "جلسهٔ شمارش"; }
        public void load() { loading(); get("/inventory/stocktakes/" + id + "/progress", r -> { prog = (JSONObject) r; get("/inventory/stocktakes/" + id + "/items", r2 -> { items = arr(r2); render(); }); }); }
        void render() {
            clear(); String st = prog.optString("status"); LinearLayout hd = Ui.card(c, prog.optString("name"));
            hd.addView(Ui.kv(c, "وضعیت", label(st, new String[][]{{"DRAFT", "پیش‌نویس"}, {"IN_PROGRESS", "در حال شمارش"}, {"COMPLETED", "شمارش تمام"}, {"APPROVED", "تأیید‌شده"}, {"CANCELLED", "لغو"}}), stColor(st)));
            hd.addView(Ui.kv(c, "پیشرفت", Ui.fa(prog.optInt("counted") + " / " + prog.optInt("total")) + " (" + Ui.num(prog.optDouble("percent")) + "٪)", 0));
            View barBg = new View(c); barBg.setBackground(Ui.rounded(Ui.BG2, 0, 4)); barBg.setLayoutParams(Ui.lp(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(8))); hd.addView(barBg);
            LinearLayout.LayoutParams blp = Ui.lp(0, Ui.dp(8)); View bar = new View(c); bar.setBackground(Ui.rounded(Ui.GREEN, 0, 4)); LinearLayout brow = Ui.row(c); brow.setLayoutParams(Ui.margin(Ui.match(), 0, -8, 0, 4)); bar.setLayoutParams(new LinearLayout.LayoutParams(0, Ui.dp(8), (float) Math.max(0.001, prog.optDouble("percent")))); View rest = new View(c); rest.setLayoutParams(new LinearLayout.LayoutParams(0, Ui.dp(8), (float) Math.max(0.001, 100 - prog.optDouble("percent")))); brow.addView(bar); brow.addView(rest); hd.addView(brow);
            body.addView(hd);
            LinearLayout act = Ui.card(c, "عملیات");
            if ("DRAFT".equals(st)) act.addView(Ui.primary(c, "شروع شمارش", () -> post("/inventory/stocktakes/" + id + "/start", null, r -> load())));
            if ("IN_PROGRESS".equals(st)) { act.addView(Ui.primary(c, "اسکن و شمارش", () -> a.scan("اسکن کالا برای شمارش", this::countByBarcode))); act.addView(Ui.ghost(c, "شمارش ردیف بعدی (" + Ui.num(prog.optInt("remaining")) + " مانده)", () -> { long nid = prog.optLong("next_item_id", 0); for (int i = 0; nid > 0 && i < items.length(); i++) if (items.optJSONObject(i).optLong("id") == nid) countItem(items.optJSONObject(i)); })); act.addView(Ui.success(c, "پایان شمارش", () -> Ui.confirm(c, "شمارش تمام شود؟ ردیف‌های شمارش‌نشده به‌عنوان اختلاف گزارش می‌شوند.", () -> post("/inventory/stocktakes/" + id + "/complete", null, r -> load())))); }
            if ("COMPLETED".equals(st)) { act.addView(Ui.ghost(c, "گزارش اختلاف", this::differences)); if (Screens.can("inventory.approve_stocktake")) act.addView(Ui.success(c, "تأیید و اعمال اصلاحات (ADJUSTMENT)", () -> Ui.confirm(c, "اختلاف‌ها به‌صورت ADJUSTMENT روی موجودی اعمال می‌شود. تأیید؟", () -> post("/inventory/stocktakes/" + id + "/approve", null, r -> { Ui.toast("تأیید شد"); Db.kv("cursor", null); Sync.kick(); load(); })))); }
            if ("APPROVED".equals(st)) act.addView(Ui.ghost(c, "گزارش اختلاف", this::differences));
            if (!"APPROVED".equals(st) && !"CANCELLED".equals(st)) act.addView(Ui.danger(c, "لغو انبارگردانی", () -> Ui.confirm(c, "لغو شود؟", () -> post("/inventory/stocktakes/" + id + "/cancel", null, r -> a.back()))));
            body.addView(act);
            LinearLayout li = Ui.card(c, "ردیف‌ها"); for (int i = 0; i < items.length(); i++) { JSONObject it = items.optJSONObject(i); boolean counted = !it.isNull("physical_qty"); li.addView(Ui.pitem(c, Db.productById(it.optLong("product_id")) == null ? Api.obj("name", it.optString("product_name")) : Db.productById(it.optLong("product_id")), it.optString("product_name"), Ui.fa(s(it, "barcode")) + " · بچ " + Ui.fa(s(it, "batch_number")) + " · سیستم " + Ui.num(it.optDouble("system_qty")), counted ? "شمارش " + Ui.num(it.optDouble("physical_qty")) + (it.optDouble("difference") != 0 ? "\nاختلاف " + Ui.num(it.optDouble("difference")) : "") : "شمارش‌نشده", counted ? (it.optDouble("difference") != 0 ? Ui.AMBER : Ui.GREEN) : Ui.MUTED, "IN_PROGRESS".equals(st) ? () -> countItem(it) : null)); } body.addView(li);
        }
        void countByBarcode(String code) { get("/inventory/stocktakes/" + id + "/item-by-barcode/" + Api.q(Db.norm(code)), r -> { JSONObject rs = (JSONObject) r; JSONArray its = rs.optJSONArray("items"); if (its == null || its.length() == 0) { Ui.toast("این کالا در این شمارش نیست"); return; } JSONObject it = its.optJSONObject(0); try { it.put("product_name", rs.optJSONObject("product").optString("name")); } catch (Exception ignore) {} countItem(it); }); }
        void countItem(JSONObject it) { LinearLayout l = Ui.col(c); l.addView(Ui.body(c, it.optString("product_name") + " · موجودی سیستم " + Ui.num(it.optDouble("system_qty")))); EditText q = Ui.input(c, "تعداد شمارش‌شدهٔ فیزیکی", true); l.addView(q); EditText reason = Ui.input(c, "دلیل اختلاف (اختیاری)"); l.addView(reason); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ثبت و بعدی", () -> { if (Ui.str(q).isEmpty()) { Ui.toast("مقدار را وارد کنید"); return; } d[0].dismiss(); JSONObject b = j("reason", Ui.str(reason), "client_key", "m" + id + "-" + it.optLong("id") + "-" + System.currentTimeMillis()); putNum(b, "item_id", it.optLong("id")); putNum(b, "physical_qty", Ui.numVal(q, 0)); Api.post("/inventory/stocktakes/count", b, r -> { Ui.done(Ui.ctx, "ثبت شد", null, null); load(); }, e -> { if (e.offline()) { Sync.queue("STOCKTAKE_COUNT", b, "شمارش " + it.optString("product_name"), null); Ui.done(Ui.ctx, "شمارش ثبت شد", null, null); } else Ui.toast(e.getMessage()); }); })); d[0] = Ui.sheet(c, "شمارش", l); q.requestFocus(); }
        void differences() { get("/inventory/stocktakes/" + id + "/differences", r -> { JSONObject df = r instanceof JSONObject ? (JSONObject) r : null; JSONArray rows = df != null ? (df.optJSONArray("items") != null ? df.optJSONArray("items") : df.optJSONArray("differences")) : (JSONArray) r; LinearLayout l = Ui.col(c); if (df != null) { l.addView(Ui.kv(c, "ارزش اختلاف (به قیمت خرید)", Ui.money(df.optDouble("total_value_diff", df.optDouble("value_difference", 0))), 0)); } if (rows == null || rows.length() == 0) l.addView(Ui.empty(c, "اختلافی نیست")); for (int i = 0; rows != null && i < rows.length(); i++) { JSONObject d = rows.optJSONObject(i); l.addView(Ui.kv(c, s(d, "product_name", s(d, "name")) + " · " + Ui.fa(s(d, "batch_number")), Ui.num(d.optDouble("system_qty")) + " → " + Ui.num(d.optDouble("physical_qty")) + " (" + Ui.num(d.optDouble("difference", d.optDouble("diff"))) + ")", d.optDouble("difference", d.optDouble("diff")) < 0 ? Ui.RED : Ui.GREEN)); } Ui.sheet(c, "گزارش اختلاف", l); }); }
    }

    /* ---------------- Waste / adjust / transfer ---------------- */
    public static final class StockOps extends Screens.Screen {
        int tab = 0; JSONObject p; JSONObject batch; TextView sel;
        StockOps(AppActivity a) { super(a); }
        public String key() { return "stockops"; } public String title() { return "ضایعات / اصلاح / انتقال"; }
        public void load() {
            clear(); body.addView(tabs(new String[]{"ضایعات (WASTE)", "اصلاح (ADJUSTMENT)", "انتقال (TRANSFER)"}, tab, t -> { tab = t; load(); }));
            LinearLayout cd = Ui.card(c, "انتخاب بچ"); LinearLayout br = Ui.row(c); EditText bc = Ui.input(c, "بارکد کالا", true); bc.setLayoutParams(Ui.weight(1)); br.addView(bc); br.addView(Ui.small(c, "اسکن", () -> a.scan("اسکن کالا", code -> { bc.setText(code); pick(code); }))); cd.addView(br); bc.setOnEditorActionListener((v, i, e) -> { pick(Ui.str(bc)); return true; }); sel = Ui.body(c, batch == null ? "بچی انتخاب نشده" : p.optString("name") + " · بچ " + Ui.fa(batch.optString("batch_number")) + " · موجودی " + Ui.num(batch.optDouble("current_qty"))); cd.addView(sel); body.addView(cd);
            LinearLayout f = Ui.card(c, tab == 0 ? "ثبت ضایعات" : tab == 1 ? "اصلاح موجودی" : "انتقال بین انبار"); EditText q = Ui.input(c, tab == 0 ? "مقدار ضایع‌شده" : tab == 1 ? "موجودی واقعی جدید" : "مقدار انتقالی", true); EditText reason = Ui.input(c, "دلیل *"); f.addView(q); f.addView(reason);
            final long[] wh = {0}; if (tab == 2) { LinearLayout wc = Ui.row(c); f.addView(Ui.label(c, "انبار مقصد")); f.addView(Ui.chips(c, wc)); getQuiet("/warehouses", r -> { JSONArray ar = arr(r); Runnable[] rd = new Runnable[1]; rd[0] = () -> { wc.removeAllViews(); for (int i = 0; i < ar.length(); i++) { JSONObject w = ar.optJSONObject(i); wc.addView(Ui.chip(c, w.optString("name"), w.optLong("id") == wh[0], () -> { wh[0] = w.optLong("id"); rd[0].run(); })); } }; rd[0].run(); }); }
            f.addView(Ui.primary(c, "ثبت", () -> { if (batch == null) { Ui.toast("ابتدا بچ را انتخاب کنید"); return; } if (Ui.str(reason).isEmpty()) { Ui.toast("دلیل لازم است"); return; } if (!Api.standalone() && batch.optLong("batch_id", batch.optLong("id")) < 0) { Ui.toast("این بچ هنوز به رایانه نرسیده"); return; } JSONObject b = j("reason", Ui.str(reason)); long bid = batch.optLong("batch_id", batch.optLong("id")); putNum(b, "batch_id", bid); if (tab == 2) { if (wh[0] == 0) { Ui.toast("انبار مقصد را انتخاب کنید"); return; } putNum(b, "quantity", Ui.numVal(q, 0)); putNum(b, "to_warehouse_id", wh[0]); post("/warehouses/transfer", b, r -> { Ui.done(Ui.ctx, "انتقال ثبت شد", null, null); Sync.kick(); batch = null; load(); }); } else { putNum(b, "new_current_qty", Ui.numVal(q, 0)); post(tab == 0 ? "/inventory/waste" : "/inventory/adjust", b, r -> { Ui.toast(tab == 0 ? "ضایعات ثبت شد" : "اصلاح ثبت شد"); Sync.kick(); batch = null; load(); }); } })); body.addView(f);
        }
        void pick(String code) { p = Db.productByBarcode(code); if (p == null) { Ui.toast("کالا یافت نشد"); return; } JSONArray bs = p.optJSONArray("batches"); if (bs == null || bs.length() == 0) { Ui.toast("بچ فعالی ندارد"); return; } if (bs.length() == 1) { batch = bs.optJSONObject(0); load(); return; } LinearLayout l = Ui.col(c); Dialog[] d = new Dialog[1]; for (int i = 0; i < bs.length(); i++) { JSONObject b = bs.optJSONObject(i); l.addView(Ui.item(c, "بچ " + Ui.fa(b.optString("batch_number")), "موجودی " + Ui.num(b.optDouble("current_qty")) + (b.isNull("expiry_date") ? "" : " · " + Ui.jdate(b.optString("expiry_date"))), null, 0, () -> { batch = b; d[0].dismiss(); load(); })); } d[0] = Ui.sheet(c, p.optString("name"), l); }
    }

    /* ---------------- Warehouses ---------------- */
    public static final class Warehouses extends Screens.Screen {
        Warehouses(AppActivity a) { super(a); }
        public String key() { return "warehouses"; } public String title() { return "انبارها"; }
        public void load() { loading(); get("/warehouses", r -> { JSONArray ar = arr(r); clear(); for (int i = 0; i < ar.length(); i++) { JSONObject w = ar.optJSONObject(i); LinearLayout cd = Ui.card(c, w.optString("name") + (w.optBoolean("is_default") ? " (پیش‌فرض)" : "")); cd.addView(Ui.kv(c, "کد", s(w, "code", "—"), 0)); cd.addView(Ui.kv(c, "موجودی / ارزش", Ui.num(w.optDouble("total_qty")) + " · " + Ui.money(w.optDouble("stock_value")), 0)); JSONArray locs = w.optJSONArray("locations"); cd.addView(Ui.kv(c, "قفسه‌ها", locs == null || locs.length() == 0 ? "—" : Ui.num(locs.length()), 0)); for (int k = 0; locs != null && k < locs.length(); k++) cd.addView(Ui.muted(c, "  • " + locs.optJSONObject(k).optString("name"))); if (Screens.can("settings.manage")) cd.addView(Ui.small(c, "+ قفسه / محل", () -> Ui.prompt(c, "نام قفسه", "مثلاً A1", false, n -> { if (!n.isEmpty()) post("/warehouses/" + w.optLong("id") + "/locations", j("name", n), x -> load()); }))); body.addView(cd); } if (Screens.can("settings.manage")) body.addView(Ui.primary(c, "+ انبار جدید", () -> { LinearLayout l = Ui.col(c); EditText n = Ui.input(c, "نام"); EditText cd2 = Ui.input(c, "کد"); EditText ad = Ui.input(c, "آدرس"); l.addView(n); l.addView(cd2); l.addView(ad); Dialog[] d = new Dialog[1]; l.addView(Ui.primary(c, "ایجاد", () -> { d[0].dismiss(); post("/warehouses", j("name", Ui.str(n), "code", Ui.str(cd2), "address", Ui.str(ad)), x -> load()); })); d[0] = Ui.sheet(c, "انبار جدید", l); })); }); }
    }

    /* ---------------- Movements ---------------- */
    public static final class Movements extends Screens.Screen {
        Movements(AppActivity a) { super(a); }
        public String key() { return "movements"; } public String title() { return "گردش موجودی"; }
        static final String[][] MT = {{"IN", "ورود"}, {"SALE_OUT", "فروش"}, {"RETURN_IN", "مرجوعی"}, {"WASTE", "ضایعات"}, {"ADJUSTMENT", "اصلاح"}, {"TRANSFER", "انتقال"}, {"TRANSFER_OUT", "انتقال خروج"}, {"TRANSFER_IN", "انتقال ورود"}};
        public void load() { loading(); get("/inventory/movements?limit=150", r -> { JSONArray ar = arr(r); clear(); if (ar.length() == 0) body.addView(Ui.empty(c, "گردشی نیست")); for (int i = 0; i < ar.length(); i++) { JSONObject m = ar.optJSONObject(i); JSONObject p = Db.productById(m.optLong("product_id")); String ty = m.optString("movement_type"); body.addView(Ui.item(c, (p == null ? "کالا #" + m.optLong("product_id") : p.optString("name")), Ui.jdate(m.optString("created_at")) + " · " + label(ty, MT) + (s(m, "reference_type").isEmpty() ? "" : " · " + s(m, "reference_type") + " " + Ui.fa(s(m, "reference_id"))), (m.optDouble("quantity") > 0 ? "+" : "") + Ui.num(m.optDouble("quantity")), m.optDouble("quantity") >= 0 ? Ui.GREEN : Ui.RED, null)); } }); }
    }

    /** v2.5.1 — picture picker: retail pack photos (Digikala/Okala/Basalam) first, own camera/gallery photo as the final word. */
    static void pickImage(AppActivity a, long pid, Runnable after) {
        LinearLayout l = Ui.col(a); TextView st = Ui.muted(a, "در حال جست‌وجو در فروشگاه‌های اینترنتی…"); l.addView(st);
        LinearLayout grid = Ui.col(a); l.addView(grid);
        Dialog[] d = new Dialog[1];
        java.util.function.Consumer<JSONObject> done = (rep) -> Api.ui(() -> { if (rep.optBoolean("ok")) { Ui.done(Ui.ctx, "تصویر کالا ثبت شد", null, null); if (d[0] != null) d[0].dismiss(); after.run(); } else Ui.toast("تصویر نامعتبر: " + rep.optString("reason")); });
        l.addView(Ui.primary(a, "📷 عکس خودم (دوربین/گالری)", () -> { android.content.Intent i = new android.content.Intent(android.content.Intent.ACTION_GET_CONTENT); i.setType("image/*"); i.addCategory(android.content.Intent.CATEGORY_OPENABLE);
            a.pickCb = (uri) -> Api.bg(() -> { try { java.io.InputStream in = a.getContentResolver().openInputStream(uri); java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream(); byte[] buf = new byte[8192]; int n; while ((n = in.read(buf)) > 0) bo.write(buf, 0, n); in.close(); done.accept(Images.setFromBytes(a, pid, bo.toByteArray(), "upload")); } catch (Exception e) { Api.ui(() -> Ui.toast("خواندن عکس ناموفق")); } });
            a.startActivityForResult(android.content.Intent.createChooser(i, "انتخاب عکس کالا"), AppActivity.REQ_PICK); }));
        EditText url = Ui.input(a, "یا نشانی تصویر (https://…)"); l.addView(url);
        l.addView(Ui.small(a, "ثبت نشانی", () -> { String u = Ui.str(url); if (u.isEmpty()) return; Ui.toast("در حال دریافت…"); Api.bg(() -> done.accept(Images.setFromUrl(a, pid, u, "manual-url"))); }));
        d[0] = Ui.sheet(a, "انتخاب تصویر کالا", l);
        Api.bg(() -> { org.json.JSONArray cands; if (Api.standalone()) cands = Images.listCandidates(pid); else { try { Object r = Api.call("GET", "/products/" + pid + "/image/candidates", null, null); cands = r instanceof JSONObject ? ((JSONObject) r).optJSONArray("candidates") : Images.listCandidates(pid); } catch (Exception e) { cands = Images.listCandidates(pid); } }
            final org.json.JSONArray fc = cands == null ? new org.json.JSONArray() : cands;
            Api.ui(() -> { st.setText(fc.length() == 0 ? "نتیجه‌ای از اینترنت نیامد — عکس خودتان را بارگذاری کنید." : "روی تصویر درست بزنید؛ برچسب «فروشگاه» یعنی عکس بسته‌بندی واقعی.");
                LinearLayout row = null;
                for (int i = 0; i < fc.length(); i++) { JSONObject x = fc.optJSONObject(i); if (x == null) continue; if (i % 3 == 0) { row = Ui.row(a); grid.addView(row); }
                    LinearLayout cell = Ui.col(a); cell.setLayoutParams(Ui.weight(1)); cell.setGravity(android.view.Gravity.CENTER); cell.setPadding(Ui.dp(4), Ui.dp(4), Ui.dp(4), Ui.dp(4));
                    android.widget.ImageView iv = new android.widget.ImageView(a); iv.setLayoutParams(Ui.lp(Ui.dp(100), Ui.dp(100))); iv.setScaleType(android.widget.ImageView.ScaleType.FIT_CENTER); iv.setBackground(Ui.rounded(0xFFFFFFFF, 0, 10)); iv.setClipToOutline(true); Images.bindUrl(iv, x.optString("url")); cell.addView(iv);
                    String src = x.optString("source"); String lab = src.startsWith("retail:") ? "فروشگاه " + (src.endsWith("digikala") ? "دیجی‌کالا" : src.endsWith("okala") ? "اُکالا" : src.endsWith("basalam") ? "باسلام" : "ترب") : src;
                    TextView t = Ui.muted(a, lab); t.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 10); t.setSingleLine(); cell.addView(t);
                    final String u = x.optString("url"), so = src; cell.setOnClickListener(v -> { cell.setAlpha(0.5f); Ui.toast("در حال دریافت…"); Api.bg(() -> { JSONObject rep; if (Api.standalone()) rep = Images.setFromUrl(a, pid, u, so); else { try { Object r = Api.call("POST", "/products/" + pid + "/image/pick", Api.obj("url", u, "source", so).toString(), "application/json"); rep = r instanceof JSONObject ? (JSONObject) r : Images.setFromUrl(a, pid, u, so); if (rep.optBoolean("ok")) { JSONObject pp = Db.productById(pid); if (pp != null) { pp.put("image_url", rep.optString("image_url")); Db.putProduct(pp, false); } } } catch (Exception e) { rep = Images.setFromUrl(a, pid, u, so); } } done.accept(rep); }); });
                    row.addView(cell); }
            }); });
    }
}
