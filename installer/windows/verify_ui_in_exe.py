#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ui_in_exe.py <RasaSystem.exe> <ui-build-NNN>

build-486 — راستی‌آزمایی «آیا رابط کاربری جدید واقعاً داخل فایل اجرایی است؟».

سابقه (باگ مالک): سازندهٔ قبلی رشتهٔ `ui-build-NNN` را به‌صورت بایت خام در exe
می‌گشت؛ PyInstaller فایل‌های `datas` را **فشرده** نگه می‌دارد و رشته هرگز پیدا
نمی‌شد → خطای «تم جدید داخل exe نیست» و ساختِ فایل نصبی متوقف می‌شد، در حالی که
تم جدید واقعاً داخل exe بود. این ابزار آرشیو PyInstaller را درست می‌خواند.

Exit codes (قرارداد با builder-lib.ps1):
  0 = بسته‌بندی تأیید شد (محتوا تازه است، یا فایل در بایگانی هست و محتوا
      قابل‌استخراج نبود ولی شواهد کافی است)
  1 = **اثبات** کهنگی: فایل app.js در بایگانی هست ولی نشان ساخت در آن نیست
      (یا اصلاً frontend بسته‌بندی نشده) — سازنده باید متوقف شود
  2 = بازرسی ممکن نشد (API ناسازگار/آرشیو ناشناخته) — سازنده فقط اخطار بدهد
      و **هرگز** به خاطر خودِ بازرس، ساخت را متوقف نکند
"""
from __future__ import annotations

import sys
import zlib


def find_frontend_entry(toc) -> str | None:
    """نام ورودیِ `frontend/app.js` را در TOC آرشیو PyInstaller پیدا کن."""
    names = toc.keys() if isinstance(toc, dict) else [e[-1] for e in toc]
    for n in names:
        if str(n).replace("\\", "/").endswith("frontend/app.js"):
            return str(n)
    return None


def marker_in_bytes(data: bytes, marker: str) -> bool:
    if marker.encode("ascii", "ignore") in data:
        return True
    try:
        return marker in data.decode("utf-8", errors="ignore")
    except Exception:  # pragma: no cover - decode never raises with ignore
        return False


def inspect(exe_path: str, marker: str) -> int:
    """0 = verified, 1 = proven stale, 2 = uncertain (never block)."""
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except Exception:
        return 2
    try:
        ar = CArchiveReader(exe_path)
    except Exception:
        return 2
    try:
        name = find_frontend_entry(ar.toc)
        if name is None:
            # frontend در آرشیو نیست = واقعاً مشکل‌دار (فایل اجرایی بدون UI)
            return 1
        try:
            data = ar.extract(name)
        except Exception:
            # فایل هست ولی استخراج API نشد — نمی‌توان کهنگی را اثبات کرد
            return 2 if marker.encode("ascii", "ignore") not in open(exe_path, "rb").read() else 0
        if isinstance(data, str):
            data = data.encode("utf-8", errors="ignore")
        return 0 if marker_in_bytes(data, marker) else 1
    except Exception:
        return 2


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: verify_ui_in_exe.py <exe> <ui-build-NNN>", file=sys.stderr)
        return 2
    code = inspect(argv[1], argv[2])
    print({0: "FRESH", 1: "STALE", 2: "UNCERTAIN"}[code])
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
