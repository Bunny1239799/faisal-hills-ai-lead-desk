from jarvis.agent.loop import run_agent

prompt = (
    "Create a new file at relative_path \"jarvis/agent/JARVIS_WRITE_TEST.txt\" "
    "with the exact content: \"JARVIS write path verified successfully on 2026-10-11. "
    "This file was created by the agent through the controlled create_file tool.\" "
    "Do not overwrite any existing file. After creating it, confirm the result."
)

result = run_agent(prompt)
print(result)
