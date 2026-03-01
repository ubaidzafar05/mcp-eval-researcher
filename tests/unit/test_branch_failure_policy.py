from types import SimpleNamespace

from core.models import SubTopic
from graph.nodes.sub_research import create_sub_research_node
from graph.pipeline import _dispatch_subresearch


def test_dispatch_subresearch_emits_send_for_each_subtopic():
    state = {
        "subtopics": [
            SubTopic(id="S1", facet="Evidence", sub_query="q1"),
            SubTopic(id="S2", facet="Mechanism", sub_query="q2"),
        ]
    }
    sends = _dispatch_subresearch(state)
    assert isinstance(sends, list)
    assert len(sends) == 2
    assert all(getattr(item, "node", "") == "sub_research" for item in sends)


def test_sub_research_fail_closed_when_no_docs():
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            subreport_failure_policy="fail_closed",
            subreport_gapfill_enabled=False,
            subreport_min_claims=3,
        )
    )
    node = create_sub_research_node(runtime)
    updates = node(
        {
            "query": "Test query",
            "shared_corpus_docs": [],
            "subtopic_id": "S1",
            "subtopic_facet": "Evidence",
            "subtopic_query": "focused sub query",
            "subtopics": [SubTopic(id="S1", facet="Evidence", sub_query="focused sub query")],
        }
    )
    assert "sub_reports" not in updates
    assert updates["subtopic_failures"] == ["S1:no_relevant_docs"]


def test_sub_research_continue_constrained_when_no_docs():
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            subreport_failure_policy="continue_constrained",
            subreport_gapfill_enabled=False,
            subreport_min_claims=3,
        )
    )
    node = create_sub_research_node(runtime)
    updates = node(
        {
            "query": "Test query",
            "shared_corpus_docs": [],
            "subtopic_id": "S1",
            "subtopic_facet": "Evidence",
            "subtopic_query": "focused sub query",
            "subtopics": [SubTopic(id="S1", facet="Evidence", sub_query="focused sub query")],
        }
    )
    assert updates["subtopic_failures"] == ["S1:no_relevant_docs"]
    assert len(updates["sub_reports"]) == 1
    assert updates["sub_reports"][0].confidence == "constrained"

