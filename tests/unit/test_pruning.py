from core.models import RetrievedDoc
from core.pruning import dedupe_docs, prune_context_docs


def test_dedupe_and_prune_context_docs():
    docs = [
        RetrievedDoc(
            provider="tavily",
            title="Doc A",
            url="https://a",
            content="A long document about cloud hive and orchestration." * 20,
        ),
        RetrievedDoc(
            provider="tavily",
            title="Doc A",
            url="https://a",
            content="A long document about cloud hive and orchestration." * 20,
        ),
        RetrievedDoc(
            provider="ddg",
            title="Doc B",
            url="https://b",
            content="Another source discussing limits and retries." * 20,
        ),
    ]
    deduped = dedupe_docs(docs)
    assert len(deduped) == 2

    pruned = prune_context_docs(deduped, per_doc_tokens=20, total_tokens=30)
    assert len(pruned) >= 1
    assert all(len(doc.content) <= 20 * 4 for doc in pruned)

