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


def test_frontmatter_not_counted_and_preserved(client, tmp_path):
    from app.storage import split_frontmatter

    text = "---\ntitel: Hamlet på Dramaten\nförfattare: Mikke\n---\n\nTre ord här.\n"
    client.post("/api/documents", json={"name": "FM", "content": text})
    assert client.get("/api/documents").json()[0]["words"] == 3
    assert (tmp_path / "FM.md").read_text() == text
    assert split_frontmatter("---\n\nText\n\n---\n")[0] == ""  # avgränsningslinje, inte frontmatter
    assert split_frontmatter("---\na: 1\n...\nText")[1] == "Text"


def test_health_version_and_security_headers(client):
    r = client.get("/api/health")
    assert r.json()["version"] and r.json()["problem"] is None
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "content-security-policy" not in client.get("/api/docs").headers


def test_allowed_hosts(tmp_path):
    from app.main import _host_only

    settings = Settings(
        data_dir=tmp_path, static_dir=None, snapshot_minutes=5, ollama_url="", ollama_model="",
        allowed_hosts=("localhost", "127.0.0.1", "::1"),
    )
    app = create_app(settings)
    assert TestClient(app, base_url="http://localhost:8080").get("/api/health").status_code == 200
    assert TestClient(app, base_url="http://127.0.0.1:8080").get("/api/documents").status_code == 200
    evil = TestClient(app, base_url="http://evil.example.com:8080").get("/api/documents")
    assert evil.status_code == 400 and "WW_ALLOWED_HOSTS" in evil.json()["detail"]
    assert _host_only("[::1]:8080") == "::1" and _host_only("Localhost:8080") == "localhost"


def test_unwritable_data_dir_reported(tmp_path):
    import os

    data = tmp_path / "data"
    data.mkdir()
    os.chmod(data, 0o500)
    try:
        if os.access(data, os.W_OK):  # körs som root – rättigheter gäller inte
            pytest.skip("rättigheter kan inte testas som root")
        settings = Settings(data_dir=data, static_dir=None, snapshot_minutes=5, ollama_url="", ollama_model="")
        c = TestClient(create_app(settings))
        h = c.get("/api/health").json()
        assert h["status"] == "error" and "chmod" in h["problem"]
        r = c.post("/api/documents", json={"name": "x"})
        assert r.status_code == 500 and "datamappen" in r.json()["detail"]
    finally:
        os.chmod(data, 0o700)


def test_index_not_cached(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html></html>")
    settings = Settings(data_dir=tmp_path / "data", static_dir=static, snapshot_minutes=5, ollama_url="", ollama_model="")
    c = TestClient(create_app(settings))
    for path in ("/", "/något"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
