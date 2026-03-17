"""test_model_router.py — Tests for the multi-tier Ollama ModelRouter."""
from agents.model_router import ModelRouter
from core.config import load_config


def test_model_router_always_returns_ollama():
    """Every task type must route to the Ollama provider."""
    cfg = load_config({"interactive_hitl": False, "router_mode": "heuristic"})
    router = ModelRouter(cfg)
    for task_type in ("planning", "research", "synthesis", "correction", "evaluation"):
        selection = router.select_model(
            task_type=task_type,
            context_size=10_000,
            latency_budget_ms=3000,
            tenant_tier="free",
        )
        assert selection.provider == "ollama", f"Expected ollama for {task_type}, got {selection.provider}"
        assert selection.model_name in {
            cfg.ollama_model_fast,
            cfg.ollama_model_primary,
            cfg.ollama_model_deep,
        }


def test_model_router_respects_configured_model():
    """The router must use the model name from config."""
    cfg = load_config(
        {
            "interactive_hitl": False,
            "router_mode": "heuristic",
            "ollama_model_primary": "llama3:latest",
        }
    )
    router = ModelRouter(cfg)
    selection = router.select_model(
        task_type="synthesis",
        context_size=500,
        latency_budget_ms=5000,
        tenant_tier="enterprise",
    )
    assert selection.provider == "ollama"
    assert selection.model_name == "llama3:latest"


def test_model_router_temperature_varies_by_task():
    """Different task types should get different temperatures."""
    cfg = load_config({"interactive_hitl": False, "router_mode": "heuristic"})
    router = ModelRouter(cfg)
    planning = router.select_model(
        task_type="planning", context_size=1000, latency_budget_ms=1000, tenant_tier="free"
    )
    synthesis = router.select_model(
        task_type="synthesis", context_size=1000, latency_budget_ms=1000, tenant_tier="free"
    )
    assert planning.temperature == 0.2
    assert synthesis.temperature == 0.5


def test_model_router_tier_selection_and_downgrade():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "router_mode": "heuristic",
            "router_allow_deep_parallel": False,
        }
    )
    router = ModelRouter(cfg)
    fast = router.select_model(
        task_type="planning", context_size=200, latency_budget_ms=1000, tenant_tier="free"
    )
    assert fast.tier == "fast"
    assert fast.model_name == cfg.ollama_model_fast

    deep = router.select_model(
        task_type="synthesis", context_size=9000, latency_budget_ms=1000, tenant_tier="free", plan_complexity="high"
    )
    assert deep.tier == "deep"
    assert deep.model_name == cfg.ollama_model_deep

    with router.use_tier("primary"):
        downgraded = router.select_model(
            task_type="synthesis",
            context_size=9000,
            latency_budget_ms=1000,
            tenant_tier="free",
            plan_complexity="high",
        )
        assert downgraded.tier == "primary"
        assert downgraded.was_downgraded is True
