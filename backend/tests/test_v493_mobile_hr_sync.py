from __future__ import annotations

from datetime import date, datetime

from app.services.timeservice import local_now


def _sync(client, headers, push, pull=True):
    return client.post("/api/mobile/sync", headers=headers, json={
        "device_id": "hr-offline-phone", "cursor": None,
        "push": push, "pull": pull, "limit": 2000,
    })


def test_mobile_hr_push_pull_and_idempotency(client, auth_headers):
    me = client.get("/api/auth/me", headers=auth_headers).json()
    user_id = me["id"]
    day = local_now().date().isoformat()

    create = {
        "id": "hr-shift-create-493",
        "type": "SHIFT_CREATE",
        "payload": {
            "name": "آفلاین صبح",
            "start_time": "08:00",
            "end_time": "16:00",
            "workdays": [0, 1, 2, 3, 4, 5, 6],
            "store": "مرکزی",
            "department": "فروش",
        },
    }
    first = _sync(client, auth_headers, [create])
    assert first.status_code == 200, first.text
    first_json = first.json()
    assert first_json["applied"][0]["status"] == "APPLIED"
    shift_id = first_json["applied"][0]["result"]["shift_id"]
    assert shift_id > 0
    assert any(row["id"] == shift_id for row in first_json["pull"]["shifts"])
    assert any(row["id"] == user_id for row in first_json["pull"]["roster_users"])

    ops = [
        {
            "id": "hr-shift-assign-493",
            "type": "SHIFT_ASSIGN",
            "payload": {"shift_id": shift_id, "user_id": user_id, "day": day},
        },
        {
            "id": "hr-attendance-in-493",
            "type": "ATTENDANCE_CLOCK_IN",
            "payload": {
                "shift_id": shift_id,
                "day": day,
                "started_at": datetime.now().replace(microsecond=0).isoformat(),
            },
        },
        {
            "id": "hr-announcement-493",
            "type": "ANNOUNCEMENT_CREATE",
            "payload": {
                "title": "آزمون همگام‌سازی منابع انسانی",
                "body": "پیام نمونه",
                "priority": 2,
                "target_kind": "ALL",
                "status": "PUBLISHED",
            },
        },
        {
            "id": "hr-payroll-493",
            "type": "PAYROLL_CREATE",
            "payload": {
                "user_id": user_id,
                "period": "1405-07",
                "base_salary": 1000000,
                "hourly_pay": 10000,
                "worked_hours": 8,
                "overtime_hours": 1,
                "bonus": 50000,
                "benefits": 0,
                "deductions": 0,
                "penalty": 0,
                "note": "offline replay",
            },
        },
    ]
    second = _sync(client, auth_headers, ops)
    assert second.status_code == 200, second.text
    result = second.json()
    assert [row["status"] for row in result["applied"]] == ["APPLIED"] * len(ops)
    pull = result["pull"]
    assert any(row["user_id"] == user_id and row["shift_id"] == shift_id for row in pull["shift_assignments"])
    assert any(row["user_id"] == user_id and row["day"] == day for row in pull["attendance"])
    assert any(row["period"] == "1405-07" and row["user_id"] == user_id for row in pull["payroll"])
    assert any(row["title"] == "آزمون همگام‌سازی منابع انسانی" for row in pull["announcements"])
    assert result["current_user"]["pc_id"] == user_id

    replay = _sync(client, auth_headers, ops, pull=False)
    assert replay.status_code == 200, replay.text
    assert [row["status"] for row in replay.json()["applied"]] == ["DUPLICATE"] * len(ops)
    payroll = client.get("/api/hr/payroll", headers=auth_headers).json()
    assert sum(1 for row in payroll if row["period"] == "1405-07" and row["user_id"] == user_id) == 1


def test_hr_roster_is_minimal_and_permission_guarded(client, auth_headers):
    users = client.get("/api/hr/roster-users", headers=auth_headers)
    assert users.status_code == 200, users.text
    assert users.json()
    assert set(users.json()[0]).issuperset({"id", "full_name", "job_title"})
    assert "password" not in users.json()[0]
