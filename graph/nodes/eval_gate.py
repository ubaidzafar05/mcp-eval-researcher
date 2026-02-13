from __future__ import annotations

from evals.deepeval_node import DeepEvalNode
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def create_eval_gate_node(runtime: GraphRuntime):
    evaluator = DeepEvalNode(runtime.config, runtime=runtime)

    def eval_gate_node(state: ResearchState) -> dict:
        result = evaluator.evaluate(
            query=state["query"],
            report=state.get("report_draft", ""),
            citations=state.get("citations", []),
        )
        correction_count = int(state.get("correction_count", 0))
        needs_retry = (not result.pass_gate) and (
            correction_count < runtime.config.correction_loop_limit
        )
        low_confidence = (not result.pass_gate) and (not needs_retry)
        runtime.tracer.event(
            state["run_id"],
            "eval_gate",
            "Evaluation scored",
            payload={
                "faithfulness": result.faithfulness,
                "relevancy": result.relevancy,
                "citation_coverage": result.citation_coverage,
                "pass_gate": result.pass_gate,
                "needs_retry": needs_retry,
            },
        )
        return {
            "eval_result": result,
            "needs_correction": needs_retry,
            "low_confidence": low_confidence,
            "metrics": {
                "faithfulness": result.faithfulness,
                "relevancy": result.relevancy,
                "citation_coverage": result.citation_coverage,
            },
            "status": "evaluated",
            "logs": [f"Eval gate pass={result.pass_gate} retry={needs_retry}."],
        }

    return eval_gate_node

