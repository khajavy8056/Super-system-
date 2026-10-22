#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RASA Persian PDF renderer — the shared engine behind the audit report and the booklet.

Used by ``scripts/make_audit_pdf.py`` (audit report) and
``scripts/make_booklet_pdf.py`` (the owner-facing product booklet).

Renders the Persian audit report as a print-quality A4 PDF using the project's
own Persian stack (reportlab + Vazirmatn + arabic-reshaper + python-bidi), i.e.
the same dependencies `app/services/pdf.py` already uses — no browser, no cloud.

Markdown features handled: ATX headings (#..####), paragraphs, bullet and
numbered lists, GFM tables, fenced code blocks (kept LTR/monospace), blockquotes,
horizontal rules, and inline `code`, **bold**, *italic*, [links](url).

RTL strategy
------------
Each inline run is shaped on its own (``reshape`` + ``get_display``) and the runs
are emitted in reverse logical order, which is the correct visual order for a
right-to-left paragraph. That keeps bold/code emphasis working, which a
whole-line reshape cannot do (bidi would move the markup tags as well).

Block extensions (used by the booklet, tolerated by the report)
-------------------------------------------------------------
``![caption](path)``                 one image, scaled to the text column
``![cap A](a.png) ![cap B](b.png)``  two images side by side
``:::card Title`` … ``:::``           a shaded card with a title bar
``:::note`` … ``:::``                 a callout box

    python scripts/rasa_pdf.py input.md out.pdf        # both variables below default
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "docs" / "AUDIT_2026_10_FA.md"
DEFAULT_OUT = ROOT / "docs" / "RASA-AUDIT-2026-10-FA.pdf"


class Spec:
    """What the furniture says: banner, running head, footer, PDF metadata."""

    def __init__(self, *, banner_title: str, banner_sub: str, running_head: str,
                 footer_left: str, doc_title: str, doc_subject: str,
                 toc_title: str = "فهرست مطالب", toc_hint: str = "",
                 chapter_breaks: bool = False, cover: bool = True,
                 toc_h2: bool = True, book_title: str = ""):
        self.banner_title = banner_title
        self.banner_sub = banner_sub
        self.running_head = running_head
        self.footer_left = footer_left
        self.doc_title = doc_title
        self.doc_subject = doc_subject
        self.toc_title = toc_title
        self.toc_hint = toc_hint
        self.chapter_breaks = chapter_breaks   # every H1 starts a new page
        self.cover = cover                     # block before the first H2 is page 1
        self.toc_h2 = toc_h2                   # list H2 sections in the TOC as well
        self.book_title = book_title           # shown on the cover, if set


SPEC = Spec(
    banner_title="رسا سیستم — گزارش ممیزی جامع",
    banner_sub="بررسی، مستندسازی، آزمایش، اصلاح و تأیید مجدد — مهر ۱۴۰۵",
    running_head="رسا سیستم — گزارش ممیزی جامع ۲۰۲۶-۱۰",
    footer_left="RASA SYSTEM — audit 2026-10",
    doc_title="RASA SYSTEM — گزارش ممیزی ۲۰۲۶-۱۰",
    doc_subject="Audit report (Persian)",
    toc_hint="شمارهٔ صفحه در ستون سمت چپ، عنوان بخش در ستون راست.",
    toc_h2=True,
)

FONT_REGULAR = ROOT / "backend" / "app" / "assets" / "fonts" / "Vazirmatn-Regular.ttf"
FONT_BOLD = ROOT / "backend" / "app" / "assets" / "fonts" / "Vazirmatn-Bold.ttf"

from reportlab.lib import colors                                     # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT         # noqa: E402
from reportlab.lib.pagesizes import A4                                # noqa: E402
from reportlab.lib.styles import ParagraphStyle                       # noqa: E402
from reportlab.lib.units import mm                                    # noqa: E402
from reportlab.pdfbase import pdfmetrics                              # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont                          # noqa: E402
from reportlab.platypus import (                                      # noqa: E402
    BaseDocTemplate, Frame, Image as RLImage, KeepTogether, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.pdfgen import canvas as rl_canvas                      # noqa: E402

# ---------------------------------------------------------------- fonts / shaping
REG, BOLD = "Vazirmatn", "Vazirmatn-Bold"
pdfmetrics.registerFont(TTFont(REG, str(FONT_REGULAR)))
pdfmetrics.registerFont(TTFont(BOLD, str(FONT_BOLD)))
pdfmetrics.registerFontFamily(REG, normal=REG, bold=BOLD, italic=REG, boldItalic=BOLD)

#: Vazirmatn (the product font) is a *text* face: it carries no arrows, bullets,
#: stars or check marks, so ✅/→/● silently vanished from the first draft. A
#: symbol face covers them. DejaVu ships with every Linux image; when it is
#: absent we degrade to ASCII substitutes instead of dropping the glyph.
SYM = "Symbols"
_SYM_CANDIDATES = [
    os.environ.get("RASA_PDF_SYMBOL_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def _register_symbol_font() -> bool:
    for cand in _SYM_CANDIDATES:
        if cand and Path(cand).is_file():
            try:
                pdfmetrics.registerFont(TTFont(SYM, cand))
                return True
            except Exception:  # noqa: BLE001 — a broken fallback is not fatal
                continue
    return False


HAS_SYMBOLS = _register_symbol_font()

from fontTools.ttLib import TTFont as _FTFont                       # noqa: E402

_VZ_CMAP: set[int] = set()
for _f in (FONT_REGULAR, FONT_BOLD):
    _VZ_CMAP |= set(_FTFont(str(_f)).getBestCmap().keys())

#: colour emoji have no monochrome glyph anywhere in these faces; map them to the
#: closest printable symbol so a status column never renders as an empty cell.
_EMOJI = {"\u2705": "\u2713", "\u274c": "\u2717", "\U0001f7e1": "\u25d0",
          "\U0001f7e2": "\u25cf", "\U0001f534": "\u25cf", "\U0001f535": "\u25cf",
          "\u26a0\ufe0f": "\u26a0", "\u23ed\ufe0f": "\u00bb", "\u23ed": "\u00bb",
          "\u26d4": "\u2717", "\U0001f6ab": "\u2717", "\U0001f512": "\u25a0",
          "\u2b50": "\u2605", "\U0001f4b0": "\u25cf", "\U0001f4c8": "\u25b2",
          "\U0001f4c9": "\u25bc", "\U0001f9ea": "\u25cb", "\u2714\ufe0f": "\u2713",
          "\ufe0f": ""}
#: last resort when no symbol face exists
_ASCII_LAST = {"\u2713": "✓".encode("ascii", "replace").decode(), "\u2717": "x",
               "\u25d0": "~", "\u25cf": "*", "\u26a0": "!", "\u2192": "->",
               "\u2190": "<-", "\u00bb": ">>", "\u2022": "-", "\u2605": "*"}


def demojify(text: str) -> str:
    for k, v in _EMOJI.items():
        text = text.replace(k, v)
    return text


#: Joiners do their work inside the Arabic shaper (they decide which medial form
#: a letter takes) and must be removed *after* shaping: Vazirmatn has no glyph for
#: U+200C, so leaving it in printed a box between "همگام" and "سازی".
_INVISIBLE = {"\u200c": "", "\u200d": "", "\u200e": "", "\u200f": "", "\ufeff": ""}


def strip_invisible(text: str) -> str:
    for ch in _INVISIBLE:
        text = text.replace(ch, "")
    return text


def force_font_glyphs(text: str) -> str:
    """Drop characters no available face can draw (box glyphs are worse than a gap)."""
    out = []
    for ch in text:
        if ch in "\n\t" or ord(ch) in _VZ_CMAP or not ch.strip():
            out.append(ch)
        elif HAS_SYMBOLS:
            out.append(ch)          # symbol font will cover it in span_markup
        else:
            out.append("")
    return "".join(out)


def span_markup(raw: str) -> str:
    """Escape one raw text run, routing glyphs Vazirmatn lacks to the symbol face."""
    raw = strip_invisible(demojify(raw))
    out: list[str] = []
    buf: list[str] = []
    sym: list[str] = []

    def flush_buf():
        if buf:
            out.append(esc("".join(buf)))
            buf.clear()

    def flush_sym():
        if sym:
            chunk = "".join(sym)
            if HAS_SYMBOLS:
                out.append(f'<font name="{SYM}">{esc(chunk)}</font>')
            else:
                out.append(esc("".join(_ASCII_LAST.get(c, "") for c in chunk)))
            sym.clear()

    for ch in raw:
        if ord(ch) in _VZ_CMAP or ch in "\n\t":
            flush_sym()
            buf.append(ch)
        else:
            flush_buf()
            sym.append(ch)
    flush_sym()
    flush_buf()
    return "".join(out)


#: UAX #9 rule L4 — in a right-to-left run the paired brackets must be mirrored.
#: python-bidi reorders the characters but does not apply L4, so «(ویندوز)» came
#: out visually as «)ویندوز(» in every heading and card title.
_MIRROR = str.maketrans({"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{",
                         "\u00ab": "\u00bb", "\u00bb": "\u00ab", "<": ">", ">": "<"})


def mirror_brackets(display: str) -> str:
    """Apply UAX #9 L4 to an already-reordered (visual) run."""
    return display.translate(_MIRROR)


def shape(text: str) -> str:
    """Arabic/Persian shaping + bidi reordering + bracket mirroring for one run."""
    import arabic_reshaper
    from bidi.algorithm import get_display

    if not text:
        return text
    return mirror_brackets(get_display(arabic_reshaper.reshape(text)))


def _canvas_text(text: str) -> str:
    """Canvas drawing takes plain text (no markup) — drop what the face lacks."""
    shaped = strip_invisible(shape(demojify(text)))
    return "".join(c for c in shaped if ord(c) in _VZ_CMAP)


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))", re.S)
#: Inline emphasis is stripped before shaping and re-applied only where it is
#: unambiguous (headings, table headers, whole paragraphs). Reversing runs
#: individually broke bracket pairs across run boundaries
#: ("(۱٫۰٫۵۲۰ (۵ بیلد عقب)" became "۱٫۰٫۵۲۰ (۵ بیلد عقب)("). Correct bidi beats
#: decorative bold inside prose, and this report is read for its numbers.
_MARKUP = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)", re.S)


def plain(text: str) -> str:
    """Drop inline markup, keep the words (links become 'label (url)')."""
    def _sub(m):
        if m.group(1) is not None:
            return m.group(1)
        if m.group(2) is not None:
            return m.group(2)
        return f"{m.group(3)} ({m.group(4)})"
    return _MARKUP.sub(_sub, text)


def inline_runs(text: str) -> list[tuple[str, str]]:
    """Split a line into (reportlab-tag, raw text) runs, logical order."""
    runs: list[tuple[str, str]] = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            runs.append(("b", part[2:-2]))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            runs.append(("code", part[1:-1]))
        elif part.startswith("[") and "](" in part:
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", part).groups()
            runs.append(("link", f"{label} ({url})"))
        else:
            runs.append(("", part))
    return runs


_RLM = "\u200f"
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
#: A Latin run is a *phrase*, not a word: ``Store Intelligence``, ``RASA SYSTEM``
#: and ``test_a.py test_b.py`` must stay in one piece. Wrapping each word with
#: RLM marks separately turned them into separate right-to-left units, which
#: printed «Intelligence Store».
_ASCII_RUN = re.compile(r"[A-Za-z0-9_./\\:*\-\[\]{}=+$]{2,}(?: [A-Za-z0-9_./\\:*\-\[\]{}=+$]{2,})*")


def protect_ascii(text: str) -> str:
    """Bracket every Latin run with RIGHT-TO-LEFT MARKS.

    Without this, the bidi algorithm treats ``test_phase2.py`` inside a Persian
    sentence as a separate left-to-right island and moves it to the *end* of the
    line, so "آزمون: test_phase2.py انجام شد" was printed as
    "test_phase2.py … آزمون" — the evidence looked attached to the wrong clause.
    A pair of RLM marks pins the run where the author wrote it.
    """
    return _ASCII_RUN.sub(lambda m: _RLM + m.group(0) + _RLM, text)


def rtl_markup(text: str) -> str:
    """One logical line → shaped, bidi-reordered, escaped reportlab markup."""
    return span_markup(strip_invisible(shape(protect_ascii(plain(text)))))


def _shape_plain(text: str) -> str:
    """Presentation-form text (no reordering) — used only for measuring."""
    import arabic_reshaper
    return arabic_reshaper.reshape(text)


def _width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(_shape_plain(text), font, size)


def wrap_rtl(text: str, max_width: float, font: str = REG, size: float = 9.6) -> list[str]:
    """Greedy word wrap on the LOGICAL text, before any reordering.

    Reordering first and then letting reportlab break lines in visual order puts
    the last line of every paragraph on top (the reader sees the sentence
    backwards, line by line). Breaking in logical order and shaping each line on
    its own keeps both the words and the lines in the right order.
    """
    max_width *= 0.985        # safety margin: reportlab measures shaped glyphs slightly wider
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        cand = f"{cur} {w}"
        if _width(cand, font, size) <= max_width:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    # a single word wider than the column still has to break somewhere
    out: list[str] = []
    for line in lines:
        if _width(line, font, size) <= max_width or len(line) < 4:
            out.append(line)
            continue
        part = ""
        for ch in line:
            if _width(part + ch, font, size) > max_width and part:
                out.append(part)
                part = ch
            else:
                part += ch
        if part:
            out.append(part)
    return out


def rtl_flow(text: str, max_width: float, font: str = REG, size: float = 9.6) -> str:
    """Complete RTL paragraph markup: logical wrapping, then shaping per line."""
    lines = wrap_rtl(plain(text), max_width, font, size)
    return "<br/>".join(rtl_markup(line) for line in lines)


_FA = re.compile(r"[\u0600-\u06FF\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def is_rtl_text(text: str) -> bool:
    """True when the run contains Persian/Arabic letters (so it must be shaped)."""
    letters = len(_FA.findall(text))
    ascii_letters = len(re.findall(r"[A-Za-z]", text))
    return letters >= ascii_letters and letters > 0


def cell_para(text: str, st, width: float | None = None) -> "Paragraph":
    """Table cell.

    Persian → an RTL paragraph wrapped inside its own column width (Latin
    identifiers pinned in place by ``protect_ascii``). Pure-ASCII cells (paths,
    ids) stay LTR and breakable, so a long evidence path wraps instead of
    overflowing the column.
    """
    has_fa = bool(re.search(r"[\u0600-\u06FF]", text))
    if has_fa:
        max_w = (width - 8) if width else TEXT_WIDTH
        return Paragraph(rtl_flow(text, max_w, REG, 8.0), st["cell"])
    return Paragraph(ltr_markup(text), st["cell_ltr"])


def code_markup(text: str) -> str:
    """Monospace block, except Persian words.

    The diagram inside the report is ASCII art with Persian labels. Courier has
    no Persian glyphs, so the first draft printed solid ████ boxes wherever a
    label appeared. Each Persian run is emitted in the product font (shaped)
    inside the same line, which keeps the diagram readable even though the
    monospace column alignment is no longer byte-exact for those runs.
    """
    out: list[str] = []
    for part in re.split(r"([\u0600-\u06FF\s]+)", text):
        if not part:
            continue
        if re.search(r"[\u0600-\u06FF]", part):
            out.append(f'<font name="{REG}">{esc(strip_invisible(shape(part)))}</font>')
        else:
            out.append(span_markup(part))
    return "".join(out)


def ltr_markup(text: str) -> str:
    """Code / ASCII blocks stay in logical order, left to right."""
    return span_markup(plain(text))


# ---------------------------------------------------------------- styles
TEXT_WIDTH = A4[0] - 2 * 15 * mm          # the single text column of this engine


def styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName=REG, alignment=TA_RIGHT)
    return {
        "body": ParagraphStyle("body", fontName=REG, fontSize=9.6, leading=15.5,
                               alignment=TA_RIGHT, spaceAfter=5, textColor=colors.HexColor("#1d2433")),
        "li": ParagraphStyle("li", fontName=REG, fontSize=9.6, leading=15.2,
                             alignment=TA_RIGHT, rightIndent=10, spaceAfter=2.5,
                             bulletIndent=0, bulletFontName=REG, bulletFontSize=9.6),
        "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=18, leading=24,
                             alignment=TA_RIGHT, spaceBefore=10, spaceAfter=10,
                             textColor=colors.HexColor("#0f2a52")),
        "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=13.5, leading=19,
                             alignment=TA_RIGHT, spaceBefore=14, spaceAfter=6,
                             textColor=colors.HexColor("#123a6b"),
                             borderPadding=(0, 0, 4, 0)),
        "h3": ParagraphStyle("h3", fontName=BOLD, fontSize=11, leading=16,
                             alignment=TA_RIGHT, spaceBefore=9, spaceAfter=4,
                             textColor=colors.HexColor("#1f4e79")),
        "h4": ParagraphStyle("h4", fontName=BOLD, fontSize=10, leading=15,
                             alignment=TA_RIGHT, spaceBefore=7, spaceAfter=3,
                             textColor=colors.HexColor("#33475b")),
        "quote": ParagraphStyle("quote", fontName=REG, fontSize=9.2, leading=14.5,
                                alignment=TA_RIGHT, rightIndent=12, leftIndent=6,
                                textColor=colors.HexColor("#3c4a5a"), spaceAfter=5),
        "cell": ParagraphStyle("cell", fontName=REG, fontSize=8.0, leading=11.4,
                               alignment=TA_RIGHT, textColor=colors.HexColor("#1d2433")),
        "cell_ltr": ParagraphStyle("cell_ltr", fontName=REG, fontSize=7.9, leading=11.4,
                                   alignment=TA_LEFT, wordWrap="CJK",
                                   textColor=colors.HexColor("#1d2433")),
        "cellh": ParagraphStyle("cellh", fontName=BOLD, fontSize=8.4, leading=11.8,
                                alignment=TA_RIGHT, textColor=colors.white),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=7.8, leading=10.4,
                               alignment=TA_LEFT, wordWrap="CJK",
                               textColor=colors.HexColor("#243447")),
    }


# ---------------------------------------------------------------- block parser
def parse(md: str):
    """Yield block tuples: (kind, payload)."""
    lines = md.splitlines()
    i = 0
    para: list[str] = []

    def flush():
        nonlocal para
        if para:
            yield ("p", " ".join(para).strip())
            para = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            yield from flush()
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            yield ("code", "\n".join(block))
            continue

        if not stripped:
            yield from flush()
            i += 1
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            yield from flush()
            yield (f"h{len(m.group(1))}", m.group(2).strip())
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            yield from flush()
            yield ("hr", "")
            i += 1
            continue

        # :::card Title … :::   |  :::note … :::
        if stripped in (":::break", ":::page"):
            yield from flush()
            yield ("break", "")
            i += 1
            continue

        m = re.match(r"^:::\s*(card|note)?\s*(.*)$", stripped)
        if m:
            yield from flush()
            kind2 = m.group(1) or "note"
            title = m.group(2).strip()
            i += 1
            body: list[str] = []
            while i < len(lines) and lines[i].strip() != ":::":
                body.append(lines[i].strip())
                i += 1
            i += 1
            yield (kind2, (title, "\n".join(body)))
            continue

        # ![caption](path) — one or more on a line (a row of images)
        if re.match(r"^(!\[[^\]]*\]\([^)]+\)\s*)+$", stripped):
            yield from flush()
            imgs = []
            for cap, path in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", stripped):
                imgs.append((cap.strip(), path.strip()))
            yield ("images", imgs)
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and \
                re.match(r"^\|[\s:|-]+\|?$", lines[i + 1].strip()):
            yield from flush()
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            yield ("table", (header, rows))
            continue

        if stripped.startswith(">"):
            yield from flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            yield ("quote", " ".join(quote))
            continue

        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            yield from flush()
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(re.match(r"^[-*]\s+(.*)$", lines[i].strip()).group(1))
                i += 1
            yield ("ul", items)
            continue

        m = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if m:
            yield from flush()
            items = []
            while i < len(lines) and re.match(r"^\d+[.)]\s+", lines[i].strip()):
                items.append(re.match(r"^\d+[.)]\s+(.*)$", lines[i].strip()).group(1))
                i += 1
            yield ("ol", items)
            continue

        para.append(stripped)
        i += 1

    yield from flush()


# ---------------------------------------------------------------- flowables
def build_table(header, rows, st) -> Table:
    ncols = len(header)
    avail = A4[0] - 2 * 15 * mm
    # weight columns: narrow for short cells (status/id), wide for prose
    weights = []
    for idx in range(ncols):
        longest = max(len((r + [""] * ncols)[idx]) for r in ([header] + rows))
        head = len(header[idx])
        # a header is a promise to the reader: it must fit. Beyond that, prose
        # length wins, dampened so one long cell cannot eat the page.
        weights.append(max(head * 1.35, min(longest * 0.62, 46), 9))
    total = sum(weights) or 1
    widths = [avail * w / total for w in reversed(weights)]

    # RTL: first logical column must appear on the RIGHT → reverse column order
    data = [[Paragraph(rtl_flow(c, widths[i] - 8, BOLD, 8.4), st["cellh"])
             for i, c in enumerate(reversed(header))]]
    for r in rows:
        cells = (r + [""] * ncols)[:ncols]
        data.append([cell_para(c, st, widths[i]) for i, c in enumerate(reversed(cells))])

    t = Table(data, colWidths=widths, repeatRows=1, hAlign="CENTER")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b9c6d4")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f7fb")]),
    ]))
    return t



# ---------------------------------------------------------------- images / cards
CAPTION = ParagraphStyle("cap", fontName=REG, fontSize=7.6, leading=11,
                         alignment=TA_CENTER, textColor=colors.HexColor("#5b6b7d"),
                         spaceBefore=3, spaceAfter=8)
CARD_TITLE = ParagraphStyle("cardtitle", fontName=BOLD, fontSize=10.2, leading=15,
                            alignment=TA_RIGHT, textColor=colors.white)
CARD_BODY = ParagraphStyle("cardbody", fontName=REG, fontSize=9.2, leading=14.6,
                           alignment=TA_RIGHT, textColor=colors.HexColor("#1d2433"))


def _image_row(imgs: list[tuple[str, str]], st) -> list:
    """One or two screenshots, scaled to the available width, caption underneath."""
    avail = A4[0] - 2 * 15 * mm
    n = max(1, len(imgs))
    gap = 5 * mm
    cell_w = (avail - gap * (n - 1)) / n
    cells, caps = [], []
    for cap, raw_path in imgs:
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / raw_path
        if not path.exists():                       # never ship a silent hole
            cells.append(Paragraph(span_markup(shape(f"[تصویر یافت نشد: {raw_path}]")), st["cell"]))
            caps.append(cap)
            continue
        from PIL import Image as _PILImage
        with _PILImage.open(path) as im:
            w, h = im.size
        # fit inside the cell while keeping the aspect ratio; never upscale past 1:1
        # beyond the column (screenshots are 1440 px wide, print is ~520 pt)
        max_h = 118 * mm
        scale = min(cell_w / w, max_h / h)
        cells.append(RLImage(str(path), width=w * scale, height=h * scale))
        caps.append(cap)
    row = Table([cells], colWidths=[cell_w] * n, hAlign="CENTER")
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    out: list = [Spacer(1, 3), row]
    label = " · ".join(c for c in caps if c)
    if label:
        out.append(Paragraph(rtl_flow(label, TEXT_WIDTH, REG, 7.6), CAPTION))
    else:
        out.append(Spacer(1, 6))
    # keep the picture and its caption on the same page
    return [KeepTogether(out)]


def _card(title: str, body: str, *, st, note: bool = False) -> list:
    """A titled, shaded box: one feature, one page element (the «کارت» the owner asked for)."""
    avail = A4[0] - 2 * 15 * mm
    inner: list = []
    # blank lines inside a card separate paragraphs; consecutive "- " lines form
    # one list (the markdown the booklet is written in)
    blocks = [b for b in re.split(r"\n\s*\n", body) if b.strip()]
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if all(re.match(r"^[-*]\s+", ln) for ln in lines):
            for ln in lines:
                inner.append(Paragraph(rtl_flow("• " + re.sub(r"^[-*]\s+", "", ln),
                                                 TEXT_WIDTH - 30, REG, 9.2), st["li"]))
            continue
        if all(re.match(r"^\d+[.)]\s+", ln) for ln in lines):
            for ln in lines:
                n, txt = re.match(r"^(\d+)[.)]\s+(.*)$", ln).groups()
                inner.append(Paragraph(rtl_flow(f"{n.translate(_FA_DIGITS)}. {txt}",
                                                 TEXT_WIDTH - 30, REG, 9.2), st["li"]))
            continue
        inner.append(Paragraph(rtl_flow(" ".join(lines), TEXT_WIDTH - 30, REG, 9.2), CARD_BODY))
    if not title:
        title = "نکته" if note else ""
    head = colors.HexColor("#b45309") if note else colors.HexColor("#1f4e79")
    rows = []
    if title:
        bar = Table([[Paragraph(rtl_flow(title, avail - 16, BOLD, 10.2), CARD_TITLE)]], colWidths=[avail])
        bar.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), head),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        rows.append([bar])
    body_box = Table([[inner]], colWidths=[avail])
    body_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf6e9") if note else colors.HexColor("#f4f8fc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e3c98f") if note else colors.HexColor("#c3d6e8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    rows.append([body_box])
    card = Table(rows, colWidths=[avail], hAlign="CENTER")
    card.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [Spacer(1, 4), KeepTogether(card), Spacer(1, 7)]


TOC_PAGES: dict[str, int] = {}
TOC_LEVEL: dict[str, int] = {}


def flowables(md: str):
    """Build the story. Everything before the first H2 is the cover block."""
    st = styles()
    in_cover = True
    seen_content = False
    first_h1 = True
    for kind, payload in parse(md):
        if kind in ("h2", "h3", "p", "table", "ul", "ol", "card", "note", "images"):
            in_cover = False
        if kind == "h1":
            # the very first H1 is the document title (cover page), not a chapter
            is_title = first_h1
            first_h1 = False
            if SPEC.chapter_breaks and seen_content and not is_title:
                yield PageBreak()
            seen_content = True
            para = Paragraph(rtl_flow(payload, TEXT_WIDTH, BOLD, 18), st["h1"])
            if SPEC.chapter_breaks and not is_title:
                para._toc_key = plain(payload)          # type: ignore[attr-defined]
                para._toc_level = 1                     # type: ignore[attr-defined]
            yield para
            yield _rule(colors.HexColor("#1f4e79"))
        elif kind == "h2":
            para = Paragraph(rtl_flow(payload, TEXT_WIDTH, BOLD, 13.5), st["h2"])
            if SPEC.toc_h2:
                para._toc_key = plain(payload)      # type: ignore[attr-defined]
                para._toc_level = 2                 # type: ignore[attr-defined]
            yield para
        elif kind == "h3":
            yield Paragraph(rtl_flow(payload, TEXT_WIDTH, BOLD, 11), st["h3"])
        elif kind == "h4":
            yield Paragraph(rtl_flow(payload, TEXT_WIDTH, BOLD, 10), st["h4"])
        elif kind == "p":
            yield Paragraph(rtl_flow(payload, TEXT_WIDTH, REG, 9.6), st["body"])
        elif kind == "quote":
            yield Paragraph(rtl_flow(payload, TEXT_WIDTH - 18, REG, 9.2), st["quote"])
        elif kind == "code":
            pre = Paragraph(code_markup(payload).replace("\n", "<br/>"), st["code"])
            box = Table([[pre]], colWidths=[A4[0] - 2 * 15 * mm])
            box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f6f8")),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d4de")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            yield box
            yield Spacer(1, 5)
        elif kind == "ul":
            for it in payload:
                # the marker must live inside the shaped line: a separate "•" run
                # is placed by bidi at the far LEFT of an RTL paragraph.
                yield Paragraph(rtl_flow("• " + it, TEXT_WIDTH - 10, REG, 9.6), st["li"])
        elif kind == "ol":
            for n, it in enumerate(payload, 1):
                # Persian digits: Latin "1." is an LTR island that bidi pushes to
                # the far LEFT of the RTL line, away from its item.
                num = str(n).translate(_FA_DIGITS)
                yield Paragraph(rtl_flow(f"{num}. {it}", TEXT_WIDTH - 10, REG, 9.6), st["li"])
        elif kind == "table":
            header, rows = payload
            yield Spacer(1, 3)
            yield build_table(header, rows, st)
            yield Spacer(1, 7)
        elif kind == "break":
            yield PageBreak()
        elif kind == "images":
            yield from _image_row(payload, st)
        elif kind in ("card", "note"):
            yield from _card(*payload, st=st, note=(kind == "note"))
        elif kind == "hr":
            yield Spacer(1, 4)
            yield _rule(colors.HexColor("#c3cfdb"))
            yield Spacer(1, 4)


def _tag_cover(items: list) -> tuple[list, list]:
    """Split the story: cover block (before the first H2) vs. the report body."""
    cover, body = [], []
    for f in items:
        if getattr(f, "_toc_key", None) is None and not body:
            cover.append(f)
        else:
            body.append(f)
    return cover, body


def _rule(color) -> Table:
    t = Table([[""]], colWidths=[A4[0] - 2 * 15 * mm], rowHeights=[0.8])
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.8, color)]))
    return KeepTogether([t])


# ---------------------------------------------------------------- page decoration
def toc_flowables(st) -> list:
    """A printed table of contents with real page numbers (RTL: title right)."""
    if not TOC_PAGES:
        return []
    data = []
    for title, page in TOC_PAGES.items():
        level = TOC_LEVEL.get(title, 2)
        fa_page = (str(page).translate(_FA_DIGITS))
        num_style = st["cell"] if level == 2 else ParagraphStyle(
            "tocnum1", parent=st["cell"], fontName=BOLD, fontSize=9,
            textColor=colors.HexColor("#0f2a52"))
        title_style = st["cell"] if level == 2 else ParagraphStyle(
            "toct1", parent=st["cell"], fontName=BOLD, fontSize=9.4,
            textColor=colors.HexColor("#0f2a52"))
        data.append([
            Paragraph(span_markup(shape(fa_page)), num_style),
            Paragraph(rtl_flow(title, A4[0] - 2 * 15 * mm - 16 * mm - 8, REG, 8.0), title_style),
        ])
    t = Table(data, colWidths=[16 * mm, A4[0] - 2 * 15 * mm - 16 * mm], hAlign="CENTER")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#dbe3ea")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    out = [Paragraph(span_markup(shape(SPEC.toc_title)), st["h2"])]
    if SPEC.toc_hint:
        out.append(Paragraph(rtl_flow(SPEC.toc_hint, TEXT_WIDTH, REG, 9.6), st["body"]))
    out += [Spacer(1, 4), t, NextPageTemplate("later")]
    return out


class AuditDoc(BaseDocTemplate):
    """Base template that remembers the page of every section heading."""

    def afterFlowable(self, flowable):  # noqa: N802 (reportlab hook name)
        key = getattr(flowable, "_toc_key", None)
        if key and key not in TOC_PAGES:
            TOC_PAGES[key] = self.page
            TOC_LEVEL[key] = getattr(flowable, "_toc_level", 2)


class NumberedCanvas(rl_canvas.Canvas):
    """»صفحهٔ X از Y« در پایین، راست‌چین — شمارهٔ صفحه در RTL هم درست خوانده شود."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._footer(total)
            super().showPage()
        super().save()

    def _footer(self, total: int) -> None:
        self.setFont(REG, 8)
        self.setFillColor(colors.HexColor("#6b7d90"))
        label = _canvas_text(f"صفحهٔ {self._pageNumber} از {total}")
        self.drawRightString(A4[0] - 15 * mm, 10 * mm, label)
        self.drawString(15 * mm, 10 * mm, _canvas_text(SPEC.footer_left))
        self.setStrokeColor(colors.HexColor("#d5dde5"))
        self.setLineWidth(0.5)
        self.line(15 * mm, 13.5 * mm, A4[0] - 15 * mm, 13.5 * mm)


def banner(canv: rl_canvas.Canvas, doc) -> None:
    """Page 1 banner. The frame on that page starts below it (see main())."""
    canv.saveState()
    canv.setFillColor(colors.HexColor("#0f2a52"))
    canv.rect(0, A4[1] - 30 * mm, A4[0], 30 * mm, stroke=0, fill=1)
    canv.setFillColor(colors.white)
    canv.setFont(BOLD, 16)
    canv.drawRightString(A4[0] - 18 * mm, A4[1] - 17 * mm, _canvas_text(SPEC.banner_title))
    canv.setFont(REG, 9)
    canv.drawRightString(A4[0] - 18 * mm, A4[1] - 25 * mm, _canvas_text(SPEC.banner_sub))
    canv.restoreState()


def running_head(canv: rl_canvas.Canvas, doc) -> None:
    """Pages 2+: a thin rule and the report name, no banner."""
    canv.saveState()
    canv.setFillColor(colors.HexColor("#0f2a52"))
    canv.setFont(BOLD, 7.6)
    canv.drawRightString(A4[0] - 15 * mm, A4[1] - 9 * mm, _canvas_text(SPEC.running_head))
    canv.setStrokeColor(colors.HexColor("#cfd9e2"))
    canv.setLineWidth(0.5)
    canv.line(15 * mm, A4[1] - 11.5 * mm, A4[0] - 15 * mm, A4[1] - 11.5 * mm)
    canv.restoreState()


def _make_doc(out: Path) -> "AuditDoc":
    doc = AuditDoc(
        str(out), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=14 * mm, bottomMargin=18 * mm,
        title=SPEC.doc_title,
        author="Arena Agent", subject=SPEC.doc_subject,
    )
    f1 = Frame(doc.leftMargin, doc.bottomMargin, doc.width,
               A4[1] - 30 * mm - 6 * mm - doc.bottomMargin, id="first")
    f2 = Frame(doc.leftMargin, doc.bottomMargin, doc.width,
               A4[1] - doc.topMargin - 8 * mm - doc.bottomMargin, id="later")
    doc.addPageTemplates([
        PageTemplate(id="first", frames=[f1], onPage=banner),
        PageTemplate(id="later", frames=[f2], onPage=running_head),
    ])
    return doc


def _split_cover(items: list) -> tuple[list, list]:
    """Cover page = everything up to ``:::break``; without one, up to the first H2."""
    for i, f in enumerate(items):
        if isinstance(f, PageBreak):
            return items[:i], items[i + 1:]
    return _tag_cover(items)


def _story(md: str, toc: list | None = None) -> list:
    """The full story: cover block (page 1), optional TOC page, then the body."""
    items = list(flowables(md))
    cover, report = _split_cover(items) if SPEC.cover else ([], items)
    while report and isinstance(report[0], PageBreak):
        report = report[1:]          # the TOC page already ends with a break
    story = [NextPageTemplate("later")]
    if cover:
        story += cover + [PageBreak()]
    if toc:
        story += toc + [PageBreak()]
    return story + report


def render(src: Path, out: Path) -> tuple[int, int]:
    """Render ``src`` (Markdown) to ``out`` (PDF). Returns (pages, toc entries)."""
    md = src.read_text(encoding="utf-8")

    # pass 1 — where does every section land? (flowables are single-use, so the
    # story is built twice from the markdown, not reused)
    TOC_PAGES.clear()
    TOC_LEVEL.clear()
    probe = out.with_suffix(".probe.pdf")
    # the probe layout is identical to the final one minus the TOC page, so the
    # only correction needed afterwards is the single TOC page inserted at +1
    _make_doc(probe).build(_story(md), canvasmaker=NumberedCanvas)
    probe.unlink(missing_ok=True)

    shift = 1 if not SPEC.cover else 1     # the TOC page, in both layouts
    TOC_PAGES.update({k: v + shift for k, v in TOC_PAGES.items()})

    # The TOC entries render from the *shifted* dict, so rebuild it from markdown
    _make_doc(out).build(_story(md, toc_flowables(styles())),
                         canvasmaker=NumberedCanvas)
    return _page_count(out), len(TOC_PAGES)


def _page_count(path: Path) -> int:
    data = path.read_bytes()
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages") or data.count(b"/Type/Page")


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    pages, toc = render(src, out)
    print(f"{out} — {out.stat().st_size / 1024:.0f} KB — {pages} pages — {toc} TOC entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
