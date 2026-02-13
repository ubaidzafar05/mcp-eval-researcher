
import pytest
from unittest.mock import MagicMock, patch
from graph.nodes.synthesizer import create_synthesizer_node
from graph.nodes.self_correction import create_self_correction_node
from graph.nodes.eval_gate import create_eval_gate_node
from graph.runtime import GraphRuntime
from core.models import RunConfig, TenantContext, RetrievedDoc, Citation

@pytest.fixture
def mock_runtime():
    config = RunConfig(tenant_id="test-tenant")
    runtime = MagicMock(spec=GraphRuntime)
    runtime.config = config
    runtime.model_router = MagicMock()
    runtime.get_llm_client = MagicMock()
    return runtime

def test_synthesizer_routing(mock_runtime):
    # Setup
    mock_selection = MagicMock()
    mock_selection.provider = "openai"
    mock_selection.model_name = "gpt-4"
    mock_runtime.model_router.select_model.return_value = mock_selection
    
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "Synthesized Report"
    mock_runtime.get_llm_client.return_value = mock_client
    
    node = create_synthesizer_node(mock_runtime)
    state = {
        "query": "test", 
        "run_id": "test-run", 
        "tavily_docs": [RetrievedDoc(title="t", url="u", snippet="s", provider="tavily", score=1.0)], 
        "tenant_context": TenantContext(tenant_id="test-tenant")
    }
    
    # Execute
    result = node(state)
    
    # Verify
    mock_runtime.model_router.select_model.assert_called_with(
        task_type="synthesis",
        tenant_id="test-tenant",
        plan_complexity="high"
    )
    mock_runtime.get_llm_client.assert_called_with("openai")
    assert "Synthesized Report" in result["report_draft"]

def test_correction_routing(mock_runtime):
    # Setup - simulate validation failure
    mock_selection = MagicMock()
    mock_selection.provider = "anthropic"
    mock_selection.model_name = "claude-3-opus"
    mock_runtime.model_router.select_model.return_value = mock_selection
    
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content[0].text = "Corrected Report"
    mock_runtime.get_llm_client.return_value = mock_client
    
    node = create_self_correction_node(mock_runtime)
    state = {
        "query": "test", 
        "run_id": "test-run", 
        "report_draft": "Bad report", 
        "citations": [],
        "tenant_context": TenantContext(tenant_id="test-tenant")
    }
    
    # Execute
    result = node(state)
    
    # Verify
    mock_runtime.model_router.select_model.assert_called()
    assert mock_runtime.model_router.select_model.call_args[1]["task_type"] == "correction"
    mock_runtime.get_llm_client.assert_called_with("anthropic")
    assert result["report_draft"] == "Corrected Report"

def test_eval_gate_routing(mock_runtime):
    # Setup
    mock_selection = MagicMock()
    mock_selection.provider = "groq"
    mock_selection.model_name = "llama-3"
    mock_runtime.model_router.select_model.return_value = mock_selection
    
    mock_client = MagicMock()
    # Mocking generic LLM judge structure
    mock_client.chat.completions.create.return_value.choices[0].message.content = '{"faithfulness": 0.9, "relevancy": 0.9, "reasons": []}'
    mock_runtime.get_llm_client.return_value = mock_client
    
    node = create_eval_gate_node(mock_runtime)
    state = {
        "query": "test", 
        "run_id": "test-run", 
        "report_draft": "Report with claim [C1]", 
        "citations": [Citation(claim_id="C1", title="t", source_url="u", evidence="e", provider="p")],
        "tenant_context": TenantContext(tenant_id="test-tenant")
    }
