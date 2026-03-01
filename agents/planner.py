from __future__ import annotations

import json
import logging
from typing import Any

from agents.prompts import PLANNER_PROMPT, SUBTOPIC_DECOMPOSER_PROMPT
from core.models import SubTopic, TaskSpec

logger = logging.getLogger(__name__)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no_json_object")
    depth = 0
    end = -1
    for idx, ch in enumerate(text[start:], start=start):
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

def generate_plan(
    query: str,
    client: Any,
    provider: str,
    model: str,
    max_tasks: int = 3,
) -> list[TaskSpec]:
    """
    Generate a research plan (list of tasks) using the specified LLM.
    """
    user_msg = (
        f"Query: {query}\n"
        f"Max Tasks: {max_tasks}\n"
        "Return a JSON object with a key 'tasks' containing a list of task objects.\n"
        "For deep research, prioritize lane diversity across: primary evidence, implementation, benchmarks, counterevidence, recency, and verification."
    )

    try:
        content = ""
        if provider == "openai" or provider == "groq" or provider == "openrouter":
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": PLANNER_PROMPT},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            content = resp.choices[0].message.content
        elif provider == "anthropic":
            resp = client.messages.create(
                model=model,
                max_tokens=2000,
                system=PLANNER_PROMPT,
                messages=[
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.2
            )
            content = resp.content[0].text
        elif provider == "huggingface":
            # HF Chat Completion
            resp = client.chat_completion(
                messages=[
                    {"role": "system", "content": PLANNER_PROMPT},
                    {"role": "user", "content": user_msg}
                ],
                max_tokens=1500,
                temperature=0.2
            )
            content = resp.choices[0].message.content

        data = _parse_json_object(content)
        tasks_data = data.get("tasks", [])

        tasks: list[TaskSpec] = []
        for i, task_dict in enumerate(tasks_data, start=1):
            # Ensure ID and Priority
            task_dict["id"] = i
            task_dict["priority"] = task_dict.get("priority", i)
            tasks.append(TaskSpec(**task_dict))

        return tasks[:max_tasks]

    except Exception as e:
        logger.error(f"Planner LLM failed: {e}. Falling back to heuristic.")
        return []


def _fallback_subtopics(query: str, count: int) -> list[SubTopic]:
    base = (query or "").strip()
    seeded = [
        ("Primary Evidence", f"{base} primary evidence and canonical references"),
        ("Mechanism", f"{base} underlying mechanisms and technical foundations"),
        ("Counterevidence", f"{base} limitations contradictions and failure cases"),
        ("Operational", f"{base} implications decisions and implementation guidance"),
    ]
    out: list[SubTopic] = []
    for idx, (facet, sub_query) in enumerate(seeded[: max(1, count)], start=1):
        out.append(
            SubTopic(
                id=f"S{idx}",
                facet=facet,
                sub_query=sub_query.strip(),
                rationale=f"Cover {facet.lower()} for balanced map-reduce synthesis.",
                complexity="medium",
            )
        )
    return out


def generate_subtopics(
    query: str,
    client: Any,
    provider: str,
    model: str,
    *,
    count: int = 3,
    max_count: int = 4,
) -> list[SubTopic]:
    requested = max(1, min(max_count, count))
    user_msg = (
        f"Query: {query}\n"
        f"Target subtopic count: {requested}\n"
        "Return JSON with key 'subtopics'."
    )
    try:
        content = ""
        if provider in {"openai", "groq", "openrouter"}:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SUBTOPIC_DECOMPOSER_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or ""
        elif provider == "anthropic":
            resp = client.messages.create(
                model=model,
                max_tokens=1500,
                system=SUBTOPIC_DECOMPOSER_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.2,
            )
            content = resp.content[0].text if resp.content else ""
        elif provider == "huggingface":
            resp = client.chat_completion(
                messages=[
                    {"role": "system", "content": SUBTOPIC_DECOMPOSER_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=1500,
                temperature=0.2,
            )
            content = resp.choices[0].message.content or ""
        else:
            return _fallback_subtopics(query, requested)

        data = _parse_json_object(content)
        items = data.get("subtopics") or []
        if not isinstance(items, list) or not items:
            return _fallback_subtopics(query, requested)
        parsed: list[SubTopic] = []
        seen_queries: set[str] = set()
        for idx, raw in enumerate(items[:max_count], start=1):
            if not isinstance(raw, dict):
                continue
            sub_query = str(raw.get("sub_query", "")).strip()
            facet = str(raw.get("facet", "")).strip() or f"Subtopic {idx}"
            if not sub_query:
                continue
            key = sub_query.lower()
            if key in seen_queries:
                continue
            seen_queries.add(key)
            parsed.append(
                SubTopic(
                    id=str(raw.get("id") or f"S{idx}"),
                    facet=facet,
                    sub_query=sub_query,
                    rationale=str(raw.get("rationale", "")).strip(),
                    complexity=str(raw.get("complexity", "medium")).strip().lower()
                    if str(raw.get("complexity", "medium")).strip().lower() in {"low", "medium", "high"}
                    else "medium",
                )
            )
        if len(parsed) < requested:
            fallback = _fallback_subtopics(query, requested)
            existing = {item.sub_query.lower() for item in parsed}
            for item in fallback:
                if item.sub_query.lower() in existing:
                    continue
                parsed.append(item)
                if len(parsed) >= requested:
                    break
        return parsed[:requested]
    except Exception as exc:  # noqa: BLE001
        logger.error("Subtopic decomposition failed: %s", exc)
        return _fallback_subtopics(query, requested)
