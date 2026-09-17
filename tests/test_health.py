from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_serves_the_patients_page():
    """The API serves the frontend at / so the UI is same-origin."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Patients" in response.text


def test_static_mount_does_not_shadow_the_api():
    """The mount is added last, so API routes still match first."""
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_unknown_path_is_a_404_not_the_page():
    assert client.get("/no-such-file.js").status_code == 404


def test_health_returns_ok():
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_openapi_schema_is_served():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
