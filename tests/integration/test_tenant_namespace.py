from core.config import load_config
from main import run_research


def test_tenant_artifacts_are_namespaced():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
            "tenant_id": "acme",
        }
    )
    result = run_research("tenant namespace test", config=cfg)
    normalized = result.artifacts_path.replace("\\", "/")
    assert "/acme/" in f"/{normalized}/"
    assert result.tenant_id == "acme"
