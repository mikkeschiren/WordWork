"""AI via OpenAI-kompatibelt API (WW_AI_API=openai)."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

MODELS = {"data": [{"id": "gpt-4.1-mini"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}, {"id": "qwen3-32b"}]}


def sse(chunks: list[dict]) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


class FakeOpenAI:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.reject_temperature = False
        self.no_models = False
        self.style = "reasoning_content"

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != "Bearer hemlig":
            return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})
        if request.url.path == "/v1/models":
            return httpx.Response(404) if self.no_models else httpx.Response(200, json=MODELS)
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            if self.reject_temperature and "temperature" in body:
                return httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'temperature'"}})
            if self.style == "reasoning_content":
                chunks = [
                    {"model": body["model"], "choices": [{"delta": {"reasoning_content": "Jag funderar."}}]},
                    {"choices": [{"delta": {"content": "1. ”vår tid och samtid” "}}]},
                    {"choices": [{"delta": {"content": "är en dubblering."}}]},
                    {"choices": [], "usage": {"completion_tokens": 20}},
                ]
            else:  # <think>-taggar i texten
                chunks = [
                    {"model": body["model"], "choices": [{"delta": {"content": "<thi"}}]},
                    {"choices": [{"delta": {"content": "nk>Hmm.</think>\n\nSvaret"}}]},
                    {"choices": [{"delta": {"content": " här."}}]},
                ]
            return httpx.Response(200, content=sse(chunks), headers={"content-type": "text/event-stream"})
        return httpx.Response(404)


@pytest.fixture
def fake():
    return FakeOpenAI()


def make(tmp_path: Path, fake: FakeOpenAI, key: str = "hemlig", model: str = "") -> TestClient:
    settings = Settings(
        data_dir=tmp_path, static_dir=None, snapshot_minutes=5,
        ollama_url="https://api.example.com", ollama_model=model, ai_api="openai", ai_key=key,
    )
    return TestClient(create_app(settings, ai_transport=httpx.MockTransport(fake.handler)))


def events(r):
    return [json.loads(line) for line in r.text.splitlines() if line.strip()]


def test_status_and_models(tmp_path, fake):
    c = make(tmp_path, fake)
    st = c.get("/api/ai/status").json()
    assert st["enabled"] and st["api"] == "openai" and st["think_control"] is False
    assert "hemlig" not in json.dumps(st)  # nyckeln lämnar aldrig servern
    names = [m["name"] for m in c.get("/api/ai/models").json()["models"]]
    assert names == ["gpt-4.1-mini", "qwen3-32b"]  # inbäddning och ljud bortfiltrerade
    assert all(r.url.path.startswith("/v1/") for r in fake.requests)


def test_chat_streams_reasoning_and_saves(tmp_path, fake):
    c = make(tmp_path, fake)
    c.post("/api/documents", json={"name": "Doc", "content": "# Text\n"})
    r = c.post("/api/ai/chat", json={"model": "gpt-4.1-mini", "quick": "repetition", "document": "# Text",
                                     "document_name": "Doc", "chat_id": "c1", "label": "Hitta upprepningar"})
    ev = events(r)
    assert [e["type"] for e in ev][0] == "start"
    assert "".join(e["text"] for e in ev if e["type"] == "thinking") == "Jag funderar."
    assert "".join(e["text"] for e in ev if e["type"] == "content") == "1. ”vår tid och samtid” är en dubblering."
    done = ev[-1]
    assert done["type"] == "done" and done["model"] == "gpt-4.1-mini" and done["tokens"] == 20
    sent = json.loads(fake.requests[-1].content)
    assert sent["stream"] is True and sent["messages"][0]["role"] == "system" and "think" not in sent
    chat = c.get("/api/documents/Doc/chats/c1").json()
    assert chat["messages"][1]["thinking"] == "Jag funderar."


def test_think_tags_are_split(tmp_path, fake):
    fake.style = "tags"
    c = make(tmp_path, fake)
    ev = events(c.post("/api/ai/chat", json={"model": "qwen3-32b", "prompt": "Hej"}))
    assert "".join(e["text"] for e in ev if e["type"] == "thinking") == "Hmm."
    assert "".join(e["text"] for e in ev if e["type"] == "content") == "Svaret här."


def test_retry_without_temperature(tmp_path, fake):
    fake.reject_temperature = True
    c = make(tmp_path, fake)
    ev = events(c.post("/api/ai/chat", json={"model": "o4-mini", "prompt": "Hej"}))
    assert ev[-1]["type"] == "done"
    bodies = [json.loads(r.content) for r in fake.requests if r.url.path == "/v1/chat/completions"]
    assert "temperature" in bodies[0] and "temperature" not in bodies[1]


def test_wrong_key_and_no_model_list(tmp_path, fake):
    c = make(tmp_path, fake, key="fel")
    st = c.get("/api/ai/status").json()
    assert st["enabled"] is False and "API-nyckeln godkändes inte" in st["reason"]
    fake.no_models = True
    c2 = make(tmp_path, fake, model="min-modell")
    assert [m["name"] for m in c2.get("/api/ai/models").json()["models"]] == ["min-modell"]


def test_settings_from_env(monkeypatch, tmp_path):
    keyfile = tmp_path / "key"
    keyfile.write_text("från-fil\n")
    monkeypatch.setenv("WW_AI_API", "openai")
    monkeypatch.setenv("WW_AI_URL", "http://localhost:1234")
    monkeypatch.delenv("WW_AI_MODEL", raising=False)
    monkeypatch.delenv("WW_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("WW_AI_KEY", raising=False)
    monkeypatch.setenv("WW_AI_KEY_FILE", str(keyfile))
    s = Settings.from_env()
    assert (s.ai_api, s.ollama_url, s.ollama_model, s.ai_key) == ("openai", "http://localhost:1234", "", "från-fil")
    monkeypatch.setenv("WW_AI_API", "annat")
    with pytest.raises(ValueError):
        Settings.from_env()
    # Ollama-läget som förut, med de äldre variabelnamnen.
    monkeypatch.delenv("WW_AI_API")
    monkeypatch.delenv("WW_AI_URL")
    monkeypatch.setenv("WW_OLLAMA_URL", "http://ollama:11434")
    s = Settings.from_env()
    assert (s.ai_api, s.ollama_url, s.ollama_model) == ("ollama", "http://ollama:11434", "")
    # Generiska standardvärden när inget är angivet.
    monkeypatch.delenv("WW_OLLAMA_URL")
    s = Settings.from_env()
    assert (s.ai_api, s.ollama_url, s.ollama_model, s.ai_key) == ("ollama", "http://localhost:11434", "", "från-fil")
