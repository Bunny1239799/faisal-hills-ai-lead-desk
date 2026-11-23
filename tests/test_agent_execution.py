import sys
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.agent import loop
from jarvis.agent.core import available_tools
from jarvis.agent.execution_tools import SANDBOX, run_python, run_tests
from jarvis.agent.tools import ToolError


def _names(schemas):
    return {s["function"]["name"] for s in schemas}


def test_run_tests_exposed_run_python_hidden():
    names = _names(loop.build_tool_schemas())
    assert "run_tests" in names
    assert "run_python" not in names


def test_both_tools_registered_as_yellow():
    perms = {t["name"]: t["permission"] for t in available_tools()}
    assert perms["run_tests"] == "YELLOW"
    assert perms["run_python"] == "YELLOW"


def test_run_tests_rejects_path_escape():
    with pytest.raises(ToolError):
        run_tests("../outside")


def test_run_tests_rejects_missing_target():
    with pytest.raises(ToolError):
        run_tests("tests/does_not_exist.py")


def test_run_python_rejects_outside_sandbox():
    with pytest.raises(ToolError):
        run_python("jarvis/agent/loop.py")


def test_run_python_rejects_non_py():
    SANDBOX.mkdir(parents=True, exist_ok=True)
    f = SANDBOX / "_not_python.txt"
    f.write_text("x", encoding="utf-8")
    try:
        with pytest.raises(ToolError):
            run_python("jarvis/sandbox/_not_python.txt")
    finally:
        f.unlink()


def test_run_python_runs_script_and_captures_output():
    SANDBOX.mkdir(parents=True, exist_ok=True)
    f = SANDBOX / "_hello_test.py"
    f.write_text("print('hello from sandbox')", encoding="utf-8")
    try:
        r = run_python("jarvis/sandbox/_hello_test.py")
        assert r["passed"] and "hello from sandbox" in r["output"]
    finally:
        f.unlink()


def test_run_python_times_out():
    SANDBOX.mkdir(parents=True, exist_ok=True)
    f = SANDBOX / "_sleep_test.py"
    f.write_text("import time\ntime.sleep(10)", encoding="utf-8")
    try:
        r = run_python("jarvis/sandbox/_sleep_test.py", timeout_seconds=1)
        assert r["timed_out"] and not r["passed"]
    finally:
        f.unlink()


def _fake_model(tool_name, arguments):
    calls = {"n": 0}

    def fake_chat(messages, tools=None, timeout=0, model=None, num_predict=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"message": {"role": "assistant", "content": "",
                                "tool_calls": [{"function": {"name": tool_name,
                                                             "arguments": arguments}}]}}
        last_tool = [m for m in messages if m.get("role") == "tool"][-1]
        return {"message": {"role": "assistant", "content": last_tool["content"]}}

    return fake_chat


def test_loop_blocks_tool_not_exposed_to_model(monkeypatch):
    monkeypatch.setattr(loop, "chat", _fake_model("run_python", {"relative_path": "jarvis/sandbox/x.py"}))
    result = loop.run_agent("hello", timeout=5)
    assert "not exposed" in result["content"]


def test_loop_recovers_from_tool_error(monkeypatch):
    monkeypatch.setattr(loop, "chat", _fake_model("list_directory", {"bogus_argument": 1}))
    result = loop.run_agent("hello", timeout=5)
    assert "'success': False" in result["content"]
