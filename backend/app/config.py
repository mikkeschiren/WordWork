"""Konfiguration via miljövariabler (prefix WW_)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    static_dir: Path | None
    snapshot_minutes: float
    ollama_url: str
    ollama_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        static = os.environ.get("WW_STATIC_DIR", "")
        return cls(
            data_dir=Path(os.environ.get("WW_DATA_DIR", "./data")).resolve(),
            static_dir=Path(static).resolve() if static else None,
            snapshot_minutes=float(os.environ.get("WW_SNAPSHOT_MINUTES", "5")),
            ollama_url=os.environ.get("WW_OLLAMA_URL", "").rstrip("/"),
            ollama_model=os.environ.get("WW_OLLAMA_MODEL", ""),
        )
