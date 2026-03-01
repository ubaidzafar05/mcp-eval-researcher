from unittest.mock import MagicMock

import pytest

from core.models import RetrievedDoc, RunConfig, TenantContext
from graph.nodes.self_correction import create_self_correction_node
from graph.nodes.synthesizer import create_synthesizer_node
from graph.runtime import GraphRuntime


@pytest.fixture
def mock_runtime():
    config = RunConfig(tenant_id="test-tenant")
    runtime = MagicMock(spec=GraphRuntime)
    runtime.config = config
    runtime.model_router = MagicMock()
    runtime.get_llm_client = MagicMock()
    runtime.tracer = MagicMock()
    return runtime


def test_synthesizer_routing(mock_runtime):
    selection = MagicMock()
    selection.provider = "openai"
    selection.model_name = "gpt-4"
    selection.temperature = 0.3
    mock_runtime.model_router.select_model.return_value = selection

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = """
## Executive Summary
Synthesis summary [C1].

## Scope and Method
- Scoped to one source.
- Claim-level citation mapping [C1].

## Evidence Matrix
- [C1] Doc evidence mapped to source URL.

## Key Findings
- [C1] Source evidence indicates a clear finding.

## Counterevidence / Alternative Interpretations
- Alternate interpretation is limited due single-source scope.

## Risks, Gaps, and Uncertainty
- Single-source dependency limits confidence.

## Recommendations
- Validate with additional sources.

## Sources Used
- [C1] Doc (tavily) - https://example.com/doc
"""
    mock_runtime.get_llm_client.return_value = mock_client

    node = create_synthesizer_node(mock_runtime)
    state = {
        "query": "test",
        "run_id": "test-run",
        "tavily_docs": [
            RetrievedDoc(
                title="Doc",
                url="https://example.com/doc",
                snippet="s",
                provider="tavily",
                score=1.0,
            )
        ],
        "tenant_context": TenantContext(tenant_id="test-tenant"),
    }

    result = node(state)

    call_kwargs = mock_runtime.model_router.select_model.call_args.kwargs
    assert call_kwargs["task_type"] == "synthesis"
    assert call_kwargs["tenant_tier"] == "free"
    assert call_kwargs["plan_complexity"] == "high"
    mock_runtime.get_llm_client.assert_called_with("openai")
    assert "## Executive Summary" in result["report_draft"]
    assert "[C1]" in result["report_draft"]


def test_correction_routing(mock_runtime):
    selection = MagicMock()
    selection.provider = "anthropic"
    selection.model_name = "claude-3-opus"
    selection.temperature = 0.2
    mock_runtime.model_router.select_model.return_value = selection

    mock_client = MagicMock()
    mock_client.messages.create.return_value.content[0].text = """
## Executive Summary
Corrected summary [C1].

## Scope and Method
- Revised for clarity and citation compliance [C1].

## Evidence Matrix
- [C1] Supporting evidence map.

## Key Findings
- [C1] Corrected and traceable finding.

## Counterevidence / Alternative Interpretations
- Alternative interpretation remains possible.

## Risks, Gaps, and Uncertainty
- Evidence scope remains narrow.

## Recommendations
- Expand source set for stronger confidence.

## Sources Used
- [C1] Placeholder source (tavily) - https://example.com/source
"""
    mock_runtime.get_llm_client.return_value = mock_client

    node = create_self_correction_node(mock_runtime)
    state = {
        "query": "test",
        "run_id": "test-run",
        "report_draft": "Bad report without citations [C1]",
        "citations": [],
        "context_docs": [
            RetrievedDoc(
                title="Doc",
                url="https://example.com/source",
                snippet="supporting snippet",
                provider="tavily",
                score=1.0,
            )
        ],
        "tenant_context": TenantContext(tenant_id="test-tenant"),
    }

    result = node(state)

    call_kwargs = mock_runtime.model_router.select_model.call_args.kwargs
    assert call_kwargs["task_type"] == "correction"
    assert call_kwargs["tenant_tier"] == "free"
    mock_runtime.get_llm_client.assert_called_with("anthropic")
    assert "## Executive Summary" in result["report_draft"]
    assert "[C1]" in result["report_draft"]
