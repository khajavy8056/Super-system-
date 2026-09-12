#!/usr/bin/env python3
"""Render docs/marketing/SALES_PLAYBOOK.html → docs/marketing/SALES_PLAYBOOK.pdf without a browser.

Pure Python (reportlab + arabic_reshaper + python-bidi): each paragraph is shaped, wrapped
by measured glyph widths and drawn right-to-left with the bundled Vazirmatn font — so the
PDF builds on any CI runner (no Chromium/Qt). The HTML is the single source of truth; the
subset used there (h1/h2/h3, p, ul/ol, table, div.say/.tip/.warn/.kpi, cover) is parsed here.

    ../.venv/bin/python scripts/make_playbook_pdf.py
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from fontTools.ttLib import TTFont as FTFont
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "marketing" / "SALES_PLAYBOOK.html"
OUT = ROOT / "docs" / "marketing" / "SALES_PLAYBOOK.pdf"
W, H = A4
M_L, M_R, M_T, M_B = 46, 46, 54, 56
INK, GOLD, EMERALD, NAVY, MUTED = HexColor("#1a2130"), HexColor("#c9a24e"), HexColor("#1e8f7a"), HexColor("#0f1622"), HexColor("#6e7787")
_reshaper = arabic_reshaper.ArabicReshaper({"delete_harakat": False, "support_ligatures": True})


def _fonts() -> None:
    for name in ("Regular", "Bold"):
        ttf = Path("/tmp") / f"Vazirmatn-{name}.ttf"
        if not ttf.exists():
            f = FTFont(str(ROOT / "frontend" / "fonts" / f"Vazirmatn-{name}.woff2"))
            f.flavor = None
            f.save(str(ttf))
        pdfmetrics.registerFont(TTFont("V" if name == "Regular" else "VB", str(ttf)))


def shape(t: str) -> str:
    return get_display(_reshaper.reshape(t))


def wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(shape(cand), font, size) <= width or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


# --- tiny HTML parser for the playbook subset -----------------------------------------
Block = tuple  # (kind, payload)


def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).replace("\xa0", " ").strip()


def parse(src: str) -> list[Block]:
    body = src.split("<body>", 1)[1].split("</body>", 1)[0]
    body = re.sub(r"<div class=\"footer\">.*?</div>", "", body, flags=re.S)
    blocks: list[Block] = []
    pos = 0
    token = re.compile(r"<(h1|h2|h3|p|ul|ol|table|div)\b([^>]*)>(.*?)</\1>", re.S)
    # divs may nest (cover contains p/h1) → handle cover/kpi/say/tip/warn specially by class
    for m in token.finditer(body):
        if m.start() < pos:
            continue
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        cls = re.search(r'class="([^"]+)"', attrs)
        cls = cls.group(1) if cls else ""
        if tag == "div" and "cover" in cls:
            # nested divs: extend to the real closing of the cover
            end = body.find("</div>\n\n<h1>", m.start())
            inner = body[m.start():end]
            pos = end
            blocks.append(("cover", [strip_tags(x) for x in re.findall(r"<(?:h1|h2|p|div)[^>]*>(.*?)</(?:h1|h2|p|div)>", inner, re.S)]))
            continue
        if tag == "div" and "kpi" in cls:
            # nested <div> items: the lazy match stopped at the first inner </div> — extend to the outer one
            end = body.find("</div>\n", m.start() + len(m.group(0)) - 6)
            seg = body[m.start():]
            depth, i, close = 0, 0, None
            for dm in re.finditer(r"<div\b|</div>", seg):
                depth += 1 if dm.group(0).startswith("<div") else -1
                if depth == 0:
                    close = dm.end(); break
            inner = seg[:close]
            pos = m.start() + close
            items = re.findall(r"<div><b>(.*?)</b>(.*?)</div>", inner, re.S)
            blocks.append(("kpi", [(strip_tags(a), strip_tags(b)) for a, b in items]))
            continue
        elif tag == "div":
            kind = "say" if "say" in cls else "tip" if "tip" in cls else "warn"
            blocks.append((kind, strip_tags(inner)))
        elif tag in ("h1", "h2", "h3"):
            blocks.append((tag, strip_tags(inner)))
        elif tag == "p":
            blocks.append(("p", strip_tags(inner)))
        elif tag in ("ul", "ol"):
            items = [strip_tags(x) for x in re.findall(r"<li>(.*?)</li>", inner, re.S)]
            blocks.append((tag, items))
        elif tag == "table":
            rows = []
            for tr in re.findall(r"<tr>(.*?)</tr>", inner, re.S):
                cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)
                rows.append([strip_tags(c) for c in cells])
            blocks.append(("table", rows))
        pos = m.end()
    return blocks


# --- renderer -------------------------------------------------------------------------
class Doc:
    def __init__(self) -> None:
        self.c = canvas.Canvas(str(OUT), pagesize=A4)
        self.c.setTitle("نقشهٔ راه بازاریابی و فروش سوپری من")
        self.c.setAuthor("سوپری من")
        self.y = H - M_T
        self.page = 1

    @property
    def width(self) -> float:
        return W - M_L - M_R

    def footer(self) -> None:
        self.c.setFont("V", 8)
        self.c.setFillColor(MUTED)
        self.c.drawCentredString(W / 2, 28, shape(f"سوپری من · نقشهٔ راه بازاریابی و فروش · صفحهٔ {self.page}"))
        self.c.setStrokeColor(GOLD)
        self.c.setLineWidth(0.6)
        self.c.line(M_L, 40, W - M_R, 40)

    def new_page(self) -> None:
        self.footer()
        self.c.showPage()
        self.page += 1
        self.y = H - M_T

    def need(self, h: float) -> None:
        if self.y - h < M_B:
            self.new_page()

    def text_right(self, t: str, x_right: float, y: float, font: str, size: float, color=INK) -> None:
        self.c.setFont(font, size)
        self.c.setFillColor(color)
        self.c.drawRightString(x_right, y, shape(t))

    def para(self, t: str, size=10.5, font="V", color=INK, indent=0.0, lead=1.75, after=5, box=None) -> None:
        width = self.width - indent - (24 if box else 0)
        lines: list[str] = []
        for raw in t.split("\n"):
            lines += wrap(raw, font, size, width)
        lh = size * lead
        h = lh * len(lines) + (14 if box else 0)
        self.need(h + after)
        top = self.y
        if box:
            fill, stroke = box
            self.c.setFillColor(fill)
            self.c.setStrokeColor(stroke)
            self.c.setLineWidth(0.8)
            self.c.roundRect(M_L, top - h, self.width, h, 6, stroke=1, fill=1)
            self.c.setFillColor(stroke)
            self.c.rect(W - M_R - 3, top - h, 3, h, stroke=0, fill=1)
        y = top - (8 if box else 0) - size
        for ln in lines:
            self.text_right(ln, W - M_R - indent - (12 if box else 0), y, font, size, color)
            y -= lh
        self.y = top - h - after

    def heading(self, level: int, t: str) -> None:
        if level == 2:
            self.new_page()
        size = {1: 19, 2: 15.5, 3: 12.5}[level]
        color = {1: NAVY, 2: HexColor("#145e63"), 3: EMERALD}[level]
        self.need(size * 3)
        self.y -= {1: 4, 2: 6, 3: 10}[level]
        self.text_right(t, W - M_R - (10 if level == 2 else 0), self.y - size, "VB", size, color)
        if level == 1:
            self.c.setStrokeColor(GOLD); self.c.setLineWidth(2)
            self.c.line(M_L, self.y - size - 8, W - M_R, self.y - size - 8)
            self.y -= size + 22
        elif level == 2:
            self.c.setFillColor(EMERALD)
            self.c.rect(W - M_R - 4, self.y - size - 4, 4, size + 8, stroke=0, fill=1)
            self.y -= size + 16
        else:
            self.y -= size + 10

    def bullets(self, items: list[str], ordered: bool) -> None:
        for i, it in enumerate(items, 1):
            marker = f"{i}." if ordered else "•"
            lines = wrap(it, "V", 10.5, self.width - 22)
            lh = 10.5 * 1.7
            self.need(lh * len(lines) + 2)
            y = self.y - 10.5
            self.text_right(marker, W - M_R, y, "VB", 10.5, EMERALD)
            for ln in lines:
                self.text_right(ln, W - M_R - 18, y, "V", 10.5)
                y -= lh
            self.y -= lh * len(lines) + 2
        self.y -= 4

    def table(self, rows: list[list[str]]) -> None:
        if not rows:
            return
        n = max(len(r) for r in rows)
        # first column narrower when it is a label column
        weights = [1.0] * n
        if n >= 2:
            weights[0] = 0.75 if n <= 3 else 0.6
        total = sum(weights)
        cols = [self.width * w / total for w in weights]
        size = 9.3
        lh = size * 1.65
        for ri, row in enumerate(rows):
            row = row + [""] * (n - len(row))
            wrapped = [wrap(cell, "VB" if ri == 0 else "V", size, cols[ci] - 10) for ci, cell in enumerate(row)]
            rh = lh * max(len(wr) for wr in wrapped) + 8
            if self.y - rh < M_B:
                self.new_page()
            top = self.y
            x_right = W - M_R
            for ci in range(n):
                cw = cols[ci]
                self.c.setStrokeColor(HexColor("#d9d2c2"))
                self.c.setLineWidth(0.5)
                if ri == 0:
                    self.c.setFillColor(NAVY)
                    self.c.rect(x_right - cw, top - rh, cw, rh, stroke=1, fill=1)
                elif ri % 2 == 0:
                    self.c.setFillColor(HexColor("#faf8f3"))
                    self.c.rect(x_right - cw, top - rh, cw, rh, stroke=1, fill=1)
                else:
                    self.c.rect(x_right - cw, top - rh, cw, rh, stroke=1, fill=0)
                y = top - size - 5
                for ln in wrapped[ci]:
                    self.text_right(ln, x_right - 5, y, "VB" if ri == 0 else "V", size, white if ri == 0 else INK)
                    y -= lh
                x_right -= cw
            self.y = top - rh
        self.y -= 10

    def kpi(self, items: list[tuple[str, str]]) -> None:
        h = 52
        self.need(h + 10)
        gap = 8
        cw = (self.width - gap * (len(items) - 1)) / len(items)
        x_right = W - M_R
        for big, small in items:
            self.c.setFillColor(NAVY)
            self.c.roundRect(x_right - cw, self.y - h, cw, h, 8, stroke=0, fill=1)
            self.c.setFont("VB", 17); self.c.setFillColor(GOLD)
            self.c.drawCentredString(x_right - cw / 2, self.y - 24, shape(big))
            self.c.setFont("V", 9); self.c.setFillColor(HexColor("#e6e2d6"))
            self.c.drawCentredString(x_right - cw / 2, self.y - 42, shape(small))
            x_right -= cw + gap
        self.y -= h + 12

    def cover(self, parts: list[str]) -> None:
        c = self.c
        c.setFillColor(NAVY); c.rect(0, 0, W, H, stroke=0, fill=1)
        c.setFillColor(HexColor("#14313a")); c.rect(0, 0, W, H * 0.42, stroke=0, fill=1)
        c.setFillColor(EMERALD); c.rect(0, 0, W, 10, stroke=0, fill=1)
        c.setStrokeColor(GOLD); c.setLineWidth(1.2); c.roundRect(M_L, M_B + 30, W - M_L - M_R, H - M_T - M_B - 60, 16, stroke=1, fill=0)
        badge, title, sub, meta, slogan = (parts + [""] * 5)[:5]
        c.setFont("V", 10); c.setFillColor(GOLD); c.drawCentredString(W / 2, H - 150, shape(badge))
        c.setFont("VB", 30); c.setFillColor(white); c.drawCentredString(W / 2, H / 2 + 80, shape(title))
        c.setFont("V", 15); c.setFillColor(HexColor("#d8d3c4"))
        for i, ln in enumerate(wrap(sub, "V", 15, self.width - 60)):
            c.drawCentredString(W / 2, H / 2 + 44 - i * 24, shape(ln))
        c.setFont("V", 10.5); c.setFillColor(HexColor("#b9c3d2"))
        for i, ln in enumerate(wrap(meta, "V", 10.5, self.width - 80)):
            c.drawCentredString(W / 2, H / 2 - 30 - i * 18, shape(ln))
        c.setFont("VB", 13); c.setFillColor(GOLD); c.drawCentredString(W / 2, H / 2 - 120, shape(slogan))
        c.setFont("V", 9); c.setFillColor(HexColor("#8d9ab0")); c.drawCentredString(W / 2, M_B + 48, shape("سوپری من — نرم‌افزار مدیریت سوپرمارکت · ویندوز + اندروید"))
        c.showPage(); self.page += 1; self.y = H - M_T

    def run(self, blocks: list[Block]) -> None:
        first_h1 = True
        for kind, payload in blocks:
            if kind == "cover":
                self.cover(payload)
            elif kind == "h1":
                if not first_h1:
                    self.new_page()
                first_h1 = False
                self.heading(1, payload)
            elif kind == "h2":
                self.heading(2, payload)
            elif kind == "h3":
                self.heading(3, payload)
            elif kind == "p":
                if payload:
                    self.para(payload)
            elif kind in ("ul", "ol"):
                self.bullets(payload, kind == "ol")
            elif kind == "table":
                self.table(payload)
            elif kind == "kpi":
                self.kpi(payload)
            elif kind == "say":
                self.para(payload, box=(HexColor("#f6f2e8"), GOLD), after=7)
            elif kind == "tip":
                self.para(payload, size=9.8, box=(HexColor("#e9f6f2"), EMERALD), after=7)
            elif kind == "warn":
                self.para(payload, size=9.8, box=(HexColor("#fdf1ee"), HexColor("#d64f5a")), after=7)
        self.footer()
        self.c.save()


def main() -> None:
    _fonts()
    blocks = parse(SRC.read_text(encoding="utf-8"))
    Doc().run(blocks)
    print("OK", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    sys.exit(main())
