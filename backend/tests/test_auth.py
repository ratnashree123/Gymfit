from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def test_login_success_returns_token_and_user(client, make_user):
    make_user("Admin", ADMIN_EMAIL, ADMIN_PASSWORD, full_name="Main Admin")
    response = client.post("/api/auth/login", data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["role"] == "Admin"
    assert "password" not in response.text.lower()


def test_login_email_is_case_insensitive(client, make_user):
    make_user("Admin", ADMIN_EMAIL, ADMIN_PASSWORD)
    response = client.post("/api/auth/login", data={"username": "ADMIN@GymFit.com", "password": ADMIN_PASSWORD})
    assert response.status_code == 200


def test_login_wrong_password_returns_401(client, make_user):
    make_user("Admin", ADMIN_EMAIL, ADMIN_PASSWORD)
    response = client.post("/api/auth/login", data={"username": ADMIN_EMAIL, "password": "WrongPass123"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_login_unknown_email_gives_same_message(client):
    response = client.post("/api/auth/login", data={"username": "nobody@gymfit.com", "password": "Whatever123"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_login_disabled_account_returns_403(client, make_user):
    make_user("Receptionist", "rec@gymfit.com", "RecPass123", active=False)
    response = client.post("/api/auth/login", data={"username": "rec@gymfit.com", "password": "RecPass123"})
    assert response.status_code == 403


def test_repeated_failures_are_rate_limited(client, make_user):
    make_user("Admin", ADMIN_EMAIL, ADMIN_PASSWORD)
    for _ in range(5):
        assert client.post("/api/auth/login", data={"username": ADMIN_EMAIL, "password": "Bad12345"}).status_code == 401
    blocked = client.post("/api/auth/login", data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_rejects_garbage_token(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert response.status_code == 401


def test_me_returns_current_user(client, admin_headers):
    response = client.get("/api/auth/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["email"] == ADMIN_EMAIL


def test_change_password_flow(client, admin_headers):
    ok = client.post("/api/auth/change-password", headers=admin_headers,
                     json={"current_password": ADMIN_PASSWORD, "new_password": "BrandNewPass9"})
    assert ok.status_code == 200
    assert client.post("/api/auth/login", data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", data={"username": ADMIN_EMAIL, "password": "BrandNewPass9"}).status_code == 200


def test_change_password_wrong_current(client, admin_headers):
    response = client.post("/api/auth/change-password", headers=admin_headers,
                           json={"current_password": "NotMyPassword1", "new_password": "BrandNewPass9"})
    assert response.status_code == 400


def test_change_password_weak_new_password(client, admin_headers):
    response = client.post("/api/auth/change-password", headers=admin_headers,
                           json={"current_password": ADMIN_PASSWORD, "new_password": "short"})
    assert response.status_code == 422
    assert "short" not in response.text  # the submitted value is never echoed back


def test_logout_is_recorded(client, admin_headers):
    assert client.post("/api/auth/logout", headers=admin_headers).status_code == 200
