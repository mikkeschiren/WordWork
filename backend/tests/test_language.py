from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path, static_dir=None, snapshot_minutes=5, ollama_url="", ollama_model=""
    )
    return TestClient(create_app(settings))


def test_check_swedish_text(client):
    words = "Det här är en recenssion av teaterföreställningen på Dramaten 2026 i Göteborgs-Posten".split()
    r = client.post("/api/spell/check", json={"words": words})
    assert r.status_code == 200
    assert r.json()["misspelled"] == ["recenssion"]


def test_compounds_and_capitalisation(client):
    words = ["kärnkraftverksolycka", "Kulturjournalisten", "Strindbergs", "TV"]
    assert client.post("/api/spell/check", json={"words": words}).json()["misspelled"] == []


def test_suggest(client):
    r = client.get("/api/spell/suggest", params={"word": "recenssion"}).json()
    assert "recension" in r["suggestions"]


def test_personal_dictionary(client, tmp_path):
    assert client.post("/api/spell/check", json={"words": ["Lagercrantzsk"]}).json()["misspelled"]
    r = client.post("/api/spell/dictionary", json={"word": "Lagercrantzsk"})
    assert r.status_code == 201 and r.json()["words"] == ["Lagercrantzsk"]
    assert client.post("/api/spell/check", json={"words": ["Lagercrantzsk"]}).json()["misspelled"] == []
    assert (tmp_path / ".wordwork" / "ordlista.txt").read_text() == "Lagercrantzsk\n"
    # gemener i listan godkänner även versal begynnelsebokstav, inte tvärtom
    client.post("/api/spell/dictionary", json={"word": "fanzinekultur"})
    assert client.post("/api/spell/check", json={"words": ["Fanzinekultur", "lagercrantzsk"]}).json()[
        "misspelled"
    ] == ["lagercrantzsk"]
    client.delete("/api/spell/dictionary/Lagercrantzsk")
    assert client.get("/api/spell/dictionary").json()["words"] == ["fanzinekultur"]
    assert client.post("/api/spell/dictionary", json={"word": "ett två tre fyra fem sex sju"}).status_code == 400
    assert client.post("/api/spell/dictionary", json={"word": "   "}).status_code == 400


def test_phrases_in_dictionary(client):
    r = client.post("/api/spell/dictionary", json={"word": "  open   source "})
    assert r.status_code == 201 and "open source" in r.json()["words"]
    # Orden i en fras godkänns inte på egen hand – det avgör editorn utifrån sammanhanget.
    assert client.post("/api/spell/check", json={"words": ["source"]}).json()["misspelled"] == ["source"]
    client.delete("/api/spell/dictionary/open source")
    assert "open source" not in client.get("/api/spell/dictionary").json()["words"]


def test_synonyms_with_base_form(client):
    groups = client.get("/api/synonyms", params={"word": "vackra"}).json()["groups"]
    by_word = {g["word"]: g for g in groups}
    assert by_word["vacker"]["base_form"] and "ljuvlig" in by_word["vacker"]["synonyms"]
    assert not by_word["vackra"]["base_form"]  # böjda former kan ha egna synonymer

    direct = client.get("/api/synonyms", params={"word": "Bra"}).json()["groups"]
    assert direct[0]["word"] == "bra" and not direct[0]["base_form"]

    assert client.get("/api/synonyms", params={"word": "xyzzy"}).json()["groups"] == []


def test_edit_dictionary(client, tmp_path):
    client.post("/api/spell/dictionary", json={"word": "Lagercrantz"})
    r = client.put("/api/spell/dictionary/Lagercrantz", json={"word": "Lagercrantzsk"})
    assert r.status_code == 200 and r.json()["words"] == ["Lagercrantzsk"]
    assert client.put("/api/spell/dictionary/finns-inte", json={"word": "x"}).status_code == 404
    r = client.put("/api/spell/dictionary", json={"words": ["  open  source ", "", "fanzine", "fanzine"]})
    assert r.json()["words"] == ["fanzine", "open source"]
    assert (tmp_path / ".wordwork" / "ordlista.txt").read_text() == "fanzine\nopen source\n"
    r = client.put("/api/spell/dictionary", json={"words": ["ett två tre fyra fem sex sju"]})
    assert r.status_code == 400 and "Ogiltiga" in r.json()["detail"]


def test_dictionary_file_edited_by_hand(client, tmp_path):
    import os, time
    client.post("/api/spell/dictionary", json={"word": "qzfanzinx"})
    path = tmp_path / ".wordwork" / "ordlista.txt"
    path.write_text("# kommentar\nBergmansk\nNew  York Times\n", encoding="utf-8")
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert client.get("/api/spell/dictionary").json()["words"] == ["Bergmansk", "New York Times"]
    assert client.post("/api/spell/check", json={"words": ["Bergmansk", "qzfanzinx"]}).json()["misspelled"] == ["qzfanzinx"]
