from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.models import Citation, EvalResult, ResearchResult, RunConfig


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass(slots=True)
class RunRegistryRecord:
    run_id: str
    query: str
    status: str
    artifacts_path: str
    low_confidence: bool
    updated_at: str

    @classmethod
    def from_dict(cls, payload: dict) -> RunRegistryRecord:
        return cls(
            run_id=str(payload.get("run_id", "")),
            query=str(payload.get("query", "")),
            status=str(payload.get("status", "unknown")),
            artifacts_path=str(payload.get("artifacts_path", "")),
            low_confidence=bool(payload.get("low_confidence", False)),
            updated_at=str(payload.get("updated_at", "")),
        )

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "query": self.query,
            "status": self.status,
            "artifacts_path": self.artifacts_path,
            "low_confidence": self.low_confidence,
            "updated_at": self.updated_at,
        }


def _registry_path(config: RunConfig) -> Path:
    return Path(config.data_dir) / "run_registry.jsonl"


def _read_all_records(path: Path) -> list[RunRegistryRecord]:
    if not path.exists():
        return []
    records: list[RunRegistryRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        records.append(RunRegistryRecord.from_dict(payload))
    return records


def _write_all_records(path: Path, records: list[RunRegistryRecord]) -> None:
    lines = [json.dumps(item.to_dict(), ensure_ascii=True) for item in records]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def upsert_registry_record(config: RunConfig, result: ResearchResult) -> None:
    path = _registry_path(config)
    records = _read_all_records(path)
    next_record = RunRegistryRecord(
        run_id=result.run_id,
        query=result.query,
        status=result.status,
        artifacts_path=result.artifacts_path,
        low_confidence=result.low_confidence,
        updated_at=_utc_now_iso(),
    )
    by_id = {item.run_id: item for item in records}
    by_id[next_record.run_id] = next_record
    merged = sorted(by_id.values(), key=lambda item: item.updated_at, reverse=True)
    _write_all_records(path, merged)


def list_registry_records(config: RunConfig, limit: int = 20) -> list[RunRegistryRecord]:
    path = _registry_path(config)
    records = _read_all_records(path)
    records.sort(key=lambda item: item.updated_at, reverse=True)
    return records[: max(1, limit)]


def get_registry_record(config: RunConfig, run_id: str) -> RunRegistryRecord | None:
    path = _registry_path(config)
    for item in _read_all_records(path):
        if item.run_id == run_id:
            return item
    return None


def load_result_from_artifacts(config: RunConfig, run_id: str) -> ResearchResult:
    record = get_registry_record(config, run_id)
    if record is None:
        raise ValueError(f"Run '{run_id}' was not found in local registry.")

    artifacts_dir = Path(record.artifacts_path) if record.artifacts_path else Path(config.output_dir) / run_id
    report_path = artifacts_dir / "final_report.md"
    citations_path = artifacts_dir / "citations.json"
    eval_path = artifacts_dir / "eval.json"
    if not report_path.exists():
        raise FileNotFoundError(f"Missing report artifact: {report_path}")
    if not eval_path.exists():
        raise FileNotFoundError(f"Missing eval artifact: {eval_path}")

    report = report_path.read_text(encoding="utf-8")
    citations_payload = []
    if citations_path.exists():
        citations_payload = json.loads(citations_path.read_text(encoding="utf-8"))
    eval_payload = json.loads(eval_path.read_text(encoding="utf-8"))

    citations = [Citation.model_validate(item) for item in citations_payload]
    eval_result = EvalResult.model_validate(eval_payload)
    return ResearchResult(
        run_id=record.run_id,
        query=record.query,
        final_report=report,
        citations=citations,
        eval_result=eval_result,
        low_confidence=record.low_confidence,
        status=record.status,
        artifacts_path=str(artifacts_dir),
    )
