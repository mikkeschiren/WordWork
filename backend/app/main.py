"""Word Work – FastAPI-applikation."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .language import Language
from .storage import Storage, StorageError


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


class DictionaryWord(BaseModel):
    word: str = Field(min_length=1, max_length=64)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    storage = Storage(settings.data_dir, settings.snapshot_minutes)
    app = FastAPI(title="Word Work", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.storage = storage
    language = Language(settings.resources_dir, settings.data_dir / ".wordwork" / "ordlista.txt")
    app.state.language = language

    @app.exception_handler(StorageError)
    async def storage_error(_: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "ai": bool(settings.ollama_url), "language": language.ready}

    # ---------- språk ----------
    def _clean_word(word: str) -> str:
        word = word.strip()
        if not word or any(c.isspace() for c in word) or len(word) > 64:
            raise HTTPException(400, "Ogiltigt ord.")
        return word

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

