import json

from fastapi.testclient import TestClient

from core.config import load_config
from service.api import app


def _collect_sse_events(response, limit: int = 20) -> list[dict]:
    events: list[dict] = []
    for raw in response.iter_lines():
        if not raw:
            continue
        line = raw.decode() if isinstance(raw, bytes) else raw
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        events.append(json.loads(payload))
        if len(events) >= limit:
            break
    return events


def test_stream_distributed_mode_emits_error_when_not_ready(monkeypatch):
    monkeypatch.setattr("service.api._distributed_available", lambda: True)
    monkeypatch.setattr(
        "service.api.load_config",
        lambda overrides=None: load_config(
            {
                "runtime_profile": "balanced",
                "enable_distributed": True,
                "interactive_hitl": False,
                **(overrides or {}),
            }
        ),
    )
    monkeypatch.setattr(
        "service.api._distributed_helpers",
        lambda: {
            "is_ready": lambda timeout_seconds=2: (False, "No active Celery workers responded to ping."),
            "dispatch": lambda **kwargs: None,
            "wait_result": lambda *args, **kwargs: {},
        },
    )

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/research/stream",
            params={
                "query": "deep research comprehensive benchmark compare ai engineering career",
                "execution_mode": "distributed",
            },
        ) as response:
            events = _collect_sse_events(response)

    assert any(event.get("stage") == "starting" for event in events)
    assert any(event.get("stage") == "accepted" for event in events)
    assert any(event.get("type") == "error" for event in events)
    assert not any(event.get("stage") == "fallback" for event in events)
