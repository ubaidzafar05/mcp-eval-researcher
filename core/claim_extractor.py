"""Pass 1 of the Two-Pass LLM pipeline.

Extracts structured claims from raw source documents using a fast LLM.
Each claim has a topic, assertion, evidence excerpt, and confidence tag.
The output feeds into Pass 2 (analytical synthesis).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from core.models import RetrievedDoc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt — kept in code since it's tightly coupled to the JSON schema.
# ---------------------------------------------------------------------------

CLAIM_EXTRACTOR_PROMPT = """\
You are a claim-extraction engine. Your job is to read raw source documents
and extract structured factual claims. Do NOT add your own analysis.
Do NOT invent information not present in the sources.

For each source, extract 1-3 claims. Each claim must be:
- A single, falsifiable assertion grounded in the source text.
- Tagged with a topic/theme label (e.g., "performance", "security", "adoption").
- Accompanied by a direct evidence excerpt (≤80 words) from the source.
- Rated as "strong", "moderate", or "weak" based on specificity and verifiability.

Return a JSON object with a single key "claims" containing an array.
Each claim object has these exact keys:
  - source_id: string (e.g. "C1")
  - topic: string
  - assertion: string
  - evidence: string
  - strength: "strong" | "moderate" | "weak"
  - source_title: string
  - source_url: string

Return ONLY valid JSON. No markdown fences. No commentary.
"""


# ---------------------------------------------------------------------------
# Data model for extracted claims
# ---------------------------------------------------------------------------

class ExtractedClaim(BaseModel):
    """A single structured claim extracted from a source document."""
    source_id: str
    topic: str
    assertion: str
    evidence: str
    strength: str = "moderate"
    source_title: str = ""
    source_url: str = ""


class ExtractionResult(BaseModel):
    """Result of the claim extraction pass."""
    claims: list[ExtractedClaim] = Field(default_factory=list)
    error: str | None = None
    provider_used: str = ""
    model_used: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_json_parse(raw: str) -> dict[str, Any]:
    """Parse JSON from LLM output, handling markdown fences and extra text."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty_response")

    # Strip markdown code fences
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Find the outermost JSON object
    start = text.find("{")
    if start < 0:
        raise ValueError("no_json_object_found")

    depth = 0
    end = -1
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = idx
                break
    if end < 0:
        raise ValueError("unclosed_json_object")

    return json.loads(text[start : end + 1])


def _build_source_block(docs: list[RetrievedDoc], max_snippet_chars: int = 400) -> str:
    """Format source documents into a numbered block for the extraction prompt."""
    parts: list[str] = []
    for i, doc in enumerate(docs, start=1):
        snippet = (doc.snippet or doc.content or "")[:max_snippet_chars].strip()
        parts.append(
            f"[C{i}] Title: {doc.title or 'Untitled'}\n"
            f"URL: {doc.url}\n"
            f"Provider: {doc.provider}\n"
            f"Content: {snippet}\n"
        )
    return "\n".join(parts)


def _validate_claims(raw_claims: list[dict[str, Any]], doc_count: int) -> list[ExtractedClaim]:
    """Validate and normalize raw claim dicts into ExtractedClaim objects."""
    valid: list[ExtractedClaim] = []
    seen_assertions: set[str] = set()

    for raw in raw_claims:
        if not isinstance(raw, dict):
            continue

        source_id = str(raw.get("source_id", "")).strip()
        assertion = str(raw.get("assertion", "")).strip()
        topic = str(raw.get("topic", "general")).strip()
        evidence = str(raw.get("evidence", "")).strip()
        strength = str(raw.get("strength", "moderate")).strip().lower()

        # Skip empty or duplicate claims
        if not assertion or len(assertion) < 10:
            continue
        normalized = re.sub(r"\s+", " ", assertion.lower())
        if normalized in seen_assertions:
            continue
        seen_assertions.add(normalized)

        # Normalize strength
        if strength not in {"strong", "moderate", "weak"}:
            strength = "moderate"

        # Ensure source_id is valid
        if not re.match(r"^C\d+$", source_id):
            source_id = f"C{len(valid) + 1}"

        valid.append(ExtractedClaim(
            source_id=source_id,
            topic=topic or "general",
            assertion=assertion,
            evidence=evidence[:320],
            strength=strength,
            source_title=str(raw.get("source_title", "")),
            source_url=str(raw.get("source_url", "")),
        ))

    return valid


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------

def extract_claims(
    docs: list[RetrievedDoc],
    client: Any,
    provider: str,
    model: str,
    *,
    max_docs: int = 16,
) -> ExtractionResult:
    """
    Pass 1: Extract structured claims from source documents using a fast LLM.

    Args:
        docs: Retrieved source documents.
        client: LLM client instance.
        provider: Provider name ("groq", "openrouter", "huggingface", etc).
        model: Model identifier.
        max_docs: Maximum number of docs to process.

    Returns:
        ExtractionResult with validated claims or error.
    """
    if not docs:
        return ExtractionResult(
            error="no_source_documents",
            provider_used=provider,
            model_used=model,
        )

    source_block = _build_source_block(docs[:max_docs])
    user_msg = f"Extract claims from these sources:\n\n{source_block}"

    try:
        content = ""
        if provider in {"openai", "groq", "openrouter"}:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": CLAIM_EXTRACTOR_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or ""
        elif provider == "anthropic":
            resp = client.messages.create(
                model=model,
                max_tokens=2000,
                system=CLAIM_EXTRACTOR_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.1,
            )
            content = resp.content[0].text if resp.content else ""
        elif provider == "huggingface":
            resp = client.chat_completion(
                messages=[
                    {"role": "system", "content": CLAIM_EXTRACTOR_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=2000,
                temperature=0.1,
            )
            content = resp.choices[0].message.content or ""
        else:
            return ExtractionResult(
                error=f"unsupported_provider:{provider}",
                provider_used=provider,
                model_used=model,
            )

        data = _safe_json_parse(content)
        raw_claims = data.get("claims", [])
        if not isinstance(raw_claims, list):
            return ExtractionResult(
                error="claims_field_not_array",
                provider_used=provider,
                model_used=model,
            )

        validated = _validate_claims(raw_claims, len(docs[:max_docs]))
        return ExtractionResult(
            claims=validated,
            provider_used=provider,
            model_used=model,
        )

    except Exception as exc:
        logger.error("Claim extraction failed: %s", exc)
        return ExtractionResult(
            error=str(exc)[:200],
            provider_used=provider,
            model_used=model,
        )


def group_claims_by_topic(claims: list[ExtractedClaim]) -> dict[str, list[ExtractedClaim]]:
    """Group extracted claims by topic for paragraph-level synthesis."""
    groups: dict[str, list[ExtractedClaim]] = {}
    for claim in claims:
        key = claim.topic.lower().strip()
        if key not in groups:
            groups[key] = []
        groups[key].append(claim)
    return groups
