def test_login_ok(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_bad_password(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_me(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert "Administrator" in r.json()["roles"]


def test_protected_route_requires_token(client):
    r = client.get("/api/products")
    assert r.status_code == 401
