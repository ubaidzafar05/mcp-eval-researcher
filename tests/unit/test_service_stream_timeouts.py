from __future__ import annotations

import asyncio

import pytest

from service.api import _with_heartbeat


@pytest.mark.asyncio
async def test_with_heartbeat_uses_stage_specific_idle_timeout_for_synthesis():
    async def mock_events():
        yield {
            "event": "on_chain_start",
            "metadata": {"langgraph_node": "synthesizer"},
        }
        await asyncio.sleep(1.2)

    events = []
    async for event in _with_heartbeat(
        mock_events(),
        interval_seconds=0.05,
        max_runtime_seconds=0,
        warn_before_idle_ratio=0.5,
        stage_idle_seconds={
            "planning": 1,
            "research": 1,
            "synthesis": 1,
            "evaluation": 1,
            "finalizing": 1,
        },
    ):
        events.append(event)
        if (event.get("data") or {}).get("type") == "error":
            break

    warning_events = [
        item for item in events
        if (item.get("data") or {}).get("type") == "status"
        and (item.get("data") or {}).get("warned_idle") is True
    ]
    assert warning_events
    assert any((item.get("data") or {}).get("active_stage") == "synthesis" for item in warning_events)

    error_events = [item for item in events if (item.get("data") or {}).get("type") == "error"]
    assert error_events
    assert any(
        "idle_timeout_stage_synthesis" in ((item.get("data") or {}).get("reason_codes") or [])
        for item in error_events
    )

