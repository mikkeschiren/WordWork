from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path,
        static_dir=None,
        snapshot_minutes=5,
        ollama_url="",
        ollama_model="",
    )
    return TestClient(create_app(settings))


def test_health(client):
    r = client.get("/api/health").json()
    assert r["status"] == "ok" and r["ai"] is False


def test_create_list_read_save(client, tmp_path):
    r = client.post("/api/documents", json={"name": "Recension: Hamlet"})
    assert r.status_code == 400  # kolon är otillåtet

    r = client.post("/api/documents", json={"name": "Recension Hamlet", "content": "# Hamlet\n"})
    assert r.status_code == 201
    doc = client.get("/api/documents/Recension Hamlet").json()
    assert doc["content"] == "# Hamlet\n"

    r = client.put(
        "/api/documents/Recension Hamlet",
        json={"content": "# Hamlet\n\nAtt vara eller inte vara.\n", "base_modified": doc["modified"]},
    )
    assert r.status_code == 200
    assert (tmp_path / "Recension Hamlet.md").read_text() == "# Hamlet\n\nAtt vara eller inte vara.\n"

    listing = client.get("/api/documents").json()
    assert [d["name"] for d in listing] == ["Recension Hamlet"]
    assert listing[0]["words"] == 6


def test_unique_names_and_swedish_chars(client):
    a = client.post("/api/documents", json={}).json()
    b = client.post("/api/documents", json={}).json()
    assert (a["name"], b["name"]) == ("Namnlös", "Namnlös 2")
    c = client.post("/api/documents", json={"name": "Åsa på ön"}).json()
    assert client.get(f"/api/documents/{c['id']}").status_code == 200


def test_path_traversal_rejected(client):
    assert client.post("/api/documents", json={"name": "../evil"}).status_code == 400
    assert client.post("/api/documents", json={"name": ".dold"}).status_code == 400
    assert client.get("/api/documents/..%2Fetc").status_code in (400, 404)


def test_conflict_detection(client):
    client.post("/api/documents", json={"name": "A"})
    r = client.put("/api/documents/A", json={"content": "x", "base_modified": 1.0})
    assert r.status_code == 409


def test_rename_and_delete_to_trash(client, tmp_path):
    client.post("/api/documents", json={"name": "Utkast", "content": "text"})
    client.put("/api/documents/Utkast", json={"content": "mer text", "snapshot": True})
    r = client.post("/api/documents/Utkast/rename", json={"name": "Krönika"})
    assert r.status_code == 200
    assert client.get("/api/documents/Utkast").status_code == 404
    assert len(client.get("/api/documents/Krönika/history").json()) == 1

    client.post("/api/documents", json={"name": "Annan"})
    assert client.post("/api/documents/Krönika/rename", json={"name": "Annan"}).status_code == 409

    assert client.delete("/api/documents/Krönika").status_code == 204
    assert client.get("/api/documents/Krönika").status_code == 404
    trash = list((tmp_path / ".trash").iterdir())
    assert any(p.name.endswith("Krönika.md") for p in trash)
    assert any(p.name.endswith("Krönika.history") for p in trash)


def test_auto_snapshot_throttled(client):
    client.post("/api/documents", json={"name": "D"})
    for i in range(3):
        client.put("/api/documents/D", json={"content": f"version {i}"})
    hist = client.get("/api/documents/D/history").json()
    assert len(hist) == 1  # bara första sparningen inom 5 min
    assert hist[0]["kind"] == "auto"


def test_manual_and_named_snapshots_and_restore(client):
    client.post("/api/documents", json={"name": "D"})
    client.put("/api/documents/D", json={"content": "ett", "snapshot": True})
    client.put("/api/documents/D", json={"content": "ett", "snapshot": True})  # identisk → ingen ny
    client.put("/api/documents/D", json={"content": "två"})
    r = client.post("/api/documents/D/history", json={"label": "Till redaktör"}).json()
    assert r["created"] and r["version"]["kind"] == "named"

    hist = client.get("/api/documents/D/history").json()
    assert [v["label"] for v in hist] == ["Till redaktör", ""]
    first = hist[-1]["id"]
    assert client.get(f"/api/documents/D/history/{first}").json()["content"] == "ett"

    client.put("/api/documents/D", json={"content": "tre – osparad i historik"})
    r = client.post(f"/api/documents/D/history/{first}/restore").json()
    assert r["content"] == "ett"
    contents = [
        client.get(f"/api/documents/D/history/{v['id']}").json()["content"]
        for v in client.get("/api/documents/D/history").json()
    ]
    assert "tre – osparad i historik" in contents  # säkrades före återställning


def test_bad_version_id(client):
    client.post("/api/documents", json={"name": "D"})
    assert client.get("/api/documents/D/history/../../x").status_code == 404
    assert client.get("/api/documents/D/history/nope").status_code == 404
