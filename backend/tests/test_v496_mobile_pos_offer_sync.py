"""POS-only offline rule snapshots remain permission-scoped on native sync."""
from tests.test_v488_people import _login, _mkuser


def test_mobile_sync_pulls_campaign_and_coupon_rules_only_for_pos_users(client, auth_headers):
    campaign = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "Build 496 offline campaign", "discount_type": "PERCENT", "discount_value": 10,
        "target_type": "ALL", "stackable": True, "per_customer_limit": 2,
    })
    assert campaign.status_code == 201, campaign.text
    coupon = client.post("/api/marketing/coupons", headers=auth_headers, json={
        "code": "B496OFFLINE", "campaign_id": campaign.json()["id"],
        "discount_type": "FIXED", "discount_value": 500, "usage_limit": 2,
    })
    assert coupon.status_code == 201, coupon.text
    customer = client.post("/api/customers", headers=auth_headers, json={
        "name": "Build 496 offline target", "phone": "0912000496",
    })
    assert customer.status_code == 201, customer.text
    targeted_coupon = client.post("/api/marketing/coupons", headers=auth_headers, json={
        "code": "B496TARGET", "customer_id": customer.json()["id"],
        "discount_type": "FIXED", "discount_value": 250, "usage_limit": 1,
    })
    assert targeted_coupon.status_code == 201, targeted_coupon.text

    _mkuser(client, auth_headers, "b496_pos_sync", roles=["Cashier"])
    pos_sync = client.post("/api/mobile/sync", headers=_login(client, "b496_pos_sync", "pass1234"),
                           json={"pull": True, "limit": 2000})
    assert pos_sync.status_code == 200, pos_sync.text
    pulled = pos_sync.json()["pull"]
    assert pulled["pos_config"]["tax_rate"] == "0"
    assert any(row["id"] == campaign.json()["id"] for row in pulled["pos_campaigns"])
    assert any(row["code"] == "B496OFFLINE" for row in pulled["pos_coupons"])
    target_snapshot = next(row for row in pulled["pos_coupons"] if row["code"] == "B496TARGET")
    assert target_snapshot["customer_id"] == customer.json()["id"]
    assert target_snapshot["customer_phone"] == "0912000496"
    snapshot_campaign = next(row for row in pulled["pos_campaigns"] if row["id"] == campaign.json()["id"])
    assert snapshot_campaign["auto_issue_validity_days"] == 30
    assert snapshot_campaign["auto_issue_sms"] is True
    assert "pos_campaign_redemptions" in pulled

    _mkuser(client, auth_headers, "b496_no_pos_sync", roles=[], permissions=["reports.view"])
    no_pos_sync = client.post("/api/mobile/sync", headers=_login(client, "b496_no_pos_sync", "pass1234"),
                              json={"pull": True, "limit": 2000})
    assert no_pos_sync.status_code == 200, no_pos_sync.text
    assert "pos_config" not in no_pos_sync.json()["pull"]
    assert "pos_campaigns" not in no_pos_sync.json()["pull"]
    assert "pos_coupons" not in no_pos_sync.json()["pull"]
