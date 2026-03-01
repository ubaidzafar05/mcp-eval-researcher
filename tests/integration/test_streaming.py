import pytest

from mcp_server.sse import event_generator


@pytest.mark.asyncio
async def test_event_generator_emits_final_payload_and_done():
    async def mock_events():
        yield {"event": "on_chat_model_stream", "data": {"chunk": type("Chunk", (), {"content": "tok"})()}}
        yield {
            "event": "on_chain_end",
            "data": {
                "output": {
                    "run_id": "run-123",
                    "status": "completed",
                    "final_report": "Final report body",
                    "artifacts_path": "outputs/run-123",
                }
            },
        }

    chunks: list[str] = []
    async for chunk in event_generator(mock_events()):
        chunks.append(chunk)

    payload = "".join(chunks)
    assert '"type": "token"' in payload
    assert '"stage": "final"' in payload
    assert '"final_report": "Final report body"' in payload
    assert '"type": "done"' in payload
