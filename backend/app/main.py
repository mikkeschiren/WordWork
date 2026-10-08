"""Word Work – FastAPI-applikation."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .ai import GENRES, QUICK_PROMPTS, AIError, OllamaClient, build_messages, context_size, is_external
from .ai_openai import OpenAIClient
from .config import Settings
from .convert import EXPORT_FORMATS, MAX_IMPORT_BYTES, PAGED_FORMATS, TEMPLATE_LABELS, ConvertError, export_document, import_file
from .language import Language, normalize_entry
from .storage import (
    SettingsStore,
    Storage,
    StorageError,
    append_chat,
    backup_zip,
    delete_chat,
    list_chats,
    list_trash,
    read_chat,
    restore_trash,
    safe_name,
    save_chat,
)


class CreateDoc(BaseModel):
    name: str | None = None
    content: str = ""


class SaveDoc(BaseModel):
    content: str
    base_modified: float | None = None
    snapshot: bool = False


class RenameDoc(BaseModel):
    name: str


class NamedVersion(BaseModel):
    label: str = Field(default="", max_length=200)


class CheckWords(BaseModel):
    words: list[str] = Field(max_length=5000)


class ChatMessage(BaseModel):
    role: str
    content: str = Field(max_length=200_000)


class ChatRequest(BaseModel):
    model: str = ""
    think: bool = True
    prompt: str = Field(default="", max_length=10_000)
    quick: str | None = None
    document: str = Field(default="", max_length=1_000_000)
    selection: str = Field(default="", max_length=1_000_000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=100)
    # Om dessa anges sparar servern fråga och svar i samtalet – även om fliken stängs.
    document_name: str | None = Field(default=None, max_length=200)
    chat_id: str | None = Field(default=None, max_length=64)
    label: str = Field(default="", max_length=200)


class SaveChat(BaseModel):
    model: str = Field(default="", max_length=200)
    messages: list[dict] = Field(default_factory=list)


class DictionaryWord(BaseModel):
    word: str = Field(min_length=1, max_length=200)


class DictionaryAll(BaseModel):
    words: list[str] = Field(max_length=20_000)


log = logging.getLogger("wordwork")

# Sidan laddar bara egna filer; inline-stilar används för t.ex. stapeldiagram.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


def data_dir_problem(path) -> str | None:
    """Kontrollerar att datamappen går att skriva i (vanligt fel: rättigheter på värden)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".wordwork" / ".skrivtest"
        probe.parent.mkdir(exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return None
    except OSError as exc:
        return (
            f"Kan inte skriva i datamappen {path} ({exc.strerror or exc}). "
            "Kontrollera rättigheterna på mappen på din dator, t.ex. med `chmod 755 data`."
        )


def _host_only(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def create_app(settings: Settings | None = None, ai_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    problem = data_dir_problem(settings.data_dir)
    if problem:
        log.error(problem)
    storage = Storage(settings.data_dir, settings.snapshot_minutes)
    user_settings = SettingsStore(settings.data_dir)
    app = FastAPI(title="Word Work", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")

    allowed = set(settings.allowed_hosts)

    @app.middleware("http")
    async def security(request: Request, call_next):
        # Skydd mot DNS-rebinding: en främmande webbplats som pekar sitt domännamn
        # mot 127.0.0.1 ska inte kunna läsa texterna via användarens webbläsare.
        if "*" not in allowed and _host_only(request.headers.get("host", "")) not in allowed:
            return JSONResponse(
                {"detail": "Okänt värdnamn. Lägg till det i WW_ALLOWED_HOSTS om du vill nå Word Work så."},
                status_code=400,
            )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response

    @app.exception_handler(PermissionError)
    async def permission_error(_: Request, exc: PermissionError) -> JSONResponse:
        log.error("Rättighetsfel: %s", exc)
        return JSONResponse(
            {"detail": data_dir_problem(settings.data_dir) or f"Rättighetsfel: {exc.strerror or exc}"},
            status_code=500,
        )
    app.state.storage = storage
    language = Language(settings.resources_dir, settings.data_dir / ".wordwork" / "ordlista.txt")
    app.state.language = language

    ollama: OllamaClient | OpenAIClient | None = None
    if settings.ollama_url and settings.ai_api == "openai":
        ollama = OpenAIClient(settings.ollama_url, settings.ollama_model, settings.ai_key, transport=ai_transport)
    elif settings.ollama_url:
        ollama = OllamaClient(settings.ollama_url, settings.ollama_model, transport=ai_transport)

    @app.exception_handler(AIError)
    async def ai_error(_: Request, exc: AIError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(ConvertError)
    async def convert_error(_: Request, exc: ConvertError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(StorageError)
    async def storage_error(_: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/health")
    def health() -> dict:
        problem = data_dir_problem(settings.data_dir)
        return {
            "status": "error" if problem else "ok",
            "version": __version__,
            "problem": problem,
            "ai": ollama is not None,
            "language": language.ready,
        }

    # ---------- AI (Ollama eller OpenAI-kompatibel server) ----------
    @app.get("/api/ai/genres")
    def ai_genres() -> list[dict]:
        """Texttyper för metadatapanelen (fungerar även när AI-stödet är avstängt)."""
        return [{"key": k, "label": label} for k, (label, _) in GENRES.items()]

    @app.get("/api/ai/status")
    async def ai_status() -> dict:
        if ollama is None:
            return {"enabled": False, "reason": "AI-stödet är avstängt (WW_AI_URL är tom)."}
        available, reason = await ollama.availability()
        if not available:
            return {"enabled": False, "configured": True, "reason": reason}
        return {
            "enabled": True,
            "host": httpx.URL(settings.ollama_url).host,
            "external": is_external(settings.ollama_url),
            "default_model": settings.ollama_model,
            "quick": list(QUICK_PROMPTS),
            "api": settings.ai_api,
            # Kan "Tänk efter först" styras? (Bara i Ollama-läget.)
            "think_control": ollama.think_control,
        }

    @app.get("/api/ai/models")
    async def ai_models() -> dict:
        if ollama is None:
            raise HTTPException(404, "AI-stödet är avstängt.")
        return {"models": await ollama.models(), "default_model": settings.ollama_model}

    @app.post("/api/ai/chat")
    async def ai_chat(body: ChatRequest) -> StreamingResponse:
        if ollama is None:
            raise HTTPException(404, "AI-stödet är avstängt.")
        available, reason = await ollama.availability()
        if not available:
            raise HTTPException(503, reason)
        if body.quick and body.quick not in QUICK_PROMPTS:
            raise HTTPException(400, "Okänt snabbval.")
        try:
            messages = build_messages(
                body.document, body.selection, [m.model_dump() for m in body.history], body.prompt, body.quick
            )
        except AIError as exc:
            raise HTTPException(400, str(exc)) from exc
        num_ctx = context_size(sum(len(m["content"]) for m in messages))
        question = messages[-1]["content"]
        save_to = None
        if body.document_name and body.chat_id:
            storage._require(body.document_name)
            storage._chat_path(body.document_name, body.chat_id)  # validerar id
            save_to = (body.document_name, body.chat_id)

        async def events():
            answer = {"role": "assistant", "content": "", "thinking": "", "meta": "", "error": ""}
            model = body.model or (ollama.default_model if ollama else "")
            finished = False
            try:
                yield json.dumps({"type": "start", "question": question}, ensure_ascii=False) + "\n"
                async for ev in ollama.chat(body.model, messages, body.think, num_ctx):
                    if ev["type"] in ("thinking", "content"):
                        answer[ev["type"]] += ev["text"]
                    elif ev["type"] == "done":
                        model = ev.get("model") or model
                        tps = f" · {round(ev['tokens_per_second'])} tokens/s" if ev.get("tokens_per_second") else ""
                        answer["meta"] = f"{model} · {ev['seconds']:g} s{tps}"
                    yield json.dumps(ev, ensure_ascii=False) + "\n"
                finished = True
            except AIError as exc:
                answer["error"] = str(exc)
                finished = True
                yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
            finally:
                # Körs också när webbläsaren kopplar ner (fliken stängs, Stoppa).
                if save_to:
                    if not finished and not answer["meta"]:
                        answer["meta"] = "Avbrutet"
                    user = {"role": "user", "content": question if body.quick else body.prompt, "label": body.label}
                    try:
                        append_chat(storage, *save_to, [user, answer], model)
                    except (StorageError, OSError) as exc:
                        log.warning("Kunde inte spara AI-samtalet: %s", exc)

        return StreamingResponse(events(), media_type="application/x-ndjson")

    # ---------- språk ----------
    def _clean_word(word: str) -> str:
        entry = normalize_entry(word)
        if entry is None:
            raise HTTPException(400, "Ange ett ord eller en fras på högst sex ord.")
        return entry

    @app.post("/api/spell/check")
    def spell_check(body: CheckWords) -> dict:
        return {"misspelled": language.check(body.words)}

    @app.get("/api/spell/suggest")
    def spell_suggest(word: str = Query(max_length=64), limit: int = Query(6, ge=1, le=12)) -> dict:
        return {"word": word, "suggestions": language.suggest(word, limit=limit)}

    @app.get("/api/spell/dictionary")
    def dictionary_list() -> dict:
        return {"words": language.personal.words()}

    @app.post("/api/spell/dictionary", status_code=201)
    def dictionary_add(body: DictionaryWord) -> dict:
        language.personal.add(_clean_word(body.word))
        return {"words": language.personal.words()}

    @app.put("/api/spell/dictionary")
    def dictionary_replace(body: DictionaryAll) -> dict:
        """Ersätter hela listan (redigering som text). Tomma rader ignoreras."""
        entries, invalid = [], []
        for raw in body.words:
            if not raw.strip():
                continue
            entry = normalize_entry(raw)
            (entries if entry else invalid).append(entry or raw.strip())
        if invalid:
            raise HTTPException(400, "Ogiltiga rader (högst sex ord per rad): " + ", ".join(invalid[:5]))
        language.personal.replace_all(entries)
        return {"words": language.personal.words()}

    @app.put("/api/spell/dictionary/{word}")
    def dictionary_rename(word: str, body: DictionaryWord) -> dict:
        new = _clean_word(body.word)
        if word not in language.personal.words():
            raise HTTPException(404, f"”{word}” finns inte i ordlistan.")
        language.personal.rename(word, new)
        return {"words": language.personal.words()}

    @app.delete("/api/spell/dictionary/{word}")
    def dictionary_remove(word: str) -> dict:
        language.personal.remove(word)
        return {"words": language.personal.words()}

    @app.get("/api/synonyms")
    def synonyms(word: str = Query(max_length=64)) -> dict:
        return {"word": word, "groups": language.synonyms(word)}

    # ---------- dokument ----------
    @app.get("/api/documents")
    def list_docs() -> list[dict]:
        return [asdict(d) for d in storage.list()]

    @app.post("/api/documents", status_code=201)
    def create_doc(body: CreateDoc) -> dict:
        return asdict(storage.create(body.name, body.content))

    @app.get("/api/documents/{name}")
    def get_doc(name: str) -> dict:
        content, modified = storage.read(name)
        return {"id": name, "name": name, "content": content, "modified": modified}

    @app.put("/api/documents/{name}")
    def save_doc(name: str, body: SaveDoc) -> dict:
        modified = storage.save(name, body.content, body.base_modified, body.snapshot)
        return {"modified": modified}

    @app.post("/api/documents/{name}/rename")
    def rename_doc(name: str, body: RenameDoc) -> dict:
        return asdict(storage.rename(name, body.name))

    @app.delete("/api/documents/{name}", status_code=204)
    def delete_doc(name: str) -> None:
        storage.delete(name)

    # ---------- inställningar ----------
    @app.get("/api/settings")
    def get_settings() -> dict:
        data = user_settings.read()
        return {"saved": data is not None, "settings": data or {}}

    @app.put("/api/settings")
    def put_settings(body: dict) -> dict:
        return {"settings": user_settings.write(body)}

    # ---------- AI-samtal ----------
    @app.get("/api/documents/{name}/chats")
    def get_chats(name: str) -> list[dict]:
        return list_chats(storage, name)

    @app.get("/api/documents/{name}/chats/{cid}")
    def get_chat(name: str, cid: str) -> dict:
        return read_chat(storage, name, cid)

    @app.put("/api/documents/{name}/chats/{cid}")
    def put_chat(name: str, cid: str, body: SaveChat) -> dict:
        return save_chat(storage, name, cid, body.messages, body.model)

    @app.delete("/api/documents/{name}/chats/{cid}", status_code=204)
    def remove_chat(name: str, cid: str) -> None:
        delete_chat(storage, name, cid)

    # ---------- papperskorg och säkerhetskopia ----------
    @app.get("/api/trash")
    def get_trash() -> list[dict]:
        return list_trash(storage)

    @app.post("/api/trash/{entry}/restore")
    def post_restore(entry: str) -> dict:
        return restore_trash(storage, entry)

    @app.get("/api/backup")
    def get_backup() -> Response:
        from datetime import datetime

        filename = f"word-work-{datetime.now().strftime('%Y-%m-%d')}.zip"
        return Response(
            backup_zip(storage),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ---------- import & export ----------
    @app.get("/api/export/formats")
    def export_formats() -> dict:
        return {
            "formats": [
                {"key": f.key, "label": f.label, "templates": f.templates, "pages": f.key in PAGED_FORMATS}
                for f in EXPORT_FORMATS.values()
            ],
            "templates": [{"key": k, "label": v} for k, v in TEMPLATE_LABELS.items()],
        }

    @app.get("/api/documents/{name}/export")
    def export_doc(name: str, format: str = "docx", template: str = "standard", chapters: int = 0) -> Response:
        content, _ = storage.read(name)
        data, fmt = export_document(name, content, format, template, chapters)
        filename = f"{name}.{fmt.ext}"
        ascii_name = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
        return Response(
            data,
            media_type=fmt.media_type,
            headers={
                "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
            },
        )

    @app.post("/api/import", status_code=201)
    async def import_doc(request: Request, filename: str = Query(min_length=1, max_length=255)) -> dict:
        size = int(request.headers.get("content-length") or 0)
        if size > MAX_IMPORT_BYTES:
            raise ConvertError("Filen är för stor (max 25 MB).")
        data = await request.body()
        stem, markdown = import_file(filename, data)
        return asdict(storage.create(safe_name(stem, "Importerad"), markdown))

    # ---------- historik ----------
    @app.get("/api/documents/{name}/history")
    def list_history(name: str) -> list[dict]:
        return [asdict(v) for v in storage.history(name)]

    @app.post("/api/documents/{name}/history", status_code=201)
    def create_version(name: str, body: NamedVersion) -> dict:
        kind = "named" if body.label.strip() else "manual"
        v = storage.snapshot(name, kind=kind, label=body.label.strip())
        return {"created": v is not None, "version": asdict(v) if v else None}

    @app.get("/api/documents/{name}/history/{vid}")
    def get_version(name: str, vid: str) -> dict:
        return {"id": vid, "content": storage.read_version(name, vid)}

    @app.post("/api/documents/{name}/history/{vid}/restore")
    def restore_version(name: str, vid: str) -> dict:
        modified = storage.restore(name, vid)
        content, _ = storage.read(name)
        return {"modified": modified, "content": content}

    # ---------- frontend ----------
    if settings.static_dir and (settings.static_dir / "index.html").is_file():
        static_dir = settings.static_dir
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (static_dir / path).resolve()
            if path and candidate.is_file() and static_dir in candidate.parents:
                return FileResponse(candidate)
            # index.html pekar på filer med hash i namnet. Den får inte cachas, annars
            # kan webbläsaren köra en gammal version efter en uppdatering.
            return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    return app

