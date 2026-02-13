from __future__ import annotations

import re
from collections.abc import Iterable
from hashlib import sha1

import trafilatura

from core.models import RetrievedDoc


def approximate_tokens(text: str) -> int:
    text = text or ""
    return max(1, len(text) // 4)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def clean_html_or_text(raw: str) -> str:
    raw = raw or ""
    extracted = trafilatura.extract(raw, output_format="txt")
    if extracted:
        return normalize_whitespace(extracted)
    # Fallback when extraction fails.
    text_only = re.sub(r"<[^>]+>", " ", raw)
    return normalize_whitespace(text_only)


def _doc_signature(doc: RetrievedDoc) -> str:
    joined = normalize_whitespace(f"{doc.title} {doc.url} {doc.content[:1000]}")
    return sha1(joined.lower().encode("utf-8")).hexdigest()


def dedupe_docs(docs: Iterable[RetrievedDoc]) -> list[RetrievedDoc]:
    seen: set[str] = set()
    result: list[RetrievedDoc] = []
    for doc in docs:
        sig = _doc_signature(doc)
        if sig in seen:
            continue
        seen.add(sig)
        result.append(doc)
    return result


def prune_context_docs(
    docs: list[RetrievedDoc],
    *,
    per_doc_tokens: int = 500,
    total_tokens: int = 1800,
) -> list[RetrievedDoc]:
    cleaned: list[RetrievedDoc] = []
    remaining = max(1, total_tokens)
    for doc in dedupe_docs(docs):
        content = clean_html_or_text(doc.content or doc.snippet)
        if not content:
            continue
        max_chars = max(40, per_doc_tokens * 4)
        content = content[:max_chars]
        token_count = approximate_tokens(content)
        if token_count > remaining:
            max_chars = max(40, remaining * 4)
            content = content[:max_chars]
            token_count = approximate_tokens(content)
        if token_count <= 0:
            continue
        remaining -= token_count
        cleaned.append(
            doc.model_copy(
                update={
                    "snippet": normalize_whitespace(doc.snippet)[:320],
                    "content": content,
                }
            )
        )
        if remaining <= 0:
            break
    return cleaned

