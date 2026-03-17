import json
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP
import numpy as np
import ollama

# Initialize FastMCP for POLARIS
app = FastMCP("POLARIS")

# Constants
MEMORY_DIR = Path("~/.openclaw/workspace/memory").expanduser()
SESSION_STATE = Path("~/.openclaw/workspace/SESSION-STATE.md").expanduser()
LONG_TERM_MEMORY = Path("~/.openclaw/workspace/MEMORY.md").expanduser()
RAG_INDEX = Path("~/.openclaw/workspace/scripts/rag/workspace_index.json").expanduser()
RAG_VECTORS = Path("~/.openclaw/workspace/scripts/rag/workspace_vectors.npy").expanduser()
EMBED_MODEL = "nomic-embed-text"

@app.tool()
def read_polaris_memory(type: str = "all") -> str:
    """Read POLARIS long-term or short-term memory. type can be 'session', 'long-term', or 'all'."""
    content = ""
    if type in ["session", "all"]:
        if SESSION_STATE.exists():
            content += f"--- SESSION STATE ---\n{SESSION_STATE.read_text()}\n\n"
    if type in ["long-term", "all"]:
        if LONG_TERM_MEMORY.exists():
            content += f"--- LONG-TERM MEMORY ---\n{LONG_TERM_MEMORY.read_text()}\n\n"
    return content if content else "No memory files found."

@app.tool()
def codebase_rag_search(query: str, top_k: int = 5) -> str:
    """Search the local codebase using semantic RAG. Excellent for finding context without knowing filenames."""
    if not RAG_INDEX.exists() or not RAG_VECTORS.exists():
        return "RAG Index not found. The background indexing task might still be running."

    # Load data
    with open(RAG_INDEX, 'r') as f:
        chunks = json.load(f)
    vectors = np.load(RAG_VECTORS)

    # Embed query
    resp = ollama.embeddings(model=EMBED_MODEL, prompt=query)
    query_vec = np.array(resp['embedding'])

    # Compute cosine similarity
    norm_vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    norm_query = query_vec / np.linalg.norm(query_vec)
    similarities = np.dot(norm_vectors, norm_query)

    # Get top results
    top_indices = np.argsort(similarities)[::-1][:top_k]
    
    results = []
    for idx in top_indices:
        results.append(f"File: {chunks[idx]['filename']} (Score: {similarities[idx]:.2f})\n---\n{chunks[idx]['content']}\n---")
    
    return "\n\n".join(results)

@app.tool()
def read_daily_logs(date: str) -> str:
    """Read the POLARIS daily logs for a specific date (Format: YYYY-MM-DD)."""
    log_path = MEMORY_DIR / f"{date}.md"
    if log_path.exists():
        return log_path.read_text()
    return f"No logs found for {date}."

if __name__ == "__main__":
    app.run(transport="stdio")
