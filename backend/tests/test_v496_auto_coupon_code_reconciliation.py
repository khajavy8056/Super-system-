"""An offline POS reuses its reserved next-purchase coupon code after sync."""


def test_pos_checkout_reuses_client_reserved_auto_coupon_code(client, auth_headers):
    product_response = client.post("/api/products", headers=auth_headers, json={
        "barcode": "6260000496001", "name": "Build 496 coupon sync item",
    })
    assert product_response.status_code == 201, product_response.text
    product = product_response.json()
    batch_response = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": product["id"], "quantity_received": 5,
        "buy_price": 40000, "sell_price": 100000,
    })
    assert batch_response.status_code == 201, batch_response.text

    campaign_response = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "Build 496 next-purchase code",
        "discount_type": "PERCENT", "discount_value": 10,
        "auto_issue_threshold": 50000, "auto_issue_validity_days": 14,
        "auto_issue_sms": False,
    })
    assert campaign_response.status_code == 201, campaign_response.text
    campaign_id = str(campaign_response.json()["id"])
    reserved_code = "NEXT-ABCDEFGH"

    checkout = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "batch_id": batch_response.json()["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 100000}],
        "client_issued_coupon_codes": {campaign_id: reserved_code},
    })
    assert checkout.status_code == 201, checkout.text
    assert checkout.json()["issued_coupon"]["code"] == reserved_code

    stored = client.get("/api/marketing/coupons", headers=auth_headers,
                        params={"q": reserved_code})
    assert stored.status_code == 200, stored.text
    assert stored.json()[0]["code"] == reserved_code
    assert stored.json()[0]["campaign_id"] == int(campaign_id)
