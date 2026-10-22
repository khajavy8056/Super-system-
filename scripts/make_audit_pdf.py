#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docs/AUDIT_2026_10_FA.md  →  docs/RASA-AUDIT-2026-10-FA.pdf

The audit report is rendered by the shared Persian engine in
``scripts/rasa_pdf.py`` (reportlab + Vazirmatn + arabic-reshaper + python-bidi —
the same stack ``app/services/pdf.py`` uses, no browser, no cloud).

    python scripts/make_audit_pdf.py [input.md] [output.pdf]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rasa_pdf  # noqa: E402


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else rasa_pdf.DEFAULT_SRC
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else rasa_pdf.DEFAULT_OUT
    pages, toc = rasa_pdf.render(src, out)
    print(f"{out} — {out.stat().st_size / 1024:.0f} KB — {pages} pages — {toc} sections in TOC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
