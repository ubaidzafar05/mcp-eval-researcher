import json
from contextlib import nullcontext

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


def test_stream_auto_falls_back_to_inline_when_distributed_unavailable(monkeypatch):
    class DummyGraph:
        async def astream_events(self, *_args, **_kwargs):
            if False:
                yield {}

    async def fake_event_generator(_events):
        yield 'data: {"type":"done","final_emitted":false}\n\n'

    monkeypatch.setattr("service.api._distributed_available", lambda: True)
    monkeypatch.setattr(
        "service.api.load_config",
        lambda overrides=None: load_config(
            {
                "runtime_profile": "balanced",
                "enable_distributed": True,
                "distributed_auto_enabled": True,
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
    monkeypatch.setattr("service.api.GraphRuntime.from_config", lambda _cfg: nullcontext(object()))
    monkeypatch.setattr("service.api.build_graph", lambda _runtime: DummyGraph())
    monkeypatch.setattr("service.api.build_initial_state", lambda _query, _runtime: {})
    monkeypatch.setattr("service.api.event_generator", fake_event_generator)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/research/stream",
            params={
                "query": "deep research comprehensive benchmark compare ai engineering career",
                "execution_mode": "auto",
            },
        ) as response:
            events = _collect_sse_events(response)

    assert any(event.get("stage") == "starting" for event in events)
    assert any(event.get("stage") == "accepted" for event in events)
    assert any(event.get("stage") == "fallback" for event in events)
    assert any(event.get("type") == "done" for event in events)
