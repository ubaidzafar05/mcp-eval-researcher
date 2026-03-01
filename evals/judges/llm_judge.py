from __future__ import annotations

import json
from typing import Any

from core.models import Citation, EvalResult, RunConfig


def _heuristic_score(query: str, report: str, citation_coverage: float) -> EvalResult:
    q_tokens = {t for t in query.lower().split() if len(t) > 2}
    r_tokens = {t for t in report.lower().split() if len(t) > 2}
    overlap = len(q_tokens & r_tokens) / max(1, len(q_tokens))
    faithfulness = min(1.0, 0.45 + citation_coverage * 0.55)
    relevancy = min(1.0, 0.35 + overlap * 0.65)
    return EvalResult(
        faithfulness=round(faithfulness, 3),
        relevancy=round(relevancy, 3),
        citation_coverage=round(citation_coverage, 3),
        pass_gate=False,
        reasons=["Heuristic judge score was used."],
        meta={"judge_fallback_used": True, "judge_fallback_reason": "heuristic_mode"},
    )


def _extract_json_block(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""

    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    start = text.find("{")
    if start < 0:
        return ""

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
        return ""
    return text[start : end + 1]


def _parse_judge_payload(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty_judge_payload")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    block = _extract_json_block(text)
    if not block:
        raise ValueError("json_block_not_found")
    data = json.loads(block)
    if not isinstance(data, dict):
        raise ValueError("judge_payload_not_object")
    return data


def _build_messages(user_payload: dict[str, Any], *, retry: bool) -> tuple[str, str]:
    system_msg = (
        "You are a strict evaluator. "
        "Output JSON only with keys: faithfulness (float), relevancy (float), reasons (string array)."
    )
    if retry:
        system_msg += (
            " Prior output was invalid. Return only one JSON object and no surrounding text."
        )
    user_msg = json.dumps(user_payload)
    return system_msg, user_msg


def _call_model(
    *,
    client: Any,
    provider: str,
    model: str,
    system_msg: str,
    user_msg: str,
) -> str:
    if provider in {"openai", "groq", "openrouter"}:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
            temperature=0.1,
        )
        return (resp.choices[0].message.content or "").strip()
    if provider == "anthropic":
        resp = client.messages.create(
            model=model,
            max_tokens=1000,
            system=system_msg,
            messages=[{"role": "user", "content": user_msg}],
            temperature=0.1,
        )
        return (resp.content[0].text if resp.content else "").strip()
    if provider == "huggingface":
        resp = client.chat_completion(
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
            max_tokens=1000,
            temperature=0.1,
        )
        return (resp.choices[0].message.content or "").strip()
    raise ValueError(f"unsupported_judge_provider:{provider}")


def _to_eval_result(
    *,
    data: dict[str, Any],
    base: EvalResult,
    retry_used: bool,
) -> EvalResult:
    faithfulness = float(data.get("faithfulness", base.faithfulness))
    relevancy = float(data.get("relevancy", base.relevancy))
    reasons = [str(r) for r in data.get("reasons", [])]
    return EvalResult(
        faithfulness=max(0.0, min(1.0, faithfulness)),
        relevancy=max(0.0, min(1.0, relevancy)),
        citation_coverage=base.citation_coverage,
        pass_gate=False,
        reasons=reasons,
        meta={"judge_fallback_used": False, "judge_retry_used": retry_used},
    )


def _strict_failure(base: EvalResult, error: str, *, retry_used: bool) -> EvalResult:
    return EvalResult(
        faithfulness=0.0,
        relevancy=0.0,
        citation_coverage=base.citation_coverage,
        pass_gate=False,
        reasons=[
            "Judge JSON parse failed in strict mode.",
            f"judge_error: {error}",
        ],
        meta={
            "judge_fallback_used": False,
            "judge_retry_used": retry_used,
            "judge_parse_error": error,
            "judge_strict_failure": True,
        },
    )


def judge_with_llm(
    query: str,
    report: str,
    citations: list[Citation],
    citation_coverage: float,
    config: RunConfig,
    client: Any,
    provider: str,
    model: str,
) -> EvalResult:
    del citations
    base = _heuristic_score(query, report, citation_coverage)
    mode = getattr(config, "judge_json_mode", "repair_retry_fallback")
    if mode == "heuristic":
        return base

    payload = {
        "query": query,
        "report": report[:9000],
        "citation_coverage": citation_coverage,
        "task": (
            "Score faithfulness and relevancy between 0 and 1. "
            "Return JSON: {faithfulness: float, relevancy: float, reasons: [str,...]}"
        ),
    }

    retry_used = False
    last_error = ""
    for attempt in range(2):
        retry_used = attempt == 1
        system_msg, user_msg = _build_messages(payload, retry=retry_used)
        try:
            content = _call_model(
                client=client,
                provider=provider,
                model=model,
                system_msg=system_msg,
                user_msg=user_msg,
            )
            data = _parse_judge_payload(content)
            return _to_eval_result(data=data, base=base, retry_used=retry_used)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if mode == "strict":
                break
            if mode != "repair_retry_fallback":
                break

    if mode == "strict":
        return _strict_failure(base, last_error or "judge_parse_failed", retry_used=retry_used)

    fallback = base.model_copy(deep=True)
    fallback.reasons = [
        *fallback.reasons,
        "Judge JSON parsing failed; used deterministic fallback.",
    ]
    fallback.meta = {
        "judge_fallback_used": True,
        "judge_retry_used": retry_used,
        "judge_parse_error": last_error or "judge_parse_failed",
    }
    return fallback
