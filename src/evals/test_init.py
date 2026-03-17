import os

import pytest


def test_project_structure():
    """Verify that all core directories exist."""
    required_dirs = [
        "mcp_server",
        "agents",
        "graph",
        "evals",
        "data",
        "logs"
    ]
    for d in required_dirs:
        assert os.path.exists(d), f"Directory {d} is missing"

def test_requirements_file():
    """Verify requirements.txt exists and has content."""
    assert os.path.exists("requirements.txt")
    with open("requirements.txt") as f:
        content = f.read()
        assert "langgraph" in content
        assert "mcp" in content
        assert "deepeval" in content

def test_langgraph_state_import():
    """Verify state can be imported (indicates basic python setup is OK)."""
    try:
        from graph.state import ResearchState
        assert ResearchState is not None
    except ImportError as e:
        pytest.fail(f"Failed to import ResearchState: {e}")
