"""پیامک فاکتور — قرارداد v3.6.3 که در v4.8.0 با همان تضمین‌ها بازنویسی شد.

قرارداد اصلی دست‌نخورده است: **هیچ خط خریداری‌شده‌ای هرگز پنهان نمی‌شود**،
ردیف‌ها به ترتیب فاکتور می‌آیند، امضای فروشگاه در ابتدا و انتها هست و کد
تخفیف خرید بعدی در پیام می‌ماند. آن‌چه تغییر کرده فقط **چیدمان** است:
مالک گفت «متن‌ها به‌هم‌ریخته نباشد»؛ از v4.8.0 هر کالا یک ردیف فشرده دارد
(قبلاً سه خط برای هر کالا بود) و ردیف‌های جمع در انتها با ترتیب ثابت می‌آیند.
"""
from decimal import Decimal as D
from types import SimpleNamespace as NS

from app.services import sms


def _inv(items, **kw):
    return NS(invoice_number="INV-42", items=items, subtotal=kw.get("subtotal", D("6000")),
              discount=kw.get("discount", D("400")), tax=kw.get("tax", D("0")),
              total_amount=kw.get("total", D("5600")))


def test_complete_receipt_keeps_all_lines_and_store_signature(monkeypatch):
    monkeypatch.setattr(sms, "_store_ctx", lambda db: {'store': 'فروشگاه بهار', 'currency': 'تومان'})
    items = [NS(id=i, product_id=i, product=NS(name=f'کالای کامل شماره {i}'),
                qty=D('1.5'), unit_sell_price=D('100'), discount=D('10'), tax=D('0'), subtotal=D('140'))
             for i in range(1, 41)]
    text = sms.render_invoice(None, _inv(list(reversed(items))), '\nکد تخفیف: ABC')

    # ۱) همهٔ ۴۰ خط حاضرند و به ترتیب فاکتور (id) آمده‌اند — نه خطی گم شده، نه برعکس.
    assert text.count('کالای کامل شماره') == 40
    assert text.index('کالای کامل شماره 1') < text.index('کالای کامل شماره 40')
    # ۲) امضا و اجزای فاکتور سر جایشان‌اند.
    assert text.startswith('فروشگاه بهار | فاکتور INV-42')
    assert text.rstrip().endswith('فروشگاه بهار')
    assert 'کد تخفیف: ABC' in text
    assert 'پرداختی: ۵,۶۰۰ تومان' in text
    assert 'جمع کالاها: ۶,۰۰۰' in text and 'تخفیف: ۴۰۰' in text
    # ۳) هر کالا یک ردیف است (چیدمان مرتب درخواستی مالک) و همه چیز یک‌خطی است.
    assert text.count('= ۱۴۰') == 40
    assert '× قیمت واحد' not in text and 'تعداد ' not in text


def test_item_cap_is_opt_in_and_never_silently_drops(monkeypatch):
    """اگر فروشگاه خودش سقف بگذارد، اقلام حذف نمی‌شوند؛ صریحاً خلاصه می‌شوند."""
    monkeypatch.setattr(sms, "_store_ctx", lambda db: {'store': 'فروشگاه', 'currency': 'تومان'})
    monkeypatch.setattr(sms, "get_setting", lambda db, key, default="": "2" if key == "sms.invoice_max_items" else default)
    items = [NS(id=i, product_id=i, product=NS(name=f'کالا {i}'), qty=D('1'), unit_sell_price=D('100'),
                discount=D('0'), tax=D('0'), subtotal=D('100')) for i in range(1, 6)]
    text = sms.render_invoice(None, _inv(items, subtotal=D('500'), total=D('500'), discount=D('0')))
    assert 'کالا 1' in text and 'کالا 2' in text
    assert 'و ۳ قلم دیگر' in text          # نه حذف بی‌صدا، نه سکوت


def test_header_carries_jalali_date(monkeypatch):
    """تاریخ سربرگ شمسی است (پیامک برای مشتری ایرانی خوانا باشد)."""
    import datetime as _dt
    monkeypatch.setattr(sms, "_store_ctx", lambda db: {'store': 'فروشگاه', 'currency': 'تومان'})
    monkeypatch.setattr(sms, "_lt_today", lambda: _dt.date(2026, 9, 27))
    items = [NS(id=1, product_id=1, product=NS(name='ماست'), qty=D('1'), unit_sell_price=D('50000'),
                discount=D('0'), tax=D('0'), subtotal=D('50000'))]
    text = sms.render_invoice(None, _inv(items, subtotal=D('50000'), total=D('50000'), discount=D('0')))
    assert '۱۴۰۵/۰۷/۰۵' in text            # 2026-09-27 → 1405/07/05


def test_template_with_items_placeholder_is_honoured(monkeypatch):
    """قالب سفارشی فروشگاه با {items} ردیف‌های مرتب را می‌گیرد، بدون حذف چیزی."""
    monkeypatch.setattr(sms, "_store_ctx", lambda db: {'store': 'فروشگاه بهار', 'currency': 'تومان'})
    monkeypatch.setattr(sms, "get_setting",
                        lambda db, key, default="": ("فاکتور {invoice}\\n{items}\\nممنون" if key == "sms.template.invoice" else default))
    items = [NS(id=1, product_id=1, product=NS(name='نان'), qty=D('2'), unit_sell_price=D('10000'),
                discount=D('0'), tax=D('0'), subtotal=D('20000'))]
    text = sms.render_invoice(None, _inv(items, subtotal=D('20000'), total=D('20000'), discount=D('0')))
    assert text.startswith('فاکتور INV-42')
    assert 'نان' in text and 'ممنون' in text

def test_pattern_mode_gets_the_short_invoice_not_the_multi_line_receipt(monkeypatch):
    """حالت الگوی ملی‌پیامک تعداد متغیر ثابت دارد؛ رسید چندخطی باید کنار گذاشته شود.

    وگرنه سرویس پیامک، پیامک فاکتور را رد می‌کند و مشتری هیچ رسیدی نمی‌گیرد —
    دقیقاً همان چیزی که مالک دربارهٔ «مرتب بودن پیامک» نگرانش بود.
    """
    settings = {"sms.provider": "melipayamak", "sms.melipayamak_mode": "pattern"}
    monkeypatch.setattr(sms, "_store_ctx", lambda db: {'store': 'فروشگاه بهار', 'currency': 'تومان'})
    monkeypatch.setattr(sms, "get_setting", lambda db, key, default="": settings.get(key, default))
    items = [NS(id=1, product_id=1, product=NS(name='ماست'), qty=D('1'), unit_sell_price=D('50000'),
                discount=D('0'), tax=D('0'), subtotal=D('50000')),
             NS(id=2, product_id=2, product=NS(name='پنیر'), qty=D('1'), unit_sell_price=D('10000'),
                discount=D('0'), tax=D('0'), subtotal=D('10000'))]
    inv = _inv(items, subtotal=D('60000'), discount=D('0'), total=D('60000'))

    long_text = sms.render_invoice(None, inv)
    short_text = sms.render_invoice_for_mode(None, inv)

    assert len(long_text.splitlines()) > 3, "رسید عادی باید ردیف‌های کالا را داشته باشد"
    assert short_text.count("\n") <= 1, short_text
    assert "فاکتور" in short_text and "فروشگاه بهار" in short_text
    assert "۶۰,۰۰۰" in short_text, short_text
