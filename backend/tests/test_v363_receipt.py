from decimal import Decimal as D
from types import SimpleNamespace as NS
from app.services import sms


def test_complete_receipt_keeps_all_lines_and_store_signature(monkeypatch):
    monkeypatch.setattr(sms, '_store_ctx', lambda db: {'store': 'فروشگاه بهار', 'currency': 'تومان'})
    items = [NS(id=i, product_id=i, product=NS(name=f'کالای کامل شماره {i}'),
                qty=D('1.5'), unit_sell_price=D('100'), discount=D('10'), tax=D('0'), subtotal=D('140'))
             for i in range(1, 41)]
    invoice = NS(invoice_number='INV-42', items=list(reversed(items)), subtotal=D('6000'),
                 discount=D('400'), tax=D('0'), total_amount=D('5600'))
    text = sms.render_invoice(None, invoice, '\nکد تخفیف: ABC')
    assert text.startswith('فروشگاه بهار\nفاکتور INV-42')
    assert text.endswith('فروشگاه بهار')
    assert text.count('× قیمت واحد') == 40
    assert text.index('1. کالای') < text.index('40. کالای')
    assert 'تعداد 1.5' in text and 'مبلغ نهایی: 5,600 تومان' in text
    assert 'کد تخفیف: ABC' in text
