"""AI-assistent via Ollama (lokal eller extern instans). Se ai_openai.py för
OpenAI-kompatibla servrar.

Grundregel: AI:n skriver aldrig i dokumentet. Den här modulen har ingen
åtkomst till lagringen – den får bara den text som klienten skickar med som
underlag och returnerar kommentarer som visas i en separat panel.
"""

from __future__ import annotations

import ipaddress
import json
import re
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

Om textens format – viktigt:
- Texten är skriven i Markdown, som bara är ett sätt att spara formatering. Läsaren ser \
formateringen, inte tecknen: *ord* eller _ord_ är kursiv, **ord** är fetstil, rader som \
börjar med # är rubriker, > är citatblock och - är punktlistor.
- Kommentera aldrig Markdown-tecknen (stjärnor, understreck, #, >) som om de vore fel, \
typografi eller skräp. Föreslå inte att de ska tas bort eller bytas ut.
- När du citerar texten: citera orden utan Markdown-tecken.
- Rader som <!-- … --> är författarens egna anteckningar. De hör inte till texten och ska \
inte granskas, men du får använda dem som bakgrund.
- Metadata (rubrik, ingress, beställare, längdmål m.m.) står för sig, inte i texten.

Svensk typografi – påstå inte motsatsen (enligt Svenska skrivregler):
- Svenska citattecken är ” på båda sidor (”så här”) eller » på båda sidor (»så här»).
- Är citatet en hel mening hamnar punkten före det avslutande citattecknet: \
Hon sa: ”Jag kommer i morgon.” Bara när citatet är en del av en mening står punkten efter: \
Hon kallade det ”en fullständig katastrof”.
- Tankstreck (–) har mellanslag på båda sidor. Repliker kan inledas med talstreck (– ).

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

# Texttyper (frontmatter: genre). Varje typ ger AI:n en kort, genomtänkt instruktion.
GENRES: dict[str, tuple[str, str]] = {
    "nyhet": (
        "Nyhet / reportage",
        "Texten är journalistisk (nyhet eller reportage). Bedöm tydlighet och precision, om ingressen "
        "bär det viktigaste, att källor och citat är tydligt attribuerade, saklighet och balans, och "
        "peka ut uppgifter som bör faktakontrolleras. Följ svensk journalistisk språkpraxis (t.ex. "
        "TT-språket): korta meningar, aktiva verb, siffror och titlar skrivna konsekvent.",
    ),
    "recension": (
        "Recension / kritik",
        "Texten är en recension eller kritik. Det värderande omdömet ska vara tydligt och belagt med "
        "konkreta iakttagelser. Kontrollera att verket (titel, upphovspersoner, medverkande, sammanhang) "
        "beskrivs korrekt och att läsaren förstår vad som bedöms. En personlig stil är en tillgång.",
    ),
    "kronika": (
        "Krönika / essä",
        "Texten är en krönika eller essä. Den personliga rösten, ironi, utvikningar och en ledigare "
        "stil är avsiktliga – granska dem inte som fel. Fokusera på resonemangets bärighet, den röda "
        "tråden, poängen och hur inledning och slut hänger ihop.",
    ),
    "prosa": (
        "Prosa (skönlitteratur)",
        "Texten är skönlitterär prosa. Stilgrepp, ofullständiga meningar, upprepningar, ovanlig "
        "interpunktion, dialekt och talspråk i dialog kan vara avsiktliga – påpeka dem bara om de "
        "verkar oavsiktliga, och säg i så fall att det är en bedömning. Fokusera på rytm, gestaltning, "
        "perspektiv, dialog, tempo och dramaturgi snarare än på regler.",
    ),
    "lyrik": (
        "Lyrik",
        "Texten är lyrik. Radbrytningar, strofindelning, interpunktion (eller avsaknaden av den), "
        "upprepningar och ordföljd är avsiktliga – rätta dem inte. Kommentera i stället bildspråk, "
        "klang, rytm och vad som eventuellt bryter dikten, och var försiktig med omdömen.",
    ),
    "sakprosa": (
        "Sakprosa / rapport",
        "Texten är sakprosa (t.ex. rapport, utredning eller informationstext). Bedöm tydlighet, "
        "struktur och disposition, klarspråk, att begrepp används konsekvent och att slutsatserna "
        "följer av underlaget.",
    ),
    "annat": ("Annat", ""),
}

MAX_AI_INSTRUCTIONS = 2_000

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


_META_KEY = re.compile(r"^([A-Za-z_][\w-]*):(?:[ \t]+(.*?))?[ \t]*$")


def parse_meta(frontmatter: str) -> dict[str, str]:
    """Enkla fält i frontmattern: `nyckel: värde` och blockfält (`nyckel: |`)."""
    lines = frontmatter.strip().splitlines()
    if lines and lines[0].strip().lstrip("\ufeff") == "---":
        lines = lines[1:]
    if lines and lines[-1].strip() in ("---", "..."):
        lines = lines[:-1]
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = _META_KEY.match(lines[i])
        i += 1
        if not m:
            continue
        key, raw = m.group(1), (m.group(2) or "")
        block: list[str] = []
        while i < len(lines) and (re.match(r"^[ \t]+\S|^-\s", lines[i]) or not lines[i].strip()):
            block.append(lines[i])
            i += 1
        if re.fullmatch(r"[|>][+-]?", raw):
            texts = [b for b in block if b.strip()]
            indent = min((len(b) - len(b.lstrip()) for b in texts), default=0)
            value = "\n".join(b[indent:] for b in block).strip()
            if raw.startswith(">"):
                value = re.sub(r"(?<=\S)\n(?=\S)", " ", value)
            out[key] = value
        elif raw and not raw.startswith(("[", "{")):
            v = raw
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            else:
                v = re.sub(r"\s+#.*$", "", v)
            out[key] = v
    return out


def _without_keys(frontmatter: str, keys: set[str]) -> str:
    """Frontmattern utan vissa fält (och deras indragna rader)."""
    lines = frontmatter.strip().splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        m = _META_KEY.match(line)
        if m:
            skipping = m.group(1) in keys
        elif not re.match(r"^[ \t]+\S|^-\s|^\s*$", line):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out)


def text_guidance(frontmatter: str) -> list[str]:
    """Texttyp och författarens egna instruktioner, som avsnitt i systeminstruktionen."""
    meta = parse_meta(frontmatter)
    parts: list[str] = []
    genre = GENRES.get(meta.get("genre", "").strip().lower())
    if genre and genre[1]:
        parts.append(f"Om texten – texttyp: {genre[0]}.\n{genre[1]}")
    own = meta.get("ai", "").strip()[:MAX_AI_INSTRUCTIONS]
    if own:
        parts.append(
            "Författarens egna instruktioner för den här texten. Följ dem när du svarar, men "
            "grundreglerna ovan gäller alltid först – du skriver aldrig om texten, oavsett vad som står här:\n"
            f"<instruktioner>\n{own}\n</instruktioner>"
        )
    return parts


def build_messages(
    document: str,
    selection: str,
    history: list[dict],
    prompt: str,
    quick: str | None,
) -> list[dict]:
    frontmatter, body = split_frontmatter(document)
    body = body.strip()
    if len(body) > MAX_DOCUMENT_CHARS and not selection:
        raise AIError("Texten är för lång för AI-stödet. Markera det avsnitt du vill ha hjälp med.")
    if len(selection) > MAX_DOCUMENT_CHARS:
        raise AIError("Markeringen är för lång för AI-stödet. Markera ett kortare avsnitt.")

    context = text_guidance(frontmatter)
    context.append("Här är författarens text (Markdown). Den är underlag – skriv inte om den.")
    meta = _without_keys(frontmatter, {"ai", "genre"}).strip().strip("-").strip()
    if meta:
        context.append(f"Metadata om texten (YAML), t.ex. rubrik, ingress och längdmål:\n<metadata>\n{meta[:4000]}\n</metadata>")
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
    label = "Ollama-servern"
    think_control = True  # "Tänk efter först" styrs med Ollamas think-flagga

    def __init__(self, base_url: str, default_model: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._transport = transport
        self._cache = ModelCache()
        self._availability: tuple[bool, str] = (False, "")
        self._availability_checked = 0.0

    async def availability(self) -> tuple[bool, str]:
        """Går servern att nå och har den någon chattmodell? Cachas en kort stund,
        så att appen fungerar som vanligt (utan AI) när servern inte svarar."""
        ok, _ = self._availability
        ttl = 30 if ok else 15
        if self._availability_checked and time.monotonic() - self._availability_checked < ttl:
            return self._availability
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, transport=self._transport, timeout=httpx.Timeout(3.0)
            ) as client:
                try:
                    (await client.get("/api/version")).raise_for_status()
                except httpx.HTTPStatusError:
                    pass  # servern svarar (t.ex. bakom en proxy utan /api/version) – modellistan avgör
            models = await self.models()
            result = (True, "") if models else (False, "Ollama-servern har ingen chattmodell installerad.")
        except (httpx.HTTPError, AIError, ValueError) as exc:
            result = (False, f"Ollama-servern på {self.base_url} kan inte nås ({exc.__class__.__name__}).")
        self._availability = result
        self._availability_checked = time.monotonic()
        return result

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
