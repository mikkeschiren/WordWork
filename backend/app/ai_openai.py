"""AI-assistent via ett OpenAI-kompatibelt API (/v1/models, /v1/chat/completions).

Fungerar med t.ex. OpenAI, OpenRouter, vLLM, LM Studio, llama.cpp-server och
Ollamas eget /v1-API. Samma gränssnitt som OllamaClient, så resten av appen
inte behöver veta vilken sorts server det är.

Skillnader mot Ollama-läget:
  - Kontextfönstret går inte att styra – det bestäms av servern.
  - "Tänk efter först" går inte att slå av eller på. Resonemang som servern
    skickar (fälten reasoning_content/reasoning eller <think>-taggar) visas.
  - Modellistan har bara namn; inbäddnings-, bild- och ljudmodeller filtreras
    bort på namnet.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx

from .ai import AIError, ModelCache

# Modeller som inte är chattmodeller, utifrån namnet.
_NOT_CHAT = re.compile(
    r"embed|ocr|whisper|tts|transcribe|dall-e|image|moderation|rerank|audio|realtime|davinci|babbage|sora|speech",
    re.I,
)


def api_base(url: str) -> str:
    """Bas-URL för API:t. "/v1" läggs till om ingen versionsdel finns i sökvägen."""
    url = url.rstrip("/")
    path = urlparse(url).path
    if re.search(r"/v\d+(?:beta\d*)?(?:/|$)", path):
        return url
    return url + "/v1"


class ThinkSplitter:
    """Delar strömmad text i resonemang (<think>…</think> först i svaret) och svar.

    Taggarna kan komma uppdelade över flera bitar, så en kort rest sparas
    tills det går att avgöra om den är början på en tagg.
    """

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.mode = "start"  # start → think → content, eller start → content
        self.buf = ""

    def feed(self, text: str) -> list[tuple[str, str]]:
        self.buf += text
        out: list[tuple[str, str]] = []
        while True:
            if self.mode == "start":
                s = self.buf.lstrip()
                if not s or (len(s) < len(self.OPEN) and self.OPEN.startswith(s)):
                    break  # vänta på mer text
                if s.startswith(self.OPEN):
                    self.buf, self.mode = s[len(self.OPEN):], "think"
                else:
                    self.mode = "content"
                continue
            if self.mode == "think":
                i = self.buf.find(self.CLOSE)
                if i >= 0:
                    if self.buf[:i]:
                        out.append(("thinking", self.buf[:i]))
                    self.buf, self.mode = self.buf[i + len(self.CLOSE):].lstrip("\n"), "content"
                    continue
                keep = next((n for n in range(len(self.CLOSE) - 1, 0, -1) if self.buf.endswith(self.CLOSE[:n])), 0)
                emit = self.buf[: len(self.buf) - keep]
                self.buf = self.buf[len(self.buf) - keep:]
                if emit:
                    out.append(("thinking", emit))
                break
            if self.buf:
                out.append(("content", self.buf))
            self.buf = ""
            break
        return out

    def flush(self) -> list[tuple[str, str]]:
        rest, self.buf = self.buf, ""
        if not rest.strip():
            return []
        return [("thinking" if self.mode == "think" else "content", rest)]


def _error_text(status: int, body: str) -> str:
    try:
        data = json.loads(body)
        err = data.get("error", data)
        msg = err.get("message") if isinstance(err, dict) else err
        body = str(msg or body)
    except ValueError:
        pass
    body = body.strip()[:300]
    if status == 401:
        return f"API-nyckeln godkändes inte (401). Kontrollera WW_AI_KEY. {body}".strip()
    if status == 403:
        return f"Servern nekade åtkomst (403): {body}"
    if status == 404:
        return f"Hittades inte (404) – stämmer adressen och modellnamnet? {body}".strip()
    if status == 429:
        return f"För många förfrågningar eller slut på kvot (429): {body}"
    return f"AI-servern svarade med fel ({status}): {body}"


class OpenAIClient:
    label = "AI-servern"
    think_control = False

    def __init__(
        self,
        base_url: str,
        default_model: str,
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = api_base(base_url)
        self.default_model = default_model
        self._key = api_key
        self._transport = transport
        self._cache = ModelCache()
        self._availability: tuple[bool, str] = (False, "")
        self._availability_checked = 0.0

    def _client(self, read_timeout: float | None = 30.0, connect: float = 10.0) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        return httpx.AsyncClient(
            base_url=self.base_url,
            transport=self._transport,
            headers=headers,
            timeout=httpx.Timeout(connect, read=read_timeout),
        )

    async def availability(self) -> tuple[bool, str]:
        ok, _ = self._availability
        ttl = 30 if ok else 15
        if self._availability_checked and time.monotonic() - self._availability_checked < ttl:
            return self._availability
        try:
            models = await self.models(timeout=3.0)
            result = (True, "") if models else (False, "AI-servern har ingen chattmodell.")
        except AIError as exc:
            result = (False, str(exc))
        self._availability = result
        self._availability_checked = time.monotonic()
        return result

    async def models(self, timeout: float = 30.0) -> list[dict]:
        if self._cache.models and time.monotonic() - self._cache.fetched < 60:
            return self._cache.models
        try:
            async with self._client(read_timeout=timeout, connect=min(timeout, 10.0)) as client:
                res = await client.get("/models")
                if res.status_code in (404, 405, 501) and self.default_model:
                    # Servern listar inte modeller – använd den förvalda.
                    result = [{"name": self.default_model, "size_gb": 0, "parameters": "", "thinking": False}]
                    self._cache = ModelCache(result, time.monotonic())
                    return result
                if res.status_code != 200:
                    raise AIError(_error_text(res.status_code, res.text))
                data = res.json().get("data", [])
        except httpx.HTTPError as exc:
            raise AIError(f"AI-servern på {self.base_url} kan inte nås ({exc.__class__.__name__}).") from exc
        except ValueError as exc:
            raise AIError(f"AI-servern på {self.base_url} svarade inte med en modellista.") from exc
        names = sorted({m.get("id", "") for m in data if isinstance(m, dict)} - {""}, key=str.lower)
        result = [
            {"name": n, "size_gb": 0, "parameters": "", "thinking": False} for n in names if not _NOT_CHAT.search(n)
        ]
        self._cache = ModelCache(result, time.monotonic())
        return result

    async def chat(self, model: str, messages: list[dict], think: bool, num_ctx: int) -> AsyncIterator[dict]:
        """Strömmar samma händelser som OllamaClient.chat. `think` och `num_ctx` kan inte styras här."""
        model = model or self.default_model
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0.4,
            "stream_options": {"include_usage": True},
        }
        started = time.monotonic()
        first_token: float | None = None
        tokens = 0
        used_model = model
        splitter = ThinkSplitter()
        try:
            async with self._client(read_timeout=300.0) as client:
                for attempt in range(2):
                    async with client.stream("POST", "/chat/completions", json=payload) as res:
                        if res.status_code != 200:
                            body = (await res.aread()).decode("utf-8", "replace")
                            # Vissa modeller/servrar tar inte emot temperature eller stream_options.
                            if attempt == 0 and res.status_code in (400, 422) and re.search(
                                r"temperature|stream_options|unsupported|not supported|unrecognized|unknown",
                                body,
                                re.I,
                            ):
                                payload.pop("temperature", None)
                                payload.pop("stream_options", None)
                                continue
                            raise AIError(_error_text(res.status_code, body))
                        async for line in res.aiter_lines():
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                            except ValueError:
                                continue
                            if chunk.get("error"):
                                err = chunk["error"]
                                raise AIError(f"AI-servern: {err.get('message', err) if isinstance(err, dict) else err}")
                            used_model = chunk.get("model") or used_model
                            usage = chunk.get("usage") or {}
                            if usage.get("completion_tokens"):
                                tokens = usage["completion_tokens"]
                            for choice in chunk.get("choices") or []:
                                delta = choice.get("delta") or {}
                                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                                if isinstance(reasoning, str) and reasoning:
                                    first_token = first_token or time.monotonic()
                                    yield {"type": "thinking", "text": reasoning}
                                content = delta.get("content")
                                if isinstance(content, str) and content:
                                    first_token = first_token or time.monotonic()
                                    for kind, text in splitter.feed(content):
                                        yield {"type": kind, "text": text}
                        break
        except httpx.HTTPError as exc:
            raise AIError(f"AI-servern på {self.base_url} kan inte nås ({exc.__class__.__name__}).") from exc
        for kind, text in splitter.flush():
            yield {"type": kind, "text": text}
        now = time.monotonic()
        gen = now - (first_token or now)
        yield {
            "type": "done",
            "model": used_model,
            "tokens": tokens,
            "seconds": round(now - started, 1),
            "tokens_per_second": round(tokens / gen, 1) if tokens and gen > 0.05 else None,
        }
