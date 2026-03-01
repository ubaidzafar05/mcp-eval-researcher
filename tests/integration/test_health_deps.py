from fastapi.testclient import TestClient

from service.api import app


def test_health_deps_reports_profile_and_subsystems():
    with TestClient(app) as client:
        response = client.get("/health/deps")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["runtime_profile"] in {"minimal", "balanced", "full"}
    assert "subsystems" in payload
    assert set(payload["subsystems"].keys()) == {"distributed", "observability", "storage"}
    for subsystem in payload["subsystems"].values():
        assert "enabled" in subsystem
        assert "ready" in subsystem
        assert "reason" in subsystem

