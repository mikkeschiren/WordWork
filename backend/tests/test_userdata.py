"""Inställningar och AI-samtal sparas som filer i datakatalogen."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(data_dir=tmp_path, static_dir=None, snapshot_minutes=5, ollama_url="", ollama_model="")
    return TestClient(create_app(settings))


def test_settings_roundtrip(client, tmp_path):
    assert client.get("/api/settings").json() == {"saved": False, "settings": {}}
    s = {"theme": "sepia", "size": 21, "quoteStyle": "angle", "aiThink": False}
    assert client.put("/api/settings", json=s).status_code == 200
    assert client.get("/api/settings").json() == {"saved": True, "settings": s}
    assert json.loads((tmp_path / ".wordwork" / "settings.json").read_text()) == s
    # Inställningsfilen är inget dokument.
    assert client.get("/api/documents").json() == []


def test_settings_validation(client, tmp_path):
    assert client.put("/api/settings", json=[1, 2]).status_code == 422
    assert client.put("/api/settings", json={"x": "a" * 70_000}).status_code == 400
    (tmp_path / ".wordwork" / "settings.json").write_text("{trasig")
    assert client.get("/api/settings").json() == {"saved": True, "settings": {}}


def test_chats_save_list_read_delete(client, tmp_path):
    client.post("/api/documents", json={"name": "Krönika"})
    msgs = [
        {"role": "user", "content": "Fråga?", "label": "Granska språket", "pending": True},
        {"role": "assistant", "content": "Svar.", "thinking": "hmm", "meta": "qwen · 3 s", "extra": 1},
    ]
    r = client.put("/api/documents/Krönika/chats/c1", json={"model": "qwen", "messages": msgs})
    assert r.status_code == 200 and r.json()["title"] == "Granska språket" and r.json()["messages"] == 2
    chat = client.get("/api/documents/Krönika/chats/c1").json()
    assert chat["messages"][0] == {"role": "user", "content": "Fråga?", "label": "Granska språket"}
    assert chat["messages"][1] == {"role": "assistant", "content": "Svar.", "thinking": "hmm", "meta": "qwen · 3 s"}
    created = chat["created"]

    client.put("/api/documents/Krönika/chats/c2", json={"messages": [{"role": "user", "content": "Andra"}]})
    client.put("/api/documents/Krönika/chats/c1", json={"messages": msgs})
    listed = client.get("/api/documents/Krönika/chats").json()
    assert {c["id"] for c in listed} == {"c1", "c2"}
    assert client.get("/api/documents/Krönika/chats/c1").json()["created"] == created

    assert client.delete("/api/documents/Krönika/chats/c2").status_code == 204
    assert [c["id"] for c in client.get("/api/documents/Krönika/chats").json()] == ["c1"]
    assert any(p.name.endswith("Krönika.chat-c2.json") for p in (tmp_path / ".trash").iterdir())
    assert client.get("/api/documents/Krönika/chats/c2").status_code == 404


def test_chat_validation(client):
    client.post("/api/documents", json={"name": "Doc"})
    assert client.put("/api/documents/Doc/chats/../x", json={"messages": []}).status_code in (400, 404)
    assert client.put("/api/documents/Doc/chats/a.b", json={"messages": []}).status_code == 400
    bad = {"messages": [{"role": "system", "content": "x"}]}
    assert client.put("/api/documents/Doc/chats/c1", json=bad).status_code == 400
    assert client.put("/api/documents/Saknas/chats/c1", json={"messages": []}).status_code == 404
    assert client.get("/api/documents/Saknas/chats").status_code == 404


def test_chats_follow_rename_and_delete(client, tmp_path):
    client.post("/api/documents", json={"name": "Gammal"})
    client.put("/api/documents/Gammal/chats/c1", json={"messages": [{"role": "user", "content": "Hej"}]})
    client.post("/api/documents/Gammal/rename", json={"name": "Ny"})
    assert [c["id"] for c in client.get("/api/documents/Ny/chats").json()] == ["c1"]
    client.post("/api/documents", json={"name": "Gammal"})
    assert client.get("/api/documents/Gammal/chats").json() == []

    client.delete("/api/documents/Ny")
    assert any(p.name.endswith("Ny.chats") for p in (tmp_path / ".trash").iterdir())
    assert not (tmp_path / ".chats" / "Ny").exists()
