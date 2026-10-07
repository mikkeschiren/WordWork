import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

DOC = """---
title: Hamlet på Dramaten
author: Mikke Schirén
---

# Hamlet

Det var en **fet** och *kursiv* kväll – med ”svenska citat” och "raka".

> Att vara eller inte vara.

- ett
- två
"""


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path, static_dir=None, snapshot_minutes=5, ollama_url="", ollama_model=""
    )
    c = TestClient(create_app(settings))
    c.post("/api/documents", json={"name": "Hamlet på Dramaten", "content": DOC})
    return c


def _docx_xml(data: bytes, part: str = "word/document.xml") -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read(part).decode("utf-8")


def test_formats_listed(client):
    r = client.get("/api/export/formats").json()
    assert [f["key"] for f in r["formats"]] == ["docx", "odt", "rtf", "html", "md", "txt"]
    assert {t["key"] for t in r["templates"]} == {"standard", "manus", "artikel"}


@pytest.mark.parametrize("fmt", ["docx", "odt", "rtf", "html", "md", "txt"])
def test_export_all_formats(client, fmt):
    r = client.get("/api/documents/Hamlet på Dramaten/export", params={"format": fmt})
    assert r.status_code == 200, r.text
    cd = r.headers["content-disposition"]
    assert "attachment" in cd and "filename*=UTF-8''Hamlet%20p%C3%A5%20Dramaten." + fmt in cd
    assert len(r.content) > 100


def test_docx_content_metadata_and_quotes(client):
    data = client.get("/api/documents/Hamlet på Dramaten/export", params={"format": "docx"}).content
    xml = _docx_xml(data)
    assert "Att vara eller inte vara." in xml
    assert "”svenska citat”" in xml and "&quot;raka&quot;" in xml  # inga "smarta" engelska citattecken
    core = _docx_xml(data, "docProps/core.xml")
    assert "Hamlet på Dramaten" in core and "Mikke Schirén" in core
    assert 'w:val="sv-SE"' in _docx_xml(data, "word/styles.xml")


@pytest.mark.parametrize("fmt", ["docx", "odt"])
def test_templates(client, fmt):
    data = client.get(
        "/api/documents/Hamlet på Dramaten/export", params={"format": fmt, "template": "manus"}
    ).content
    styles = _docx_xml(data, "word/styles.xml" if fmt == "docx" else "styles.xml")
    assert "Times New Roman" in styles
    assert client.get(
        "/api/documents/Hamlet på Dramaten/export", params={"format": fmt, "template": "nope"}
    ).status_code == 400


def test_txt_and_md(client):
    txt = client.get("/api/documents/Hamlet på Dramaten/export", params={"format": "txt"}).text
    assert "title:" not in txt and "Att vara eller inte vara." in txt and "**" not in txt
    md = client.get("/api/documents/Hamlet på Dramaten/export", params={"format": "md"}).text
    assert md == DOC


def test_roundtrip_docx(client):
    data = client.get("/api/documents/Hamlet på Dramaten/export", params={"format": "docx"}).content
    r = client.post("/api/import", params={"filename": "Hamlet (kopia).docx"}, content=data)
    assert r.status_code == 201, r.text
    doc = client.get(f"/api/documents/{r.json()['name']}").json()
    md = doc["content"]
    assert md.startswith("---\n") and "title: Hamlet på Dramaten" in md
    for part in ["# Hamlet", "**fet**", "*kursiv*", "> Att vara eller inte vara.", "- ett", "”svenska citat”"]:
        assert part in md, (part, md)


def test_import_html_cleans_formatting(client):
    html = (
        "<html><body><h2>Rubrik</h2>"
        "<p>Hej <u>under</u> <span style='font-family:Comic Sans'>värld</span>"
        "<img src='bild.png' alt='bild'> x<sup>2</sup></p>"
        "<table><tr><th>Namn</th><th>Roll</th></tr><tr><td>Hamlet</td><td>Prins</td></tr></table>"
        "</body></html>"
    ).encode()
    r = client.post("/api/import", params={"filename": "webb.html"}, content=html)
    md = client.get(f"/api/documents/{r.json()['name']}").json()["content"]
    assert "## Rubrik" in md
    assert "Hej under värld x2" in md
    assert "Namn – Roll" in md and "Hamlet – Prins" in md
    assert "<" not in md and "png" not in md


def test_import_footnotes(client, tmp_path):
    # Skapa en docx med fotnot via Pandoc.
    client.post("/api/documents", json={"name": "fn", "content": "Text[^1] här.\n\n[^1]: En fotnot.\n"})
    data = client.get("/api/documents/fn/export", params={"format": "docx"}).content
    r = client.post("/api/import", params={"filename": "fn.docx"}, content=data)
    md = client.get(f"/api/documents/{r.json()['name']}").json()["content"]
    assert "Text¹ här." in md and "## Fotnoter" in md and "1.  En fotnot." in md


def test_import_text_encodings_and_errors(client):
    r = client.post("/api/import", params={"filename": "gammal.txt"}, content="Åsa på ön".encode("cp1252"))
    assert client.get(f"/api/documents/{r.json()['name']}").json()["content"] == "Åsa på ön\n"
    assert client.post("/api/import", params={"filename": "bild.png"}, content=b"x").status_code == 400
    r = client.post("/api/import", params={"filename": "trasig.docx"}, content=b"inte en docx")
    assert r.status_code == 400 and "Pandoc" in r.json()["detail"]
    # ogiltiga tecken i filnamnet ersätts
    r = client.post("/api/import", params={"filename": "Recension: Hamlet?.md"}, content=b"# Hej")
    assert r.json()["name"] == "Recension Hamlet"


@pytest.mark.parametrize("template", ["standard", "manus", "artikel"])
def test_a4_page_size(client, template):
    url = "/api/documents/Hamlet på Dramaten/export"
    docx = client.get(url, params={"format": "docx", "template": template}).content
    assert 'w:w="11906"' in _docx_xml(docx) and 'w:h="16838"' in _docx_xml(docx)  # A4 i twips
    odt = client.get(url, params={"format": "odt", "template": template}).content
    styles = zipfile.ZipFile(io.BytesIO(odt)).read("styles.xml").decode()
    assert 'fo:page-width="21cm"' in styles and 'fo:page-height="29.7cm"' in styles


def test_a4_rtf_and_html(client):
    url = "/api/documents/Hamlet på Dramaten/export"
    rtf = client.get(url, params={"format": "rtf"}).content
    assert rb"\paperw11906\paperh16838" in rtf
    html = client.get(url, params={"format": "html"}).text
    assert "size: A4" in html
