"""Fillagring av dokument (Markdown) och versionshistorik.

Struktur i datakatalogen:

    <data>/<namn>.md                     aktuella dokument
    <data>/.history/<namn>/index.json    metadata för versioner
    <data>/.history/<namn>/<vid>.md      ögonblicksbilder
    <data>/.trash/<tid>-<namn>.md        borttagna dokument (raderas aldrig på riktigt)
    <data>/.chats/<namn>/<id>.json       AI-samtal om dokumentet
    <data>/.wordwork/settings.json       inställningar

Samtalen följer dokumentet vid namnbyte och hamnar i papperskorgen med det.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

EXT = ".md"
MAX_NAME = 120
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WORD = re.compile(r"\w+(?:[-'’]\w+)*", re.UNICODE)


class StorageError(Exception):
    status = 400


class NotFound(StorageError):
    status = 404


class Conflict(StorageError):
    status = 409


SETTINGS_FILE = ".wordwork/settings.json"
MAX_SETTINGS_BYTES = 64_000
MAX_CHAT_BYTES = 4_000_000
MAX_CHAT_MESSAGES = 400
_CHAT_ID = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
_MESSAGE_FIELDS = ("content", "label", "thinking", "meta", "error")


# YAML-frontmatter i början av filen (samma regel som i frontend och Pandoc).
_FRONTMATTER = re.compile(
    r"\A\ufeff?---[ \t]*\r?\n(?![ \t]*\r?\n)(?:[\s\S]*?\r?\n)?(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)"
)


def split_frontmatter(text: str) -> tuple[str, str]:
    m = _FRONTMATTER.match(text)
    return (m.group(0), text[m.end():]) if m else ("", text)


def count_words(text: str) -> int:
    """Räknar ord i brödtexten (frontmatter räknas inte)."""
    return len(_WORD.findall(split_frontmatter(text)[1]))


def validate_name(name: str) -> str:
    name = " ".join(name.split())  # normalisera blanksteg
    if not name:
        raise StorageError("Namnet får inte vara tomt.")
    if len(name) > MAX_NAME:
        raise StorageError(f"Namnet får vara högst {MAX_NAME} tecken.")
    if name.startswith(".") or _FORBIDDEN.search(name):
        raise StorageError('Namnet får inte börja med punkt eller innehålla \\ / : * ? " < > |')
    return name


def safe_name(name: str, fallback: str = "Namnlös") -> str:
    """Gör om t.ex. ett filnamn till ett giltigt dokumentnamn."""
    name = _FORBIDDEN.sub(" ", name).lstrip(". ")
    name = " ".join(name.split())[:MAX_NAME].strip()
    return name or fallback


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass
class Version:
    id: str
    created: str  # ISO 8601, UTC
    kind: str  # "auto" | "manual" | "named" | "restore"
    label: str
    words: int


@dataclass
class DocumentInfo:
    id: str
    name: str
    modified: float
    words: int


class Storage:
    def __init__(self, root: Path, snapshot_minutes: float = 5.0) -> None:
        self.root = root
        self.snapshot_minutes = snapshot_minutes
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # rapporteras via /api/health – appen ska ändå starta
        self._lock = threading.RLock()

    # ---------- sökvägar ----------
    def _doc_path(self, name: str) -> Path:
        name = validate_name(name)
        path = (self.root / f"{name}{EXT}").resolve()
        if path.parent != self.root:
            raise StorageError("Ogiltigt namn.")
        return path

    def _hist_dir(self, name: str) -> Path:
        return self.root / ".history" / validate_name(name)

    def _chat_dir(self, name: str) -> Path:
        return self.root / ".chats" / validate_name(name)

    def _chat_path(self, name: str, cid: str) -> Path:
        if not _CHAT_ID.match(cid):
            raise StorageError("Ogiltigt samtals-id.")
        return self._chat_dir(name) / f"{cid}.json"

    def _require(self, name: str) -> Path:
        path = self._doc_path(name)
        if not path.is_file():
            raise NotFound(f"Dokumentet ”{name}” finns inte.")
        return path

    # ---------- dokument ----------
    def list(self) -> list[DocumentInfo]:
        docs = []
        for p in self.root.glob(f"*{EXT}"):
            if p.name.startswith("."):
                continue
            st = p.stat()
            docs.append(
                DocumentInfo(
                    id=p.stem,
                    name=p.stem,
                    modified=st.st_mtime,
                    words=count_words(p.read_text(encoding="utf-8")),
                )
            )
        return sorted(docs, key=lambda d: d.modified, reverse=True)

    def read(self, name: str) -> tuple[str, float]:
        path = self._require(name)
        return path.read_text(encoding="utf-8"), path.stat().st_mtime

    def unique_name(self, base: str) -> str:
        base = validate_name(base)
        candidate, n = base, 2
        while self._doc_path(candidate).exists():
            candidate = f"{base} {n}"
            n += 1
        return candidate

    def create(self, name: str | None, content: str = "") -> DocumentInfo:
        with self._lock:
            name = self.unique_name(name or "Namnlös")
            path = self._doc_path(name)
            _atomic_write(path, content)
            return DocumentInfo(name, name, path.stat().st_mtime, count_words(content))

    def save(
        self,
        name: str,
        content: str,
        base_modified: float | None = None,
        snapshot: bool = False,
    ) -> float:
        with self._lock:
            path = self._require(name)
            current_mtime = path.stat().st_mtime
            if base_modified is not None and abs(current_mtime - base_modified) > 1e-3:
                raise Conflict(
                    "Dokumentet har ändrats någon annanstans (t.ex. i en annan flik). "
                    "Ladda om innan du sparar."
                )
            if path.read_text(encoding="utf-8") != content:
                _atomic_write(path, content)
            if snapshot:
                self.snapshot(name, kind="manual")
            else:
                self._maybe_auto_snapshot(name, content)
            return path.stat().st_mtime

    def rename(self, old: str, new: str) -> DocumentInfo:
        with self._lock:
            src = self._require(old)
            new = validate_name(new)
            if new == old:
                return DocumentInfo(old, old, src.stat().st_mtime, 0)
            dst = self._doc_path(new)
            if dst.exists():
                raise Conflict(f"Det finns redan ett dokument som heter ”{new}”.")
            os.replace(src, dst)
            old_hist, new_hist = self._hist_dir(old), self._hist_dir(new)
            for old_dir, new_dir in ((old_hist, new_hist), (self._chat_dir(old), self._chat_dir(new))):
                if old_dir.exists():
                    new_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_dir), str(new_dir))
            text = dst.read_text(encoding="utf-8")
            return DocumentInfo(new, new, dst.stat().st_mtime, count_words(text))

    def delete(self, name: str) -> None:
        """Flyttar dokumentet (och dess historik och AI-samtal) till papperskorgen."""
        with self._lock:
            src = self._require(name)
            stamp = _now().strftime("%Y%m%dT%H%M%S")
            trash = self.root / ".trash"
            trash.mkdir(exist_ok=True)
            os.replace(src, trash / f"{stamp}-{src.name}")
            hist = self._hist_dir(name)
            if hist.exists():
                shutil.move(str(hist), str(trash / f"{stamp}-{name}.history"))
            chats = self._chat_dir(name)
            if chats.exists():
                shutil.move(str(chats), str(trash / f"{stamp}-{name}.chats"))

    # ---------- historik ----------
    def _load_index(self, name: str) -> list[Version]:
        f = self._hist_dir(name) / "index.json"
        if not f.exists():
            return []
        return [Version(**v) for v in json.loads(f.read_text(encoding="utf-8"))]

    def _save_index(self, name: str, versions: list[Version]) -> None:
        f = self._hist_dir(name) / "index.json"
        _atomic_write(f, json.dumps([asdict(v) for v in versions], ensure_ascii=False, indent=1))

    def history(self, name: str) -> list[Version]:
        self._require(name)
        return list(reversed(self._load_index(name)))

    def read_version(self, name: str, vid: str) -> str:
        self._require(name)
        if not re.fullmatch(r"\d{8}T\d{12}", vid):
            raise NotFound("Versionen finns inte.")
        f = self._hist_dir(name) / f"{vid}{EXT}"
        if not f.is_file():
            raise NotFound("Versionen finns inte.")
        return f.read_text(encoding="utf-8")

    def snapshot(self, name: str, kind: str = "manual", label: str = "") -> Version | None:
        """Sparar en ögonblicksbild. Hoppar över om innehållet är identiskt med
        senaste versionen (utom för namngivna versioner, där etiketten uppdateras)."""
        with self._lock:
            path = self._require(name)
            content = path.read_text(encoding="utf-8")
            versions = self._load_index(name)
            if versions and self.read_version(name, versions[-1].id) == content:
                if kind == "named" and label:
                    versions[-1].label = label
                    versions[-1].kind = "named"
                    self._save_index(name, versions)
                    return versions[-1]
                return None
            now = _now()
            ids = {v.id for v in versions}
            vid = now.strftime("%Y%m%dT%H%M%S%f")
            while vid in ids:  # två versioner samma mikrosekund
                now = now.replace(microsecond=(now.microsecond + 1) % 1_000_000)
                vid = now.strftime("%Y%m%dT%H%M%S%f")
            v = Version(vid, now.isoformat(), kind, label, count_words(content))
            _atomic_write(self._hist_dir(name) / f"{vid}{EXT}", content)
            versions.append(v)
            self._save_index(name, versions)
            return v

    def _maybe_auto_snapshot(self, name: str, content: str) -> None:
        versions = self._load_index(name)
        if versions:
            last = datetime.fromisoformat(versions[-1].created)
            if (_now() - last).total_seconds() < self.snapshot_minutes * 60:
                return
        if not content.strip() and not versions:
            return
        self.snapshot(name, kind="auto")

    def restore(self, name: str, vid: str) -> float:
        with self._lock:
            content = self.read_version(name, vid)
            # Säkra nuvarande text först – inget ska kunna gå förlorat.
            self.snapshot(name, kind="auto", label="Före återställning")
            path = self._doc_path(name)
            _atomic_write(path, content)
            self.snapshot(name, kind="restore")
            return path.stat().st_mtime


# ---------- inställningar ----------
def _check_json_size(data: object, limit: int, what: str) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if len(text.encode("utf-8")) > limit:
        raise StorageError(f"{what} är för stort (max {limit // 1000} kB).")
    return text


class SettingsStore:
    """Inställningar som ett JSON-objekt. Frontend äger formatet; servern sparar bara."""

    def __init__(self, root: Path) -> None:
        self.path = root / SETTINGS_FILE
        self._lock = threading.Lock()

    def read(self) -> dict | None:
        """None om inga inställningar har sparats än."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return {}  # trasig fil: börja om med standardvärden i stället för att krascha
        return data if isinstance(data, dict) else {}

    def write(self, data: dict) -> dict:
        if not isinstance(data, dict):
            raise StorageError("Inställningarna måste vara ett objekt.")
        text = _check_json_size(data, MAX_SETTINGS_BYTES, "Inställningarna")
        with self._lock:
            _atomic_write(self.path, text + "\n")
        return data


# ---------- AI-samtal ----------
def _clean_messages(messages: object) -> list[dict]:
    if not isinstance(messages, list):
        raise StorageError("Meddelandena måste vara en lista.")
    if len(messages) > MAX_CHAT_MESSAGES:
        raise StorageError(f"Samtalet har för många meddelanden (max {MAX_CHAT_MESSAGES}).")
    out = []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            raise StorageError("Ogiltigt meddelande.")
        clean = {"role": m["role"]}
        for key in _MESSAGE_FIELDS:
            value = m.get(key)
            if isinstance(value, str) and value:
                clean[key] = value
        out.append(clean)
    return out


def _chat_title(messages: list[dict]) -> str:
    for m in messages:
        if m["role"] == "user":
            title = " ".join((m.get("label") or m.get("content") or "").split())
            if title:
                return title if len(title) <= 80 else title[:79] + "…"
    return "Tomt samtal"


def _chat_summary(chat: dict) -> dict:
    return {
        "id": chat["id"],
        "created": chat["created"],
        "updated": chat["updated"],
        "model": chat.get("model", ""),
        "title": _chat_title(chat["messages"]),
        "messages": len(chat["messages"]),
    }


def list_chats(storage: Storage, name: str) -> list[dict]:
    """Dokumentets samtal, senast ändrade först."""
    storage._require(name)
    folder = storage._chat_dir(name)
    chats = []
    for f in folder.glob("*.json") if folder.exists() else []:
        try:
            chats.append(_chat_summary(json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError, TypeError):
            continue  # en trasig fil ska inte dölja de andra
    return sorted(chats, key=lambda c: c["updated"], reverse=True)


def read_chat(storage: Storage, name: str, cid: str) -> dict:
    storage._require(name)
    path = storage._chat_path(name, cid)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NotFound("Samtalet finns inte.") from None


def save_chat(storage: Storage, name: str, cid: str, messages: object, model: str = "") -> dict:
    """Skapar eller ersätter ett samtal. Returnerar sammanfattningen."""
    with storage._lock:
        storage._require(name)
        path = storage._chat_path(name, cid)
        now = _now().isoformat(timespec="seconds")
        created = now
        if path.exists():
            try:
                created = json.loads(path.read_text(encoding="utf-8")).get("created", now)
            except (OSError, ValueError):
                pass
        chat = {"id": cid, "created": created, "updated": now, "model": model[:200], "messages": _clean_messages(messages)}
        _atomic_write(path, _check_json_size(chat, MAX_CHAT_BYTES, "Samtalet") + "\n")
        return _chat_summary(chat)


def delete_chat(storage: Storage, name: str, cid: str) -> None:
    """Flyttar samtalet till papperskorgen."""
    with storage._lock:
        storage._require(name)
        path = storage._chat_path(name, cid)
        if not path.exists():
            raise NotFound("Samtalet finns inte.")
        trash = storage.root / ".trash"
        trash.mkdir(exist_ok=True)
        stamp = _now().strftime("%Y%m%dT%H%M%S")
        os.replace(path, trash / f"{stamp}-{validate_name(name)}.chat-{cid}.json")
