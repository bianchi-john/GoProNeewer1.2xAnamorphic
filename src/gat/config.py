"""Configurazione del toolkit: default, file di config e risorse incluse.

I default possono essere sovrascritti da un file di config JSON
(``~/.config/gat/config.json`` o indicato con ``--config``) e, con priorità
massima, dagli argomenti della CLI/GUI.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Radice del pacchetto installato / repository (…/src/gat).
_PKG_DIR = Path(__file__).resolve().parent
# Risorse incluse: cerca sia in struttura repo sia accanto al pacchetto.
_RESOURCE_CANDIDATES = [
    _PKG_DIR.parent.parent / "resources",  # repo: <root>/resources
    _PKG_DIR / "resources",  # pacchetto: gat/resources
]

DEFAULT_LENS_PROFILE_NAME = "neewer_lens.json"

# Percorsi noti in cui cercare l'eseguibile Gyroflow (oltre a PATH).
GYROFLOW_SEARCH_PATHS = [
    "~/Applications/Gyroflow.AppImage",
    "~/Applications/gyroflow",
    "~/.local/bin/Gyroflow.AppImage",
    "~/.local/bin/gyroflow",
    "/opt/gyroflow/Gyroflow.AppImage",
]


def resource_path(name: str) -> Path | None:
    """Restituisce il percorso di una risorsa inclusa, o None se assente."""
    for base in _RESOURCE_CANDIDATES:
        candidate = base / name
        if candidate.exists():
            return candidate
    return None


def default_lens_profile() -> Path | None:
    """Percorso del profilo lente calibrato di default incluso nel repo."""
    return resource_path(DEFAULT_LENS_PROFILE_NAME)


def default_config_path() -> Path:
    """Percorso standard del file di config utente (XDG)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "gat" / "config.json"


@dataclass
class Settings:
    """Parametri della pipeline.

    Il tool tratta SOLO clip 2.7K 16:9: il desqueeze 1.2x produce il formato
    cinematografico ~2.13:1 e l'export avviene a PIENA risoluzione (nessun
    downscale a 1080p), con un encode H.265 di alta qualità. Non esiste più la
    scelta di formato o di "qualità" bassa: i default sono già di alta qualità.
    """

    # Stabilizzazione
    stabilize: bool = True
    gyroflow_bin: str | None = None  # None = autodetect
    calibration_file: str | None = None  # None = profilo di default incluso
    gyroflow_codec: str = "H.264/AVC"
    gyroflow_bitrate: int = 100  # Mbps, output intermedio di Gyroflow

    # Desqueeze / export (piena risoluzione, alta qualità)
    squeeze: float = 1.2
    zoom: str = "auto"  # "auto" | float  (ritaglio anti-vignettatura)
    crf: int = 18  # H.265: più basso = qualità più alta (16-18 = alta qualità)
    preset: str = "slow"  # preset x265 (qualità/efficienza; "slow" = alta qualità)
    audio_bitrate: str = "256k"

    def merged(self, overrides: dict) -> "Settings":
        """Restituisce una copia con i valori non-None di ``overrides`` applicati."""
        data = asdict(self)
        for key, value in overrides.items():
            if value is not None and key in data:
                data[key] = value
        return Settings(**data)


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Carica i :class:`Settings`, applicando il file di config se presente.

    Se ``config_path`` è None usa quello di default; se il file non esiste
    restituisce i default senza errore.
    """
    settings = Settings()
    path = Path(config_path) if config_path else default_config_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Config non valida ({path}): {exc}") from exc
        settings = settings.merged(raw)
    return settings


def save_settings(settings: Settings, config_path: str | Path | None = None) -> Path:
    """Scrive i :class:`Settings` su file JSON (crea le cartelle)."""
    path = Path(config_path) if config_path else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2))
    return path
