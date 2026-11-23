import pytest

from jarvis.agent.core import AgentCoreError, execute_tool
from jarvis.agent.loop import build_tool_schemas
from jarvis.agent.permissions import permission_level
from jarvis.agent.skills import SPECIALIST_SKILLS, load_skill


def test_skills_are_green_and_exposed():
    names = {schema["function"]["name"] for schema in build_tool_schemas()}
    for tool_name in ("list_specialist_skills", "load_skill"):
        assert permission_level(tool_name) == "GREEN"
        assert tool_name in names


def test_list_specialist_skills_matches_catalog():
    result = execute_tool("list_specialist_skills", {})
    assert result["success"] is True
    assert result["result"]["skills"] == sorted(SPECIALIST_SKILLS)


def test_load_skill_returns_brief():
    result = execute_tool("load_skill", {"name": "Developer"})
    assert result["success"] is True
    assert result["result"]["name"] == "developer"
    assert result["result"]["brief"] == SPECIALIST_SKILLS["developer"]


def test_unknown_skill_fails_closed():
    with pytest.raises(AgentCoreError, match="Unknown skill"):
        execute_tool("load_skill", {"name": "ceo"})


def test_load_skill_direct_unknown():
    with pytest.raises(ValueError, match="Unknown skill"):
        load_skill("marketer")
