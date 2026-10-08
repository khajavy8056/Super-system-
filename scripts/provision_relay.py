#!/usr/bin/env python3
"""تأمین کانال پشتیبانی برای یک نصب (بدون قرار دادن رمز در کد یا مخزن).

از v1.0.0 توکن رلهٔ پشتیبانی در `config.py` نیست؛ هر نصب مقدار خودش را در
`system_settings` نگه می‌دارد (اولویت بر متغیر محیطی). این اسکریپت همان مقدار را
روی یک پایگاه‌دادهٔ نصب می‌نویسد تا نصب‌های فروشگاه‌ها بدون دست‌زدن به سورس تأمین شوند:

    RASA_RELAY_TOKEN=... python scripts/provision_relay.py --db backend/data/supermarket.db
    python scripts/provision_relay.py --db ... --token ... --url https://... --inbox ...

توکن به‌صورت secret ذخیره می‌شود: از API بیرون «•••» برمی‌گردد و در لاگ/لاگ حسابرسی
مقدارش ثبت نمی‌شود. اگر مقداری داده نشود، اسکریپت فقط وضعیت فعلی را گزارش می‌کند.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

KEYS = {
    "support.relay_url": ("url", "نشانی رلهٔ پشتیبانی"),
    "support.relay_token": ("token", "توکن کانال پشتیبانی (محرمانه)"),
    "support.inbox_id": ("inbox", "شناسهٔ صندوق ورودی پشتیبانی"),
}


def mask(v: str) -> str:
    if not v:
        return "—"
    return f"{v[:6]}…{v[-4:]} ({len(v)} کاراکتر)" if len(v) > 12 else "•••"


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision the support relay for one installation")
    ap.add_argument("--db", default="backend/data/supermarket.db", help="مسیر پایگاه‌دادهٔ نصب")
    ap.add_argument("--token", default=os.environ.get("RASA_RELAY_TOKEN", ""))
    ap.add_argument("--url", default=os.environ.get("RASA_RELAY_URL", ""))
    ap.add_argument("--inbox", default=os.environ.get("RASA_RELAY_INBOX", ""))
    ap.add_argument("--remove", action="store_true", help="حذف مقادیر ذخیره‌شده (بازگشت به متغیر محیطی)")
    a = ap.parse_args()

    path = Path(a.db)
    if not path.exists():
        print(f"❌ پایگاه‌داده پیدا نشد: {path}", file=sys.stderr)
        return 2
    values = {"support.relay_url": a.url, "support.relay_token": a.token, "support.inbox_id": a.inbox}
    conn = sqlite3.connect(str(path))
    try:
        if not conn.execute("select name from sqlite_master where type='table' and name='system_settings'").fetchone():
            print("❌ این فایل جدول system_settings ندارد — یک پایگاه‌دادهٔ RASA نیست.", file=sys.stderr)
            return 2
        for key, (_, desc) in KEYS.items():
            row = conn.execute("select value from system_settings where key=?", (key,)).fetchone()
            cur = row[0] if row else ""
            if a.remove:
                conn.execute("delete from system_settings where key=?", (key,))
                print(f"🗑 {key}: حذف شد" + (f" (بود: {mask(cur)})" if cur else ""))
                continue
            new = values[key]
            if not new:
                print(f"   {key}: {mask(cur) if cur else 'خالی'}")
                continue
            secret = 1 if key.endswith("token") else 0
            conn.execute(
                "insert into system_settings(key, value, description, is_secret, created_at, updated_at) "
                "values(?,?,?,?,datetime('now'),datetime('now')) "
                "on conflict(key) do update set value=excluded.value, is_secret=excluded.is_secret, updated_at=datetime('now')",
                (key, new, desc, secret))
            print(f"✅ {key}: {mask(new)}")
        conn.commit()
    finally:
        conn.close()
    print("\nیادآوری: توکنی که یک بار در مخزن عمومی بوده، سوخته است — آن را در ربات باطل و دوباره بسازید.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
