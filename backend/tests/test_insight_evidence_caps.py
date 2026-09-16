# -*- coding: utf-8 -*-
"""v3.5.9 — the «هوش فروشگاه» evidence payloads must stay bounded.

Why this file exists
--------------------
The Android detail screen turns ``evidence["table"]`` into a ``Chart.bars`` view whose
height is 30dp per row. The SUPPLIER generator used to put *every* wholesaler in that
table with no cap, so a store with many suppliers produced a view taller than the
Android canvas limit — that is what hung and then killed the screen. The cap now lives
in the service, and it is tested here against the REAL generator through the REAL API,
because a cap that is never exercised by any test is a cap that will be removed.
"""

SUPPLIER_COUNT = 30
PRODUCT_COUNT = 5
EVIDENCE_CAP = 25   # mirrors the cap in app/services/insights.py


def test_supplier_insight_evidence_table_is_capped(client, auth_headers):
    sup_ids = []
    for i in range(SUPPLIER_COUNT):
        r = client.post("/api/accounting/suppliers", json={"name": f"StressSupplier {i:02d}"},
                        headers=auth_headers)
        assert r.status_code == 201, r.text
        sup_ids.append(r.json()["id"])

    for p in range(PRODUCT_COUNT):
        r = client.post("/api/products", json={"barcode": f"6269900{p:06d}",
                                               "name": f"StressGoods {p}"}, headers=auth_headers)
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        for i, sid in enumerate(sup_ids):
            # supplier i buys ~1 % dearer than the cheapest, so the dearest ends up ~29 %
            # over the best price for the same goods and scores far below 70 — which is what
            # makes the generator emit a row for it at all.
            rr = client.post("/api/batches/receive", headers=auth_headers, json={
                "product_id": pid, "quantity_received": 10, "buy_price": 10000 + i * 100,
                "sell_price": 40000, "supplier_id": sid})
            assert rr.status_code == 201, rr.text

    r = client.post("/api/insights/run", json={}, headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/insights", params={"status": "ALL", "limit": 500}, headers=auth_headers)
    assert r.status_code == 200, r.text
    sup_insights = [x for x in r.json() if x["kind"] == "SUPPLIER"]
    assert sup_insights, ("expected at least one SUPPLIER insight from "
                          f"{SUPPLIER_COUNT} differently-priced wholesalers")

    for x in sup_insights:
        table = x["evidence"].get("table", [])
        assert table, "the cap must trim the table, not empty it"
        assert len(table) <= EVIDENCE_CAP, (
            f"SUPPLIER evidence table has {len(table)} rows; the Android chart view is "
            "30dp per row and cannot draw that — this is the hang that v3.5.9 fixed")
        # The suggestion is ABOUT the worst supplier; the cap must not cut out its own subject.
        assert any(row["name"] in x["title"] for row in table), (
            "the worst supplier was trimmed out of its own evidence table")

    # Guard against this test going vacuous: the generator only drops suppliers with fewer
    # than 3 batches, and every supplier here got 5, so all SUPPLIER_COUNT must have
    # qualified. That is more than EVIDENCE_CAP, so a trim is guaranteed to have happened —
    # if this assertion ever fails, the cap is no longer being exercised at all.
    trimmed = [x for x in sup_insights if len(x["evidence"].get("table", [])) == EVIDENCE_CAP]
    assert trimmed, (f"no SUPPLIER table was trimmed to {EVIDENCE_CAP}; with {SUPPLIER_COUNT} "
                     "qualifying wholesalers the cap should have bitten — this test would "
                     "otherwise pass without testing anything")


def test_measured_feed_payload_stays_small(client, auth_headers):
    """The tab that used to hang asks for up to 80 accepted/measured suggestions at once.

    Every card the phone builds carries a daily before/after series, so an unbounded
    series would blow up both the JSON and the number of points the chart walks.
    """
    r = client.get("/api/insights", params={"status": "ACCEPTED,MEASURED", "limit": 80},
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) <= 80
    for x in rows:
        daily = (x.get("result") or {}).get("daily") or {}
        points = len(daily.get("before") or []) + len(daily.get("after") or [])
        assert points <= 61, f"insight {x.get('id')} ships {points} chart points; _daily_series caps at 60"
