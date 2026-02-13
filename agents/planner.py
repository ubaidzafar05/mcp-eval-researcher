from __future__ import annotations

import json
import logging
from typing import Any

from core.models import TaskSpec
from agents.prompts import PLANNER_PROMPT

logger = logging.getLogger(__name__)

def generate_plan(
    query: str,
    client: Any,
    provider: str,
    model: str,
    max_tasks: int = 3,
) -> list[TaskSpec]:
    """
    Generate a research plan (list of tasks) using the specified LLM.
    """
    user_msg = (
        f"Query: {query}\n"
        f"Max Tasks: {max_tasks}\n"
        "Return a JSON object with a key 'tasks' containing a list of task objects."
    )
    
    try:
        content = ""
        if provider == "openai" or provider == "groq":
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": PLANNER_PROMPT},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            content = resp.choices[0].message.content
        elif provider == "anthropic":
            resp = client.messages.create(
                model=model,
                max_tokens=2000,
                system=PLANNER_PROMPT,
                messages=[
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.2
            )
            content = resp.content[0].text
            
        data = json.loads(content)
        tasks_data = data.get("tasks", [])
        
        tasks: list[TaskSpec] = []
        for i, task_dict in enumerate(tasks_data, start=1):
            # Ensure ID and Priority
            task_dict["id"] = i
            task_dict["priority"] = task_dict.get("priority", i)
            tasks.append(TaskSpec(**task_dict))
            
        return tasks[:max_tasks]

    except Exception as e:
        logger.error(f"Planner LLM failed: {e}. Falling back to heuristic.")
        return []
