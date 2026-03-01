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
            branch_coverage={
                "subtopic_count": len(state.get("subtopics", [])),
                "subtopic_success_count": len(state.get("sub_reports", [])),
                "subtopic_failed_count": max(
                    0,
                    len(state.get("subtopics", [])) - len(state.get("sub_reports", [])),
                ),
                "failures": list(state.get("subtopic_failures", [])),
            },
        )
        subtopic_count = len(state.get("subtopics", []))
        subtopic_success = len(state.get("sub_reports", []))
        subtopic_failed = max(0, subtopic_count - subtopic_success)
        branch_failure_labels = list(state.get("subtopic_failures", []))
        if subtopic_count > 0 and subtopic_failed > 0:
            reasons = list(result.reasons or [])
            reasons.append(
                f"Subtopic coverage degraded: {subtopic_success}/{subtopic_count} branches completed."
            )
            result.reasons = list(dict.fromkeys(reasons))
            result.meta = dict(result.meta or {})
            result.meta["branch_coverage"] = {
                "subtopic_count": subtopic_count,
                "subtopic_success_count": subtopic_success,
                "subtopic_failed_count": subtopic_failed,
                "failures": branch_failure_labels,
            }
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
                "reason_count": len(result.reasons),
            },
        )
        metrics = dict(state.get("metrics", {}))
        eval_meta = dict(result.meta or {})
        provider_alerts = list(state.get("provider_alerts", []))
        constrained_codes = list(eval_meta.get("reason_codes", []))
        quality_failure_buckets = [
            code
            for code in constrained_codes
            if code
            in {
                "placeholder_content",
                "verification_floor",
                "primary_source_floor",
                "narrative_directness",
                "insight_density_low",
                "mechanics_overuse_top_sections",
                "verified_floor_top_sections",
                "ctier_overuse_top_sections",
            }
        ]
        if subtopic_count > 0 and subtopic_failed > 0:
            constrained_codes = list(dict.fromkeys([*constrained_codes, "subtopic_partial_failure"]))
        if any(alert == "provider_quota_exhausted:tavily" for alert in provider_alerts):
            constrained_codes = list(dict.fromkeys([*constrained_codes, "provider_quota_exhausted"]))
        metrics.update(
            {
                "faithfulness": result.faithfulness,
                "relevancy": result.relevancy,
                "citation_coverage": result.citation_coverage,
                "provider_floor_met": bool(eval_meta.get("source_ok_for_gate", eval_meta.get("source_ok", False))),
                "judge_fallback_used": bool(eval_meta.get("judge_fallback_used", False)),
                "constrained_reason_codes": constrained_codes,
                "quality_failure_buckets": quality_failure_buckets,
                "provider_alerts": provider_alerts,
                "subtopic_count": subtopic_count,
                "subtopic_success_count": subtopic_success,
                "subtopic_failed_count": subtopic_failed,
                "subtopic_reason_codes": branch_failure_labels,
            }
        )
        return {
            "eval_result": result,
            "needs_correction": needs_retry,
            "low_confidence": low_confidence,
            "metrics": metrics,
            "status": "evaluated",
            "logs": [
                f"Eval gate pass={result.pass_gate} retry={needs_retry} reasons={len(result.reasons)}."
            ],
        }

    return eval_gate_node
