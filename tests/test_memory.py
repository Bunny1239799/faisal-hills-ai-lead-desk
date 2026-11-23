import pytest
from pathlib import Path
from jarvis.memory.store import VectorStore

@pytest.fixture
def temp_store(tmp_path):
    store_path = tmp_path / "vector_store.json"
    return VectorStore(store_path=store_path)

def test_add_and_search(temp_store, monkeypatch):
    # Mock embedding function
    monkeypatch.setattr("jarvis.memory.store.get_embedding", lambda text: [0.1, 0.2] if "hello" in text else [0.2, 0.1])

    temp_store.add_text("hello world", {"id": 1})
    temp_store.add_text("foo bar", {"id": 2})

    results = temp_store.search("hello", top_k=1)

    assert len(results) == 1
    assert results[0]["metadata"]["id"] == 1
    assert results[0]["text"] == "hello world"

def test_persistence(tmp_path, monkeypatch):
    store_path = tmp_path / "vector_store.json"

    # Mock embedding
    monkeypatch.setattr("jarvis.memory.store.get_embedding", lambda text: [0.1, 0.1])

    store = VectorStore(store_path=store_path)
    store.add_text("persisted text", {"id": 3})

    # Reload
    new_store = VectorStore(store_path=store_path)
    assert len(new_store.documents) == 1
    assert new_store.documents[0]["metadata"]["id"] == 3
