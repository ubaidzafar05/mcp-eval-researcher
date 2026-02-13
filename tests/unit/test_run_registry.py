import json
from pathlib import Path

from core.config import load_config
from core.models import Citation, EvalResult, ResearchResult
from core.run_registry import (
    get_registry_record,
    list_registry_records,
    load_result_from_artifacts,
    upsert_registry_record,
)


def test_registry_upsert_and_list(tmp_path: Path):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "data_dir": str(tmp_path / "data"),
            "output_dir": str(tmp_path / "outputs"),
        }
    )
    result = ResearchResult(
        run_id="run-test-1",
        query="test query",
        final_report="report",
        citations=[],
        eval_result=EvalResult(),
        low_confidence=False,
        status="completed",
        artifacts_path=str(tmp_path / "outputs" / "run-test-1"),
    )
    upsert_registry_record(cfg, result)
    rows = list_registry_records(cfg, limit=10)
    assert rows
    assert rows[0].run_id == "run-test-1"
    row = get_registry_record(cfg, "run-test-1")
    assert row is not None
    assert row.query == "test query"


def test_load_result_from_artifacts(tmp_path: Path):
    run_id = "run-test-2"
    artifacts = tmp_path / "outputs" / run_id
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "final_report.md").write_text("hello report", encoding="utf-8")
    (artifacts / "citations.json").write_text(
        json.dumps(
            [
                {
                    "claim_id": "c1",
                    "source_url": "https://example.com",
                    "title": "Example",
                    "provider": "tavily",
                    "evidence": "sample",
                }
            ]
        ),
        encoding="utf-8",
    )
    (artifacts / "eval.json").write_text(
        json.dumps(
            {
                "faithfulness": 0.8,
                "relevancy": 0.9,
                "citation_coverage": 1.0,
                "pass_gate": True,
                "reasons": [],
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(
        {
            "interactive_hitl": False,
            "data_dir": str(tmp_path / "data"),
            "output_dir": str(tmp_path / "outputs"),
        }
    )
    initial = ResearchResult(
        run_id=run_id,
        query="resume query",
        final_report="hello report",
        citations=[Citation(claim_id="c1", source_url="https://example.com")],
        eval_result=EvalResult(faithfulness=0.8, relevancy=0.9, citation_coverage=1.0, pass_gate=True),
        low_confidence=False,
        status="completed",
        artifacts_path=str(artifacts),
    )
    upsert_registry_record(cfg, initial)

    resumed = load_result_from_artifacts(cfg, run_id)
    assert resumed.run_id == run_id
    assert resumed.query == "resume query"
    assert resumed.final_report == "hello report"
    assert resumed.eval_result.pass_gate is True
    assert resumed.citations
