from agents.model_router import ModelRouter
from core.config import load_config


def test_model_router_enterprise_synthesis_prefers_anthropic():
    cfg = load_config({"interactive_hitl": False})
    router = ModelRouter(cfg)
    provider, model = router.select_model(
        task_type="synthesis",
        context_size=20_000,
        latency_budget_ms=3000,
        tenant_tier="enterprise",
    )
    assert provider == "anthropic"
    assert "claude" in model


def test_model_router_latency_optimized_prefers_groq():
    cfg = load_config({"interactive_hitl": False, "model_routing_strategy": "latency_optimized"})
    router = ModelRouter(cfg)
    provider, _ = router.select_model(
        task_type="evaluation",
        context_size=10_000,
        latency_budget_ms=500,
        tenant_tier="free",
    )
    assert provider == "groq"


def test_model_router_cost_strategy_can_use_local():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "model_routing_strategy": "cost_optimized",
            "enable_local_llm": True,
        }
    )
    router = ModelRouter(cfg)
    provider, model = router.select_model(
        task_type="correction",
        context_size=10_000,
        latency_budget_ms=5000,
        tenant_tier="pro",
    )
    assert provider == "local"
    assert model == "local-default"
