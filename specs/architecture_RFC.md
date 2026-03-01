# Architecture RFC: Solving the "AI Research Quality" Deficit (Rev 2)

## 1. Context: The Core Problem
The current AI is failing because we are asking it to do too much (10 rigid sections) with too little data (2600 tokens) in a single breath. If we want it to act like a team, we have to architect it like a team: specialized roles, deep independent research, and a final editor.

The user has selected **Approach C: The Recursive "Sub-Topic" Team**. This document details exactly *how* we build it.

---

## 2. Approach C: The Recursive "Sub-Topic" Team (Detailed Architecture)

### The Concept
We will shift from a linear "Extract -> Synthesize" pipeline to a **Map-Reduce (Fan-Out / Fan-In)** architecture using LangGraph's native parallel execution capabilities. 

Instead of reading a massive pile of disjointed web pages, the final Synthesizer will read **3 to 4 highly polished, focused sub-reports** written by independent AI "agents".

### Data Flow & LangGraph Map-Reduce
LangGraph supports dynamic parallel branching via the `Send` API. Here is the new flow:

```mermaid
graph TD
    Start[User Query] --> Planner[Planner Node]
    
    Planner -- Generate Sub-Query 1 --> SR1[Sub-Research Node]
    Planner -- Generate Sub-Query 2 --> SR2[Sub-Research Node]
    Planner -- Generate Sub-Query 3 --> SR3[Sub-Research Node]
    
    subgraph Parallel Sub-Research (The "Team")
        direction LR
        Search[Retrieve Docs] --> Extract[Extract Claims] --> SubDraft[Draft Focused Sub-Report]
    end
    
    SR1 -. executes .-> Search
    SR2 -. executes .-> Search
    SR3 -. executes .-> Search
    
    SR1 --> |Sub-Report 1| MasterSynth[Master Synthesizer Node]
    SR2 --> |Sub-Report 2| MasterSynth
    SR3 --> |Sub-Report 3| MasterSynth
    
    MasterSynth --> |Merge & Format| FinalOutput[Final Master Report]
```

### Module & State Changes

#### 1. State Update (`graph/state.py`)
We need to update the global `ResearchState` to support appending sub-reports concurrently.
```python
from typing import Annotated
import operator
from pydantic import BaseModel

class SubReport(BaseModel):
    sub_query: str
    content: str
    citations: list[Citation]
    docs: list[RetrievedDoc]

class ResearchState(TypedDict):
    query: str
    # Use Annotated and operator.add so parallel nodes can append to the list safely
    sub_reports: Annotated[list[SubReport], operator.add] 
    report_draft: str
    citations: list[Citation]
    # ... other existing fields
```

#### 2. The Planner Node (`graph/nodes/planner.py`)
*Current behavior:* Generates a JSON list of search queries, which are then run sequentially or aggregated.
*New behavior:* Uses an LLM to decompose the main query into 3-4 distinct sub-topics (e.g., "History", "Technical Specs", "Risks").
*Tech:* Returns `[Send("sub_research", {"sub_query": sq.query})]` which tells LangGraph to spin up parallel nodes.

#### 3. New Node: `sub_research_node` (`graph/nodes/sub_research.py`)
This is a new orchestrator for the individual "Analyst".
It accepts a separate state: `class SubResearchState(TypedDict): sub_query: str`
**Flow inside this node:**
1. Call Tavily/Firecrawl just for this `sub_query` (Top 5 results).
2. Call `extract_claims` on these specific docs.
3. Call an LLM (e.g., `gpt-4o-mini`) with a **Sub-Report Prompt**: *"Write a comprehensive 500-word analysis on [sub_query] based. Cite your sources."*
4. Return: `{"sub_reports": [SubReport(...)]}`. This appends exactly one sub-report to the master state.

#### 4. Master Synthesizer Node (`graph/nodes/synthesizer.py`)
*Current behavior:* Reads raw web snippets, tries to write a 10-section report.
*New behavior:*
1. Reads `state["sub_reports"]`.
2. Concatenates the text of the 3-4 sub-reports.
3. Calls the heavy, premium LLM (e.g., `gpt-4o` or `claude-3.5-sonnet`).
4. **Master Prompt Focus:** *"You are the Chief Editor. Merge the following analyst sub-reports into a cohesive Executive Summary, Key Findings, and Action Plan. Resolve conflicting evidence. Do NOT invent new facts outside the sub-reports."*
5. Merges citations from the sub-reports and deduplicates them.

### API & Tech Stack Requirements
*   **LangGraph `Send` API:** Crucial for dynamic Fan-Out. Without this, we can't spawn variable numbers of sub-researchers.
*   **LLM Tiering (Free Edition - No Google):**
    *   *Planner:* `llama-3-8b-8192` (Groq). Instant speed for structural decomposition.
    *   *Sub-Researcher:* `llama-3-70b-8192` (Groq) or `mistral-nemo-12b-instruct:free` (OpenRouter). 
    *   *Master Synthesizer:* `llama-3-70b-8192` (Groq) or `qwen-2.5-72b-instruct:free` (OpenRouter). 
*   **Concurrency:** LangGraph handles this natively via Python `asyncio`.

---

## 3. Free API Strategy: The "Three-Pillar" Defense

Since we cannot use Google/Gemini and must rely on free tiers of Groq, OpenRouter, and Hugging Face, we will implement **Cross-Provider Load Balancing** to ensure the "Team" doesn't hit Rate Limits (429 errors) mid-run.

| Role | Provider 1 (Primary) | Provider 2 (Fallback) | Strategy |
| :--- | :--- | :--- | :--- |
| **Planner** | Groq (Llama-3-8b) | HF (Mistral-7B) | Fast tokens, low weight. |
| **Search** | DuckDuckGo | Tavily (Free) | No key required for DDG. |
| **Sub-Researcher 1** | Groq (Llama-3-70b) | OpenRouter (Gemma-2-9b) | Distribute agents across providers to |
| **Sub-Researcher 2** | OpenRouter (Mistral-Nemo) | Groq (Mixtral-8x7b) | avoid cumulative Rate Limit exhaustion |
| **Sub-Researcher 3** | HF (Zephyr-7b) | Groq (Llama-3-8b) | on a single API key. |
| **Final Editor** | Groq (Llama-3-70b) | OpenRouter (Qwen-2.5-72B) | Reserve the highest reasoning for the end. |

---

## 4. Implementation Steps (Iterative Plan)
... (rest of the plan remains the same)

1.  **Phase 1: State & Types**
    *   Update `core/models.py` and `graph/state.py` with the `SubReport` model and `Annotated[list, operator.add]`.
2.  **Phase 2: The Sub-Researcher**
    *   Create `graph/nodes/sub_research.py`.
    *   Draft the `SUB_RESEARCHER_PROMPT`.
3.  **Phase 3: The Graph Plumbing (`pipeline.py`)**
    *   Rewrite `planner.py` to yield `Send` objects.
    *   Update `pipeline.py` edges (Planner -> `Send("sub_research")`, `sub_research` -> Synthesizer).
4.  **Phase 4: The Master Editor**
    *   Update `synthesizer.py` to ingest sub-reports instead of raw docs.
    *   Rewrite `SYNTHESIZER_PROMPT` to act as an editor.

**Are you aligned with this structural plan? If yes, we can begin Phase 1 immediately using the iterative build workflow.**
