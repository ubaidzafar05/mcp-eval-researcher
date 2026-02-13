import sys

from core.config import load_config
from mcp_server.transport_runtime import TransportRuntime


def test_transport_runtime_start_and_probe():
    python = sys.executable
    cfg = load_config(
        {
            "interactive_hitl": False,
            "judge_provider": "stub",
            "mcp_web_server_cmd": f"{python} -m mcp_server.web_stdio_app",
            "mcp_local_server_cmd": f"{python} -m mcp_server.local_stdio_app",
        }
    )
    runtime = TransportRuntime(cfg)
    try:
        runtime.start()
        probe = runtime.startup_probe()
        assert probe.web_connected is True
        assert probe.local_connected is True
        assert "ddg_search" in probe.web_tools
        assert "read_local_file" in probe.local_tools
    finally:
        runtime.close()
