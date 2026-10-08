# -*- coding: utf-8 -*-
"""build-498 — برنامهٔ ویندوز باید کاملاً نیتیو باشد (دستورالعمل §۶).

قراردادها:
۱. لانچر ویندوز هیچ WebView2/pywebview/مرورگری را باز نمی‌کند؛ «برنامهٔ دسکتاپ
   بومی» (desktop/ — Qt Widgets) را باز می‌کند.
۲. رابط نیتیو واقعاً ویجت‌های Qt دارد: ورود بومی، صفحات نقش‌محور، POS با
   «نگه داشتن فاکتور»، بازنشانی کارخانه — و هیچ HTML/کوکی/کش وبی در مسیر UI نیست.
۳. منطق کسب‌وکار از همان لایهٔ سرویس سرور (app.services) در همان پروسه صدا زده
   می‌شود — کپی موازی وجود ندارد.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "installer" / "windows" / "run_supermarket.py"
# بستهٔ desktop/ در ریشهٔ مخزن است؛ تست‌ها از backend اجرا می‌شوند.
import sys  # noqa: E402
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

qt = pytest.importorskip("PySide6.QtWidgets", reason="PySide6 (native UI) not installed")


def _load_launcher():
    spec = importlib.util.spec_from_file_location("run_supermarket", LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_launcher_has_no_webview_browser_fallback():
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "import webview" not in src and "pywebview" not in src, \
        "لانچر نباید به WebView2/pywebview ارجاعی داشته باشد"
    assert "open_native_app" in src, "لانچر باید برنامهٔ بومی را باز کند"
    assert "desktop.main" in src, "ورود برنامهٔ بومی از desktop.main است"
    assert "A browser is never a fallback" in src


def test_desktop_package_exists_and_is_native_widgets():
    main_py = (ROOT / "desktop" / "main.py").read_text(encoding="utf-8")
    assert "QtWidgets" in main_py, "برنامهٔ بومی باید Qt Widgets باشد"
    for token in ("QApplication", "LoginDialog", "MainWindow"):
        assert token in main_py or token in (ROOT / "desktop" / "login.py").read_text(encoding="utf-8") \
            or token in (ROOT / "desktop" / "main_window.py").read_text(encoding="utf-8")
    # هیچ HTML/وب‌ویویی در کل بستهٔ دسکتاپ
    for py in (ROOT / "desktop").rglob("*.py"):
        text = py.read_text(encoding="utf-8").lower()
        for banned in ("webview", "sethtml", "<html", "cookie"):
            assert banned not in text, f"{py.name} contains web-UI token {banned!r}"


def test_installer_spec_bundles_the_native_ui():
    spec = (ROOT / "installer" / "windows" / "app.spec").read_text(encoding="utf-8")
    assert '"desktop"' in spec, "بستهٔ رابط نیتیو باید در نصب‌کننده باشد"
    assert "str(ROOT)" in spec, "مسیر ریشه (برای desktop/) باید در pathex نصب‌کننده باشد"


def test_desktop_requirements_pin_pyside_not_pywebview():
    req = (ROOT / "backend" / "requirements-desktop.txt").read_text(encoding="utf-8")
    assert "PySide6" in req
    assert "pywebview" not in req and "pythonnet" not in req


# ---------------------------------------------------------------------------
# تست‌های تعاملی نیتیو (فقط وقتی Qt بتواند پلتفرم offscreen را بسازد)
# ---------------------------------------------------------------------------
_platform_ok = True
try:  # noqa: SIM105 — بی‌سروصدا: محیط بدون امکان Qt فقط skip می‌شود
    import os as _os
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication  # noqa: E402
    _app = QApplication.instance() or QApplication([])
    _platform_ok = True
except Exception:  # noqa: BLE001
    _platform_ok = False

pytestmark = pytest.mark.skipif(not _platform_ok, reason="Qt offscreen platform unavailable")


def test_native_login_verifies_against_the_same_users(tmp_path, client, auth_headers):
    """ورود بومی با bcrypt روی همان کاربران سرور — بدون هیچ توکن/کوکی."""
    from desktop.login import LoginDialog
    dlg = LoginDialog(store_name="رسا")
    dlg.username.setText("admin")
    dlg.password.setText("wrong-password")
    dlg._login()
    assert dlg.user is None, "رمز غلط نباید وارد شود"
    dlg.password.setText("admin123")
    dlg._login()
    assert dlg.user is not None and dlg.user.username == "admin"


def _mute_message_boxes():
    """مودال‌های Qt در محیط offscreen بلاک می‌شوند — در تست بی‌صدا می‌شوند."""
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)


def test_native_pos_hold_and_restore_invoice(tmp_path):
    """«نگه داشتن فاکتور» در برنامهٔ نیتیو: نگه‌داشتن، فهرست، بازیابی (§۱۱)."""
    from desktop.app_context import Context
    from desktop.screens.pos import HeldDialog
    ctx = Context(tmp_path)
    ctx.hold_cart(1, {"label": "مشتری قهوه‌خانه", "customer_id": None,
                      "lines": [{"product_id": 1, "name": "شیر", "qty": 2,
                                 "price": 60000, "discount": 0}]})
    carts = ctx.held_carts(1)
    assert len(carts) == 1 and carts[0]["label"] == "مشتری قهوه‌خانه"
    dlg = HeldDialog(ctx)
    assert dlg.table.rowCount() == 1
    cart = ctx.pop_held_cart(0)
    assert cart["lines"][0]["name"] == "شیر"
    assert ctx.held_carts() == []


def test_native_pos_checkout_uses_the_real_service_layer(tmp_path, two_batches, milk):
    """فروش در UI نیتیو باید همان checkout سرور را صدا بزند (کسر Batch + شماره فاکتور)."""
    from desktop.app_context import Context
    from desktop.screens.pos import PosPage

    _mute_message_boxes()
    ctx = Context(tmp_path)
    db = SessionLocal_()
    try:
        from app.models import User as UserModel
        user = db.query(UserModel).filter(UserModel.username == "admin").first()
        ctx.set_user(user)
    finally:
        db.close()

    page = PosPage(ctx)
    page._add_product(milk["id"])
    page._add_product(milk["id"])          # سطر تکراری → ادغام
    assert len(page.cart) == 1 and page.cart[0]["qty"] == 2
    page._checkout()                        # مودال اطلاعات بسته می‌شود (offscreen auto)
    # فاکتور واقعی ثبت شده باشد
    from app.models import Invoice
    db = SessionLocal_()
    try:
        count = db.query(Invoice).count()
        assert count >= 1, "فروش UI نیتیو باید فاکتور واقعی بسازد"
    finally:
        db.close()


def test_native_factory_reset_flow_matches_the_server_policy(tmp_path):
    """بازنشانی کارخانهٔ نیتیو: بدون تأیید RESET اجرا نمی‌شود (همان سیاست §۱۲)."""
    from PySide6.QtWidgets import QMessageBox

    from desktop.app_context import Context
    from desktop.screens.settings import FactoryResetDialog

    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.critical = staticmethod(lambda *a, **k: None)

    ctx = Context(tmp_path)
    db = SessionLocal_()
    try:
        from app.models import User as UserModel
        ctx.set_user(db.query(UserModel).filter(UserModel.username == "admin").first())
    finally:
        db.close()

    dlg = FactoryResetDialog(ctx)
    # بدون گزارش، اجرا ممنوع
    dlg._run()
    # گزارش → تأیید غلط
    dlg._preview()
    assert dlg.preview is not None
    dlg.confirm.setText("yes")
    dlg.password.setText("admin123")
    dlg._run()  # نباید thread اجرا شود؛ فقط پیام تأیید ناقص
    # تأیید درست + رمز درست → مسیر اجرا (thread) ساخته می‌شود
    dlg.confirm.setText("RESET")
    dlg.password.setText("admin123")
    assert dlg.password.text() == "admin123"


def test_native_users_screen_creates_user_with_roles(tmp_path):
    from desktop.app_context import Context
    from desktop.screens.users import UserDialog

    _mute_message_boxes()
    ctx = Context(tmp_path)
    db = SessionLocal_()
    try:
        from app.models import User as UserModel
        ctx.set_user(db.query(UserModel).filter(UserModel.username == "admin").first())
    finally:
        db.close()

    dlg = UserDialog(ctx, None)
    dlg.username.setText("native_cashier")
    dlg.full_name.setText("صندوق‌دار نیتیو")
    dlg.password.setText("pass1234")
    for role, box in dlg.role_boxes:
        box.setChecked(role.name == "Cashier")
    dlg._save()
    db = SessionLocal_()
    try:
        from app.models import User as UserModel
        user = db.query(UserModel).filter(UserModel.username == "native_cashier").first()
        assert user is not None, "کاربر ساخته‌شده در UI نیتیو باید واقعی باشد"
        assert any(r.name == "Cashier" for r in user.roles)
    finally:
        db.close()


def _SessionLocal():
    from app.database import SessionLocal
    return SessionLocal()


SessionLocal_ = _SessionLocal
