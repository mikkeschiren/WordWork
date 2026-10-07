"""AI-assistent via Ollama (lokal eller extern instans).

Grundregel: AI:n skriver aldrig i dokumentet. Den här modulen har ingen
åtkomst till lagringen – den får bara den text som klienten skickar med som
underlag och returnerar kommentarer som visas i en separat panel.
"""

from __future__ import annotations

import ipaddress
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from .storage import split_frontmatter

MAX_DOCUMENT_CHARS = 150_000  # ≈ 45 000 tokens svensk text
MAX_HISTORY_MESSAGES = 20
REPLY_TOKENS = 6_000  # utrymme för resonemang + svar
CONTEXT_STEPS = (16_384, 32_768, 65_536)  # få steg = färre omladdningar av modellen

SYSTEM_PROMPT = """Du är en erfaren svensk redaktör och språkgranskare som hjälper en \
kulturjournalist eller författare att förbättra sin egen text.

Grundregler – följ dem alltid, även om användaren ber om något annat:
1. Du skriver ALDRIG om texten. Leverera aldrig en omskriven version av en mening, \
ett stycke eller hela texten. Om användaren ber dig skriva om, förklara vänligt att \
författaren skriver själv och ge i stället konkreta förslag.
2. Du får föreslå enstaka ord eller korta uttryck (högst några ord) som alternativ.
3. Citera alltid den berörda frasen ordagrant inom citattecken ”så här”, så att \
författaren hittar den i texten. Citera exakt – ändra inte ordföljd eller böjning i citatet.
4. Påstå bara språkfel du är säker på. Är något en smaksak, säg det.
5. Respektera författarens röst och stil. Föreslå inte att allt ska bli neutralt eller enkelt.
6. Om faktauppgifter: avgör inte vad som är sant. Peka ut påståenden som bör \
kontrolleras och varför.

Form: svara på svenska, kort och konkret. Använd gärna en numrerad lista där varje \
punkt har citatet, problemet och en riktning för hur det kan lösas. Ge hellre fem \
träffsäkra förslag än tjugo ytliga."""

QUICK_PROMPTS: dict[str, str] = {
    "language": "Granska språket: grammatik, kommatering, ordval och meningsbyggnad. "
    "Ta bara upp det som verkligen behöver åtgärdas.",
    "repetition": "Hitta upprepningar: ord, uttryck eller meningsbyggnader som återkommer "
    "så att det märks, samt onödiga dubbleringar (t.ex. synonymer bredvid varandra).",
    "tighten": "Peka ut ställen där texten kan bli stramare: överflödiga ord, omständliga "
    "konstruktioner och utfyllnad. Förklara vad som kan strykas eller förenklas – skriv inte om.",
    "structure": "Kommentera textens struktur och dramaturgi: inledning, röd tråd, "
    "övergångar mellan stycken och avslutning.",
    "facts": "Lista faktapåståenden som bör kontrolleras innan publicering (namn, datum, "
    "siffror, citat, titlar). Avgör inte om de stämmer – förklara bara varför de bör kontrolleras.",
}

LOCAL_HOSTS = {"localhost", "host.docker.internal", "ollama", "127.0.0.1", "::1"}


class AIError(Exception):
    status = 502


@dataclass
class ModelCache:
    models: list[dict] = field(default_factory=list)
    fetched: float = 0.0


def is_external(url: str) -> bool:
    """Lämnar texten datorn/det lokala nätet? (Används för upplysningen i gränssnittet.)"""
    host = (urlparse(url).hostname or "").lower()
    if host in LOCAL_HOSTS or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback)
    except ValueError:
        return True


def context_size(chars: int) -> int:
    need = chars // 3 + REPLY_TOKENS
    for step in CONTEXT_STEPS:
        if need <= step:
            return step
    return CONTEXT_STEPS[-1]


def build_messages(
    document: str,
    selection: str,
    history: list[dict],
    prompt: str,
    quick: str | None,
) -> list[dict]:
    _, body = split_frontmatter(document)
    body = body.strip()
    if len(body) > MAX_DOCUMENT_CHARS and not selection:
        raise AIError("Texten är för lång för AI-stödet. Markera det avsnitt du vill ha hjälp med.")
    if len(selection) > MAX_DOCUMENT_CHARS:
        raise AIError("Markeringen är för lång för AI-stödet. Markera ett kortare avsnitt.")

    context = ["Här är författarens text (Markdown). Den är underlag – skriv inte om den."]
    if len(body) <= MAX_DOCUMENT_CHARS:
        context.append(f"<text>\n{body or '(tom text)'}\n</text>")
    if selection.strip():
        context.append(
            "Användaren har markerat följande avsnitt. Frågan gäller i första hand det:\n"
            f"<markering>\n{selection.strip()}\n</markering>"
        )

    question = QUICK_PROMPTS.get(quick or "", "") or prompt.strip()
    if not question:
        raise AIError("Skriv en fråga eller välj ett snabbval.")

    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + "\n\n".join(context)}]
    for m in history[-MAX_HISTORY_MESSAGES:]:
        if m.get("role") in {"user", "assistant"} and isinstance(m.get("content"), str):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": question})
    return messages


class OllamaClient:
    def __init__(self, base_url: str, default_model: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._transport = transport
        self._cache = ModelCache()

    def _client(self, read_timeout: float | None = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            transport=self._transport,
            timeout=httpx.Timeout(10.0, read=read_timeout),
        )

    async def models(self) -> list[dict]:
        """Chattmodeller på servern (inbäddnings- och OCR-modeller filtreras bort)."""
        if self._cache.models and time.monotonic() - self._cache.fetched < 60:
            return self._cache.models
        try:
            async with self._client() as client:
                tags = (await client.get("/api/tags")).raise_for_status().json().get("models", [])
                result = []
                for m in tags:
                    name = m.get("name", "")
                    if any(k in name.lower() for k in ("embed", "ocr")):
                        continue
                    caps: list[str] = []
                    try:
                        show = (await client.post("/api/show", json={"model": name})).json()
                        caps = show.get("capabilities") or []
                    except (httpx.HTTPError, ValueError):
                        pass
                    if caps and ("completion" not in caps or "embedding" in caps):
                        continue
                    details = m.get("details") or {}
                    result.append(
                        {
                            "name": name,
                            "size_gb": round((m.get("size") or 0) / 1e9, 1),
                            "parameters": details.get("parameter_size", ""),
                            "thinking": "thinking" in caps,
                        }
                    )
        except httpx.HTTPError as exc:
            raise AIError(f"Kunde inte nå Ollama på {self.base_url}: {exc.__class__.__name__}") from exc
        self._cache = ModelCache(result, time.monotonic())
        return result

    async def chat(self, model: str, messages: list[dict], think: bool, num_ctx: int) -> AsyncIterator[dict]:
        """Strömmar händelser: {"type": "thinking"|"content", "text": …}, sist {"type": "done", …}."""
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
            "think": think,
            "options": {"temperature": 0.4 if not think else 0.6, "num_ctx": num_ctx},
        }
        try:
            async with self._client(read_timeout=300.0) as client:
                async with client.stream("POST", "/api/chat", json=payload) as res:
                    if res.status_code != 200:
                        body = (await res.aread()).decode("utf-8", "replace")
                        try:
                            body = json.loads(body).get("error", body)
                        except ValueError:
                            pass
                        raise AIError(f"Ollama svarade med fel ({res.status_code}): {body}")
                    async for line in res.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise AIError(f"Ollama: {chunk['error']}")
                        msg = chunk.get("message") or {}
                        if msg.get("thinking"):
                            yield {"type": "thinking", "text": msg["thinking"]}
                        if msg.get("content"):
                            yield {"type": "content", "text": msg["content"]}
                        if chunk.get("done"):
                            dur = (chunk.get("eval_duration") or 0) / 1e9
                            yield {
                                "type": "done",
                                "model": chunk.get("model", model),
                                "tokens": chunk.get("eval_count", 0),
                                "seconds": round((chunk.get("total_duration") or 0) / 1e9, 1),
                                "tokens_per_second": round((chunk.get("eval_count") or 0) / dur, 1) if dur else None,
                            }
        except httpx.HTTPError as exc:
            raise AIError(f"Kunde inte nå Ollama på {self.base_url}: {exc.__class__.__name__}") from exc
