from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SmsMessage, User
from ..security import get_current_user, require_permission
from ..services import sms as sms_svc
from ..services.audit import write_audit

router = APIRouter(prefix="/sms", tags=["sms"])


class SmsIn(BaseModel):
    phone: str
    text: str


@router.post("/send", status_code=201)
def send(body: SmsIn, db: Session = Depends(get_db),
         user: User = Depends(require_permission("pos.sell"))):
    """Queue an SMS job. Delivery happens out-of-band (never blocks POS, §68)."""
    if not body.phone.strip() or not body.text.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="phone and text are required")
    msg = SmsMessage(phone=body.phone.strip(), text=body.text.strip(), status="PENDING",
                     created_at=datetime.utcnow())
    db.add(msg)
    write_audit(db, action="SMS_QUEUED", user_id=user.id if user else None,
                entity_type="SmsMessage", entity_id=None,
                after={"phone": body.phone, "chars": len(body.text)})
    db.commit()
    return {"id": msg.id, "status": msg.status}


@router.post("/dispatch")
def dispatch(db: Session = Depends(get_db),
             _: User = Depends(require_permission("settings.manage"))):
    """Manually trigger one dispatch pass (also used by the worker + tests)."""
    return sms_svc.dispatch_pending(db)


@router.get("")
def list_sms(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    rows = db.execute(select(SmsMessage).order_by(SmsMessage.created_at.desc()).limit(100)).scalars().all()
    return [
        {"id": m.id, "phone": m.phone, "text": m.text, "status": m.status,
         "retry_count": m.retry_count, "error_message": m.error_message,
         "sent_at": m.sent_at.isoformat() if m.sent_at else None}
        for m in rows
    ]


@router.post("/{sms_id}/retry")
def retry(sms_id: int, db: Session = Depends(get_db),
          user: User = Depends(require_permission("settings.manage"))):
    """§171 — re-queue a FAILED message; the worker/dispatch delivers it."""
    from fastapi import HTTPException
    try:
        msg = sms_svc.retry_message(db, sms_id)
    except sms_svc.SmsProviderError as e:
        raise HTTPException(status_code=409 if e.kind == "ALREADY_SENT" else 404,
                            detail={"code": e.kind, "message": e.detail})
    write_audit(db, action="SMS_RETRY_REQUESTED", user_id=user.id, entity_type="SmsMessage",
                entity_id=msg.id)
    db.commit()
    return {"id": msg.id, "status": msg.status}


@router.post("/test-connection")
def test_connection(db: Session = Depends(get_db),
                    _: User = Depends(require_permission("settings.manage"))):
    """§177 — provider connectivity check (no customer SMS is sent)."""
    return sms_svc.test_connection(db)


@router.post("/daily-report", status_code=201)
def daily_report(db: Session = Depends(get_db),
                 user: User = Depends(require_permission("reports.view"))):
    """§175 — queue the management summary SMS to the admin phone."""
    from fastapi import HTTPException
    try:
        msg = sms_svc.queue_daily_report(db)
    except sms_svc.SmsProviderError as e:
        raise HTTPException(status_code=422, detail={"code": e.kind, "message": e.detail})
    write_audit(db, action="SMS_QUEUED", user_id=user.id, entity_type="SmsMessage", entity_id=msg.id,
                after={"kind": "daily_report"})
    db.commit()
    return {"id": msg.id, "status": msg.status, "text": msg.text}


@router.get("/guide")
def guide(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """v2.3 — step-by-step in-app guide for wiring the shop's SMS panel (Melipayamak
    first; Kavenegar second) + the current configuration state, so the phone and
    the PC show the SAME tutorial next to the SMS section and can tell the user
    exactly which step is still missing."""
    provider = sms_svc.get_setting(db, "sms.provider", "").strip()
    mode = (sms_svc.get_setting(db, "sms.melipayamak_mode", "line") or "line").strip()
    state = {
        "provider": provider,
        "mode": mode,
        "has_username": bool(sms_svc.get_setting(db, "sms.username", "")),
        "has_password": bool(sms_svc.get_setting(db, "sms.password", "")),
        "has_sender": bool(sms_svc.get_setting(db, "sms.sender", "")),
        "has_body_id": bool(sms_svc.get_setting(db, "sms.melipayamak_body_id", "")),
        "has_api_key": bool(sms_svc.get_setting(db, "sms.api_key", "")),
        "send_invoice": sms_svc.get_setting(db, "sms.send_invoice", "true").lower() != "false",
        "send_immediately": sms_svc.get_setting(db, "sms.send_immediately", "true").lower() != "false",
        "print_after_checkout": sms_svc.get_setting(db, "pos.print_after_checkout", "true").lower() != "false",
    }
    missing = []
    if not provider:
        missing.append("sms.provider")
    elif provider == "melipayamak":
        if not state["has_username"]:
            missing.append("sms.username")
        if not state["has_password"]:
            missing.append("sms.password")
        if mode == "pattern" and not state["has_body_id"]:
            missing.append("sms.melipayamak_body_id")
        if mode != "pattern" and not state["has_sender"]:
            missing.append("sms.sender")
    elif provider == "kavenegar":
        if not state["has_api_key"]:
            missing.append("sms.api_key")
    state["missing"] = missing
    state["ready"] = not missing
    steps = [
        {"n": 1, "title": "ثبت‌نام در ملی‌پیامک", "site": "https://www.melipayamak.com",
         "text": "در سایت ملی‌پیامک ثبت‌نام کنید (شمارهٔ موبایل + کد ملی؛ احراز هویت طبق قانون الزامی است). پس از ورود به «پنل کاربری» می‌روید."},
        {"n": 2, "title": "انتخاب نوع خط", "text": "دو راه دارید:\n• خط خدماتی اشتراکی + الگو (پیشنهاد ما): بدون خرید خط، پیامک‌ها به شماره‌های «مسدودِ تبلیغات» هم می‌رسد. در پنل: «ارسال الگو (پترن)» → «ایجاد الگوی جدید».\n• خط اختصاصی: از منوی «خطوط» یک خط بخرید؛ شمارهٔ خط را در «شمارهٔ خط ارسال» وارد کنید."},
        {"n": 3, "title": "ساخت الگو (فقط حالت الگو)", "text": "در «ایجاد الگو» متن را دقیقاً با متغیرهای ترتیبی بنویسید؛ مثال:\nفروشگاه {0} | فاکتور {1} | مبلغ {2} تومان\nاز خرید شما سپاسگزاریم\nپس از تأیید (چند ساعت تا یک روز کاری) یک «کد الگو / bodyId» می‌گیرید؛ همان را در «شناسهٔ الگو» وارد کنید. متن الگوی داخل برنامه باید همان تعداد خط/متغیر را داشته باشد."},
        {"n": 4, "title": "ساخت کاربر وب‌سرویس", "text": "در پنل: «تنظیمات» → «وب‌سرویس» → «ایجاد نام کاربری وب‌سرویس». نام کاربری و رمز وب‌سرویس (نه رمز ورود پنل) را در «نام کاربری پنل پیامک» و «رمز/کلید API» وارد کنید."},
        {"n": 5, "title": "شارژ اعتبار", "text": "از «افزایش اعتبار» حداقل مبلغی شارژ کنید؛ بدون اعتبار، ارسال با خطای «اعتبار کافی نیست» (کد ۲) برمی‌گردد."},
        {"n": 6, "title": "تنظیم در همین برنامه", "text": "سرویس پیامک = melipayamak · حالت = pattern یا line · مقادیر بالا را وارد و ذخیره کنید؛ سپس «تست اتصال سرویس پیامک» را بزنید (اعتبار پنل را نشان می‌دهد)."},
        {"n": 7, "title": "پیامک خودکار فاکتور", "text": "«ارسال پیامک فاکتور» روشن باشد. مستقل از پرینتر است: می‌توانید «چاپ خودکار رسید» را خاموش کنید و فقط پیامک برود. به محض تأیید فاکتور برای مشتریِ دارای شمارهٔ موبایل ارسال می‌شود (مشتری آزاد = بدون پیامک)."},
        {"n": 8, "title": "کاوه‌نگار (جایگزین)", "site": "https://panel.kavenegar.com", "text": "ثبت‌نام → «تنظیمات» → «API Key» را کپی کنید؛ در برنامه: سرویس = kavenegar و کلید API را وارد کنید."},
    ]
    return {"state": state, "steps": steps,
            "settings": ["sms.provider", "sms.melipayamak_mode", "sms.username", "sms.password", "sms.sender", "sms.melipayamak_body_id", "sms.api_key", "sms.send_invoice", "sms.send_immediately", "sms.admin_phone", "sms.low_stock_alert"]}


@router.get("/templates")
def templates(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    """§166 — the editable SMS patterns and their placeholders."""
    out = []
    for kind, (key, default) in sms_svc.TEMPLATE_KEYS.items():
        import re as _re
        out.append({"kind": kind, "key": key, "default": default,
                    "value": sms_svc.get_setting(db, key, default),
                    "placeholders": sorted(set(_re.findall(r"{(\w+)}", default)))})
    return out
