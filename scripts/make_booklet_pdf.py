#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docs/BOOKLET_FA.md  →  docs/RASA-BOOKLET-2026-10-FA.pdf

The owner-facing booklet: product tour with screenshots, the store-intelligence
chapter, and the on-site sales plan. Rendered by the shared Persian engine in
``scripts/rasa_pdf.py`` (same stack the app's own PDF service uses).

    python scripts/make_booklet_pdf.py [input.md] [output.pdf]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rasa_pdf  # noqa: E402

DEFAULT_SRC = rasa_pdf.ROOT / "docs" / "BOOKLET_FA.md"
DEFAULT_OUT = rasa_pdf.ROOT / "docs" / "RASA-BOOKLET-2026-10-FA.pdf"


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    rasa_pdf.SPEC = rasa_pdf.Spec(
        banner_title="رسا سیستم — کتابچهٔ معرفی، امکانات و فروش",
        banner_sub="نرم‌افزار مدیریت فروشگاه · نسخهٔ ۱٫۰٫۵۲۶ (بیلد ۵۲۶۰۰) · مهر ۱۴۰۵",
        running_head="رسا سیستم — کتابچهٔ معرفی، امکانات و فروش",
        footer_left="RASA SYSTEM — booklet 2026-10",
        doc_title="RASA SYSTEM — کتابچهٔ معرفی، امکانات و فروش",
        doc_subject="Product booklet + on-site sales plan (Persian)",
        toc_title="فهرست فصل‌ها",
        toc_hint="هر فصل از صفحهٔ جدید شروع می‌شود؛ شمارهٔ صفحه در ستون سمت چپ است.",
        chapter_breaks=True,
        toc_h2=False,
    )
    pages, toc = rasa_pdf.render(src, out)
    print(f"{out} — {out.stat().st_size / 1024:.0f} KB — {pages} pages — {toc} chapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
