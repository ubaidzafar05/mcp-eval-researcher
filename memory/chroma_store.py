from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from core.models import Citation, RetrievedDoc

try:
    chromadb: Any | None = importlib.import_module("chromadb")
except Exception:  # noqa: BLE001
    chromadb = None


def _tokenize(text: str) -> set[str]:
    return {t for t in text.lower().split() if len(t) > 2}


class ChromaMemoryStore:
    """Chroma-backed memory with safe JSON fallback."""

    def __init__(self, persist_dir: str):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.backup_file = self.persist_dir / "memory_store.jsonl"
        self.collection = None
        if chromadb is not None:
            try:
                client = chromadb.PersistentClient(path=str(self.persist_dir))
                self.collection = client.get_or_create_collection("cloud_hive_memory")
            except Exception:  # noqa: BLE001
                self.collection = None

    def add_run(self, run_id: str, query: str, summary: str, citations: list[Citation]) -> None:
        payload: dict[str, Any] = {
            "id": run_id,
            "query": query,
            "summary": summary,
            "citations": [c.model_dump() for c in citations],
        }
        with self.backup_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
        if self.collection is not None:
            try:
                self.collection.add(
                    ids=[run_id],
                    documents=[f"{query}\n{summary}"],
                    metadatas=[{"query": query}],
                )
            except Exception:  # noqa: BLE001
                pass

    def retrieve_similar(self, query: str, k: int = 3) -> list[RetrievedDoc]:
        if self.collection is not None:
            try:
                result = self.collection.query(query_texts=[query], n_results=max(1, k))
                docs_raw = result.get("documents") or [[]]
                metas_raw = result.get("metadatas") or [[]]
                docs = docs_raw[0] if docs_raw else []
                metas = metas_raw[0] if metas_raw else []
                out: list[RetrievedDoc] = []
                for i, text in enumerate(docs):
                    meta_any = metas[i] if i < len(metas) else {}
                    meta = dict(meta_any) if isinstance(meta_any, dict) else {}
                    out.append(
                        RetrievedDoc(
                            provider="memory",
                            title=f"Memory result {i + 1}",
                            url="",
                            snippet=text[:280],
                            content=text,
                            score=0.5,
                            meta=meta,
                        )
                    )
                if out:
                    return out
            except Exception:  # noqa: BLE001
                pass

        if not self.backup_file.exists():
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        query_tokens = _tokenize(query)
        for line in self.backup_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            blob = f"{row.get('query', '')} {row.get('summary', '')}"
            tokens = _tokenize(blob)
            overlap = len(query_tokens & tokens)
            score = overlap / max(1, len(query_tokens))
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[RetrievedDoc] = []
        for score, row in scored[:k]:
            results.append(
                RetrievedDoc(
                    provider="memory",
                    title=f"Memory: {row.get('query', '')[:60]}",
                    url="",
                    snippet=row.get("summary", "")[:280],
                    content=row.get("summary", ""),
                    score=score,
                )
            )
        return results
