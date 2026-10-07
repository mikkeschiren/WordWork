"""Word Work – FastAPI-applikation."""

from __future__ import annotations

import json
from dataclasses import asdict
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai import QUICK_PROMPTS, AIError, OllamaClient, build_messages, context_size, is_external
from .config import Settings
from .convert import EXPORT_FORMATS, MAX_IMPORT_BYTES, TEMPLATE_LABELS, ConvertError, export_document, import_file
from .language import Language, normalize_entry
from .storage import Storage, StorageError, safe_name


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


class DictionaryWord(BaseModel):
    word: str = Field(min_length=1, max_length=200)


def create_app(settings: Settings | None = None, ai_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    storage = Storage(settings.data_dir, settings.snapshot_minutes)
    app = FastAPI(title="Word Work", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.storage = storage
    language = Language(settings.resources_dir, settings.data_dir / ".wordwork" / "ordlista.txt")
    app.state.language = language

    ollama = (
        OllamaClient(settings.ollama_url, settings.ollama_model, transport=ai_transport)
        if settings.ollama_url
        else None
    )

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
        return {"status": "ok", "ai": ollama is not None, "language": language.ready}

    # ---------- AI (Ollama) ----------
    @app.get("/api/ai/status")
    def ai_status() -> dict:
        if ollama is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "host": httpx.URL(settings.ollama_url).host,
            "external": is_external(settings.ollama_url),
            "default_model": settings.ollama_model,
            "quick": list(QUICK_PROMPTS),
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

        async def events():
            yield json.dumps({"type": "start", "question": question}, ensure_ascii=False) + "\n"
            try:
                async for ev in ollama.chat(body.model, messages, body.think, num_ctx):
                    yield json.dumps(ev, ensure_ascii=False) + "\n"
            except AIError as exc:
                yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

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

    # ---------- import & export ----------
    @app.get("/api/export/formats")
    def export_formats() -> dict:
        return {
            "formats": [
                {"key": f.key, "label": f.label, "templates": f.templates} for f in EXPORT_FORMATS.values()
            ],
            "templates": [{"key": k, "label": v} for k, v in TEMPLATE_LABELS.items()],
        }

    @app.get("/api/documents/{name}/export")
    def export_doc(name: str, format: str = "docx", template: str = "standard") -> Response:
        content, _ = storage.read(name)
        data, fmt = export_document(name, content, format, template)
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
            return FileResponse(static_dir / "index.html")

    return app

