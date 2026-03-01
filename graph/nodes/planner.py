from __future__ import annotations

import re

from agents.planner import generate_plan, generate_subtopics
from core.models import QueryProfile, SubTopic, TaskSpec
from core.query_profile import profile_query, safe_analysis_policy
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _should_use_firecrawl(query: str) -> bool:
    query_l = query.lower()
    keywords = (
        "docs",
        "documentation",
        "api",
        "tutorial",
        "guide",
        "changelog",
        "release notes",
    )
    has_url = bool(re.search(r"https?://\S+", query))
    return has_url or any(token in query_l for token in keywords)


def _facet_terms(profile: QueryProfile) -> str:
    if not profile.domain_facets:
        return ""
    return " ".join(profile.domain_facets[:4])


def _safe_query_variant(query: str, profile: QueryProfile, dual_use_depth: str) -> str:
    policy = safe_analysis_policy(profile, dual_use_depth=dual_use_depth)
    if policy == "standard":
        return query
    if policy == "strict_defensive":
        return f"{query} defensive detection safeguards policy controls abuse prevention"
    if policy == "balanced_defensive":
        return f"{query} attack patterns limitations defensive testing detection hardening"
    return f"{query} defensive detection mitigations monitoring safeguards"


def _build_tasks(
    query: str,
    max_tasks: int,
    *,
    research_mode: str = "balanced",
    query_profile: QueryProfile | None = None,
    dual_use_depth: str = "dynamic_defensive",
) -> list[TaskSpec]:
    query_profile = query_profile or profile_query(query, dual_use_depth=dual_use_depth)
    firecrawl_needed = _should_use_firecrawl(query)
    safe_query = _safe_query_variant(query, query_profile, dual_use_depth)
    facet_terms = _facet_terms(query_profile)
    facet_suffix = f" {facet_terms}".strip()
    if research_mode == "peak":
        task_pool = [
            TaskSpec(
                id=1,
                title="Primary Evidence Lane",
                search_query=(
                    f"{safe_query} peer reviewed papers standards government institutional evidence {facet_suffix}"
                ).strip(),
                tool_hint="ddg",
                priority=1,
            ),
            TaskSpec(
                id=2,
                title="Core Mechanism Lane",
                search_query=f"{safe_query} mechanism architecture technical foundations {facet_suffix}".strip(),
                tool_hint="tavily",
                priority=2,
            ),
            TaskSpec(
                id=3,
                title="Implementation Lane",
                search_query=(
                    f"{safe_query} implementation patterns deployment constraints design tradeoffs {facet_suffix}"
                ).strip(),
                tool_hint="ddg",
                priority=3,
            ),
            TaskSpec(
                id=4,
                title="Benchmark and Evaluation Lane",
                search_query=(
                    f"{safe_query} benchmark evaluation dataset metrics reproducibility {facet_suffix}"
                ).strip(),
                tool_hint="tavily",
                priority=4,
            ),
            TaskSpec(
                id=5,
                title="Counterevidence Lane",
                search_query=(
                    f"{safe_query} contradictions criticism failure cases limitations counterevidence"
                ).strip(),
                tool_hint="ddg",
                priority=5,
            ),
            TaskSpec(
                id=6,
                title="Recency and Drift Lane",
                search_query=(
                    f"{safe_query} 2025 2026 latest updates standards changes recent evidence"
                ).strip(),
                tool_hint="tavily",
                priority=6,
            ),
            TaskSpec(
                id=7,
                title="Gap-Fill Lane",
                search_query=(
                    f"{safe_query} unresolved questions unknowns gap analysis validation checklist"
                ).strip(),
                tool_hint="any",
                priority=7,
            ),
            TaskSpec(
                id=8,
                title="Primary Source Extraction",
                search_query=safe_query,
                tool_hint="firecrawl" if firecrawl_needed else "any",
                priority=8,
                firecrawl_needed=firecrawl_needed,
            ),
        ]
    else:
        task_pool = [
            TaskSpec(
                id=1,
                title="Mechanism and Baseline Understanding",
                search_query=f"{safe_query} mechanism overview technical foundations {facet_suffix}".strip(),
                tool_hint="tavily",
                priority=1,
            ),
            TaskSpec(
                id=2,
                title="Primary Technical and Official Evidence",
                search_query=(
                    f"{safe_query} official documentation standards peer reviewed evidence {facet_suffix}"
                ).strip(),
                tool_hint="ddg",
                priority=2,
            ),
            TaskSpec(
                id=3,
                title="Contradictory Evidence and Limitations",
                search_query=(
                    f"{safe_query} false positives false negatives limitations critiques counterevidence"
                ).strip(),
                tool_hint="tavily",
                priority=3,
            ),
            TaskSpec(
                id=4,
                title="Operational Implications and Risk Controls",
                search_query=(
                    f"{safe_query} operational guidance risk controls monitoring best practices"
                ).strip(),
                tool_hint="ddg",
                priority=4,
            ),
            TaskSpec(
                id=5,
                title="Primary Source Extraction" if firecrawl_needed else "Primary Source Verification",
                search_query=safe_query,
                tool_hint="firecrawl" if firecrawl_needed else "any",
                priority=5,
                firecrawl_needed=firecrawl_needed,
            ),
        ]
    tasks = task_pool[: max(1, max_tasks)]
    if firecrawl_needed and not any(task.firecrawl_needed for task in tasks):
        firecrawl_task = task_pool[-1].model_copy(deep=True)
        if tasks:
            tasks[-1] = firecrawl_task
        else:
            tasks = [firecrawl_task]
    for i, task in enumerate(tasks, start=1):
        task.id = i
        task.priority = i
    return tasks


def _target_subtopic_count(query: str, profile: QueryProfile, *, default_count: int, max_count: int) -> int:
    score = 0
    if len(query) > 180:
        score += 1
    if profile.intent_type in {"comparative", "operational", "security_dual_use"}:
        score += 1
    if len(profile.domain_facets) >= 6:
        score += 1
    return min(max_count, max(2, default_count + (1 if score >= 2 else 0)))


def _fallback_subtopics_from_profile(query: str, profile: QueryProfile, *, count: int) -> list[SubTopic]:
    facets = profile.domain_facets or []
    seeded: list[tuple[str, str]] = [
        ("Primary Evidence", f"{query} primary evidence official references"),
        ("Mechanism", f"{query} mechanisms foundations core concepts"),
        ("Counterevidence", f"{query} limitations contradictions failure modes"),
        ("Operational", f"{query} implications recommendations actions"),
    ]
    for facet in facets[:4]:
        seeded.append((facet.title(), f"{query} {facet}"))
    deduped: list[SubTopic] = []
    seen: set[str] = set()
    for idx, (facet, sub_query) in enumerate(seeded, start=1):
        key = sub_query.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            SubTopic(
                id=f"S{idx}",
                facet=facet,
                sub_query=sub_query.strip(),
                rationale="Heuristic facet split fallback",
                complexity="medium",
            )
        )
        if len(deduped) >= count:
            break
    return deduped


def create_planner_node(runtime: GraphRuntime):
    def planner_node(state: ResearchState) -> dict:
        query = state["query"]
        max_tasks = runtime.config.max_tasks
        if runtime.config.research_mode == "peak":
            max_tasks = max(max_tasks, runtime.config.max_planner_tasks_peak)
        elif runtime.config.research_depth == "deep":
            max_tasks = max(max_tasks, 5)
        query_profile = state.get("query_profile") or profile_query(
            query,
            dual_use_depth=runtime.config.dual_use_depth,
            cleanup_mode=runtime.config.query_cleanup_mode,
        )
        planning_query = query_profile.normalized_query or query
        tenant_context = state.get("tenant_context")
        tenant_tier = tenant_context.quota_tier if tenant_context else "default"

        tasks: list[TaskSpec] = []
        subtopics: list[SubTopic] = []

        # Adaptive Planning
        if runtime.model_router:
            model_selection = runtime.model_router.select_model(
                task_type="planning",
                context_size=0,
                latency_budget_ms=3000,
                tenant_tier=tenant_tier,
                tenant_context=tenant_context,
            )
            try:
                client = runtime.get_llm_client(model_selection.provider)
                tasks = generate_plan(
                    planning_query,
                    client,
                    model_selection.provider,
                    model_selection.model_name,
                    max_tasks,
                )
            except Exception:
                # Fallback handled below
                pass

        if not tasks:
            tasks = _build_tasks(
                planning_query,
                max_tasks,
                research_mode=runtime.config.research_mode,
                query_profile=query_profile,
                dual_use_depth=runtime.config.dual_use_depth,
            )

        if runtime.config.subtopic_mode == "map_reduce":
            target_subtopics = _target_subtopic_count(
                planning_query,
                query_profile,
                default_count=runtime.config.subtopic_count_default,
                max_count=runtime.config.subtopic_count_max,
            )
            if runtime.model_router:
                model_selection = runtime.model_router.select_model(
                    task_type="planning",
                    context_size=0,
                    latency_budget_ms=3000,
                    tenant_tier=tenant_tier,
                    tenant_context=tenant_context,
                )
                try:
                    client = runtime.get_llm_client(model_selection.provider)
                    subtopics = generate_subtopics(
                        planning_query,
                        client,
                        model_selection.provider,
                        model_selection.model_name,
                        count=target_subtopics,
                        max_count=runtime.config.subtopic_count_max,
                    )
                except Exception:
                    pass
            if not subtopics:
                subtopics = _fallback_subtopics_from_profile(
                    planning_query,
                    query_profile,
                    count=target_subtopics,
                )

        memory_docs = runtime.memory_store.retrieve_similar(query=planning_query, k=3)
        heuristic_firecrawl = _should_use_firecrawl(planning_query)
        firecrawl_requested = heuristic_firecrawl or any(
            task.firecrawl_needed for task in tasks
        )
        runtime.tracer.event(
            state["run_id"],
            "planner",
            "Built plan tasks",
            payload={
                "task_count": len(tasks),
                "subtopic_count": len(subtopics),
                "firecrawl_requested": firecrawl_requested,
            },
        )
        return {
            "tasks": tasks,
            "subtopics": subtopics,
            "query_profile": query_profile,
            "memory_docs": memory_docs,
            "firecrawl_requested": firecrawl_requested,
            "metrics": {
                "query_normalization": {
                    "original_query": query,
                    "normalized_query": planning_query,
                    "extracted_facets": query_profile.domain_facets,
                    "typed_constraints": query_profile.typed_constraints,
                    "must_have_evidence_fields": query_profile.must_have_evidence_fields,
                }
            },
            "status": "planned",
            "logs": [
                f"Planner created {len(tasks)} tasks and {len(subtopics)} subtopics."
                if runtime.config.subtopic_mode == "map_reduce"
                else f"Planner created {len(tasks)} tasks."
            ],
        }

    return planner_node
