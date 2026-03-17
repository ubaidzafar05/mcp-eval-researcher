from __future__ import annotations

import tempfile

from memory.chroma_store import ChromaMemoryStore


def test_memory_store_embedding_fallback_does_not_crash():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ChromaMemoryStore(
            tmpdir,
            ollama_endpoint="http://localhost:11434",
            ollama_model_embed="nomic-embed-text",
        )
        store._embed_client = None
        assert store._embed_texts(["query"]) is None
        store.add_run("run-1", "query", "summary", [])
        results = store.retrieve_similar("query", k=2)
        assert isinstance(results, list)
