"""Konfiguration via miljövariabler (prefix WW_)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# Generiska standardvärden. Egna värden (server, modell, nyckel) hör hemma i .env.
DEFAULT_AI_URL = "http://localhost:11434"  # lokal Ollama
DEFAULT_AI_MODEL = ""  # tom = första chattmodellen servern har
DEFAULT_ALLOWED_HOSTS = "localhost,127.0.0.1,::1"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    static_dir: Path | None
    snapshot_minutes: float
    ollama_url: str
    ollama_model: str
    resources_dir: Path = Path(__file__).resolve().parent.parent / "resources" / "sv"
    # Tillåtna värdnamn i Host-huvudet (skydd mot DNS-rebinding). "*" = ingen kontroll.
    allowed_hosts: tuple[str, ...] = ("*",)
    # "ollama" (Ollamas eget API) eller "openai" (OpenAI-kompatibelt API).
    ai_api: str = "ollama"
    # API-nyckel (bara för OpenAI-kompatibla tjänster som kräver det). Visas aldrig i webbläsaren.
    ai_key: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        static = os.environ.get("WW_STATIC_DIR", "")
        api = os.environ.get("WW_AI_API", "ollama").strip().lower() or "ollama"
        if api not in ("ollama", "openai"):
            raise ValueError(f"WW_AI_API måste vara ollama eller openai (inte {api!r}).")
        # WW_AI_URL/WW_AI_MODEL gäller båda lägena; de äldre WW_OLLAMA_* fungerar fortfarande.
        url = os.environ.get("WW_AI_URL", os.environ.get("WW_OLLAMA_URL", DEFAULT_AI_URL))
        model = (
            os.environ.get("WW_AI_MODEL", "").strip()
            or os.environ.get("WW_OLLAMA_MODEL", "").strip()
            or DEFAULT_AI_MODEL
        )
        key = os.environ.get("WW_AI_KEY", "").strip()
        key_file = os.environ.get("WW_AI_KEY_FILE", "").strip()
        if not key and key_file:
            key = Path(key_file).read_text(encoding="utf-8").strip()
        return cls(
            data_dir=Path(os.environ.get("WW_DATA_DIR", "./data")).resolve(),
            static_dir=Path(static).resolve() if static else None,
            snapshot_minutes=float(os.environ.get("WW_SNAPSHOT_MINUTES", "5")),
            # Tom adress stänger av AI-stödet helt.
            ollama_url=url.strip().rstrip("/"),
            ollama_model=model,
            ai_api=api,
            ai_key=key,
            allowed_hosts=tuple(
                h.strip().lower()
                for h in os.environ.get("WW_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS).split(",")
                if h.strip()
            ),
            resources_dir=Path(
                os.environ.get(
                    "WW_RESOURCES_DIR",
                    Path(__file__).resolve().parent.parent / "resources" / "sv",
                )
            ).resolve(),
        )
