from fastapi.testclient import TestClient


REGISTER_PAYLOAD = {
    "email": "persona@example.com",
    "password": "una-clave-segura",
    "full_name": "Persona Ejemplo",
    "organization_name": "Agencia Local",
}


def test_register_creates_user_and_starter_organization(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "persona@example.com"
    assert body["role"] == "owner"
    assert body["organization"] == {
        "id": 1,
        "name": "Agencia Local",
        "plan": "starter",
        "max_profiles": 3,
    }
    assert "password" not in body
    assert "password_hash" not in body


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    assert client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD).status_code == 201
    response = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 409


def test_login_and_get_current_user(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["organization"]["name"] == "Agencia Local"


def test_invalid_login_and_missing_token_are_rejected(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "clave-incorrecta"},
    )
    assert login.status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


def test_registration_validates_inputs(client: TestClient) -> None:
    payload = {**REGISTER_PAYLOAD, "email": "no-es-email", "password": "corta"}
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
