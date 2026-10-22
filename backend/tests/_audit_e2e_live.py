# -*- coding: utf-8 -*-
"""Independent end-to-end audit probe (2026-10) — run against a LIVE server.

Every expected number below is computed by hand from the business rules in the
README/blueprint and NOT read from the implementation, so a passing assert is
real evidence rather than a tautology.

    RASA_URL=http://127.0.0.1:8000 python tests/_audit_e2e_live.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

import httpx

BASE = os.environ.get("RASA_URL", "http://127.0.0.1:8000")
C = httpx.Client(base_url=BASE, timeout=30.0,
                  limits=httpx.Limits(max_keepalive_connections=1, max_connections=4))

RESULTS: list[tuple[str, str, str]] = []   # (id, status, note)


def ok(tid: str, note: str = "") -> None:
    RESULTS.append((tid, "PASS", note))
    print(f"  PASS  {tid} {note}")


def fail(tid: str, note: str) -> None:
    RESULTS.append((tid, "FAIL", note))
    print(f"  FAIL  {tid} {note}")


def check(tid: str, cond: bool, note: str = "") -> None:
    (ok if cond else fail)(tid, note)


def main() -> int:
    r = C.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        print("cannot log in:", r.status_code, r.text[:200])
        return 2
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}

    today = date.today()
    print("\n== A. catalogue + receiving ==")
    import random
    bc = "AUD9" + "".join(str(random.randint(0, 9)) for _ in range(9))
    r = C.post("/api/products", headers=H, json={
        "barcode": bc, "name": "برنج آزمون مستقل", "min_stock": 2})
    check("A1-product-create", r.status_code == 201, f"{r.status_code} {r.text[:160]}")
    if r.status_code != 201:
        _summary(); return 1
    p = r.json()
    pid = p["id"]

    # two batches: B expires sooner and costs more (FEFO must pick B)
    r = C.post("/api/batches/receive", headers=H, json={
        "product_id": pid, "quantity_received": 10, "buy_price": 100000,
        "sell_price": 150000, "expiry_date": (today + timedelta(days=30)).isoformat()})
    check("A2-receive-A", r.status_code == 201, f"{r.status_code} {r.text[:120]}")
    a = r.json()
    r = C.post("/api/batches/receive", headers=H, json={
        "product_id": pid, "quantity_received": 5, "buy_price": 120000,
        "sell_price": 160000, "expiry_date": (today + timedelta(days=5)).isoformat()})
    check("A3-receive-B", r.status_code == 201, f"{r.status_code} {r.text[:120]}")
    b = r.json()

    r = C.get(f"/api/products/{pid}/detail", headers=H)
    check("A4-stock-is-sum-of-batches", float(r.json().get("total_stock", -1)) == 15.0,
          f"total_stock={r.json().get('total_stock')} expected 15")

    print("\n== B. POS: FEFO allocation, exact money ==")
    r = C.post("/api/pos/cart/validate", headers=H, json={"items": [{"product_id": pid, "quantity": 3}]})
    check("B1-validate-ok", r.status_code == 200, f"{r.status_code} {r.text[:160]}")
    if r.status_code == 200:
        v = r.json()
        lines = v.get("items", [])
        exp_batch = b.get("id")
        check("B2-fefo-picks-nearest-expiry", len(lines) == 1 and lines[0]["batch_id"] == exp_batch,
              f"batch={lines[0]['batch_id'] if lines else None} expected {exp_batch}")
        check("B3-gross-3x160000", float(v["totals"]["gross"]) == 480000.0, f"{v['totals']}")
        check("B4-profit-3x(160000-120000)", float(v["totals"]["profit"]) == 120000.0,
              f"{v['totals']['profit']}")

    r = C.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": pid, "quantity": 3}],
        "payments": [{"method": "CASH", "amount": 480000}]})
    check("B5-checkout-201", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    inv1 = r.json() if r.status_code == 201 else {}
    check("B6-total-480000", float(inv1.get("total_amount", 0)) == 480000.0, f"{inv1.get('total_amount')}")
    check("B7-payment-PAID", inv1.get("payment_status") == "PAID", f"{inv1.get('payment_status')}")
    check("B8-invoice-number-format", str(inv1.get("invoice_number", "")).startswith("INV-"),
          f"{inv1.get('invoice_number')}")

    r = C.get(f"/api/products/{pid}/detail", headers=H)
    check("B9-stock-15-3=12", float(r.json().get("total_stock", -1)) == 12.0,
          f"{r.json().get('total_stock')}")

    print("\n== C. discounts + tax math ==")
    # 2 units from B @160000 = 320000, line discount 20000, invoice discount 30000,
    # tax 9% → taxable 270000, tax 24300, total 294300
    r = C.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": pid, "quantity": 2, "batch_id": b["id"], "discount": 20000}],
        "payments": [{"method": "CASH", "amount": 294300}],
        "invoice_discount": 30000, "tax_rate": 9})
    check("C1-checkout-discount-tax", r.status_code == 201, f"{r.status_code} {r.text[:250]}")
    if r.status_code == 201:
        inv2 = r.json()
        check("C2-subtotal-gross-320000", float(inv2["subtotal"]) == 320000.0, f"{inv2['subtotal']}")
        check("C3-discount-50000-once", float(inv2["discount"]) == 50000.0, f"{inv2['discount']}")
        check("C4-tax-24300", abs(float(inv2["tax"]) - 24300.0) < 0.01, f"{inv2['tax']}")
        check("C5-total-294300", abs(float(inv2["total_amount"]) - 294300.0) < 0.01,
              f"{inv2['total_amount']}")
        check("C6-line-profit-nets-line-discount-only",
              abs(float(inv2["items"][0]["profit"]) - ((160000 - 120000) * 2 - 20000)) < 0.01,
              f"{inv2['items'][0]['profit']} expected 60000")

    r = C.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": pid, "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 1}]})
    check("C7-payment-mismatch-rejected", r.status_code == 422, f"{r.status_code} {r.text[:160]}")

    print("\n== D. overstock / boundary ==")
    r = C.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": pid, "quantity": 9999}],
        "payments": [{"method": "CASH", "amount": 1}]})
    check("D1-oversell-rejected", r.status_code == 422 and "INSUFFICIENT_STOCK" in r.text,
          f"{r.status_code} {r.text[:160]}")
    r = C.post("/api/pos/checkout", headers=H, json={"items": [], "payments": []})
    check("D2-empty-cart-rejected", r.status_code == 422, f"{r.status_code}")
    r = C.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": pid, "quantity": 0}], "payments": []})
    check("D3-zero-qty-rejected", r.status_code == 422, f"{r.status_code} {r.text[:120]}")

    print("\n== E. void restores stock exactly ==")
    before = float(C.get(f"/api/products/{pid}/detail", headers=H).json().get("total_stock", -1))
    r = C.post(f"/api/invoices/{inv1['invoice_id']}/void", headers=H,
               json={"reason": "audit probe", "admin_password": "admin123"})
    check("E1-void-ok", r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}")
    after = float(C.get(f"/api/products/{pid}/detail", headers=H).json().get("total_stock", -1))
    check("E2-void-restores-3", abs(after - (before + 3)) < 0.001, f"{before} -> {after}")

    print("\n== F. reports agree with invoices ==")
    r = C.get("/api/reports/sales", headers=H, params={"start": today.isoformat(),
                                                       "end": today.isoformat()})
    check("F1-sales-report", r.status_code == 200, f"{r.status_code}")
    if r.status_code == 200:
        body = r.json()
        rows = body.get("rows") or body.get("invoices") or []
        paid = [x for x in rows if x.get("status") != "VOID"]
        live_total = sum(float(x["total"]) for x in paid)
        expect = 294300.0  # inv1 voided; inv2 is the only live invoice for this product today
        # the shop DB may hold other invoices; compare against this product's own total
        check("F2-report-includes-live-invoice", live_total >= expect - 0.01,
              f"report_total={live_total} >= {expect}")

    print("\n== G. ledger / credit sale ==")
    r = C.post("/api/customers", headers=H, json={
        "name": "مشتری آزمون", "phone": "0912" + str(int(today.strftime("%d%H%M%S")))})
    check("G1-customer-create", r.status_code == 201, f"{r.status_code} {r.text[:160]}")
    cust = r.json()
    cid = cust["id"]
    r = C.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": pid, "quantity": 1}],
        "payments": [{"method": "ACCOUNT", "amount": 160000}],
        "customer_id": cid})
    check("G2-credit-sale", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 201:
        check("G3-credit-invoice-not-PAID", r.json()["payment_status"] == "ON_ACCOUNT",
              f"{r.json()['payment_status']}")
    r = C.get(f"/api/customers/{cid}/ledger", headers=H)
    bal = float(r.json().get("balance", -1)) if r.status_code == 200 else None
    check("G4-ledger-balance-160000", bal == 160000.0, f"balance={bal}")
    r = C.get(f"/api/customers/{cid}/ledger/verify", headers=H)
    check("G5-ledger-integrity", r.status_code == 200 and r.json().get("ok") is True,
          f"{r.status_code} {str(r.json())[:160]}")
    r = C.post(f"/api/customers/{cid}/settle", headers=H,
               json={"amount": 160000, "method": "CASH"})
    check("G6-settle", r.status_code in (200, 201), f"{r.status_code} {r.text[:160]}")
    bal = float(C.get(f"/api/customers/{cid}/ledger", headers=H).json().get("balance", -1))
    check("G7-settled-to-zero", bal == 0.0, f"{bal}")
    r = C.post(f"/api/customers/{cid}/settle", headers=H, json={"amount": 1000, "method": "CASH"})
    check("G8-overpay-rejected", r.status_code >= 400, f"{r.status_code} {r.text[:160]}")

    print("\n== H. walk-in cannot buy on account ==")
    r = C.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": pid, "quantity": 1}],
        "payments": [{"method": "ACCOUNT", "amount": 160000}]})
    check("H1-walkin-account-rejected", r.status_code == 422, f"{r.status_code} {r.text[:200]}")

    print("\n== I. accounting integrity ==")
    r = C.get("/api/accounting/trial-balance", headers=H)
    check("I1-trial-balance", r.status_code == 200, f"{r.status_code}")
    if r.status_code == 200:
        tb = r.json()
        check("I2-trial-balanced", abs(float(tb.get("total_debit", 0)) - float(tb.get("total_credit", 0))) < 0.01,
              f"debit={tb.get('total_debit')} credit={tb.get('total_credit')}")
    r = C.get("/api/accounting/balance-sheet", headers=H)
    if r.status_code == 200:
        bs = r.json()
        check("I3-balance-sheet-balances",
              abs(float(bs.get("total_assets", 0)) - (float(bs.get("total_liabilities", 0)) + float(bs.get("total_equity", 0)))) < 0.01,
              f"assets={bs.get('total_assets')} L+E={float(bs.get('total_liabilities',0))+float(bs.get('total_equity',0))}")

    print("\n== J. permissions (RBAC) ==")
    uname = "audcash" + "".join(str(random.randint(0,9)) for _ in range(8))
    r = C.post("/api/users", headers=H, json={
        "username": uname, "password": "pass1234", "full_name": "Audit Cashier",
        "roles": ["Cashier"]})
    check("J1-create-cashier", r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}")
    r = C.post("/api/auth/login", data={"username": uname, "password": "pass1234"})
    check("J2-cashier-login", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        CH = {"Authorization": f"Bearer {r.json()['access_token']}"}
        for tid, path in [
            ("J3-cashier-no-settings", "/api/settings"),
            ("J4-cashier-no-users", "/api/users"),
            ("J5-cashier-no-accounting", "/api/accounting/journal"),
            ("J6-cashier-no-audit", "/api/audit"),
        ]:
            rr = C.get(path, headers=CH)
            check(tid, rr.status_code == 403, f"{path} -> {rr.status_code}")
        rr = C.post("/api/pos/checkout", headers=CH, json={
            "items": [{"product_id": pid, "quantity": 1}],
            "payments": [{"method": "CASH", "amount": 160000}]})
        check("J7-cashier-can-sell", rr.status_code == 201, f"{rr.status_code} {rr.text[:200]}")
        rr = C.get("/api/accounting/trial-balance", headers=CH)
        check("J8-cashier-no-trial-balance", rr.status_code == 403, f"{rr.status_code}")
    r = C.post("/api/pos/checkout", headers={"Authorization": "Bearer garbage"},
               json={"items": [], "payments": []})
    check("J9-bad-token-401", r.status_code in (401, 403), f"{r.status_code} {r.text[:120]}")
    r = C.get("/api/products")
    check("J10-anonymous-401", r.status_code in (401, 403), f"{r.status_code}")

    print("\n== K. schema exposure gate (I-18) ==")
    r = C.get("/openapi.json")
    check("K1-openapi-anonymous-hidden", r.status_code == 404, f"{r.status_code}")
    r = C.get("/openapi.json", headers={"Authorization": "Bearer not-a-real-token"})
    check("K2-openapi-garbage-token-hidden", r.status_code == 404,
          f"{r.status_code} — a fake bearer must not open the schema")

    print("\n== L. insights / intelligence ==")
    r = C.get("/api/insights", headers=H)
    check("L1-insights-list", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
    r = C.get("/api/insights/summary", headers=H)
    check("L2-insights-summary", r.status_code in (200, 404), f"{r.status_code}")
    if r.status_code == 200:
        s = r.json()
        print("     summary keys:", list(s)[:12])

    print("\n== M. backup ==")
    r = C.post("/api/system/backup", headers=H)
    check("M1-backup", r.status_code in (200, 201), f"{r.status_code} {r.text[:160]}")

    _summary()
    return 0 if all(s == "PASS" for _, s, _ in RESULTS) else 1


def _summary() -> None:
    print("\n" + "=" * 60)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    print(f"RESULT: {passed}/{len(RESULTS)} passed")
    for tid, s, note in RESULTS:
        if s != "PASS":
            print(f"  !! {tid}: {note}")


if __name__ == "__main__":
    sys.exit(main())
