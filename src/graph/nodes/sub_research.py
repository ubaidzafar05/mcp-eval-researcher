from __future__ import annotations

import re
import logging
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.callbacks.manager import dispatch_custom_event

from agents.prompts import SUB_RESEARCH_PROMPT
from core.citations import normalize_url
from core.claim_extractor import build_fallback_extraction, extract_claims
from core.config import token_budget_for_task, timeout_for_task
from core.models import Citation, ClaimRecord, RetrievedDoc, SubReport, SubTopic
from core.query_profile import profile_query
from core.source_quality import clean_evidence_text, prioritize_docs, source_tier
from core.synthesis.llm_caller import _needs_no_think
from core.verification import relevance_score, verify_claim
from graph.runtime import GraphRuntime
from graph.state import ResearchState

logger = logging.getLogger(__name__)


def _is_timeout_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg


def _safe_web_call(
    runtime: GraphRuntime,
    *,
    tool: str,
    query: str,
    k: int,
) -> list[RetrievedDoc]:
    try:
        return runtime.mcp_client.call_web_tool(tool, query, k)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "MCP tool call failed: %s", str(exc)[:240],
            extra={"tool": tool},
        )
        return []


def _subtopic_from_state(state: ResearchState) -> SubTopic | None:
    subtopic_id = str(state.get("subtopic_id", "")).strip()
    sub_query = str(state.get("subtopic_query", "")).strip()
    sub_facet = str(state.get("subtopic_facet", "")).strip()
    if subtopic_id and sub_query:
        return SubTopic(
            id=subtopic_id,
            facet=sub_facet or "Subtopic",
            sub_query=sub_query,
            rationale="Dispatched branch",
            complexity="medium",
        )
    subtopics = list(state.get("subtopics", []))
    if not subtopics:
        return None
    if subtopic_id:
        for item in subtopics:
            if item.id == subtopic_id:
                return item
    return subtopics[0]


def _facet_tokens(subtopic: SubTopic) -> list[str]:
    text = f"{subtopic.facet} {subtopic.sub_query}".lower()
    tokens = [tok for tok in re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", text) if len(tok) >= 4]
    return tokens[:8]


def _slice_docs(
    docs: list[RetrievedDoc],
    *,
    subtopic: SubTopic,
    query_profile,
    max_docs: int,
) -> list[RetrievedDoc]:
    facets = list(dict.fromkeys([*query_profile.domain_facets, *_facet_tokens(subtopic)]))
    ranked = sorted(
        docs,
        key=lambda doc: (
            -relevance_score(
                doc,
                query=subtopic.sub_query,
                facets=facets,
            ),
            -float(doc.score or 0.0),
        ),
    )
    out: list[RetrievedDoc] = []
    seen_domains: set[str] = set()
    for doc in ranked:
        url = normalize_url(doc.url)
        if not url:
            continue
        domain = (url.split("/")[2] if "://" in url else url).lower()
        if domain in seen_domains and len(out) >= max_docs // 2:
            continue
        out.append(doc.model_copy(update={"url": url}))
        seen_domains.add(domain)
        if len(out) >= max_docs:
            break
    return out


def _gapfill_docs(
    runtime: GraphRuntime,
    *,
    subtopic: SubTopic,
    query_profile,
    max_queries: int,
    k: int,
) -> list[RetrievedDoc]:
    facet_hint = " ".join((query_profile.domain_facets or [])[:3]).strip()
    gap_queries = [
        f"{subtopic.sub_query} primary source official evidence {facet_hint}".strip(),
        f"{subtopic.sub_query} contradiction limitation counterevidence".strip(),
    ][: max(0, max_queries)]
    # Run all provider calls in parallel instead of sequential loop.
    calls: list[tuple[str, str]] = []
    for query in gap_queries:
        calls.append(("ddg_search", query))
        calls.append(("tavily_search", query))
    docs: list[RetrievedDoc] = []
    with ThreadPoolExecutor(max_workers=min(4, len(calls)), thread_name_prefix="gapfill") as pool:
        futures = {
            pool.submit(_safe_web_call, runtime, tool=tool, query=q, k=k): (tool, q)
            for tool, q in calls
        }
        for future in as_completed(futures):
            try:
                docs.extend(future.result())
            except Exception:  # noqa: BLE001
                pass
    return docs


def _build_subreport_fallback(
    subtopic: SubTopic,
    reason: str,
    docs: list[RetrievedDoc] | None = None,
) -> SubReport:
    lines = [
        "## Subtopic Analysis",
        f"Research on **{subtopic.facet}** encountered limitations ({reason.replace('_', ' ')}). "
        "Below is the available evidence collected before the constraint was reached.",
        "",
    ]
    # Include whatever raw doc content we have so the report isn't empty.
    if docs:
        lines.append("### Available Evidence")
        for doc in docs[:6]:
            snippet = (doc.snippet or doc.content or "")[:500].strip()
            if snippet:
                title = doc.title or "Unknown Source"
                url = doc.url or "unknown"
                lines.append(f"**{title}** ({url})")
                lines.append(f"> {snippet}")
                lines.append("")
    lines.extend([
        "### Evidence Gaps",
        f"- Branch constrained due to: {reason.replace('_', ' ')}.",
        "- Additional sources or longer processing time may improve coverage.",
    ])
    content = "\n".join(lines)
    return SubReport(
        sub_query=subtopic.sub_query,
        facet=subtopic.facet,
        content=content,
        claims=[
            ClaimRecord(
                claim_id="C0",
                assertion=f"{subtopic.facet} branch constrained due to {reason}.",
                status="constrained",
                reason_codes=[reason],
                confidence="low",
                source="fallback",
                reason=reason,
            )
        ],
        citations=[],
        confidence="constrained",
        reason_codes=[reason],
        missing_proof_fields=["additional_corroboration", "higher_tier_sources"],
    )


def _compose_subreport_text(
    runtime: GraphRuntime,
    *,
    subtopic: SubTopic,
    claims: list[ClaimRecord],
    citations: list[Citation],
    docs: list[RetrievedDoc],
    tenant_tier: str,
    tenant_context: Any,
) -> str:
    claim_lines: list[str] = []
    citation_lookup = {c.claim_id: c for c in citations}
    for claim in claims:
        citation = citation_lookup.get(claim.claim_id)
        evidence = citation.evidence if citation else ""
        claim_lines.append(
            f"- [{claim.claim_id}] ({claim.status}) {claim.assertion}\n"
            f"  Evidence: {evidence}\n"
            f"  Reasons: {', '.join(claim.reason_codes) if claim.reason_codes else 'none'}"
        )
    source_lines = [
        f"- [{citation.claim_id}] {citation.title} ({citation.provider}) {citation.source_url}"
        for citation in citations
    ]
    user_msg = (
        f"Subtopic facet: {subtopic.facet}\n"
        f"Subtopic query: {subtopic.sub_query}\n"
        f"Target words: {runtime.config.subreport_target_words}\n\n"
        f"Claims:\n{chr(10).join(claim_lines) or '- none'}\n\n"
        f"Sources:\n{chr(10).join(source_lines) or '- none'}\n\n"
        "Write the sub-report in markdown with required sections."
    )
    selection = runtime.model_router.select_model(
        task_type="synthesis",
        context_size=len(user_msg),
        latency_budget_ms=9000,
        tenant_tier=tenant_tier,
        tenant_context=tenant_context,
        plan_complexity="medium",
    )
    try:
        client = runtime.get_llm_client(
            selection.provider,
            request_timeout_seconds=runtime.config.llm_request_timeout_seconds_synthesis,
        )
        if selection.provider in {"openai", "groq", "openrouter", "ollama"}:
            effective_system = SUB_RESEARCH_PROMPT
            if _needs_no_think(selection.model_name):
                effective_system = "/no_think\n" + SUB_RESEARCH_PROMPT
            resp = client.chat.completions.create(
                model=selection.model_name,
                messages=[
                    {"role": "system", "content": effective_system},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=token_budget_for_task(runtime.config, "subreport"),
                temperature=0.2,
                timeout=timeout_for_task(runtime.config, "subreport"),
            )
            return (resp.choices[0].message.content or "").strip()
        if selection.provider == "anthropic":
            resp = client.messages.create(
                model=selection.model_name,
                max_tokens=4096,
                system=SUB_RESEARCH_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.2,
            )
            return (resp.content[0].text if resp.content else "").strip()
        if selection.provider == "huggingface":
            resp = client.chat_completion(
                messages=[
                    {"role": "system", "content": SUB_RESEARCH_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=4096,
                temperature=0.2,
            )
            return (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        if _is_timeout_error(exc):
            # LLM timed out — build a useful sub-report directly from raw claims + docs.
            sections = [
                "## Subtopic Analysis",
                f"Research on **{subtopic.facet}** collected evidence from {len(docs)} sources. "
                "Due to synthesis time constraints the following presents the raw analytical findings.",
                "",
                "### Key Findings",
            ]
            for claim in claims:
                citation = citation_lookup.get(claim.claim_id)
                evidence = (citation.evidence if citation else "")[:400]
                sections.append(
                    f"**[{claim.claim_id}]** ({claim.status.upper()}) {claim.assertion}"
                )
                if evidence:
                    sections.append(f"> {evidence}")
                sections.append("")
            # Include raw doc snippets for substance
            sections.append("### Supporting Evidence")
            for doc in docs[:6]:
                snippet = (doc.snippet or doc.content or "")[:500].strip()
                if snippet:
                    title = doc.title or "Unknown Source"
                    url = doc.url or "unknown"
                    sections.append(f"**{title}** ({url})")
                    sections.append(f"> {snippet}")
                    sections.append("")
            sections.extend([
                "### Evidence Gaps",
                "- Sub-report synthesis timed out; findings are presented as-is from raw evidence.",
                "- Further analysis may reveal additional patterns and causal mechanisms.",
            ])
            return "\n".join(sections).strip()

    fallback_lines = [
        "## Subtopic Answer",
        f"{subtopic.facet}: evidence synthesized from {len(docs)} documents with strict verification guards.",
        "",
        "## Claims",
    ]
    for claim in claims:
        fallback_lines.append(f"- [{claim.claim_id}] ({claim.status}) {claim.assertion}")
    fallback_lines.extend(
        [
            "",
            "## Evidence Gaps",
            "- Expand provider diversity or higher-tier corroboration where claims are constrained.",
        ]
    )
    return "\n".join(fallback_lines).strip()


def create_sub_research_node(runtime: GraphRuntime):
    def _emit_progress(subtopic_id: str, phase: str, **extra: Any) -> None:
        try:
            dispatch_custom_event(
                "sub_research_progress",
                {"subtopic_id": subtopic_id, "phase": phase, "stage": "research", **extra},
            )
        except Exception:  # noqa: BLE001
            pass  # dispatch may fail outside async context

    def sub_research_node(state: ResearchState) -> dict:
        subtopic = _subtopic_from_state(state)
        if subtopic is None:
            return {
                "subtopic_failures": ["subtopic:missing"],
                "logs": ["Sub-research branch skipped: no subtopic payload."],
            }
        query_profile = state.get("query_profile") or profile_query(state["query"])
        shared_docs = list(state.get("shared_corpus_docs", []))
        slice_docs = _slice_docs(
            shared_docs,
            subtopic=subtopic,
            query_profile=query_profile,
            max_docs=10,
        )
        if (
            runtime.config.subreport_gapfill_enabled
            and len(slice_docs) < max(4, runtime.config.subreport_min_claims)
        ):
            gapfill = _gapfill_docs(
                runtime,
                subtopic=subtopic,
                query_profile=query_profile,
                max_queries=runtime.config.subreport_gapfill_max_queries,
                k=5,
            )
            merged = [*slice_docs, *gapfill]
            merged = prioritize_docs(
                merged,
                source_quality_bar=runtime.config.source_quality_bar,
                min_tier_ab_sources=runtime.config.min_tier_ab_sources,
            )
            slice_docs = _slice_docs(
                merged,
                subtopic=subtopic,
                query_profile=query_profile,
                max_docs=12,
            )
            _emit_progress(subtopic.id, "gap_fill_complete", doc_count=len(slice_docs))
        if not slice_docs:
            if runtime.config.subreport_failure_policy == "fail_closed":
                return {
                    "subtopic_failures": [f"{subtopic.id}:no_relevant_docs"],
                    "logs": [f"Subtopic {subtopic.id} failed-closed: no relevant docs."],
                }
            fallback = _build_subreport_fallback(subtopic, "no_relevant_docs")
            return {
                "sub_reports": [fallback],
                "subtopic_failures": [f"{subtopic.id}:no_relevant_docs"],
                "logs": [f"Subtopic {subtopic.id} constrained: no relevant docs."],
            }

        tenant_context = state.get("tenant_context")
        tenant_tier = tenant_context.quota_tier if tenant_context else "default"
        selection = runtime.model_router.select_model(
            task_type="research",
            context_size=sum(len((doc.snippet or doc.content or "")[:300]) for doc in slice_docs),
            latency_budget_ms=7000,
            tenant_tier=tenant_tier,
            tenant_context=tenant_context,
            plan_complexity="medium",
        )
        claims_result = None
        _claim_had_error = False
        # In relaxed mode skip LLM claim extraction entirely — build directly
        # from raw doc snippets.  This avoids spending 90 s+ waiting for Groq
        # rate-limit timeouts when the synthesizer will paraphrase anyway.
        if runtime.config.relaxed_quality_mode:
            claims_result = build_fallback_extraction(
                slice_docs,
                max_claims=max(3, runtime.config.subreport_min_claims),
            )
        else:
            try:
                client = runtime.get_llm_client(
                    selection.provider,
                    request_timeout_seconds=runtime.config.llm_request_timeout_seconds_research,
                )
                claims_result = extract_claims(
                    slice_docs,
                    client,
                    selection.provider,
                    selection.model_name,
                    max_docs=min(12, len(slice_docs)),
                )
                # extract_claims() catches internally — check for error result
                if getattr(claims_result, "error", None):
                    _claim_had_error = True
                    logger.warning(
                        "Claim extraction returned error for subtopic %s: %s; using fallback",
                        subtopic.id,
                        claims_result.error,
                    )
                    claims_result = build_fallback_extraction(
                        slice_docs,
                        max_claims=max(1, runtime.config.subreport_min_claims),
                    )
            except Exception as exc:  # noqa: BLE001
                _claim_had_error = True
                logger.warning(
                    "Claim extraction exception for subtopic %s: %s; using fallback",
                    subtopic.id,
                    str(exc)[:120],
                )
                claims_result = build_fallback_extraction(
                    slice_docs,
                    max_claims=max(1, runtime.config.subreport_min_claims),
                )
        extracted_claims = list(getattr(claims_result, "claims", []) or [])
        fallback_used = bool(getattr(claims_result, "fallback_used", False))
        _emit_progress(subtopic.id, "claims_extracted", claim_count=len(extracted_claims))
        # Only retry on first-time empty when NO error occurred (avoid burning
        # another full timeout cycle on a known-bad provider response).
        if (
            not extracted_claims
            and not _claim_had_error
            and runtime.config.subreport_failure_policy == "retry_once"
        ):
            retry_selection = runtime.model_router.select_model(
                task_type="research",
                context_size=sum(len((doc.snippet or doc.content or "")[:320]) for doc in slice_docs),
                latency_budget_ms=9000,
                tenant_tier=tenant_tier,
                tenant_context=tenant_context,
                plan_complexity="high",
            )
            try:
                retry_client = runtime.get_llm_client(
                    retry_selection.provider,
                    request_timeout_seconds=runtime.config.llm_request_timeout_seconds_research,
                )
                retry_result = extract_claims(
                    slice_docs,
                    retry_client,
                    retry_selection.provider,
                    retry_selection.model_name,
                    max_docs=min(12, len(slice_docs)),
                )
                if not getattr(retry_result, "error", None):
                    extracted_claims = list(getattr(retry_result, "claims", []) or [])
            except Exception:  # noqa: BLE001
                extracted_claims = []
        if not extracted_claims:
            if runtime.config.relaxed_quality_mode:
                claims_result = build_fallback_extraction(
                    slice_docs,
                    max_claims=max(1, runtime.config.subreport_min_claims),
                )
                extracted_claims = list(claims_result.claims or [])
                fallback_used = True
            elif runtime.config.subreport_failure_policy == "fail_closed":
                return {
                    "subtopic_failures": [f"{subtopic.id}:claim_extraction_failed"],
                    "logs": [f"Subtopic {subtopic.id} failed-closed: claim extraction failed."],
                }
            else:
                fallback = _build_subreport_fallback(subtopic, "claim_extraction_failed", docs=slice_docs)
                return {
                    "sub_reports": [fallback],
                    "subtopic_failures": [f"{subtopic.id}:claim_extraction_failed"],
                    "logs": [f"Subtopic {subtopic.id} constrained: claim extraction failed."],
                }

        sub_index_match = re.search(r"(\d+)$", subtopic.id)
        sub_index = int(sub_index_match.group(1)) if sub_index_match else 1
        claim_records: list[ClaimRecord] = []
        citations: list[Citation] = []
        missing_fields: set[str] = set()
        constrained_count = 0
        verified_count = 0
        for idx, claim in enumerate(extracted_claims, start=1):
            claim_id = f"C{sub_index * 100 + idx}"
            source_doc = next(
                (doc for doc in slice_docs if normalize_url(doc.url) == normalize_url(claim.source_url)),
                None,
            )
            if source_doc is None:
                source_doc = slice_docs[min(idx - 1, len(slice_docs) - 1)]
            if fallback_used:
                status = "constrained"
                reason_codes = ["fallback_claim_from_source"]
                confidence = "low"
            else:
                verified = verify_claim(
                    claim_id=claim_id,
                    doc=source_doc,
                    peers=slice_docs,
                    query_profile=query_profile,
                    query=subtopic.sub_query,
                    availability_policy=runtime.config.availability_policy,
                    availability_enforcement_scope=runtime.config.availability_enforcement_scope,
                    opportunity_query_detection=runtime.config.opportunity_query_detection,
                    freshness_max_months=runtime.config.freshness_max_months,
                    verification_min_sources_per_claim=runtime.config.verification_min_sources_per_claim,
                    require_primary_or_official_proof=runtime.config.require_primary_or_official_proof,
                )
                status = "unverified" if verified.status == "withheld" else verified.status
                reason_codes = verified.reason_codes
                confidence = "high" if status == "verified" else "medium" if status == "constrained" else "low"
            claim_records.append(
                ClaimRecord(
                    claim_id=claim_id,
                    assertion=claim.assertion,
                    status=status,  # type: ignore[arg-type]
                    reason_codes=reason_codes,
                    evidence=clean_evidence_text(claim.evidence, max_chars=runtime.config.max_evidence_quote_chars),
                    source=normalize_url(source_doc.url) or source_doc.provider,
                    confidence=confidence,  # type: ignore[arg-type]
                    reason=claim.reason if getattr(claim, "reason", None) else None,
                )
            )
            citations.append(
                Citation(
                    claim_id=claim_id,
                    source_url=normalize_url(source_doc.url),
                    title=source_doc.title,
                    provider=source_doc.provider,
                    evidence=clean_evidence_text(claim.evidence or source_doc.snippet or source_doc.content, max_chars=runtime.config.max_evidence_quote_chars),
                    source_tier=source_tier(source_doc.url, source_doc.provider, source_doc.title),  # type: ignore[arg-type]
                    confidence=confidence,  # type: ignore[arg-type]
                )
            )
            if status == "verified":
                verified_count += 1
            elif status == "constrained":
                constrained_count += 1
                missing_fields.update(reason_codes)
            else:
                missing_fields.update(reason_codes)
        if len(claim_records) < runtime.config.subreport_min_claims:
            missing_fields.add("insufficient_claims")
            constrained_count = max(1, constrained_count)
        if verified_count == 0 and len(slice_docs) >= runtime.config.subreport_min_claims:
            missing_fields.add("branch_verified_floor_not_met")
            constrained_count = max(1, constrained_count)

        _emit_progress(subtopic.id, "synthesis_starting", claim_count=len(claim_records))
        content = _compose_subreport_text(
            runtime,
            subtopic=subtopic,
            claims=claim_records,
            citations=citations,
            docs=slice_docs,
            tenant_tier=tenant_tier,
            tenant_context=tenant_context,
        )
        confidence: str = "high"
        if constrained_count > 0:
            confidence = "mixed"
        if verified_count == 0:
            confidence = "constrained"
        reason_codes = sorted(missing_fields)
        sub_report = SubReport(
            sub_query=subtopic.sub_query,
            facet=subtopic.facet,
            content=content,
            claims=claim_records,
            citations=citations,
            confidence=confidence,  # type: ignore[arg-type]
            reason_codes=reason_codes,
            missing_proof_fields=reason_codes,
        )
        runtime.tracer.event(
            state["run_id"],
            "sub_research",
            "Subtopic branch completed",
            payload={
                "subtopic_id": subtopic.id,
                "facet": subtopic.facet,
                "claim_count": len(claim_records),
                "verified_count": verified_count,
                "constrained_count": constrained_count,
                "confidence": confidence,
            },
        )
        return {
            "sub_reports": [sub_report],
            "logs": [f"Subtopic {subtopic.id} completed with {len(claim_records)} claims."],
        }

    return sub_research_node
