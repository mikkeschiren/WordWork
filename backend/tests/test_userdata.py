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


def test_trash_list_and_restore(client, tmp_path):
    client.post("/api/documents", json={"name": "Essä", "content": "# Essä\n\nEtt två tre.\n"})
    client.post("/api/documents/Essä/history", json={"label": "v1"})
    client.put("/api/documents/Essä/chats/c1", json={"messages": [{"role": "user", "content": "Hej"}]})
    client.put("/api/documents/Essä/chats/c2", json={"messages": [{"role": "user", "content": "Andra"}]})
    client.delete("/api/documents/Essä/chats/c2")
    trash = client.get("/api/trash").json()
    assert [t["kind"] for t in trash] == ["chat"] and trash[0]["title"] == "Andra"
    # Ett samtal återställs till sitt dokument.
    assert client.post(f"/api/trash/{trash[0]['id']}/restore").json() == {"kind": "chat", "name": "Essä", "id": "c2"}
    assert {c["id"] for c in client.get("/api/documents/Essä/chats").json()} == {"c1", "c2"}

    client.delete("/api/documents/Essä")
    item = client.get("/api/trash").json()[0]
    assert item["kind"] == "document" and item["name"] == "Essä" and item["history"] and item["chats"] == 2
    # Ett nytt dokument med samma namn finns – det återställda får ett annat namn.
    client.post("/api/documents", json={"name": "Essä"})
    r = client.post(f"/api/trash/{item['id']}/restore").json()
    assert r == {"kind": "document", "name": "Essä (återställd)"}
    assert client.get("/api/documents/Essä (återställd)").json()["content"] == "# Essä\n\nEtt två tre.\n"
    assert len(client.get("/api/documents/Essä (återställd)/history").json()) == 1
    assert len(client.get("/api/documents/Essä (återställd)/chats").json()) == 2
    assert client.get("/api/trash").json() == []


def test_trash_errors(client, tmp_path):
    assert client.post("/api/trash/finns-inte.md/restore").status_code == 404
    assert client.post("/api/trash/..%2Fx/restore").status_code in (400, 404)
    client.post("/api/documents", json={"name": "A"})
    client.put("/api/documents/A/chats/c1", json={"messages": [{"role": "user", "content": "Hej"}]})
    client.delete("/api/documents/A/chats/c1")
    entry = client.get("/api/trash").json()[0]["id"]
    client.delete("/api/documents/A")
    r = client.post(f"/api/trash/{entry}/restore")
    assert r.status_code == 400 and "Återställ dokumentet först" in r.json()["detail"]


def test_backup_zip(client, tmp_path):
    import io
    import zipfile

    client.post("/api/documents", json={"name": "Text", "content": "Hej"})
    client.put("/api/settings", json={"theme": "dark"})
    client.put("/api/documents/Text/chats/c1", json={"messages": [{"role": "user", "content": "Hej"}]})
    r = client.get("/api/backup")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "word-work-" in r.headers["content-disposition"]
    names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert {"Text.md", ".wordwork/settings.json", ".chats/Text/c1.json"} <= names
