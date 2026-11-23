import pytest
from jarvis.agent.research_tools import web_search_tool

def test_web_search_tool_structure():
    result = web_search_tool("test query")
    assert result["status"] == "success"
    assert result["query"] == "test query"
    assert "note" in result
