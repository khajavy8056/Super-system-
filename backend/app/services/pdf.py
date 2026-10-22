# -*- coding: utf-8 -*-
"""build-488 — گزارش PDF حرفه‌ای (§۲۳).

خروجی: PDF خوانا و مناسب چاپ با فونت وزیرمتن (OFL، همان فونت محصول) شامل
عنوان، اطلاعات گزارش، تاریخ و بازه، جدول‌ها، نمودارها (ستونی/خطی با دادهٔ واقعی)
و خلاصهٔ آماری. وابستگی‌ها از قبل در requirements-dev ثبت شده‌اند:
reportlab + arabic-reshaper + python-bidi.

فونت: `Vazirmatn-Regular.ttf` — در `app/assets/fonts` (بستهٔ نصبی) و در صورت
نبود، منبع اندروید مخزن. اگر فونت یافت نشد PDF ساخته می‌شود اما متن فارسی
جایگزین نمی‌شود — سرویس وضعیت را در `font_status` گزارش می‌دهد (هیچ عددی
ساختگی نیست، §۵۲).
"""
from __future__ import annotations

import io
import os
from datetime import datetime

_FONT_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", "Vazirmatn-Regular.ttf"),
    os.path.join(os.path.dirname(__file__), "..", "..", "mobile-android", "app", "src", "main",
                 "assets", "fonts", "Vazirmatn-Regular.ttf"),
]

PAGE_W, PAGE_H = 595.27, 841.89  # A4
MARGIN = 40


def _find_font() -> str | None:
    env = os.environ.get("RASA_PDF_FONT")
    if env and os.path.isfile(env):
        return env
    for c in _FONT_CANDIDATES:
        p = os.path.abspath(c)
        if os.path.isfile(p):
            return p
    return None


def _shape(text: str) -> str:
    """شکل‌دهی متن فارسی/عربی + راست‌به‌چپ (در صورت وجود کتابخانه‌ها)."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(str(text)))
    except Exception:
        return str(text)


class PdfFont:
    def __init__(self) -> None:
        self.path = _find_font()
        self.status = "ok" if self.path else "font_missing"
        self.name = "Vazirmatn"
        if self.path:
            try:
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont
                pdfmetrics.registerFont(TTFont(self.name, self.path))
            except Exception:
                self.status = "font_invalid"
                self.path = None
        if not self.path:
            self.name = "Helvetica"

    @property
    def font_status(self) -> str:
        return self.status


def _fmt_money(n) -> str:
    try:
        return f"{int(round(float(n))):,}"
    except Exception:
        return str(n)


def report_pdf(*, title: str, subtitle: str = "", period: str = "",
               tables: list[dict] | None = None,
               charts: list[dict] | None = None,
               summary: list[list[str]] | None = None,
               generated_by: str = "") -> tuple[bytes, str]:
    """ساخت PDF گزارش → (bytes, font_status). جداول: {title, columns:[], rows:[[]]}.
    نمودارها: {title, type: bar|line, points:[{x,y}]} — از دادهٔ واقعی (§۵۲)."""
    from reportlab.lib.colors import Color, HexColor
    from reportlab.pdfgen import canvas as pdfcanvas

    font = PdfFont()
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    ink = HexColor("#1a2233")
    soft = HexColor("#eef1f6")
    accent = HexColor("#2f6fed")
    muted = HexColor("#5b6472")

    def rtl(text: str, x: float, y: float, size: float = 10, color=ink, right_edge: float = PAGE_W - MARGIN):
        """متن فارسی راست‌چین — موقعیت x لبهٔ راست است."""
        c.setFillColor(color)
        c.setFont(font.name, size)
        t = _shape(text)
        c.drawRightString(right_edge, y, t)

    def page_header(page_no: int):
        c.setFillColor(accent)
        c.rect(0, PAGE_H - 24, PAGE_W, 24, stroke=0, fill=1)
        c.setFillColor(Color(1, 1, 1))
        c.setFont(font.name, 9)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 16, _shape(title))
        c.setFillColor(muted)
        c.setFont(font.name, 8)
        c.drawString(MARGIN, 18, f"Rasa System · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        c.drawRightString(PAGE_W - MARGIN, 18, _shape(f"صفحهٔ {page_no}"))

    y = PAGE_H - 60
    page = 1
    page_header(page)

    # سربرگ گزارش
    rtl(title, PAGE_W - MARGIN, y, size=17, color=ink)
    y -= 22
    if subtitle:
        rtl(subtitle, PAGE_W - MARGIN, y, size=11, color=muted)
        y -= 18
    if period:
        rtl(f"بازهٔ گزارش: {period}", PAGE_W - MARGIN, y, size=10, color=muted)
        y -= 14
    if generated_by:
        rtl(f"تنظیم‌کننده: {generated_by}", PAGE_W - MARGIN, y, size=10, color=muted)
        y -= 14
    y -= 8

    def new_page_if_needed(need: float):
        nonlocal y, page
        if y - need < 56:
            c.showPage()
            page += 1
            page_header(page)
            y = PAGE_H - 56

    # خلاصهٔ آماری
    if summary:
        new_page_if_needed(24 + 16 * len(summary))
        rtl("خلاصهٔ آماری", PAGE_W - MARGIN, y, size=12, color=accent)
        y -= 18
        for label, value in summary:
            rtl(f"{label}:  {value}", PAGE_W - MARGIN, y, size=10)
            y -= 15
        y -= 8

    # جدول‌ها
    for tbl in (tables or []):
        cols = tbl.get("columns") or []
        rows = tbl.get("rows") or []
        col_w = (PAGE_W - 2 * MARGIN) / max(1, len(cols))
        new_page_if_needed(24 + 18 + 16 * min(len(rows), 20))
        rtl(tbl.get("title") or "", PAGE_W - MARGIN, y, size=12, color=accent)
        y -= 16
        # سرستون
        c.setFillColor(soft)
        c.rect(MARGIN, y - 5, PAGE_W - 2 * MARGIN, 16, stroke=0, fill=1)
        for i, col in enumerate(cols):
            x_right = PAGE_W - MARGIN - i * col_w
            rtl(str(col), 0, y, size=9, right_edge=x_right - 4)
        y -= 18
        for r_i, row in enumerate(rows):
            new_page_if_needed(16)
            if r_i % 2 == 1:
                c.setFillColor(HexColor("#f7f9fc"))
                c.rect(MARGIN, y - 5, PAGE_W - 2 * MARGIN, 15, stroke=0, fill=1)
            for i, cell in enumerate(row[:len(cols)]):
                x_right = PAGE_W - MARGIN - i * col_w
                rtl(str(cell), 0, y, size=9, right_edge=x_right - 4)
            y -= 16
        y -= 10

    # نمودارها
    for ch in (charts or []):
        pts = (ch.get("points") or [])[:31]
        if not pts:
            continue
        new_page_if_needed(150)
        rtl(ch.get("title") or "", PAGE_W - MARGIN, y, size=12, color=accent)
        y -= 8
        chart_h = 110
        base_y = y - chart_h
        values = [float(p.get("y") or 0) for p in pts]
        vmax = max(values) or 1
        n = len(pts)
        step = (PAGE_W - 2 * MARGIN) / max(1, n)
        if ch.get("type") == "line":
            c.setStrokeColor(accent)
            c.setLineWidth(1.4)
            for i in range(n - 1):
                x1 = MARGIN + i * step + step / 2
                x2 = MARGIN + (i + 1) * step + step / 2
                y1 = base_y + (values[i] / vmax) * (chart_h - 12)
                y2 = base_y + (values[i + 1] / vmax) * (chart_h - 12)
                c.line(x1, y1, x2, y2)
        else:
            for i, v in enumerate(values):
                bw = step * 0.62
                bx = MARGIN + i * step + (step - bw) / 2
                bh = (v / vmax) * (chart_h - 12)
                c.setFillColor(accent)
                c.rect(bx, base_y, bw, max(1, bh), stroke=0, fill=1)
        # خط پایه + برچسب بازه
        c.setStrokeColor(muted)
        c.setLineWidth(0.5)
        c.line(MARGIN, base_y, PAGE_W - MARGIN, base_y)
        c.setFillColor(muted)
        c.setFont(font.name, 7)
        for i in range(0, n, max(1, n // 8)):
            c.drawCentredString(MARGIN + i * step + step / 2, base_y - 10, _shape(str(pts[i].get("x") or "")))
        rtl(f"بیشینه: {_fmt_money(vmax)}", PAGE_W - MARGIN, base_y - 10, size=8, color=muted)
        y = base_y - 24

    if font.status != "ok":
        rtl("توجه: فونت فارسی یافت نشد؛ متن‌ها ممکن است ناخوانا باشند (font_status="
            + font.status + ")", PAGE_W - MARGIN, y, size=8, color=HexColor("#b00020"))

    c.showPage()
    c.save()
    return buf.getvalue(), font.status
