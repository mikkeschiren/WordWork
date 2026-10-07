"""Konfiguration via miljövariabler (prefix WW_)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OLLAMA_URL = "https://ollama.dglive.net"
DEFAULT_OLLAMA_MODEL = "qwen3.6:35b"
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

    @classmethod
    def from_env(cls) -> "Settings":
        static = os.environ.get("WW_STATIC_DIR", "")
        return cls(
            data_dir=Path(os.environ.get("WW_DATA_DIR", "./data")).resolve(),
            static_dir=Path(static).resolve() if static else None,
            snapshot_minutes=float(os.environ.get("WW_SNAPSHOT_MINUTES", "5")),
            # Tom WW_OLLAMA_URL stänger av AI-stödet helt.
            ollama_url=os.environ.get("WW_OLLAMA_URL", DEFAULT_OLLAMA_URL).strip().rstrip("/"),
            ollama_model=os.environ.get("WW_OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL,
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
