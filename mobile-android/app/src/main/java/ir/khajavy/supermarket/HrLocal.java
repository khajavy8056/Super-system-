package ir.khajavy.supermarket;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Offline HR API backed by the phone's own SQLite database. */
final class HrLocal {
    private HrLocal() {}

    static Object handle(String method, String[] seg, JSONObject q, JSONObject body) throws Exception {
        String area = seg.length > 1 ? seg[1] : "";
        if ("shifts".equals(area)) return shifts(method, seg, q, body);
        if ("roster-users".equals(area) && "GET".equals(method)) return rosterUsers();
        if ("attendance".equals(area)) return attendance(method, seg, q, body);
        if ("announcements".equals(area)) return announcements(method, seg, body);
        if ("payroll".equals(area)) return payroll(method, seg, q, body);
        if ("performance".equals(area)) return performance(method, seg, q);
        if ("widgets".equals(area)) return new JSONObject().put("widgets", new JSONArray());
        throw new Api.ApiError(404, "NOT_FOUND", "بخش منابع انسانی روی گوشی پیدا نشد");
    }

    private static Object shifts(String method, String[] seg, JSONObject q, JSONObject b) throws Exception {
        if (seg.length > 2 && "my".equals(seg[2]) && "GET".equals(method)) return myShifts();
        if (seg.length > 2 && "day".equals(seg[2]) && "GET".equals(method)) {
            String day = seg.length > 3 ? seg[3] : today();
            JSONArray staff = attendanceForDay(day);
            return new JSONObject().put("day", day).put("staff", staff);
        }
        if (seg.length > 2 && "performance".equals(seg[2]) && "GET".equals(method)) {
            long localId = localUser(seg.length > 3 ? Long.parseLong(seg[3]) : Db.localUserId());
            return dayPerformance(localId, seg.length > 4 ? seg[4] : today());
        }
        if (seg.length > 2 && "assignments".equals(seg[2])) {
            long assignmentId = Long.parseLong(seg[3]);
            if ("DELETE".equals(method)) return unassign(assignmentId);
            if (seg.length > 4 && "move".equals(seg[4]) && "POST".equals(method)) return moveAssignment(assignmentId, b);
        }
        if (seg.length == 2 && "roster-users".equals(seg[1]) && "GET".equals(method)) return rosterUsers();
        if (seg.length == 2 && "GET".equals(method)) return listShifts();
        if (seg.length == 2 && "POST".equals(method)) return createShift(b);
        if (seg.length > 2 && "PATCH".equals(method)) return updateShift(Long.parseLong(seg[2]), b);
        if (seg.length > 3 && "assign".equals(seg[3]) && "POST".equals(method)) return assign(Long.parseLong(seg[2]), b);
        throw new Api.ApiError(404, "NOT_FOUND", "عملیات شیفت روی گوشی پیدا نشد");
    }

    private static JSONArray listShifts() throws Exception {
        JSONArray out = new JSONArray();
        for (JSONObject row : rows("SELECT * FROM local_shifts ORDER BY status DESC,start_time,id DESC")) {
            JSONObject item = shiftOut(row); JSONArray roster = new JSONArray();
            for (JSONObject a : rows("SELECT a.id,a.day,a.status,a.user_id,COALESCE(u.full_name,u.username,'') full_name,COALESCE(u.job_title,'') job_title FROM local_shift_assignments a LEFT JOIN users u ON u.id=a.user_id WHERE a.shift_id=? AND a.status='ACTIVE' ORDER BY a.day,a.id", row.optLong("id"))) {
                JSONObject r = new JSONObject(); r.put("assignment_id", a.optLong("id")); r.put("user_id", a.optLong("user_id"));
                r.put("day", a.optString("day")); r.put("status", a.optString("status"));
                r.put("full_name", a.optString("full_name")); r.put("job_title", a.optString("job_title")); roster.put(r);
            }
            item.put("roster", roster); out.put(item);
        }
        return out;
    }

    private static JSONObject shiftOut(JSONObject row) throws Exception {
        JSONObject out = new JSONObject();
        for (String k : new String[]{"id", "name", "start_time", "end_time", "store", "department", "role_hint", "status", "created_by", "updated_at"})
            out.put(k, row.isNull(k) ? JSONObject.NULL : row.opt(k));
        out.put("pc_id", row.optLong("pc_id"));
        out.put("workdays", jsonArray(row.optString("workdays", "[]")));
        return out;
    }

    private static JSONArray rosterUsers() throws Exception {
        JSONArray out = new JSONArray();
        for (JSONObject row : rows("SELECT id,pc_id,username,full_name,job_title FROM users WHERE is_active=1 ORDER BY full_name,username LIMIT 2000")) {
            JSONObject user = new JSONObject(); user.put("id", row.optLong("id"));
            user.put("pc_id", row.optLong("pc_id")); user.put("full_name", row.optString("full_name", row.optString("username")));
            user.put("job_title", row.optString("job_title")); out.put(user);
        }
        return out;
    }

    private static Object createShift(JSONObject b) throws Exception {
        String name = b.optString("name", "").trim(), start = b.optString("start_time", ""), end = b.optString("end_time", "");
        validateTime(start); validateTime(end);
        if (name.isEmpty()) throw new Api.ApiError(400, "EMPTY_NAME", "نام شیفت خالی است");
        if (start.equals(end)) throw new Api.ApiError(400, "BAD_RANGE", "ساعت شروع و پایان نمی‌توانند یکی باشند");
        JSONArray days = b.optJSONArray("workdays"); if (days == null) days = new JSONArray();
        JSONArray validDays = new JSONArray(); java.util.TreeSet<Integer> sorted = new java.util.TreeSet<>();
        for (int i = 0; i < days.length(); i++) { int day = days.optInt(i, -1); if (day < 0 || day > 6) throw new Api.ApiError(400, "BAD_WORKDAY", "روز کاری باید بین صفر تا شش باشد"); sorted.add(day); }
        for (Integer day : sorted) validDays.put(day);
        long id = Db.nextLocalId("hr_shift"); String now = Db.now(); long owner = Db.localUserId();
        exec("INSERT INTO local_shifts(id,pc_id,name,start_time,end_time,workdays,store,department,role_hint,status,created_by,updated_at,is_local) VALUES(?,0,?,?,?,?,?,?,?,'ACTIVE',?,?,1)",
                id, name, start, end, validDays.toString(), b.optString("store", ""), b.optString("department", ""), nullIfEmpty(b.optString("role_hint", "")), owner, now);
        JSONObject saved = one("SELECT * FROM local_shifts WHERE id=?", id); JSONObject out = shiftOut(saved); out.put("roster", new JSONArray());
        JSONObject op = new JSONObject(b.toString()); op.put("local_shift_id", id); op.put("workdays", validDays);
        enqueue("SHIFT_CREATE", op, "تعریف شیفت «" + name + "»");
        return out;
    }

    private static Object updateShift(long id, JSONObject b) throws Exception {
        JSONObject old = findShift(id); if (old == null) throw new Api.ApiError(404, "SHIFT_NOT_FOUND", "شیفت پیدا نشد");
        ContentValues cv = new ContentValues();
        if (b.has("name")) { String value = b.optString("name", "").trim(); if (value.isEmpty()) throw new Api.ApiError(400, "EMPTY_NAME", "نام شیفت خالی است"); cv.put("name", value); }
        if (b.has("start_time")) { validateTime(b.optString("start_time")); cv.put("start_time", b.optString("start_time")); }
        if (b.has("end_time")) { validateTime(b.optString("end_time")); cv.put("end_time", b.optString("end_time")); }
        if (b.has("workdays")) cv.put("workdays", b.optJSONArray("workdays") == null ? "[]" : b.optJSONArray("workdays").toString());
        for (String field : new String[]{"store", "department", "role_hint", "status"}) if (b.has(field)) cv.put(field, b.isNull(field) ? null : b.optString(field));
        String newStart = cv.containsKey("start_time") ? cv.getAsString("start_time") : old.optString("start_time");
        String newEnd = cv.containsKey("end_time") ? cv.getAsString("end_time") : old.optString("end_time");
        if (newStart.equals(newEnd)) throw new Api.ApiError(400, "BAD_RANGE", "ساعت شروع و پایان نمی‌توانند یکی باشند");
        cv.put("updated_at", Db.now()); Db.db().update("local_shifts", cv, "id=?", new String[]{String.valueOf(id)});
        JSONObject op = new JSONObject(b.toString()); op.put("shift_id", id); op.put("local_shift_id", id); enqueue("SHIFT_UPDATE", op, "ویرایش شیفت " + old.optString("name"));
        JSONObject updated = findShift(id); JSONObject out = shiftOut(updated); out.put("roster", listShiftRoster(id)); return out;
    }

    private static Object assign(long shiftId, JSONObject b) throws Exception {
        JSONObject shift = findShift(shiftId); if (shift == null) throw new Api.ApiError(404, "SHIFT_NOT_FOUND", "شیفت پیدا نشد");
        long userId = localUser(b.optLong("user_id"));
        if (one("SELECT id FROM users WHERE id=? AND is_active=1", userId) == null) throw new Api.ApiError(404, "USER_NOT_FOUND", "کارمند فعال پیدا نشد");
        String day = b.optString("day", "").trim(); if (!day.isEmpty()) validateDay(day);
        JSONObject existing = one("SELECT * FROM local_shift_assignments WHERE shift_id=? AND user_id=? AND day=? ORDER BY id DESC LIMIT 1", shiftId, userId, day);
        long assignmentId;
        if (existing != null) {
            assignmentId = existing.optLong("id");
            if ("ACTIVE".equals(existing.optString("status"))) return new JSONObject().put("assignment_id", assignmentId).put("user_id", userId).put("day", day).put("status", "ACTIVE");
            exec("UPDATE local_shift_assignments SET status='ACTIVE',updated_at=? WHERE id=?", Db.now(), assignmentId);
        } else {
            assignmentId = Db.nextLocalId("hr_assignment");
            exec("INSERT INTO local_shift_assignments(id,pc_id,shift_id,user_id,day,status,created_at,updated_at,is_local) VALUES(?,0,?,?,?,'ACTIVE',?,?,1)", assignmentId, shiftId, userId, day, Db.now(), Db.now());
        }
        JSONObject op = new JSONObject(); op.put("shift_id", shiftId); op.put("day", day); op.put("local_assignment_id", assignmentId);
        long remoteUserId = Db.pcUserIdForLocal(userId);
        if (remoteUserId > 0) op.put("user_id", remoteUserId);
        enqueue("SHIFT_ASSIGN", op, "تخصیص شیفت به " + userName(userId));
        return new JSONObject().put("assignment_id", assignmentId).put("user_id", userId).put("day", day).put("status", "ACTIVE");
    }

    private static Object unassign(long assignmentId) throws Exception {
        JSONObject a = one("SELECT * FROM local_shift_assignments WHERE id=?", assignmentId);
        if (a == null) throw new Api.ApiError(404, "ASSIGNMENT_NOT_FOUND", "تخصیص شیفت پیدا نشد");
        exec("UPDATE local_shift_assignments SET status='CANCELLED',updated_at=? WHERE id=?", Db.now(), assignmentId);
        JSONObject op = new JSONObject(); op.put("assignment_id", assignmentId); op.put("local_assignment_id", assignmentId);
        enqueue("SHIFT_UNASSIGN", op, "لغو تخصیص شیفت " + userName(a.optLong("user_id")));
        return new JSONObject().put("ok", true);
    }

    private static Object moveAssignment(long assignmentId, JSONObject b) throws Exception {
        JSONObject old = one("SELECT * FROM local_shift_assignments WHERE id=?", assignmentId);
        if (old == null) throw new Api.ApiError(404, "ASSIGNMENT_NOT_FOUND", "تخصیص شیفت پیدا نشد");
        long targetShift = b.optLong("shift_id"); if (findShift(targetShift) == null) throw new Api.ApiError(404, "SHIFT_NOT_FOUND", "شیفت مقصد پیدا نشد");
        String day = b.has("day") && !b.isNull("day") ? b.optString("day") : old.optString("day", "");
        if (!day.isEmpty()) validateDay(day);
        long userId = old.optLong("user_id"), newId = Db.nextLocalId("hr_assignment"); String now = Db.now();
        Db.db().beginTransaction();
        try {
            exec("UPDATE local_shift_assignments SET status='CANCELLED',updated_at=? WHERE id=?", now, assignmentId);
            exec("INSERT INTO local_shift_assignments(id,pc_id,shift_id,user_id,day,status,created_at,updated_at,is_local) VALUES(?,0,?,?,?,'ACTIVE',?,?,1)", newId, targetShift, userId, day, now, now);
            Db.db().setTransactionSuccessful();
        } finally { Db.db().endTransaction(); }
        JSONObject op = new JSONObject(); op.put("assignment_id", assignmentId); op.put("shift_id", targetShift); op.put("day", day);
        op.put("local_assignment_id", newId); enqueue("SHIFT_MOVE", op, "انتقال شیفت " + userName(userId));
        return new JSONObject().put("assignment_id", newId).put("user_id", userId).put("shift_id", targetShift).put("day", day).put("status", "ACTIVE");
    }

    private static JSONArray listShiftRoster(long shiftId) throws Exception {
        JSONArray out = new JSONArray();
        for (JSONObject a : rows("SELECT a.id,a.day,a.status,a.user_id,u.full_name,u.job_title FROM local_shift_assignments a LEFT JOIN users u ON u.id=a.user_id WHERE a.shift_id=? AND a.status='ACTIVE' ORDER BY a.day,a.id", shiftId)) {
            JSONObject item = new JSONObject(); item.put("assignment_id", a.optLong("id")); item.put("day", a.optString("day"));
            item.put("status", a.optString("status")); item.put("user_id", a.optLong("user_id"));
            item.put("full_name", a.optString("full_name")); item.put("job_title", a.optString("job_title")); out.put(item);
        }
        return out;
    }

    private static Object myShifts() throws Exception {
        JSONObject status = attendanceStatus(true); JSONArray assignments = new JSONArray(); long uid = Db.localUserId();
        for (JSONObject row : rows("SELECT a.id assignment_id,a.day,a.shift_id,s.name shift_name,s.start_time,s.end_time,s.workdays,s.store,s.department FROM local_shift_assignments a JOIN local_shifts s ON s.id=a.shift_id WHERE a.user_id=? AND a.status='ACTIVE' AND s.status='ACTIVE' ORDER BY a.day DESC,s.start_time", uid)) {
            JSONObject item = new JSONObject(row.toString()); item.put("workdays", jsonArray(row.optString("workdays", "[]"))); assignments.put(item);
        }
        return new JSONObject().put("status", status).put("assignments", assignments);
    }

    private static JSONArray matchingShifts(long userId, String day) throws Exception {
        int weekday = weekday(day); JSONArray out = new JSONArray();
        for (JSONObject a : rows("SELECT a.day assignment_day,s.* FROM local_shift_assignments a JOIN local_shifts s ON s.id=a.shift_id WHERE a.user_id=? AND a.status='ACTIVE' AND s.status='ACTIVE' ORDER BY s.start_time,a.id", userId)) {
            String assignmentDay = a.optString("assignment_day", "");
            if (assignmentDay.length() > 0 && !assignmentDay.equals(day)) continue;
            if (assignmentDay.isEmpty()) { JSONArray workdays = jsonArray(a.optString("workdays", "[]")); if (workdays.length() > 0 && !contains(workdays, weekday)) continue; }
            boolean duplicate = false; for (int i = 0; i < out.length(); i++) if (out.optJSONObject(i).optLong("id") == a.optLong("id")) duplicate = true;
            if (!duplicate) out.put(a);
        }
        return out;
    }

    private static JSONObject attendanceStatus(boolean autoEnter) throws Exception {
        long userId = Db.localUserId(); String day = today(); Date now = new Date();
        JSONArray shifts = matchingShifts(userId, day); JSONObject active = null; boolean inWindow = false;
        long grace = 15L * 60L * 1000L; JSONObject upcoming = null; Date upcomingStart = null;
        for (int i = 0; i < shifts.length(); i++) {
            JSONObject shift = shifts.optJSONObject(i); Date start = at(day, shift.optString("start_time")), end = at(day, shift.optString("end_time"));
            if (!end.after(start)) end = new Date(end.getTime() + 24L * 60L * 60L * 1000L);
            if (!now.before(new Date(start.getTime() - grace)) && !now.after(end)) { active = shift; inWindow = true; break; }
            if (now.before(start) && (upcomingStart == null || start.before(upcomingStart))) { upcoming = shift; upcomingStart = start; }
        }
        if (active == null) {
            if (upcoming != null) active = upcoming;
            else if (shifts.length() > 0) active = shifts.optJSONObject(shifts.length() - 1);
        }
        JSONObject att = one("SELECT * FROM local_attendance WHERE user_id=? AND day=? ORDER BY id DESC LIMIT 1", userId, day);
        boolean autoClocked = false;
        if (autoEnter && active != null && inWindow && att == null) {
            JSONObject result = (JSONObject) clockIn(active.optLong("id"), day, true);
            att = one("SELECT * FROM local_attendance WHERE id=?", result.optLong("id")); autoClocked = true;
        }
        if (active == null && att != null && att.optLong("shift_id") > 0) active = findShift(att.optLong("shift_id"));
        boolean present = att != null && !att.isNull("started_at") && att.optString("started_at").length() > 0 && (att.isNull("ended_at") || att.optString("ended_at").isEmpty());
        String state = shifts.length() == 0 && att == null ? "NO_SHIFT" : att != null && !att.isNull("ended_at") && !att.optString("ended_at").isEmpty() ? "COMPLETED" : present || inWindow ? "IN_SHIFT" : "OUT_OF_SHIFT";
        int minutes = present ? Math.max(0, (int) ((now.getTime() - parseDateTime(att.optString("started_at")).getTime()) / 60000L)) : 0;
        JSONArray windows = new JSONArray();
        for (int i = 0; i < shifts.length(); i++) {
            JSONObject sh = shifts.optJSONObject(i); Date start = at(day, sh.optString("start_time")), end = at(day, sh.optString("end_time"));
            if (!end.after(start)) end = new Date(end.getTime() + 86400000L);
            windows.put(new JSONObject().put("id", sh.optLong("id")).put("name", sh.optString("name"))
                    .put("start_time", sh.optString("start_time")).put("end_time", sh.optString("end_time"))
                    .put("in_window", !now.before(new Date(start.getTime() - grace)) && !now.after(end)));
        }
        JSONObject activeOut = active == null ? null : new JSONObject().put("id", active.optLong("id")).put("name", active.optString("name"))
                .put("start_time", active.optString("start_time")).put("end_time", active.optString("end_time"));
        JSONObject out = new JSONObject(); out.put("day", day); out.put("has_shift", shifts.length() > 0 || att != null);
        out.put("in_shift_window", inWindow); out.put("auto_entered", autoClocked); out.put("auto_clocked_in", autoClocked);
        out.put("shift_state", state); out.put("active_shift", activeOut == null ? JSONObject.NULL : activeOut); out.put("shift_windows", windows);
        out.put("shift_id", active != null ? active.optLong("id") : att == null ? JSONObject.NULL : att.optLong("shift_id"));
        out.put("shift_name", active == null ? JSONObject.NULL : active.optString("name"));
        out.put("start_time", active == null ? JSONObject.NULL : active.optString("start_time"));
        out.put("end_time", active == null ? JSONObject.NULL : active.optString("end_time"));
        out.put("present", present); out.put("since", att == null || att.isNull("started_at") ? JSONObject.NULL : att.optString("started_at"));
        out.put("ended_at", att == null || att.isNull("ended_at") ? JSONObject.NULL : att.optString("ended_at"));
        out.put("minutes", present ? minutes : JSONObject.NULL); out.put("late_minutes", att == null || att.isNull("late_minutes") ? JSONObject.NULL : att.optInt("late_minutes"));
        out.put("shifts_today", windows); return out;
    }

    private static Object attendance(String method, String[] seg, JSONObject q, JSONObject b) throws Exception {
        String action = seg.length > 2 ? seg[2] : "";
        if ("status".equals(action) && "GET".equals(method)) return attendanceStatus("1".equals(q.optString("auto")) || "true".equalsIgnoreCase(q.optString("auto")));
        if ("enter".equals(action) && "POST".equals(method)) return attendanceStatus(true);
        if ("clock-in".equals(action) && "POST".equals(method)) return clockIn(q.optLong("shift_id"), q.optString("day", ""), false);
        if ("clock-out".equals(action) && "POST".equals(method)) return clockOut(q.optString("day", ""));
        if ("my-summary".equals(action) && "GET".equals(method)) {
            String end = q.optString("end", today()), start = q.optString("start", addDays(end, -29));
            return summaryForUser(Db.localUserId(), start, end);
        }
        if ("summary".equals(action) && "GET".equals(method)) {
            String end = q.optString("end", today()), start = q.optString("start", addDays(end, -29));
            long wanted = q.optLong("user_id", 0); JSONArray out = new JSONArray();
            if (wanted > 0) out.put(summaryForUser(localUser(wanted), start, end));
            else for (JSONObject user : rows("SELECT id FROM users WHERE is_active=1 ORDER BY id")) out.put(summaryForUser(user.optLong("id"), start, end));
            return out;
        }
        if ("today".equals(action) && "GET".equals(method)) return attendanceForDay(today());
        throw new Api.ApiError(404, "NOT_FOUND", "عملیات حضور روی گوشی پیدا نشد");
    }

    private static Object clockIn(long requestedShift, String requestedDay, boolean automatic) throws Exception {
        long userId = Db.localUserId(); String day = requestedDay == null || requestedDay.isEmpty() ? today() : requestedDay; validateDay(day);
        JSONObject old = one("SELECT * FROM local_attendance WHERE user_id=? AND day=? ORDER BY id DESC LIMIT 1", userId, day);
        if (old != null && !old.isNull("started_at") && !old.optString("started_at").isEmpty())
            throw new Api.ApiError(400, "ALREADY_CLOCKED_IN", "حضور این روز قبلاً ثبت شده است");
        long shiftId = requestedShift;
        if (shiftId <= 0 && old != null) shiftId = old.optLong("shift_id");
        JSONObject shift = shiftId == 0 ? null : findShift(shiftId);
        if (shift == null && shiftId > 0) shift = findShift(Db.remoteShiftId(shiftId));
        long localId = old == null ? Db.nextLocalId("hr_attendance") : old.optLong("id");
        Date started = new Date(); String start = formatDateTime(started); Integer late = null;
        if (shift != null) { Date planned = at(day, shift.optString("start_time")); late = Math.max(0, (int) ((started.getTime() - planned.getTime()) / 60000L)); }
        ContentValues cv = new ContentValues(); cv.put("id", localId); cv.put("pc_id", old == null ? 0 : old.optLong("pc_id"));
        if (shift == null) cv.putNull("shift_id"); else cv.put("shift_id", shift.optLong("id")); cv.put("user_id", userId); cv.put("day", day);
        cv.put("started_at", start); cv.put("ended_at", (String) null); if (late == null) cv.putNull("late_minutes"); else cv.put("late_minutes", late);
        cv.put("updated_at", start); cv.put("is_local", 1);
        Db.db().insertWithOnConflict("local_attendance", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        JSONObject op = new JSONObject(); op.put("attendance_id", localId); op.put("shift_id", shift == null ? JSONObject.NULL : shift.optLong("id"));
        op.put("day", day); op.put("started_at", start); op.put("late_minutes", late == null ? JSONObject.NULL : late);
        enqueue("ATTENDANCE_CLOCK_IN", op, automatic ? "ثبت خودکار حضور" : "ثبت حضور");
        return new JSONObject().put("id", localId).put("day", day).put("started_at", start).put("late_minutes", late == null ? JSONObject.NULL : late).put("auto_entered", automatic);
    }

    private static Object clockOut(String requestedDay) throws Exception {
        String day = requestedDay == null || requestedDay.isEmpty() ? today() : requestedDay; validateDay(day); long userId = Db.localUserId();
        JSONObject row = one("SELECT * FROM local_attendance WHERE user_id=? AND day=? ORDER BY id DESC LIMIT 1", userId, day);
        if (row != null && !row.isNull("ended_at") && !row.optString("ended_at").isEmpty()) throw new Api.ApiError(400, "ALREADY_CLOCKED_OUT", "پایان حضور قبلاً ثبت شده است");
        Date ended = new Date(); String end = formatDateTime(ended); long id = row == null ? Db.nextLocalId("hr_attendance") : row.optLong("id");
        long shiftId = row == null ? 0 : row.optLong("shift_id"); JSONObject shift = shiftId == 0 ? null : findShift(shiftId);
        Integer early = null;
        if (shift != null) { Date plannedEnd = at(day, shift.optString("end_time")); if (!plannedEnd.after(at(day, shift.optString("start_time")))) plannedEnd = new Date(plannedEnd.getTime() + 86400000L); early = Math.max(0, (int) ((plannedEnd.getTime() - ended.getTime()) / 60000L)); }
        ContentValues cv = new ContentValues(); cv.put("id", id); cv.put("pc_id", row == null ? 0 : row.optLong("pc_id"));
        if (shiftId == 0) cv.putNull("shift_id"); else cv.put("shift_id", shiftId); cv.put("user_id", userId); cv.put("day", day);
        if (row == null || row.isNull("started_at")) cv.putNull("started_at"); else cv.put("started_at", row.optString("started_at"));
        cv.put("ended_at", end); if (row == null || row.isNull("late_minutes")) cv.putNull("late_minutes"); else cv.put("late_minutes", row.optInt("late_minutes"));
        if (early == null) cv.putNull("early_leave_minutes"); else cv.put("early_leave_minutes", early); cv.put("updated_at", end); cv.put("is_local", 1);
        Db.db().insertWithOnConflict("local_attendance", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        JSONObject op = new JSONObject(); op.put("attendance_id", id); op.put("day", day); op.put("ended_at", end);
        op.put("early_leave_minutes", early == null ? JSONObject.NULL : early); enqueue("ATTENDANCE_CLOCK_OUT", op, "ثبت پایان حضور");
        return new JSONObject().put("id", id).put("day", day).put("ended_at", end).put("early_leave_minutes", early == null ? JSONObject.NULL : early);
    }

    private static JSONArray attendanceForDay(String day) throws Exception {
        JSONArray out = new JSONArray(); int wd = weekday(day); HashMap<Long, JSONObject> staff = new HashMap<>();
        for (JSONObject a : rows("SELECT a.id assignment_id,a.day assignment_day,a.user_id,s.id shift_id,s.name shift_name,s.start_time,s.end_time,s.workdays,u.full_name,u.username FROM local_shift_assignments a JOIN local_shifts s ON s.id=a.shift_id JOIN users u ON u.id=a.user_id WHERE a.status='ACTIVE' AND s.status='ACTIVE' ORDER BY s.start_time,a.id")) {
            String assigned = a.optString("assignment_day", ""); if (!assigned.isEmpty() && !assigned.equals(day)) continue;
            if (assigned.isEmpty()) { JSONArray workdays = jsonArray(a.optString("workdays", "[]")); if (workdays.length() > 0 && !contains(workdays, wd)) continue; }
            long uid = a.optLong("user_id"); if (staff.containsKey(uid)) continue;
            JSONObject record = new JSONObject(); record.put("user_id", uid); record.put("name", a.optString("full_name", a.optString("username")));
            record.put("shift_id", a.optLong("shift_id")); record.put("shift_name", a.optString("shift_name")); record.put("start_time", a.optString("start_time")); record.put("end_time", a.optString("end_time"));
            record.put("day", day); record.put("assignment_id", a.optLong("assignment_id")); staff.put(uid, record);
        }
        for (JSONObject attendance : rows("SELECT DISTINCT user_id FROM local_attendance WHERE day=?", day)) {
            long uid = attendance.optLong("user_id"); if (!staff.containsKey(uid)) { JSONObject user = one("SELECT full_name,username FROM users WHERE id=?", uid); if (user != null) staff.put(uid, new JSONObject().put("user_id", uid).put("name", user.optString("full_name", user.optString("username"))).put("shift_id", JSONObject.NULL).put("shift_name", JSONObject.NULL).put("start_time", JSONObject.NULL).put("end_time", JSONObject.NULL).put("day", day)); }
        }
        for (Map.Entry<Long, JSONObject> entry : staff.entrySet()) {
            JSONObject item = entry.getValue(); JSONObject attendance = one("SELECT * FROM local_attendance WHERE user_id=? AND day=? ORDER BY id DESC LIMIT 1", entry.getKey(), day);
            boolean present = attendance != null && !attendance.isNull("started_at") && (attendance.isNull("ended_at") || attendance.optString("ended_at").isEmpty());
            item.put("present", present); item.put("since", attendance == null || attendance.isNull("started_at") ? JSONObject.NULL : attendance.optString("started_at"));
            item.put("ended_at", attendance == null || attendance.isNull("ended_at") ? JSONObject.NULL : attendance.optString("ended_at"));
            int minutes = present ? Math.max(0, (int) ((new Date().getTime() - parseDateTime(attendance.optString("started_at")).getTime()) / 60000L)) : 0;
            item.put("minutes", present ? minutes : JSONObject.NULL); out.put(item);
        }
        return out;
    }

    private static JSONObject summaryForUser(long userId, String start, String end) throws Exception {
        validateDay(start); validateDay(end); Date s = parseDay(start), e = parseDay(end); if (e.before(s)) { Date swap = s; s = e; e = swap; }
        int planned = 0, worked = 0, late = 0, early = 0, scheduled = 0, presentDays = 0;
        Calendar cursor = Calendar.getInstance(); cursor.setTime(s); Calendar stop = Calendar.getInstance(); stop.setTime(e);
        while (!cursor.after(stop)) {
            String day = formatDay(cursor.getTime()); JSONArray shifts = matchingShifts(userId, day); int planDay = 0;
            for (int i = 0; i < shifts.length(); i++) { JSONObject sh = shifts.optJSONObject(i); Date st = at(day, sh.optString("start_time")), en = at(day, sh.optString("end_time")); if (!en.after(st)) en = new Date(en.getTime() + 86400000L); planDay += Math.max(0, (int) ((en.getTime() - st.getTime()) / 60000L)); }
            if (planDay > 0) scheduled++;
            planned += planDay;
            List<JSONObject> dayAttendance = rows("SELECT * FROM local_attendance WHERE user_id=? AND day=? ORDER BY id", userId, day);
            if (!dayAttendance.isEmpty()) presentDays++;
            for (JSONObject a : dayAttendance) {
                if (!a.isNull("late_minutes")) late += a.optInt("late_minutes");
                if (!a.isNull("early_leave_minutes")) early += a.optInt("early_leave_minutes");
                if (!a.isNull("started_at")) { Date began = parseDateTime(a.optString("started_at")); Date finished = a.isNull("ended_at") ? new Date() : parseDateTime(a.optString("ended_at")); worked += Math.max(0, (int) ((finished.getTime() - began.getTime()) / 60000L)); }
            }
            cursor.add(Calendar.DAY_OF_MONTH, 1);
        }
        JSONObject out = new JSONObject(); out.put("user_id", userId); JSONObject user = one("SELECT username,full_name FROM users WHERE id=?", userId);
        if (user != null) { out.put("username", user.optString("username")); out.put("full_name", user.optString("full_name", user.optString("username"))); }
        out.put("start_day", formatDay(s)); out.put("end_day", formatDay(e)); out.put("days_scheduled", scheduled); out.put("days_present", presentDays);
        out.put("planned_minutes", planned); out.put("worked_minutes", worked); out.put("overtime_minutes", planned > 0 ? Math.max(0, worked - planned) : worked);
        out.put("deficit_minutes", planned > 0 ? Math.max(0, planned - worked) : 0); out.put("late_minutes", late); out.put("early_leave_minutes", early); return out;
    }

    private static JSONObject dayPerformance(long userId, String day) throws Exception {
        validateDay(day); JSONArray shifts = matchingShifts(userId, day), attendanceRows = new JSONArray();
        int planned = 0, worked = 0, late = 0, early = 0;
        for (int i = 0; i < shifts.length(); i++) { JSONObject sh = shifts.optJSONObject(i); Date st = at(day, sh.optString("start_time")), en = at(day, sh.optString("end_time")); if (!en.after(st)) en = new Date(en.getTime() + 86400000L); planned += (int) ((en.getTime() - st.getTime()) / 60000L); }
        for (JSONObject a : rows("SELECT * FROM local_attendance WHERE user_id=? AND day=? ORDER BY id", userId, day)) {
            if (!a.isNull("late_minutes")) late += a.optInt("late_minutes"); if (!a.isNull("early_leave_minutes")) early += a.optInt("early_leave_minutes");
            if (!a.isNull("started_at")) { Date start = parseDateTime(a.optString("started_at")), end = a.isNull("ended_at") ? new Date() : parseDateTime(a.optString("ended_at")); worked += Math.max(0, (int) ((end.getTime() - start.getTime()) / 60000L)); }
            attendanceRows.put(new JSONObject().put("shift_id", a.isNull("shift_id") ? JSONObject.NULL : a.optLong("shift_id")).put("started_at", a.isNull("started_at") ? JSONObject.NULL : a.optString("started_at")).put("ended_at", a.isNull("ended_at") ? JSONObject.NULL : a.optString("ended_at")).put("late_minutes", a.isNull("late_minutes") ? JSONObject.NULL : a.optInt("late_minutes")).put("early_leave_minutes", a.isNull("early_leave_minutes") ? JSONObject.NULL : a.optInt("early_leave_minutes")));
        }
        JSONObject user = one("SELECT username FROM users WHERE id=?", userId); String name = user == null ? "" : user.optString("username");
        JSONObject out = new JSONObject(); out.put("user_id", userId); out.put("day", day); out.put("sales_total", 0); out.put("invoices_total", 0);
        out.put("sales_in_shift", 0); out.put("invoices_in_shift", 0); out.put("sales_out_of_shift", 0); out.put("invoices_out_of_shift", 0);
        out.put("shift_windows", new JSONArray()); out.put("planned_minutes", planned); out.put("worked_minutes", worked);
        out.put("overtime_minutes", planned > 0 ? Math.max(0, worked - planned) : worked); out.put("deficit_minutes", planned > 0 ? Math.max(0, planned - worked) : 0);
        out.put("attendance", attendanceRows); out.put("username", name); return out;
    }

    private static Object announcements(String method, String[] seg, JSONObject b) throws Exception {
        String tail = seg.length > 2 ? seg[2] : "";
        if ("GET".equals(method)) {
            boolean all = "all".equals(tail); JSONArray out = new JSONArray(); long owner = Db.localUserId();
            for (JSONObject row : rows("SELECT * FROM local_announcements ORDER BY priority ASC,created_at DESC LIMIT 500")) {
                if (!all && !visibleAnnouncement(row)) continue;
                JSONObject item = new JSONObject(row.toString()); JSONObject read = one("SELECT delivered_at,seen_at,read_at FROM local_announcement_reads WHERE announcement_id=? AND user_id=?", row.optLong("id"), owner);
                if (read != null) { item.put("delivered_at", read.isNull("delivered_at") ? JSONObject.NULL : read.opt("delivered_at")); item.put("seen_at", read.isNull("seen_at") ? JSONObject.NULL : read.opt("seen_at")); item.put("read_at", read.isNull("read_at") ? JSONObject.NULL : read.opt("read_at")); }
                JSONArray targetRoles = jsonArray(row.optString("target_roles", "[]")), targetUsers = jsonArray(row.optString("target_users", "[]"));
                item.put("target_roles", targetRoles); item.put("target_users", targetUsers); item.put("pc_id", row.optLong("pc_id")); out.put(item);
            }
            return out;
        }
        if ("POST".equals(method) && seg.length > 3 && ("read".equals(seg[3]) || "seen".equals(seg[3]))) {
            long id = Long.parseLong(seg[2]); String field = "read".equals(seg[3]) ? "read_at" : "seen_at"; long owner = Db.localUserId(); String now = Db.now();
            ContentValues read = new ContentValues(); read.put("announcement_id", id); read.put("user_id", owner);
            JSONObject priorRead = one("SELECT delivered_at,seen_at,read_at FROM local_announcement_reads WHERE announcement_id=? AND user_id=?", id, owner);
            read.put("delivered_at", priorRead == null || priorRead.isNull("delivered_at") ? now : priorRead.optString("delivered_at"));
            read.put("seen_at", priorRead == null || priorRead.isNull("seen_at") ? null : priorRead.optString("seen_at"));
            read.put("read_at", priorRead == null || priorRead.isNull("read_at") ? null : priorRead.optString("read_at"));
            read.put(field, now); Db.db().insertWithOnConflict("local_announcement_reads", null, read, SQLiteDatabase.CONFLICT_REPLACE);
            JSONObject op = new JSONObject(); op.put("announcement_id", id); op.put("local_announcement_id", id); enqueue("ANNOUNCEMENT_" + ("read".equals(seg[3]) ? "READ" : "SEEN"), op, "ثبت مشاهدهٔ اطلاعیه");
            return new JSONObject().put("ok", true);
        }
        if ("POST".equals(method) && seg.length == 2) {
            String title = b.optString("title", "").trim(); if (title.isEmpty()) throw new Api.ApiError(400, "EMPTY_TITLE", "عنوان اطلاعیه را وارد کنید");
            long id = Db.nextLocalId("hr_announcement"); String now = Db.now(); JSONArray roles = b.optJSONArray("target_roles"), users = b.optJSONArray("target_users");
            String status = b.optString("status", "PUBLISHED"), kind = b.optString("target_kind", "ALL");
            exec("INSERT INTO local_announcements(id,title,body,created_by,status,priority,publish_at,expires_at,target_kind,target_store,target_roles,target_users,attachment_path,created_at,updated_at,is_local) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                    id, title, b.optString("body", ""), Db.localUserId(), status, b.optInt("priority", 3), b.isNull("publish_at") ? null : b.optString("publish_at"), b.isNull("expires_at") ? null : b.optString("expires_at"), kind, nullIfEmpty(b.optString("target_store", "")), roles == null ? "[]" : roles.toString(), users == null ? "[]" : users.toString(), b.isNull("attachment_path") ? null : b.optString("attachment_path"), now, now);
            JSONObject op = new JSONObject(b.toString()); op.put("local_announcement_id", id);
            if (users != null) op.put("target_users", remoteUsers(users));
            enqueue("ANNOUNCEMENT_CREATE", op, "انتشار اطلاعیه «" + title + "»");
            JSONObject saved = one("SELECT * FROM local_announcements WHERE id=?", id); return saved;
        }
        if ("DELETE".equals(method) && seg.length > 2) {
            long id = Long.parseLong(seg[2]); JSONObject row = findAnnouncement(id); if (row == null) throw new Api.ApiError(404, "ANNOUNCEMENT_NOT_FOUND", "اطلاعیه پیدا نشد");
            exec("UPDATE local_announcements SET status='CANCELLED',updated_at=? WHERE id=?", Db.now(), id);
            JSONObject op = new JSONObject(); op.put("announcement_id", id); op.put("local_announcement_id", id); enqueue("ANNOUNCEMENT_CANCEL", op, "لغو اطلاعیه"); return new JSONObject().put("ok", true);
        }
        throw new Api.ApiError(404, "NOT_FOUND", "عملیات اطلاعیه پیدا نشد");
    }

    private static boolean visibleAnnouncement(JSONObject row) throws Exception {
        String status = row.optString("status", "PUBLISHED"); if (!("PUBLISHED".equals(status) || "SCHEDULED".equals(status))) return false;
        String kind = row.optString("target_kind", "ALL"); JSONObject user = Screens.user; if (user == null) user = new JSONObject(Prefs.get("user_json", "{}"));
        if ("STORE".equals(kind) && !row.optString("target_store", "").equals(user.optString("store", Prefs.get("store_name", "")))) return false;
        if ("ROLES".equals(kind)) {
            JSONArray wanted = jsonArray(row.optString("target_roles", "[]")), roles = user.optJSONArray("roles"); boolean match = false;
            for (int i = 0; roles != null && i < roles.length(); i++) if (containsString(wanted, roles.optString(i))) match = true;
            if (!match) return false;
        }
        if ("USERS".equals(kind)) {
            JSONArray wanted = jsonArray(row.optString("target_users", "[]")); long pcId = Db.pcUserIdForLocal(Db.localUserId());
            if (!containsLong(wanted, Db.localUserId()) && !containsLong(wanted, pcId)) return false;
        }
        return true;
    }

    private static Object payroll(String method, String[] seg, JSONObject q, JSONObject b) throws Exception {
        if (seg.length == 2 && "GET".equals(method)) {
            JSONArray out = new JSONArray(); String period = q.optString("period", "");
            String sql = "SELECT p.*,u.full_name,u.username FROM local_payroll p LEFT JOIN users u ON u.id=p.user_id" + (period.isEmpty() ? "" : " WHERE p.period=?") + " ORDER BY p.period DESC,p.id";
            for (JSONObject row : period.isEmpty() ? rows(sql) : rows(sql, period)) out.put(payrollOut(row)); return out;
        }
        if (seg.length == 2 && "POST".equals(method)) {
            long userId = localUser(b.optLong("user_id")); String period = b.optString("period", "").trim();
            if (period.length() != 7 || period.charAt(4) != '-') throw new Api.ApiError(400, "BAD_PERIOD", "دورهٔ پرداخت باید به شکل YYYY-MM باشد");
            if (one("SELECT id FROM local_payroll WHERE user_id=? AND period=?", userId, period) != null) throw new Api.ApiError(400, "DUPLICATE", "برای این کارمند و دوره قبلاً حقوق ثبت شده است");
            JSONObject values = new JSONObject(b.toString()); values.put("user_id", userId); values.put("period", period);
            long id = savePayroll(0, values, "DRAFT"); JSONObject op = new JSONObject(b.toString());
            long remoteUserId = Db.pcUserIdForLocal(userId);
            if (remoteUserId > 0) op.put("user_id", remoteUserId); else op.remove("user_id");
            op.put("period", period); op.put("local_payroll_id", id);
            enqueue("PAYROLL_CREATE", op, "ثبت حقوق " + period); return payrollOut(one("SELECT p.*,u.full_name,u.username FROM local_payroll p LEFT JOIN users u ON u.id=p.user_id WHERE p.id=?", id));
        }
        if (seg.length > 2) {
            long id = Long.parseLong(seg[2]); JSONObject row = one("SELECT * FROM local_payroll WHERE id=?", id);
            if (row == null) throw new Api.ApiError(404, "PAYROLL_NOT_FOUND", "ردیف حقوق پیدا نشد");
            String action = seg.length > 3 ? seg[3] : "";
            if ("PATCH".equals(method)) {
                if ("PAID".equals(row.optString("status")) || "PAYMENT_PENDING_SYNC".equals(row.optString("status"))) throw new Api.ApiError(400, "LOCKED", "ردیف پرداخت‌شده قابل ویرایش نیست");
                JSONObject merged = new JSONObject(row.toString()); for (String key : new String[]{"base_salary", "hourly_pay", "worked_hours", "overtime_hours", "bonus", "benefits", "deductions", "penalty", "note"}) if (b.has(key)) merged.put(key, b.opt(key));
                savePayroll(id, merged, row.optString("status")); JSONObject op = new JSONObject(b.toString()); op.put("payroll_id", Db.remotePayrollId(id)); op.put("local_payroll_id", id);
                enqueue("PAYROLL_UPDATE", op, "ویرایش حقوق " + row.optString("period")); return payrollOut(one("SELECT p.*,u.full_name,u.username FROM local_payroll p LEFT JOIN users u ON u.id=p.user_id WHERE p.id=?", id));
            }
            if ("POST".equals(method) && "approve".equals(action)) {
                if (!"DRAFT".equals(row.optString("status"))) throw new Api.ApiError(400, "BAD_STATUS", "فقط پیش‌نویس قابل تأیید است");
                exec("UPDATE local_payroll SET status='APPROVED',updated_at=? WHERE id=?", Db.now(), id);
                JSONObject op = new JSONObject(); op.put("payroll_id", Db.remotePayrollId(id)); op.put("local_payroll_id", id); enqueue("PAYROLL_APPROVE", op, "تأیید حقوق " + row.optString("period")); return new JSONObject().put("id", id).put("status", "APPROVED");
            }
            if ("POST".equals(method) && "pay".equals(action)) {
                if (!"APPROVED".equals(row.optString("status"))) throw new Api.ApiError(400, "BAD_STATUS", "پیش از پرداخت باید حقوق تأیید شود");
                exec("UPDATE local_payroll SET status='PAYMENT_PENDING_SYNC',updated_at=? WHERE id=?", Db.now(), id);
                JSONObject op = new JSONObject(); op.put("payroll_id", Db.remotePayrollId(id)); op.put("local_payroll_id", id); enqueue("PAYROLL_PAY", op, "پرداخت حقوق " + row.optString("period")); return new JSONObject().put("id", id).put("status", "PAYMENT_PENDING_SYNC");
            }
        }
        throw new Api.ApiError(404, "NOT_FOUND", "عملیات حقوق روی گوشی پیدا نشد");
    }

    private static JSONObject payrollOut(JSONObject row) throws Exception {
        JSONObject out = new JSONObject(); if (row == null) return out;
        for (String field : new String[]{"id", "user_id", "period", "base_salary", "hourly_pay", "worked_hours", "overtime_hours", "bonus", "benefits", "deductions", "penalty", "total", "status", "payment_ref", "note", "created_by", "full_name", "username"}) out.put(field, row.isNull(field) ? JSONObject.NULL : row.opt(field));
        out.put("pc_id", row.optLong("pc_id")); return out;
    }

    private static long savePayroll(long id, JSONObject b, String status) throws Exception {
        long useId = localUser(b.optLong("user_id")); String period = b.optString("period", "");
        double base = b.optDouble("base_salary"), hourly = b.optDouble("hourly_pay"), worked = b.optDouble("worked_hours"), overtime = b.optDouble("overtime_hours");
        double bonus = b.optDouble("bonus"), benefits = b.optDouble("benefits"), deductions = b.optDouble("deductions"), penalty = b.optDouble("penalty");
        for (double v : new double[]{base, hourly, worked, overtime, bonus, benefits, deductions, penalty}) if (v < 0) throw new Api.ApiError(400, "BAD_AMOUNT", "مبلغ و ساعت نمی‌توانند منفی باشند");
        double total = Math.max(0, Math.round(base + hourly * worked + overtime * hourly * 1.4 + bonus + benefits - deductions - penalty));
        if (id <= 0) {
            id = Db.nextLocalId("hr_payroll");
            exec("INSERT INTO local_payroll(id,pc_id,user_id,period,base_salary,hourly_pay,worked_hours,overtime_hours,bonus,benefits,deductions,penalty,total,status,payment_ref,note,created_by,updated_at,is_local) VALUES(?,0,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                    id, useId, period, base, hourly, worked, overtime, bonus, benefits, deductions, penalty, total, status, b.isNull("payment_ref") ? null : b.optString("payment_ref"), b.isNull("note") ? null : b.optString("note"), Db.localUserId(), Db.now());
        } else {
            exec("UPDATE local_payroll SET user_id=?,period=?,base_salary=?,hourly_pay=?,worked_hours=?,overtime_hours=?,bonus=?,benefits=?,deductions=?,penalty=?,total=?,status=?,payment_ref=?,note=?,created_by=?,updated_at=?,is_local=1 WHERE id=?",
                    useId, period, base, hourly, worked, overtime, bonus, benefits, deductions, penalty, total, status, b.isNull("payment_ref") ? null : b.optString("payment_ref"), b.isNull("note") ? null : b.optString("note"), Db.localUserId(), Db.now(), id);
        }
        return id;
    }

    private static Object performance(String method, String[] seg, JSONObject q) throws Exception {
        if (!"GET".equals(method)) throw new Api.ApiError(405, "METHOD", "روش مجاز نیست");
        String selector = seg.length > 2 ? seg[2] : "me";
        if ("team".equals(selector)) {
            JSONArray out = new JSONArray(); for (JSONObject u : rows("SELECT id,pc_id,username,full_name,job_title FROM users WHERE is_active=1 ORDER BY id")) out.put(performanceReport(u.optLong("id"), q)); return out;
        }
        long target = "me".equals(selector) ? Db.localUserId() : Long.parseLong(selector);
        if ("charts".equals(selector)) target = seg.length > 3 ? Long.parseLong(seg[3]) : Db.localUserId();
        target = localUser(target);
        if ("charts".equals(selector)) return chartSeries(target, q);
        if ("pdf".equals(selector)) throw new Api.ApiError(501, "PDF_OFFLINE", "ساخت PDF عملکرد هنگام اتصال به رایانه در دسترس است");
        return performanceReport(target, q);
    }

    private static JSONObject performanceReport(long userId, JSONObject q) throws Exception {
        String end = q.optString("end", today()), start = q.optString("start", addDays(end, -29)); validateDay(start); validateDay(end);
        long startMs = parseDay(start).getTime(), endMs = parseDay(addDays(end, 1)).getTime(); double total = 0, inShift = 0, outShift = 0; int count = 0; HashMap<String, Double> perDay = new HashMap<>();
        for (JSONObject invoice : rows("SELECT total,at FROM invoices WHERE user_id=? AND status='PAID' AND at>=? AND at<? ORDER BY at", userId, start, addDays(end, 1))) {
            double amount = invoice.optDouble("total"); String at = invoice.optString("at"), day = at.length() >= 10 ? at.substring(0, 10) : start;
            total += amount; count++; perDay.put(day, (perDay.containsKey(day) ? perDay.get(day) : 0) + amount);
            boolean inside = false; JSONArray windows = matchingShifts(userId, day);
            Date time = parseDateTime(at);
            for (int i = 0; i < windows.length(); i++) { JSONObject sh = windows.optJSONObject(i); Date from = at(day, sh.optString("start_time")), to = at(day, sh.optString("end_time")); if (!to.after(from)) to = new Date(to.getTime() + 86400000L); if (!time.before(from) && time.before(to)) inside = true; }
            if (inside) inShift += amount; else outShift += amount;
        }
        JSONObject user = one("SELECT full_name,username,job_title FROM users WHERE id=?", userId); String name = user == null ? "" : user.optString("full_name", user.optString("username"));
        JSONArray series = new JSONArray(); Date cursor = parseDay(start), last = parseDay(end); Calendar cal = Calendar.getInstance();
        while (!cursor.after(last)) { String day = formatDay(cursor); series.put(new JSONObject().put("day", day).put("sales", Math.round(perDay.containsKey(day) ? perDay.get(day) : 0))); cal.setTime(cursor); cal.add(Calendar.DAY_OF_MONTH, 1); cursor = cal.getTime(); }
        JSONObject rep = new JSONObject(); rep.put("user_id", userId); rep.put("full_name", name); rep.put("job_title", user == null ? "" : user.optString("job_title")); rep.put("from", start); rep.put("to", end);
        rep.put("sales_total", Math.round(total)); rep.put("invoice_count", count); rep.put("avg_invoice", count == 0 ? 0 : Math.round(total / count)); rep.put("customer_count", 0);
        rep.put("sales_in_shift", Math.round(inShift)); rep.put("sales_out_of_shift", Math.round(outShift)); rep.put("worked_days", countAttendanceDays(userId, start, end));
        rep.put("late_minutes_total", sumAttendanceField(userId, start, end, "late_minutes")); rep.put("early_leave_minutes_total", sumAttendanceField(userId, start, end, "early_leave_minutes"));
        rep.put("score_total", 0); rep.put("score_events", 0); rep.put("achievements", new JSONArray()); double goal = q.optDouble("goal", 0);
        rep.put("goal", goal); rep.put("goal_progress", goal == 0 ? JSONObject.NULL : Math.round(total * 1000 / goal) / 10.0); rep.put("daily_series", series); return rep;
    }

    private static JSONArray chartSeries(long userId, JSONObject q) throws Exception {
        JSONObject report = performanceReport(userId, q); JSONArray points = new JSONArray(), invoices = new JSONArray(); JSONArray daily = report.optJSONArray("daily_series");
        for (int i = 0; daily != null && i < daily.length(); i++) { JSONObject day = daily.optJSONObject(i); points.put(new JSONObject().put("x", day.optString("day")).put("y", day.optDouble("sales"))); invoices.put(new JSONObject().put("x", day.optString("day")).put("y", 0)); }
        JSONArray out = new JSONArray(); out.put(new JSONObject().put("id", "sales_daily").put("title", "فروش روزانه").put("type", "line").put("points", points));
        out.put(new JSONObject().put("id", "invoices_daily").put("title", "تعداد تراکنش").put("type", "bar").put("points", invoices)); return out;
    }

    private static int countAttendanceDays(long userId, String start, String end) throws Exception {
        JSONObject row = one("SELECT COUNT(DISTINCT day) n FROM local_attendance WHERE user_id=? AND day>=? AND day<=?", userId, start, end); return row == null ? 0 : row.optInt("n");
    }
    private static int sumAttendanceField(long userId, String start, String end, String field) throws Exception {
        JSONObject row = one("SELECT COALESCE(SUM(" + field + "),0) n FROM local_attendance WHERE user_id=? AND day>=? AND day<=?", userId, start, end); return row == null ? 0 : row.optInt("n");
    }

    private static void enqueue(String type, JSONObject payload, String label) { if (!Api.standalone()) Sync.queue(type, payload, label, null); }
    private static JSONObject findShift(long id) throws Exception {
        JSONObject row = one("SELECT * FROM local_shifts WHERE id=?", id); if (row != null) return row;
        long local = Db.localShiftIdForPc(id); return local > 0 ? one("SELECT * FROM local_shifts WHERE id=?", local) : null;
    }
    private static JSONObject findAnnouncement(long id) throws Exception {
        JSONObject row = one("SELECT * FROM local_announcements WHERE id=?", id); if (row != null) return row;
        return one("SELECT * FROM local_announcements WHERE pc_id=?", id);
    }
    private static long localUser(long id) throws Exception {
        JSONObject local = one("SELECT id FROM users WHERE id=?", id);
        if (local != null) return local.optLong("id");
        long mapped = Db.localUserIdForPc(id);
        return mapped > 0 ? mapped : id;
    }
    /** Convert the roster's phone-side user IDs before an HR operation crosses to the PC. */
    private static JSONArray remoteUsers(JSONArray localUsers) throws Exception {
        JSONArray out = new JSONArray();
        for (int i = 0; i < localUsers.length(); i++) {
            long id = localUsers.optLong(i), pcId = Db.pcUserIdForLocal(id);
            if (pcId > 0) out.put(pcId);
        }
        return out;
    }
    private static String userName(long id) throws Exception { JSONObject u = one("SELECT full_name,username FROM users WHERE id=?", id); return u == null ? "کارمند" : u.optString("full_name", u.optString("username")); }
    private static void validateTime(String value) throws Api.ApiError {
        if (value == null || !value.matches("(?:[01]?[0-9]|2[0-3]):[0-5][0-9]")) throw new Api.ApiError(400, "BAD_TIME", "زمان را با قالب HH:mm وارد کنید");
        String[] bits = value.split(":"); if (bits[0].length() == 1) throw new Api.ApiError(400, "BAD_TIME", "زمان را با قالب HH:mm وارد کنید");
    }
    private static void validateDay(String value) throws Exception { if (value == null || !value.matches("\\d{4}-\\d{2}-\\d{2}")) throw new Api.ApiError(400, "BAD_DAY", "تاریخ باید YYYY-MM-DD باشد"); parseDay(value); }
    private static int weekday(String day) throws Exception { Calendar c = Calendar.getInstance(); c.setTime(parseDay(day)); return (c.get(Calendar.DAY_OF_WEEK) + 5) % 7; }
    private static Date at(String day, String time) throws Exception { validateDay(day); validateTime(time); return parseDateTime(day + "T" + time + ":00"); }
    private static String today() { return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date()); }
    private static String formatDay(Date d) { return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(d); }
    private static String formatDateTime(Date d) { return new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(d); }
    private static Date parseDay(String s) throws Exception { SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd", Locale.US); f.setLenient(false); return f.parse(s); }
    private static Date parseDateTime(String s) throws Exception { SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US); f.setLenient(false); return f.parse(s.length() == 16 ? s + ":00" : s); }
    private static String addDays(String day, int amount) throws Exception { Calendar c = Calendar.getInstance(); c.setTime(parseDay(day)); c.add(Calendar.DAY_OF_MONTH, amount); return formatDay(c.getTime()); }
    private static JSONArray jsonArray(String raw) throws Exception { if (raw == null || raw.trim().isEmpty()) return new JSONArray(); if (raw.trim().startsWith("[")) return new JSONArray(raw); JSONArray out = new JSONArray(); for (String v : raw.split(",")) if (!v.trim().isEmpty()) out.put(Integer.parseInt(v.trim())); return out; }
    private static boolean contains(JSONArray a, int value) { for (int i = 0; i < a.length(); i++) if (a.optInt(i, -1) == value) return true; return false; }
    private static boolean containsString(JSONArray a, String value) { for (int i = 0; i < a.length(); i++) if (value.equals(a.optString(i))) return true; return false; }
    private static boolean containsLong(JSONArray a, long value) { for (int i = 0; i < a.length(); i++) if (a.optLong(i, Long.MIN_VALUE) == value) return true; return false; }
    private static String nullIfEmpty(String s) { return s == null || s.isEmpty() ? null : s; }

    private static List<JSONObject> rows(String sql, Object... values) throws Exception {
        List<JSONObject> out = new ArrayList<>();
        try (Cursor c = Db.db().rawQuery(sql, Local.args(values))) {
            String[] columns = c.getColumnNames();
            while (c.moveToNext()) {
                JSONObject row = new JSONObject();
                for (int i = 0; i < columns.length; i++) {
                    switch (c.getType(i)) {
                        case Cursor.FIELD_TYPE_NULL: row.put(columns[i], JSONObject.NULL); break;
                        case Cursor.FIELD_TYPE_INTEGER: row.put(columns[i], c.getLong(i)); break;
                        case Cursor.FIELD_TYPE_FLOAT: row.put(columns[i], c.getDouble(i)); break;
                        default: row.put(columns[i], c.getString(i));
                    }
                }
                out.add(row);
            }
        }
        return out;
    }
    private static JSONObject one(String sql, Object... values) throws Exception { List<JSONObject> result = rows(sql, values); return result.isEmpty() ? null : result.get(0); }
    private static void exec(String sql, Object... values) { Db.db().execSQL(sql, Local.args(values)); }
}
