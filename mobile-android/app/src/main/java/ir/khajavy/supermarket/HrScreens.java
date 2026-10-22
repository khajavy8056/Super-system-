package ir.khajavy.supermarket;

import android.app.AlertDialog;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;

/** Native announcement, payroll and performance panels shared with the PC HR API. */
public final class HrScreens {
    private HrScreens() {}

    public static final class Announcements extends Screens.Screen {
        private boolean all = false;
        Announcements(AppActivity a) { super(a); }
        public String key() { return "announcements"; }
        public String title() { return "اطلاعیه‌های کارکنان"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            loading(); Api.get("/hr/announcements" + (all ? "/all" : ""), value -> render(value), error -> { clear(); offline("اطلاعیه‌های کارکنان"); });
        }
        private void render(Object value) {
            clear();
            LinearLayout actions = Ui.card(c, "اطلاعیه‌های فروشگاه");
            actions.addView(Ui.body(c, "پیام‌های متناسب با نقش و حساب شما؛ تغییرات محلی در زمان اتصال همگام می‌شوند."));
            if (Screens.can("announcements.publish")) actions.addView(Ui.primary(c, "اطلاعیهٔ تازه", this::create));
            if (Screens.can("announcements.manage")) actions.addView(Ui.ghost(c, all ? "نمایش اطلاعیه‌های من" : "مدیریت همهٔ اطلاعیه‌ها", () -> { all = !all; load(); }));
            body.addView(actions);
            JSONArray rows = value instanceof JSONArray ? (JSONArray) value : new JSONArray();
            if (rows.length() == 0) { body.addView(Ui.empty(c, "اطلاعیه‌ای برای نمایش نیست.")); return; }
            for (int i = 0; i < rows.length(); i++) {
                JSONObject item = rows.optJSONObject(i); if (item == null) continue;
                String title = item.optString("title", "اطلاعیه"), status = item.optString("status", "PUBLISHED");
                LinearLayout card = Ui.card(c, title);
                String date = item.optString("created_at", ""); if (date.length() >= 10) date = Ui.jdate(date.substring(0, 10));
                card.addView(Ui.kv(c, "وضعیت / اولویت", statusFa(status) + " · " + Ui.num(item.optInt("priority", 3)), "PUBLISHED".equals(status) ? Ui.GREEN : Ui.AMBER));
                if (!date.isEmpty()) card.addView(Ui.muted(c, date));
                card.addView(Ui.body(c, item.optString("body", "")));
                if (item.isNull("read_at") || item.optString("read_at").isEmpty()) {
                    card.addView(Ui.ghost(c, "علامت‌گذاری به‌عنوان خوانده‌شده", () -> Api.post("/hr/announcements/" + item.optLong("id") + "/read", new JSONObject(), result -> load(), error -> Ui.toast(error.getMessage()))));
                } else card.addView(Ui.kv(c, "خوانده‌شده", "بله", Ui.GREEN));
                if (Screens.can("announcements.manage") || (Screens.can("announcements.publish") && item.optLong("created_by") == Screens.user.optLong("id")))
                    card.addView(Ui.danger(c, "لغو اطلاعیه", () -> Ui.confirm(c, "این اطلاعیه لغو شود؟", () -> Api.delete("/hr/announcements/" + item.optLong("id"), result -> load(), error -> Ui.toast(error.getMessage())))));
                body.addView(card);
                if (item.isNull("seen_at") || item.optString("seen_at").isEmpty()) Api.post("/hr/announcements/" + item.optLong("id") + "/seen", new JSONObject(), result -> {}, error -> {});
            }
        }
        private void create() {
            LinearLayout form = Ui.col(c); form.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8));
            EditText title = input(form, "عنوان اطلاعیه"); EditText text = input(form, "متن پیام"); text.setMinLines(4); text.setGravity(Gravity.TOP | Gravity.START);
            Spinner priority = new Spinner(c); priority.setAdapter(new ArrayAdapter<>(c, android.R.layout.simple_spinner_dropdown_item, new String[]{"عادی", "مهم", "فوری"})); form.addView(priority);
            ScrollView scroll = new ScrollView(c); scroll.addView(form);
            new AlertDialog.Builder(c).setTitle("اطلاعیهٔ تازه").setView(scroll).setNegativeButton("انصراف", null)
                    .setPositiveButton("انتشار", (dialog, which) -> {
                        String name = title.getText().toString().trim(); if (name.isEmpty()) { Ui.toast("عنوان اطلاعیه را وارد کنید."); return; }
                        JSONObject data = new JSONObject();
                        try { data.put("title", name); data.put("body", text.getText().toString().trim()); data.put("priority", priority.getSelectedItemPosition() == 2 ? 1 : priority.getSelectedItemPosition() == 1 ? 2 : 3); data.put("target_kind", "ALL"); data.put("status", "PUBLISHED"); }
                        catch (Exception e) { Ui.toast("اطلاعات اطلاعیه نامعتبر است."); return; }
                        Api.post("/hr/announcements", data, result -> load(), error -> Ui.toast(error.getMessage()));
                    }).show();
        }
        private EditText input(LinearLayout parent, String hint) { EditText v = Ui.input(c, hint); v.setSingleLine(false); parent.addView(v); return v; }
        private String statusFa(String status) { if ("SCHEDULED".equals(status)) return "زمان‌بندی‌شده"; if ("DRAFT".equals(status)) return "پیش‌نویس"; if ("CANCELLED".equals(status)) return "لغوشده"; if ("EXPIRED".equals(status)) return "منقضی"; return "منتشرشده"; }
    }

    public static final class Payroll extends Screens.Screen {
        private JSONArray staff = new JSONArray(); private JSONArray rows = new JSONArray();
        Payroll(AppActivity a) { super(a); }
        public String key() { return "payroll"; }
        public String title() { return "حقوق و دستمزد"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            loading();
            Api.get("/hr/payroll", value -> {
                rows = value instanceof JSONArray ? (JSONArray) value : new JSONArray();
                if (Screens.can("payroll.manage")) Api.get("/hr/roster-users", people -> { staff = people instanceof JSONArray ? (JSONArray) people : new JSONArray(); render(); }, error -> render());
                else render();
            }, error -> { clear(); offline("حقوق و دستمزد"); });
        }
        private void render() {
            clear(); LinearLayout intro = Ui.card(c, "پرداخت کارکنان");
            intro.addView(Ui.body(c, "پیش‌نویس، تأیید و پرداخت؛ اطلاعات ذخیره‌شده روی گوشی هنگام بازگشت اتصال به رایانه فرستاده می‌شوند."));
            if (Screens.can("payroll.manage")) intro.addView(Ui.primary(c, "ثبت حقوق", this::create)); body.addView(intro);
            if (rows.length() == 0) { body.addView(Ui.empty(c, "ردیف حقوقی ثبت نشده است.")); return; }
            for (int i = 0; i < rows.length(); i++) {
                JSONObject row = rows.optJSONObject(i); if (row == null) continue;
                LinearLayout card = Ui.card(c, row.optString("full_name", row.optString("username", "کارمند")) + " · " + row.optString("period", ""));
                card.addView(Ui.kv(c, "خالص پرداختی", Ui.money(row.optDouble("total")), Ui.TEAL));
                card.addView(Ui.kv(c, "وضعیت", statusFa(row.optString("status")), "PAID".equals(row.optString("status")) ? Ui.GREEN : Ui.AMBER));
                card.addView(Ui.kv(c, "پایه / ساعات", Ui.money(row.optDouble("base_salary")) + " · " + Ui.num(row.optDouble("worked_hours")) + " ساعت", 0));
                if (!row.isNull("payment_ref") && !row.optString("payment_ref").isEmpty()) card.addView(Ui.muted(c, "سند حسابداری: " + row.optString("payment_ref")));
                if (Screens.can("payroll.manage")) {
                    if ("DRAFT".equals(row.optString("status"))) {
                        card.addView(Ui.ghost(c, "ویرایش پیش‌نویس", () -> edit(row)));
                        card.addView(Ui.primary(c, "تأیید حقوق", () -> Ui.confirm(c, "این ردیف حقوق تأیید شود؟", () -> Api.post("/hr/payroll/" + row.optLong("id") + "/approve", new JSONObject(), result -> load(), error -> Ui.toast(error.getMessage())))));
                    } else if ("APPROVED".equals(row.optString("status"))) {
                        card.addView(Ui.primary(c, "ثبت پرداخت", () -> Ui.confirm(c, "پرداخت از صندوق/حسابداری ثبت شود؟", () -> Api.post("/hr/payroll/" + row.optLong("id") + "/pay", new JSONObject(), result -> load(), error -> Ui.toast(error.getMessage())))));
                    }
                }
                body.addView(card);
            }
        }
        private void create() {
            if (staff.length() == 0) { Ui.toast("فهرست کارکنان هنوز دریافت نشده است."); return; }
            LinearLayout form = Ui.col(c); form.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8));
            ArrayList<String> names = new ArrayList<>(); for (int i = 0; i < staff.length(); i++) { JSONObject u = staff.optJSONObject(i); names.add(u == null ? "کارمند" : u.optString("full_name", "کارمند")); }
            Spinner picker = new Spinner(c); picker.setAdapter(new ArrayAdapter<>(c, android.R.layout.simple_spinner_dropdown_item, names)); form.addView(picker);
            int[] jy = Jalali.toJalali(java.util.Calendar.getInstance().get(java.util.Calendar.YEAR), java.util.Calendar.getInstance().get(java.util.Calendar.MONTH) + 1, java.util.Calendar.getInstance().get(java.util.Calendar.DAY_OF_MONTH));
            EditText period = field(form, "دوره (YYYY-MM)"); period.setText(String.format(java.util.Locale.US, "%04d-%02d", jy[0], jy[1]));
            EditText base = moneyField(form, "حقوق پایه"); EditText hourly = moneyField(form, "مزد ساعتی"); EditText worked = numberField(form, "ساعات کارکرد"); EditText overtime = numberField(form, "ساعات اضافه‌کاری");
            EditText bonus = moneyField(form, "پاداش"); EditText benefits = moneyField(form, "مزایا"); EditText deductions = moneyField(form, "کسورات"); EditText penalty = moneyField(form, "جریمه"); EditText note = field(form, "یادداشت");
            ScrollView scroll = new ScrollView(c); scroll.addView(form);
            new AlertDialog.Builder(c).setTitle("ثبت حقوق").setView(scroll).setNegativeButton("انصراف", null)
                    .setPositiveButton("ذخیرهٔ پیش‌نویس", (dialog, which) -> {
                        JSONObject person = staff.optJSONObject(picker.getSelectedItemPosition()); if (person == null) return;
                        JSONObject data = new JSONObject();
                        try { data.put("user_id", person.optLong("id")); data.put("period", period.getText().toString().trim()); data.put("base_salary", numeric(base)); data.put("hourly_pay", numeric(hourly)); data.put("worked_hours", numeric(worked)); data.put("overtime_hours", numeric(overtime)); data.put("bonus", numeric(bonus)); data.put("benefits", numeric(benefits)); data.put("deductions", numeric(deductions)); data.put("penalty", numeric(penalty)); data.put("note", note.getText().toString().trim()); }
                        catch (Exception e) { Ui.toast("مبالغ و ساعات را بررسی کنید."); return; }
                        Api.post("/hr/payroll", data, result -> load(), error -> Ui.toast(error.getMessage()));
                    }).show();
        }
        private void edit(JSONObject row) {
            LinearLayout form = Ui.col(c); form.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8));
            EditText base = moneyField(form, "حقوق پایه"); base.setText(String.valueOf(row.optDouble("base_salary")));
            EditText hourly = moneyField(form, "مزد ساعتی"); hourly.setText(String.valueOf(row.optDouble("hourly_pay")));
            EditText worked = numberField(form, "ساعات کارکرد"); worked.setText(String.valueOf(row.optDouble("worked_hours")));
            EditText overtime = numberField(form, "ساعات اضافه‌کاری"); overtime.setText(String.valueOf(row.optDouble("overtime_hours")));
            EditText bonus = moneyField(form, "پاداش"); bonus.setText(String.valueOf(row.optDouble("bonus")));
            EditText benefits = moneyField(form, "مزایا"); benefits.setText(String.valueOf(row.optDouble("benefits")));
            EditText deductions = moneyField(form, "کسورات"); deductions.setText(String.valueOf(row.optDouble("deductions")));
            EditText penalty = moneyField(form, "جریمه"); penalty.setText(String.valueOf(row.optDouble("penalty")));
            EditText note = field(form, "یادداشت"); note.setText(row.optString("note", "")); ScrollView scroll = new ScrollView(c); scroll.addView(form);
            new AlertDialog.Builder(c).setTitle("ویرایش پیش‌نویس").setView(scroll).setNegativeButton("انصراف", null).setPositiveButton("ذخیره", (dialog, which) -> {
                JSONObject data = new JSONObject();
                try { data.put("base_salary", numeric(base)); data.put("hourly_pay", numeric(hourly)); data.put("worked_hours", numeric(worked)); data.put("overtime_hours", numeric(overtime)); data.put("bonus", numeric(bonus)); data.put("benefits", numeric(benefits)); data.put("deductions", numeric(deductions)); data.put("penalty", numeric(penalty)); data.put("note", note.getText().toString()); }
                catch (Exception e) { Ui.toast("مقادیر واردشده معتبر نیست."); return; }
                Api.patch("/hr/payroll/" + row.optLong("id"), data, result -> load(), error -> Ui.toast(error.getMessage()));
            }).show();
        }
        private EditText field(LinearLayout parent, String hint) { EditText input = Ui.input(c, hint); input.setSingleLine(true); parent.addView(input); return input; }
        private EditText moneyField(LinearLayout parent, String hint) { EditText input = field(parent, hint); input.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL); return input; }
        private EditText numberField(LinearLayout parent, String hint) { EditText input = field(parent, hint); input.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL); return input; }
        private double numeric(EditText v) { String text = Db.norm(v.getText().toString().trim()); return text.isEmpty() ? 0 : Double.parseDouble(text.replace(",", "")); }
        private String statusFa(String value) { if ("DRAFT".equals(value)) return "پیش‌نویس"; if ("APPROVED".equals(value)) return "تأییدشده"; if ("PAID".equals(value)) return "پرداخت‌شده"; if ("PAYMENT_PENDING_SYNC".equals(value)) return "در انتظار همگام‌سازی پرداخت"; return value; }
    }

    public static final class Performance extends Screens.Screen {
        private boolean team = false;
        Performance(AppActivity a) { super(a); }
        public String key() { return "performance"; }
        public String title() { return "عملکرد کارکنان"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            loading(); boolean canTeam = Screens.can("performance.view") || Screens.can("performance.view_all");
            String path = team && canTeam ? "/hr/performance/team" : "/hr/performance/me";
            Api.get(path, value -> render(value, team && canTeam), error -> { clear(); offline("گزارش عملکرد کارکنان"); });
        }
        private void render(Object value, boolean showingTeam) {
            clear(); LinearLayout intro = Ui.card(c, "عملکرد واقعی از فروش و حضور ثبت‌شده");
            intro.addView(Ui.body(c, "آمار فقط از فاکتورهای پرداخت‌شده و داده‌های شیفت/حضور محلی یا همگام‌شده محاسبه می‌شود."));
            boolean canTeam = Screens.can("performance.view") || Screens.can("performance.view_all");
            if (canTeam) intro.addView(Ui.ghost(c, showingTeam ? "گزارش من" : "عملکرد تیم", () -> { team = !team; load(); }));
            body.addView(intro);
            if (showingTeam) {
                JSONArray staff = value instanceof JSONArray ? (JSONArray) value : new JSONArray();
                if (staff.length() == 0) body.addView(Ui.empty(c, "گزارش تیم در دسترس نیست."));
                for (int i = 0; i < staff.length(); i++) { JSONObject row = staff.optJSONObject(i); if (row == null) continue; LinearLayout card = Ui.card(c, row.optString("full_name", "کارمند")); card.addView(Ui.kv(c, "فروش", Ui.money(row.optDouble("sales_total")), Ui.TEAL)); card.addView(Ui.kv(c, "فاکتور / حضور", Ui.num(row.optInt("invoice_count")) + " / " + Ui.num(row.optInt("worked_days")) + " روز", 0)); card.addView(Ui.kv(c, "داخل / خارج شیفت", Ui.money(row.optDouble("sales_in_shift")) + " / " + Ui.money(row.optDouble("sales_out_of_shift")), Ui.VIOLET)); body.addView(card); }
                return;
            }
            if (!(value instanceof JSONObject)) { body.addView(Ui.empty(c, "گزارش شخصی دریافت نشد.")); return; }
            JSONObject row = (JSONObject) value; LinearLayout stats = Ui.card(c, "گزارش شخصی · " + row.optString("from", "") + " تا " + row.optString("to", ""));
            stats.addView(Ui.kv(c, "فروش کل", Ui.money(row.optDouble("sales_total")), Ui.GREEN));
            stats.addView(Ui.kv(c, "تعداد / میانگین فاکتور", Ui.num(row.optInt("invoice_count")) + " / " + Ui.money(row.optDouble("avg_invoice")), 0));
            stats.addView(Ui.kv(c, "فروش داخل شیفت", Ui.money(row.optDouble("sales_in_shift")), Ui.TEAL));
            stats.addView(Ui.kv(c, "فروش خارج از شیفت", Ui.money(row.optDouble("sales_out_of_shift")), Ui.VIOLET));
            stats.addView(Ui.kv(c, "روزهای حضور / مجموع تأخیر", Ui.num(row.optInt("worked_days")) + " / " + Ui.num(row.optInt("late_minutes_total")) + " دقیقه", row.optInt("late_minutes_total") > 0 ? Ui.AMBER : Ui.GREEN));
            stats.addView(Ui.kv(c, "پیشرفت هدف", row.isNull("goal_progress") ? "هدف تعریف نشده" : Ui.num(row.optDouble("goal_progress")) + "%", 0)); body.addView(stats);
            JSONArray daily = row.optJSONArray("daily_series"); if (daily != null && daily.length() > 0) { LinearLayout chart = Ui.card(c, "فروش روزانه"); double max = 0; for (int i = 0; i < daily.length(); i++) max = Math.max(max, daily.optJSONObject(i).optDouble("sales")); for (int i = Math.max(0, daily.length() - 14); i < daily.length(); i++) { JSONObject day = daily.optJSONObject(i); LinearLayout line = Ui.row(c); line.setGravity(Gravity.CENTER_VERTICAL); TextView label = Ui.text(c, Ui.jdate(day.optString("day")), 11, Ui.MUTED, false); label.setLayoutParams(Ui.lp(Ui.dp(78), Ui.dp(30))); line.addView(label); View bar = new View(c); bar.setBackground(Ui.rounded(Ui.PRIMARY, 0, 5)); int width = max <= 0 ? 0 : (int) (Ui.dp(160) * day.optDouble("sales") / max); line.addView(bar, Ui.lp(Math.max(2, width), Ui.dp(9))); TextView amount = Ui.muted(c, Ui.money(day.optDouble("sales"))); amount.setPadding(Ui.dp(8), 0, 0, 0); line.addView(amount); chart.addView(line); } body.addView(chart); }
        }
    }
}
