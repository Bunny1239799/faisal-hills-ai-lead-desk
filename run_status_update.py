from jarvis.agent.loop import run_agent

prompt = """
You are JARVIS. Your task is to update the persistent project state.

1. Read the current file at relative_path "D:/JARVIS/00_Core/CURRENT_STATE.md" if it exists (you may need to use the correct relative path from the project root or note if the tool is restricted to the laya-gateway tree).
2. If the tool cannot reach D:\\JARVIS directly, first create or update a status file inside the current project at relative_path "jarvis/agent/CURRENT_AGENT_STATUS.md".

Write a clear, factual status that includes:
- Date: 2026-10-11
- Mission 001: COMPLETED
- build_tool_schemas is now dynamic
- create_file tool is implemented, exposed, and verified working via direct call
- End-to-end agent write still limited by hardware timeout
- Next priority: make agent write path reliable and continue Stage 1–2 work

Use the create_file tool. Do not overwrite important existing files unless necessary. After writing, confirm what you did.
"""

result = run_agent(prompt, timeout=1800)  # 30 minutes
print(result)
