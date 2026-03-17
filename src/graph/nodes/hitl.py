from __future__ import annotations

from collections.abc import Callable

from graph.runtime import GraphRuntime
from graph.state import ResearchState

HITLInputProvider = Callable[[ResearchState], str]


def create_hitl_node(
    runtime: GraphRuntime,
    input_provider: HITLInputProvider | None = None,
):
    def hitl_node(state: ResearchState) -> dict:
        if not state.get("low_confidence", False):
            return {"hitl_decision": "accept", "logs": ["HITL skipped (high confidence)."]}

        used_retry = bool(state.get("hitl_retry_used", False))
        if runtime.config.hitl_mode == "never":
            decision = "accept_with_warning"
        elif runtime.config.interactive_hitl and input_provider is not None:
            decision = input_provider(state).strip().lower()
        else:
            decision = "accept_with_warning"

        if decision not in {"accept", "accept_with_warning", "retry", "abort"}:
            decision = "accept_with_warning"
        if decision == "retry" and used_retry:
            decision = "accept_with_warning"

        runtime.tracer.event(
            state["run_id"],
            "hitl",
            "HITL decision resolved",
            payload={"decision": decision, "retry_used": used_retry},
        )
        return {
            "hitl_decision": decision,
            "hitl_retry_used": used_retry or decision == "retry",
            "status": "hitl",
            "logs": [f"HITL decision: {decision}"],
        }

    return hitl_node

