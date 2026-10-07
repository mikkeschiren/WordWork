"""Språkverktyg: stavningskontroll (Hunspell-ordlista via spylls), egen ordlista
och synonymer (Synlex/MyThes)."""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from spylls.hunspell import Dictionary

from .storage import _atomic_write

log = logging.getLogger("wordwork.language")

MAX_WORD_LEN = 64


def _clean(word: str) -> str:
    return word.strip().strip("-'’")


MAX_PHRASE_WORDS = 6


def normalize_entry(entry: str) -> str | None:
    """Ett ord eller en fras (2–6 ord, åtskilda av ett blanksteg). None om ogiltig."""
    parts = entry.split()
    if not parts or len(parts) > MAX_PHRASE_WORDS:
        return None
    if any(len(p) > MAX_WORD_LEN for p in parts):
        return None
    return " ".join(parts)


class PersonalDictionary:
    """Egen ordlista – en rad per ord eller fras i en vanlig textfil.

    Fraser (t.ex. "open source") godkänns bara som helhet: själva matchningen
    mot texten görs i editorn, eftersom den kräver ordens ordning och position.
    Ett ord som bara finns i en fras godkänns alltså inte på egen hand här.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._words: set[str] = set()
        if path.is_file():
            self._words = {w.strip() for w in path.read_text(encoding="utf-8").splitlines() if w.strip()}

    def words(self) -> list[str]:
        return sorted(self._words, key=str.casefold)

    def __contains__(self, word: str) -> bool:
        # "Bergman" i listan godkänner bara "Bergman"; "fanzine" godkänner även "Fanzine".
        return word in self._words or (word[:1].isupper() and word.lower() in self._words)

    def add(self, word: str) -> None:
        with self._lock:
            self._words.add(word)
            self._save()

    def remove(self, word: str) -> None:
        with self._lock:
            self._words.discard(word)
            self._save()

    def _save(self) -> None:
        _atomic_write(self.path, "".join(f"{w}\n" for w in self.words()))


class Language:
    """Laddar ordlistor i bakgrunden; anrop väntar tills de är klara."""

    def __init__(self, resources: Path, personal_path: Path) -> None:
        self.resources = resources
        self.personal = PersonalDictionary(personal_path)
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._dic: Dictionary | None = None
        self._thesaurus: dict[str, list[str]] = {}
        self._suggest_cache: dict[str, list[str]] = {}
        threading.Thread(target=self._load, name="language-load", daemon=True).start()

    # ---------- laddning ----------
    def _load(self) -> None:
        try:
            t = time.monotonic()
            self._dic, self._thesaurus = _load_resources(self.resources)
            log.info("Språkresurser laddade på %.1f s", time.monotonic() - t)
        except Exception as exc:  # pragma: no cover – loggas och rapporteras via API
            log.exception("Kunde inte ladda språkresurser")
            self._error = exc
        finally:
            self._ready.set()

    def _wait(self) -> Dictionary:
        if not self._ready.wait(timeout=60) or self._dic is None:
            raise RuntimeError(f"Språkresurserna kunde inte laddas: {self._error}")
        return self._dic

    @property
    def ready(self) -> bool:
        return self._ready.is_set() and self._dic is not None

    # ---------- stavning ----------
    def check(self, words: list[str]) -> list[str]:
        """Returnerar de ord som är felstavade."""
        dic = self._wait()
        bad = []
        for raw in words:
            w = _clean(raw)
            if not w or len(w) > MAX_WORD_LEN or any(c.isdigit() for c in w):
                continue
            if w in self.personal:
                continue
            if not _lookup(dic, w):
                bad.append(raw)
        return bad

    def suggest(self, word: str, limit: int = 6, budget: float = 2.0, settle: float = 0.35) -> list[str]:
        """Rättningsförslag. Hunspells sammansättningsregler gör att vissa förslag
        tar flera sekunder; vi returnerar det som hunnit komma inom tidsbudgeten."""
        dic = self._wait()
        word = _clean(word)[:MAX_WORD_LEN]
        if not word:
            return []
        if word in self._suggest_cache:
            return self._suggest_cache[word][:limit]

        q: queue.Queue[str | None] = queue.Queue()
        stop = threading.Event()

        def run() -> None:
            try:
                for s in dic.suggest(word):
                    q.put(s)
                    if stop.is_set():
                        break
            except Exception:  # pragma: no cover
                log.exception("Fel vid förslag för %r", word)
            finally:
                q.put(None)

        threading.Thread(target=run, daemon=True).start()
        results: list[str] = []
        start = time.monotonic()
        complete = False
        while len(results) < limit:
            # När första förslaget kommit väntar vi bara en kort stund på fler.
            deadline = (settle if results else budget) - (time.monotonic() - start)
            if results:
                deadline = max(deadline, 0.05)
            if deadline <= 0:
                break
            try:
                s = q.get(timeout=deadline)
            except queue.Empty:
                break
            if s is None:
                complete = True
                break
            if s != word and s not in results:
                results.append(s)
        stop.set()
        if complete or len(results) >= limit:
            self._suggest_cache[word] = results
        return results

    # ---------- synonymer ----------
    def synonyms(self, word: str) -> list[dict]:
        """Synonymgrupper för ordet och – om ordet är böjt – för dess grundformer."""
        dic = self._wait()
        word = _clean(word)
        if not word:
            return []
        heads: list[str] = []
        for cand in (word, word.lower()):
            if cand in self._thesaurus and cand not in heads:
                heads.append(cand)
        for stem in _stems(dic, word):
            for cand in (stem, stem.lower()):
                if cand in self._thesaurus and cand not in heads:
                    heads.append(cand)
        return [
            {"word": h, "base_form": h.lower() != word.lower(), "synonyms": self._thesaurus[h]}
            for h in heads
        ]


_RESOURCES: dict[Path, tuple[Dictionary, dict[str, list[str]]]] = {}
_RESOURCES_LOCK = threading.Lock()


def _load_resources(path: Path) -> tuple[Dictionary, dict[str, list[str]]]:
    """Ordlistorna är oföränderliga och delas mellan app-instanser (t.ex. i tester)."""
    with _RESOURCES_LOCK:
        if path not in _RESOURCES:
            _RESOURCES[path] = (
                Dictionary.from_files(str(path / "sv_SE")),
                _load_mythes(path / "th_sv_SE.dat"),
            )
        return _RESOURCES[path]


_LOOKUP_CACHE: dict[str, bool] = {}
_LOOKUP_LOCK = threading.Lock()


def _lookup(dic: Dictionary, word: str) -> bool:
    hit = _LOOKUP_CACHE.get(word)
    if hit is None:
        hit = bool(dic.lookup(word))
        with _LOOKUP_LOCK:
            if len(_LOOKUP_CACHE) > 300_000:
                _LOOKUP_CACHE.clear()
            _LOOKUP_CACHE[word] = hit
    return hit


def _stems(dic: Dictionary, word: str) -> list[str]:
    stems: list[str] = []
    try:
        for form in dic.lookuper.good_forms(word):
            entry = getattr(form, "in_dictionary", None)
            stem = entry.stem if entry is not None else getattr(form, "stem", None)
            if stem and stem not in stems:
                stems.append(stem)
    except Exception:  # pragma: no cover – spylls internt API; synonymer är best effort
        log.debug("Kunde inte hitta grundform för %r", word, exc_info=True)
    return stems


def _load_mythes(path: Path) -> dict[str, list[str]]:
    """Läser MyThes-format: 'ord|antal' följt av 'antal' rader '(ordklass)|syn|syn …'."""
    result: dict[str, list[str]] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 1  # första raden är teckenkodningen
    while i < len(lines):
        head, _, count = lines[i].partition("|")
        i += 1
        n = int(count) if count.strip().isdigit() else 0
        syns: list[str] = result.setdefault(head.strip(), [])
        for line in lines[i : i + n]:
            for s in line.split("|")[1:]:
                s = s.strip()
                if s and s != head and s not in syns:
                    syns.append(s)
        i += n
    return {k: v for k, v in result.items() if v}
