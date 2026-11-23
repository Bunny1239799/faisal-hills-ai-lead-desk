import pytest
from jarvis.automations.n8n.webhook import trigger_n8n_workflow

def test_trigger_n8n_workflow():
    result = trigger_n8n_workflow("wf_123", {"data": "test"})
    assert result["success"] is True
    assert result["workflow_id"] == "wf_123"
