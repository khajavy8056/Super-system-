"""RASA SYSTEM — backend package (مدیریت سوپرمارکت رسا سیستم / smart supermarket ERP)."""

__version__ = "1.0.524"
#: build-524 — شمارهٔ ساخت (۵۲۴ = 52400). نسخهٔ معنایی تغییر نمی‌کند؛ «عدد سوم»
#: یعنی همین Build. منبع داخلی تشخیص نسخهٔ نصب‌شده برای Update (§۴۱).
#: v1.0.524: re-baselined from 1.0.521 (c1e81ed) and re-applied full audit I-01..I-25 without regressions:
#:   I-01 decimal returns, I-02 tender-aware GL + ledger, I-03 session cash, I-04 profit/PII leak,
#:   I-05 UTC→local_day unify, I-06 cashflow, I-20 invoice counter local-day, I-22 purchase orders (FK fixed),
#:   plus login regression root-cause fix (Api 401 mapping + rate-limit 30/60 + SHA fallback).
BUILD = 52400
