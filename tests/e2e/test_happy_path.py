from pathlib import Path

from core.config import load_config
from main import run_research


def test_e2e_happy_path_creates_artifacts():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
        }
    )
    result = run_research("Design robust free-tier LLM pipelines", config=cfg)
    assert result.final_report
    assert len(result.citations) >= 1
    artifacts = Path(result.artifacts_path)
    assert artifacts.exists()
    assert (artifacts / "eval.json").exists()
    assert (artifacts / "citations.json").exists()
