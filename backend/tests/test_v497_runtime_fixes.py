# -*- coding: utf-8 -*-
"""build-497 — رفع خطاهای زمان اجرا پیدا‌شده در بررسی عمیق (دستورالعمل §۲/§۳).

هر مورد این‌جا یک باگ واقعی NameError بود که فقط در مسیر خطا فعال می‌شد:
۱. ``app/services/sms.py::_audit`` — اگر ثبت Audit می‌شکست، خودِ هندلر خطا با
   ``NameError: logging`` کرش می‌کرد (``logging`` هرگز import نشده بود) و به‌جای
   «بلعیدن بعد از لاگ»، ارسال پیام را پایین می‌کشید.
۲. ``app/services/hw/transports.py`` — کلاس ``DriverMissingError`` تعریف‌شده در
   ``hw/base.py`` هرگز import نشده بود؛ با پرینتر/اسکنر بدون درایور، به‌جای
   پیام صادقانهٔ «DRIVER_MISSING» دو لایه NameError می‌آمد.
"""
from __future__ import annotations

import importlib


def test_sms_audit_handler_never_raises_nameerror(db_session=None):
    """مسیر شکستِ Audit در سرویس پیامک باید لاگ شود، نه NameError بدهد."""
    from unittest.mock import patch

    from app.services import sms as sms_svc
    importlib.reload(sms_svc)  # اطمینان از ماژول اصلاح‌شده

    class _Msg:
        id = 1
        phone = "09120000000"
        status = "SENT"
        retry_count = 0

    with patch("app.services.audit.write_audit", side_effect=RuntimeError("boom")):
        # نباید هیچ استثنایی بیرون بزند — قاعدهٔ «ممیزی هرگز ارسال را خراب نمی‌کند»
        sms_svc._audit(None, "SMS_SENT", _Msg(), "file", error=None)  # type: ignore[arg-type]


def test_hw_serial_transport_reports_driver_missing_without_nameerror():
    """گزارش صادقانهٔ «درایور نیست» باید بدون NameError کار کند (§۸۳ صداقت سخت‌افزار)."""
    from app.services.hw.base import DriverMissingError
    from app.services.hw.transports import SerialTransport

    t = SerialTransport("COM3")
    ok, msg = t.write(b"x")
    assert ok is False
    assert msg.startswith("DRIVER_MISSING"), msg

    ok, line, status = t.read_line()
    assert ok is False and status.startswith("DRIVER_MISSING"), status

    # کلاس همان تعریف واحد base.py است (نه کپی جداگانه)
    from app.services.hw import transports
    assert transports.DriverMissingError is DriverMissingError
