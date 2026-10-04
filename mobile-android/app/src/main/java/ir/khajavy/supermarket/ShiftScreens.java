package ir.khajavy.supermarket;

import android.app.AlertDialog;
import android.text.InputType;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** Native HR/shift panels backed by the same permission-checked PC API as Windows. */
public final class ShiftScreens {
    private ShiftScreens() {}

    public static final class Mine extends Screens.Screen {
        Mine(AppActivity a) { super(a); }
        public String key() { return "my-shifts"; }
        public String title() { return "شیفت‌های من"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            loading();
            Api.get("/hr/shifts/my", value -> {
                clear();
                JSONObject root = value instanceof JSONObject ? (JSONObject) value : new JSONObject();
                JSONObject status = root.optJSONObject("status");
                LinearLayout today = Ui.card(c, "وضعیت امروز");
                if (status != null) {
                    String state = status.optString("shift_state", "NO_SHIFT");
                    String label = "IN_SHIFT".equals(state) ? "در حال شیفت" : "OUT_OF_SHIFT".equals(state) ? "خارج از بازهٔ شیفت" : "COMPLETED".equals(state) ? "پایان‌یافته" : "شیفتی تعیین نشده";
                    today.addView(Ui.kv(c, "وضعیت", label, "IN_SHIFT".equals(state) ? Ui.GREEN : "COMPLETED".equals(state) ? Ui.TEAL : Ui.AMBER));
                    today.addView(Ui.kv(c, "شیفت", status.optString("shift_name", "—"), 0));
                    today.addView(Ui.kv(c, "زمان", status.optString("start_time", "—") + " تا " + status.optString("end_time", "—"), 0));
                    if (status.optBoolean("present")) today.addView(Ui.kv(c, "کارکرد فعلی", minutes(status.optInt("minutes", 0)), Ui.GREEN));
                } else today.addView(Ui.muted(c, "وضعیت شیفت همگام نشده است."));
                body.addView(today);
                JSONArray assignments = root.optJSONArray("assignments");
                LinearLayout list = Ui.card(c, "برنامهٔ شیفت‌های من");
                if (assignments == null || assignments.length() == 0) list.addView(Ui.muted(c, "شیفت دیگری برای حساب شما ثبت نشده است."));
                else for (int i = 0; i < assignments.length(); i++) {
                    JSONObject sh = assignments.optJSONObject(i);
                    list.addView(Ui.kv(c, sh.optString("shift_name", "شیفت"), sh.optString("day", "تکرارشونده") + " · " + sh.optString("start_time", "—") + " تا " + sh.optString("end_time", "—"), Ui.TEAL));
                    String dep = sh.optString("department", "");
                    if (!dep.isEmpty()) list.addView(Ui.muted(c, "قسمت: " + dep));
                }
                body.addView(list);
                Api.get("/hr/attendance/my-summary", summary -> {
                    if (!(summary instanceof JSONObject) || list.getParent() != body) return;
                    JSONObject s = (JSONObject) summary;
                    LinearLayout card = Ui.card(c, "خلاصهٔ ۳۰ روزه");
                    card.addView(Ui.kv(c, "روزهای حضور", Ui.num(s.optInt("days_present")) + " / " + Ui.num(s.optInt("days_scheduled")), 0));
                    card.addView(Ui.kv(c, "کارکرد / برنامه", minutes(s.optInt("worked_minutes")) + " / " + minutes(s.optInt("planned_minutes")), Ui.TEAL));
                    card.addView(Ui.kv(c, "اضافه‌کاری / کسری", minutes(s.optInt("overtime_minutes")) + " / " + minutes(s.optInt("deficit_minutes")), Ui.VIOLET));
                    card.addView(Ui.kv(c, "تأخیر", minutes(s.optInt("late_minutes")), s.optInt("late_minutes") > 0 ? Ui.AMBER : Ui.GREEN));
                    body.addView(card, Math.max(0, body.indexOfChild(list)) + 1);
                }, error -> {});
            }, error -> { clear(); offline("برنامهٔ شیفت‌های من"); });
        }
    }

    public static final class Roster extends Screens.Screen {
        private JSONArray shifts = new JSONArray(), people = new JSONArray();
        Roster(AppActivity a) { super(a); }
        public String key() { return "shifts"; }
        public String title() { return "برنامه‌ریزی شیفت"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            loading();
            Api.get("/hr/shifts", value -> {
                shifts = value instanceof JSONArray ? (JSONArray) value : new JSONArray();
                Api.get("/hr/roster-users", users -> { people = users instanceof JSONArray ? (JSONArray) users : new JSONArray(); render(); }, error -> render());
            }, error -> { clear(); offline("برنامه‌ریزی شیفت"); });
        }
        private void render() {
            clear();
            LinearLayout intro = Ui.card(c, "شیفت‌های فروشگاه");
            intro.addView(Ui.body(c, "تعریف بازهٔ کاری، قسمت و تخصیص کاربر؛ تغییرات آفلاین روی گوشی ذخیره و هنگام اتصال همگام می‌شوند."));
            if (Screens.can("shifts.manage")) intro.addView(Ui.primary(c, "تعریف شیفت", this::createShift));
            body.addView(intro);
            if (shifts.length() == 0) { body.addView(Ui.empty(c, "شیفتی ثبت نشده است.")); return; }
            for (int i = 0; i < shifts.length(); i++) {
                JSONObject sh = shifts.optJSONObject(i);
                if (sh == null) continue;
                LinearLayout card = Ui.card(c, sh.optString("name", "شیفت"));
                card.addView(Ui.kv(c, "ساعت", sh.optString("start_time", "—") + " تا " + sh.optString("end_time", "—"), Ui.TEAL));
                card.addView(Ui.kv(c, "فروشگاه / قسمت", sh.optString("store", "—") + " / " + sh.optString("department", "—"), 0));
                JSONArray days = sh.optJSONArray("workdays");
                card.addView(Ui.kv(c, "روزهای کاری", dayLabels(days), 0));
                JSONArray roster = sh.optJSONArray("roster");
                if (roster != null) for (int j = 0; j < roster.length(); j++) {
                    JSONObject assignment = roster.optJSONObject(j);
                    if (assignment == null) continue;
                    String date = assignment.optString("day", "");
                    LinearLayout row = Ui.row(c); row.setGravity(android.view.Gravity.CENTER_VERTICAL);
                    TextView name = Ui.text(c, assignment.optString("full_name", "کاربر"), 13, Ui.TEXT, true); name.setLayoutParams(Ui.weight(1)); row.addView(name);
                    row.addView(Ui.muted(c, date.isEmpty() ? "تکرارشونده" : Ui.jdate(date)));
                    if (Screens.can("shifts.manage")) row.addView(Ui.small(c, "لغو", () -> Api.delete("/hr/shifts/assignments/" + assignment.optLong("assignment_id"), result -> load(), error -> Ui.toast(error.getMessage()))));
                    card.addView(row);
                }
                if (Screens.can("shifts.manage")) {
                    card.addView(Ui.ghost(c, "تخصیص به کاربر", () -> assign(sh)));
                    card.addView(Ui.ghost(c, "ویرایش شیفت", () -> editShift(sh)));
                }
                body.addView(card);
            }
        }
        private void createShift() {
            LinearLayout form = Ui.col(c); form.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8));
            EditText name = field(form, "نام شیفت"); EditText start = field(form, "شروع (HH:mm)"); start.setText("09:00");
            EditText end = field(form, "پایان (HH:mm)"); end.setText("17:00");
            EditText store = field(form, "فروشگاه"); EditText department = field(form, "قسمت / دپارتمان");
            EditText workdays = field(form, "روزهای هفته (۰ تا ۶، جداشده با کاما)"); workdays.setText("0,1,2,3,4,5,6");
            ScrollView scroll = new ScrollView(c); scroll.addView(form);
            new AlertDialog.Builder(c).setTitle("تعریف شیفت").setView(scroll)
                    .setNegativeButton("انصراف", null)
                    .setPositiveButton("ذخیره", (dialog, which) -> {
                        String title = name.getText().toString().trim();
                        if (title.isEmpty()) { Ui.toast("نام شیفت را وارد کنید."); return; }
                        JSONObject body = new JSONObject(); JSONArray days = new JSONArray();
                        try {
                            body.put("name", title); body.put("start_time", start.getText().toString().trim()); body.put("end_time", end.getText().toString().trim());
                            body.put("store", store.getText().toString().trim()); body.put("department", department.getText().toString().trim());
                            for (String day : workdays.getText().toString().split(",")) { String value = day.trim(); if (!value.isEmpty()) days.put(Integer.parseInt(value)); }
                            body.put("workdays", days);
                        } catch (Exception e) { Ui.toast("زمان و روزهای کاری را بررسی کنید."); return; }
                        Api.post("/hr/shifts", body, result -> load(), error -> Ui.toast(error.getMessage()));
                    }).show();
        }
        private void editShift(JSONObject shift) {
            LinearLayout form = Ui.col(c); form.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8));
            EditText name = field(form, "نام شیفت"); name.setText(shift.optString("name", ""));
            EditText start = field(form, "شروع (HH:mm)"); start.setText(shift.optString("start_time", "09:00"));
            EditText end = field(form, "پایان (HH:mm)"); end.setText(shift.optString("end_time", "17:00"));
            EditText store = field(form, "فروشگاه"); store.setText(shift.optString("store", ""));
            EditText department = field(form, "قسمت / دپارتمان"); department.setText(shift.optString("department", ""));
            StringBuilder dayText = new StringBuilder(); JSONArray oldDays = shift.optJSONArray("workdays");
            for (int i = 0; oldDays != null && i < oldDays.length(); i++) { if (dayText.length() > 0) dayText.append(','); dayText.append(oldDays.optInt(i)); }
            EditText workdays = field(form, "روزهای هفته (۰ تا ۶، جداشده با کاما)"); workdays.setText(dayText.length() == 0 ? "0,1,2,3,4,5,6" : dayText.toString());
            ScrollView scroll = new ScrollView(c); scroll.addView(form);
            new AlertDialog.Builder(c).setTitle("ویرایش شیفت").setView(scroll).setNegativeButton("انصراف", null)
                    .setPositiveButton("ذخیره", (dialog, which) -> {
                        JSONObject body = new JSONObject(); JSONArray days = new JSONArray();
                        try {
                            body.put("name", name.getText().toString().trim()); body.put("start_time", start.getText().toString().trim()); body.put("end_time", end.getText().toString().trim());
                            body.put("store", store.getText().toString().trim()); body.put("department", department.getText().toString().trim());
                            for (String value : workdays.getText().toString().split(",")) if (!value.trim().isEmpty()) days.put(Integer.parseInt(value.trim()));
                            body.put("workdays", days);
                        } catch (Exception e) { Ui.toast("زمان و روزهای کاری را بررسی کنید."); return; }
                        Api.patch("/hr/shifts/" + shift.optLong("id"), body, result -> load(), error -> Ui.toast(error.getMessage()));
                    }).show();
        }
        private EditText field(LinearLayout parent, String hint) { EditText input = Ui.input(c, hint); input.setSingleLine(true); parent.addView(input); return input; }
        private void assign(JSONObject shift) {
            if (people.length() == 0) { Ui.toast("فهرست کارمندان دریافت نشده است."); return; }
            ArrayList<String> labels = new ArrayList<>();
            for (int i = 0; i < people.length(); i++) { JSONObject person = people.optJSONObject(i); labels.add(person == null ? "کاربر" : person.optString("full_name", "کاربر")); }
            LinearLayout form = Ui.col(c); form.setPadding(Ui.dp(12), Ui.dp(8), Ui.dp(12), Ui.dp(8));
            Spinner picker = new Spinner(c); picker.setAdapter(new ArrayAdapter<>(c, android.R.layout.simple_spinner_dropdown_item, labels)); form.addView(picker);
            EditText day = field(form, "تاریخ اختیاری (YYYY-MM-DD؛ خالی = تکرارشونده)");
            ScrollView scroll = new ScrollView(c); scroll.addView(form);
            new AlertDialog.Builder(c).setTitle("تخصیص «" + shift.optString("name") + "»").setView(scroll)
                    .setNegativeButton("انصراف", null)
                    .setPositiveButton("تخصیص", (dialog, which) -> {
                        JSONObject person = people.optJSONObject(picker.getSelectedItemPosition());
                        if (person == null) return;
                        JSONObject body = new JSONObject();
                        try { body.put("user_id", person.optLong("id")); body.put("day", day.getText().toString().trim()); }
                        catch (Exception e) { Ui.toast("اطلاعات تخصیص نامعتبر است."); return; }
                        Api.post("/hr/shifts/" + shift.optLong("id") + "/assign", body, result -> load(), error -> Ui.toast(error.getMessage()));
                    }).show();
        }
    }

    public static final class Attendance extends Screens.Screen {
        Attendance(AppActivity a) { super(a); }
        public String key() { return "attendance"; }
        public String title() { return "حضور امروز کارکنان"; }
        public boolean autoRefresh() { return true; }
        public void load() {
            loading();
            Api.get("/hr/attendance/today", value -> {
                clear(); LinearLayout summary = Ui.card(c, "گزارش حضور امروز");
                JSONArray staff = value instanceof JSONArray ? (JSONArray) value : new JSONArray();
                int present = 0;
                for (int i = 0; i < staff.length(); i++) if (staff.optJSONObject(i) != null && staff.optJSONObject(i).optBoolean("present")) present++;
                summary.addView(Ui.kv(c, "حاضر / برنامه‌ریزی‌شده", Ui.num(present) + " / " + Ui.num(staff.length()), present > 0 ? Ui.GREEN : Ui.MUTED));
                body.addView(summary);
                if (staff.length() == 0) { body.addView(Ui.empty(c, "برای امروز حضور یا شیفت ثبت نشده است.")); return; }
                for (int i = 0; i < staff.length(); i++) {
                    JSONObject row = staff.optJSONObject(i); if (row == null) continue;
                    LinearLayout card = Ui.card(c, row.optString("name", "کارمند"));
                    card.addView(Ui.kv(c, "شیفت", row.optString("shift_name", "—") + " · " + row.optString("start_time", "—") + " تا " + row.optString("end_time", "—"), 0));
                    card.addView(Ui.kv(c, "وضعیت", row.optBoolean("present") ? "حاضر · " + minutes(row.optInt("minutes", 0)) : "هنوز ورود ثبت نشده", row.optBoolean("present") ? Ui.GREEN : Ui.AMBER));
                    body.addView(card);
                }
            }, error -> { clear(); offline("گزارش حضور کارکنان"); });
        }
    }

    private static String minutes(int value) { int m = Math.max(0, value); return Ui.fa((m / 60) + " ساعت " + (m % 60) + " دقیقه"); }
    private static String dayLabels(JSONArray values) {
        if (values == null || values.length() == 0) return "هر روز";
        String[] names = {"دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"};
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < values.length(); i++) { int day = values.optInt(i, -1); if (day < 0 || day >= names.length) continue; if (out.length() > 0) out.append("، "); out.append(names[day]); }
        return out.length() == 0 ? "هر روز" : out.toString();
    }
}
