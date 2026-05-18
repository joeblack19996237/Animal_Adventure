from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_status_ok():
    response = client.get("/health")
    assert response.json() == {"status": "ok"}


def test_ready_returns_200():
    response = client.get("/ready")
    assert response.status_code == 200


def test_ready_returns_database_key():
    response = client.get("/ready")
    body = response.json()
    assert "database" in body


def test_ready_returns_config_key():
    response = client.get("/ready")
    body = response.json()
    assert "config" in body


def test_ready_returns_websocket_key():
    response = client.get("/ready")
    body = response.json()
    assert "websocket" in body


def test_ready_returns_status_ready_when_all_ok():
    response = client.get("/ready")
    body = response.json()
    assert body.get("status") == "ready"
