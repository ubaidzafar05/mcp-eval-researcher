import time

import pytest

from core.config import load_config
from main import run_research


@pytest.mark.stress
def test_stress_batch_basic():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
        }
    )
    queries = [
        "LangGraph retry routing",
        "Tavily vs DDG retrieval behavior",
        "Rate limit protection for free tier APIs",
    ]
    durations: list[float] = []
    completed = 0
    for query in queries:
        start = time.perf_counter()
        result = run_research(query, config=cfg)
        durations.append(time.perf_counter() - start)
        if result.status != "aborted":
            completed += 1
    assert completed >= 2
    p50 = sorted(durations)[len(durations) // 2]
    assert p50 < 30.0
