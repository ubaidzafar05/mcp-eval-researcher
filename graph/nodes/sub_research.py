from __future__ import annotations

import re
from typing import Any

from agents.prompts import SUB_RESEARCH_PROMPT
from core.citations import normalize_url
from core.claim_extractor import extract_claims
from core.models import Citation, ClaimRecord, RetrievedDoc, SubReport, SubTopic
from core.query_profile import profile_query
from core.source_quality import clean_evidence_text, prioritize_docs, source_tier
from core.verification import relevance_score, verify_claim
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _is_timeout_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg


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
    docs: list[RetrievedDoc] = []
    facet_hint = " ".join((query_profile.domain_facets or [])[:3]).strip()
    gap_queries = [
        f"{subtopic.sub_query} primary source official evidence {facet_hint}".strip(),
        f"{subtopic.sub_query} contradiction limitation counterevidence".strip(),
    ]
    for query in gap_queries[: max(0, max_queries)]:
        docs.extend(runtime.mcp_client.call_web_tool("ddg_search", query, k))
        docs.extend(runtime.mcp_client.call_web_tool("tavily_search", query, k))
    return docs


def _build_subreport_fallback(subtopic: SubTopic, reason: str) -> SubReport:
    content = (
        "## Subtopic Answer\n"
        f"Evidence for **{subtopic.facet}** is currently constrained. The branch could not produce enough "
        "verified support for a high-confidence sub-report.\n\n"
        "## Claims\n"
        f"- Constrained: branch failed due to `{reason}`.\n\n"
        "## Evidence Gaps\n"
        "- Missing corroborated sources and/or high-signal evidence for this facet."
    )
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
        if selection.provider in {"openai", "groq", "openrouter"}:
            resp = client.chat.completions.create(
                model=selection.model_name,
                messages=[
                    {"role": "system", "content": SUB_RESEARCH_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
            )
            return (resp.choices[0].message.content or "").strip()
        if selection.provider == "anthropic":
            resp = client.messages.create(
                model=selection.model_name,
                max_tokens=1800,
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
                max_tokens=1800,
                temperature=0.2,
            )
            return (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        if _is_timeout_error(exc):
            return (
                "## Subtopic Answer\n"
                "Branch synthesis timed out; returning constrained claim registry for this facet.\n\n"
                "## Claims\n"
                + "\n".join(
                    f"- [{claim.claim_id}] ({claim.status}) {claim.assertion}" for claim in claims
                )
                + "\n\n## Evidence Gaps\n- llm_timeout_subresearch"
            ).strip()

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
        except Exception as exc:  # noqa: BLE001
            if _is_timeout_error(exc):
                return {
                    "sub_reports": [_build_subreport_fallback(subtopic, "llm_timeout_subresearch")],
                    "subtopic_failures": [f"{subtopic.id}:llm_timeout_subresearch"],
                    "logs": [f"Subtopic {subtopic.id} constrained due to LLM timeout."],
                }
            claims_result = None
        extracted_claims = list(getattr(claims_result, "claims", []) or [])
        if (
            not extracted_claims
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
                extracted_claims = list(getattr(retry_result, "claims", []) or [])
            except Exception:  # noqa: BLE001
                extracted_claims = []
        if not extracted_claims:
            if runtime.config.subreport_failure_policy == "fail_closed":
                return {
                    "subtopic_failures": [f"{subtopic.id}:claim_extraction_failed"],
                    "logs": [f"Subtopic {subtopic.id} failed-closed: claim extraction failed."],
                }
            fallback = _build_subreport_fallback(subtopic, "claim_extraction_failed")
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
            claim_records.append(
                ClaimRecord(
                    claim_id=claim_id,
                    assertion=claim.assertion,
                    status=verified.status,  # type: ignore[arg-type]
                    reason_codes=verified.reason_codes,
                    evidence=clean_evidence_text(claim.evidence, max_chars=runtime.config.max_evidence_quote_chars),
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
                    confidence="high" if verified.status == "verified" else "medium" if verified.status == "constrained" else "low",
                )
            )
            if verified.status == "verified":
                verified_count += 1
            elif verified.status == "constrained":
                constrained_count += 1
                missing_fields.update(verified.reason_codes)
            else:
                missing_fields.update(verified.reason_codes)
        if len(claim_records) < runtime.config.subreport_min_claims:
            missing_fields.add("insufficient_claims")
            constrained_count = max(1, constrained_count)
        if verified_count == 0 and len(slice_docs) >= runtime.config.subreport_min_claims:
            missing_fields.add("branch_verified_floor_not_met")
            constrained_count = max(1, constrained_count)

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
