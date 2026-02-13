from __future__ import annotations

from collections.abc import Iterable
from time import perf_counter

from core.config import load_config
from core.metrics import record_graph_run
from core.models import Citation, EvalResult, ResearchResult, RunConfig
from core.retention import cleanup_old_artifacts
from core.run_registry import load_result_from_artifacts, upsert_registry_record
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def _as_citations(values: Iterable[object]) -> list[Citation]:
    out: list[Citation] = []
    for value in values:
        if isinstance(value, Citation):
            out.append(value)
        else:
            out.append(Citation.model_validate(value))
    return out


def _default_hitl_input(state: dict) -> str:
    from rich.prompt import Prompt

    return Prompt.ask(
        "Low-confidence output detected. Choose action",
        choices=["accept", "accept_with_warning", "retry", "abort"],
        default="accept_with_warning",
    )


def run_research(query: str, *, config: RunConfig | None = None) -> ResearchResult:
    cfg = config or load_config()
    hitl_input_provider = _default_hitl_input if cfg.interactive_hitl else None
    started = perf_counter()
    with GraphRuntime.from_config(cfg) as runtime:
        final_state = run_graph(query, runtime, hitl_input_provider=hitl_input_provider)

    citations = _as_citations(final_state.get("citations", []))
    eval_state = final_state.get("eval_result") or EvalResult()
    eval_result = (
        eval_state
        if isinstance(eval_state, EvalResult)
        else EvalResult.model_validate(eval_state)
    )
    status = final_state.get("status", "completed")
    record_graph_run(status=status, duration_seconds=perf_counter() - started)
    cleanup_old_artifacts(
        [cfg.output_dir, cfg.logs_dir],
        cfg.retention_days,
    )
    result = ResearchResult(
        run_id=final_state["run_id"],
        query=query,
        final_report=final_state.get("final_report", final_state.get("report_draft", "")),
        citations=citations,
        eval_result=eval_result,
        low_confidence=bool(final_state.get("low_confidence", False)),
        status=status,
        artifacts_path=final_state.get("artifacts_path", ""),
        tenant_id=cfg.tenant_id,
    )
    upsert_registry_record(cfg, result)
    return result


def resume_research(run_id: str, *, config: RunConfig | None = None) -> ResearchResult:
    cfg = config or load_config()
    return load_result_from_artifacts(cfg, run_id)


if __name__ == "__main__":
    # Useful for quick manual execution.
    result = run_research("Cloud Hive dry run query", config=load_config({"interactive_hitl": False}))
    print(result.model_dump_json(indent=2))
