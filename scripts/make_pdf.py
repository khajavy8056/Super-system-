#!/usr/bin/env python3
"""Render docs/SCREENSHOTS.md to docs/SCREENSHOTS.pdf (real WebEngine print).

Same offscreen toolchain as scripts/shoot.py (see make_qt_stublibs.py for the
stub-library prerequisite). The markdown is parsed line-by-line (headings,
paragraphs, images, blockquote, lists, code fences) — enough for this file —
and rendered as an RTL Persian A4 document with embedded PNGs (base64).
"""
from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--no-sandbox --disable-gpu --disable-software-rasterizer --font-render-hinting=none",
)

from PySide6.QtCore import QEventLoop, QMarginsF, QTimer, QUrl
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_to_html(md: str) -> str:
    out: list[str] = []
    in_code = False
    for line in md.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            out.append("</pre>" if not in_code else '<pre class="code">')
            continue
        if in_code:
            out.append(esc(line))
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{esc(m.group(2))}</h{lvl}>")
            continue
        m = re.match(r"^!\[[^\]]*\]\((screenshots/[^)]+)\)$", line.strip())
        if m:
            p = DOCS / m.group(1)
            b64 = base64.b64encode(p.read_bytes()).decode()
            out.append(f'<img src="data:image/png;base64,{b64}"/>')
            continue
        if line.startswith("> "):
            out.append(f"<blockquote>{esc(line[2:])}</blockquote>")
            continue
        if re.match(r"^\s*[-*]\s+", line):
            item = re.sub(r"^\s*[-*]\s+", "", line)
            out.append(f"<li>{esc(item)}</li>")
            continue
        if line.strip() == "---":
            out.append("<hr/>")
            continue
        if line.strip():
            out.append(f"<p>{esc(line)}</p>")
    # merge consecutive <li> into <ul>
    html = "".join(out)
    html = re.sub(r"(?:<li>.*?</li>)+", lambda m: f"<ul>{m.group(0)}</ul>", html, flags=re.S)
    return html


CSS = """
@font-face { font-family: 'Vazirmatn'; src: url('file://%(fontdir)s/Vazirmatn-Regular.ttf'); font-weight: 400; }
@font-face { font-family: 'Vazirmatn'; src: url('file://%(fontdir)s/Vazirmatn-Bold.ttf'); font-weight: 700; }
* { box-sizing: border-box; }
body { font-family: 'Vazirmatn', sans-serif; direction: rtl; color: #14181f;
       font-size: 11.5pt; line-height: 1.9; margin: 0; }
h1 { font-size: 20pt; margin: 0 0 6pt; border-bottom: 3px solid #0ea5a4; padding-bottom: 8pt; }
h2 { font-size: 15pt; margin: 18pt 0 6pt; color: #0b7285; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin: 12pt 0 4pt; color: #364fc7; page-break-after: avoid; }
p { margin: 4pt 0; text-align: justify; }
blockquote { background: #e7f5f5; border-right: 4px solid #0ea5a4; padding: 8pt 10pt;
             border-radius: 6px; margin: 8pt 0; }
img { max-width: 100%; border: 1px solid #d5dbe3; border-radius: 8px; margin: 8pt 0;
      page-break-inside: avoid; }
li { margin: 2pt 0; }
hr { border: none; border-top: 1px dashed #adb5bd; margin: 14pt 0; }
pre.code { direction: ltr; text-align: left; background: #f1f3f5; border: 1px solid #d5dbe3;
           border-radius: 6px; padding: 8pt; font-size: 9pt; font-family: monospace;
           white-space: pre-wrap; page-break-inside: avoid; }
"""


def main() -> None:
    fontdir = Path.home() / ".fonts"
    md = (DOCS / "SCREENSHOTS.md").read_text(encoding="utf-8")
    # strip the "how to regenerate" section from the PDF (dev-only)
    md = md.split("## نحوهٔ تولید مجدد تصاویر")[0]
    css = CSS.replace("%(fontdir)s", str(fontdir))
    html = f"""<!doctype html><html lang="fa"><head><meta charset="utf-8">
<title>راهنمای تصویری سامانه سوپرمارکت</title>
<style>{css}</style></head><body>{md_to_html(md)}</body></html>"""
    tmp = DOCS / "_screenshots_pdf.html"
    tmp.write_text(html, encoding="utf-8")

    app = QApplication.instance() or QApplication(sys.argv[:1])
    view = QWebEngineView()
    view.resize(900, 1200)
    view.show()
    loop = QEventLoop()
    view.loadFinished.connect(lambda ok: loop.quit())
    view.load(QUrl.fromLocalFile(str(tmp)))
    QTimer.singleShot(60000, loop.quit)
    loop.exec()

    out = DOCS / "SCREENSHOTS.pdf"
    page = view.page()
    done = QEventLoop()
    layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(14, 14, 14, 14))
    page.pdfPrintingFinished.connect(lambda *a: done.quit())
    page.printToPdf(str(out), layout)
    QTimer.singleShot(120000, done.quit)
    done.exec()
    size = out.stat().st_size if out.exists() else 0
    print(f"SCREENSHOTS.pdf written: {size/1024/1024:.1f} MB")
    tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
