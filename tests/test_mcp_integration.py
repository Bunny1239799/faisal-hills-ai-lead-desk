import pytest
from jarvis.mcp.client import MCPClient

def test_mcp_client_call_tool():
    client = MCPClient(server_path="mock_server")
    result = client.call_tool("test_tool", {"arg": "value"})
    assert result["success"] is True
    assert "Executed test_tool" in result["result"]
