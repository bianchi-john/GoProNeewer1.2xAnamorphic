"""Toolkit configuration: defaults, config file and bundled resources.

Defaults can be overridden by a JSON config file (``~/.config/gat/config.json``
or the file given with ``--config``) and, with the highest priority, by CLI/GUI
arguments.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

# Bundled resources live inside the package so they ship with wheels/AppImage.
RESOURCE_DIR = Path(__file__).resolve().parent / "resources"
PREVIEW_DIR = RESOURCE_DIR / "previews"

DEFAULT_LENS_PROFILE_NAME = "neewer_lens.json"

# Bundled CC0 sample images for the Summer look preview (label -> file name).
PREVIEW_SAMPLES = {
    "Coastal village": "coastal_village.jpg",
    "Beach": "beach.jpg",
    "Mountain lake": "mountain_lake.jpg",
}

# Well-known locations searched for the Gyroflow executable (besides PATH).
GYROFLOW_SEARCH_PATHS = [
    "~/Applications/Gyroflow.AppImage",
    "~/Applications/gyroflow",
    "~/.local/bin/Gyroflow.AppImage",
    "~/.local/bin/gyroflow",
    "/opt/gyroflow/Gyroflow.AppImage",
]


def resource_path(name: str) -> Path | None:
    """Return the path of a bundled resource, or None if it is missing."""
    candidate = RESOURCE_DIR / name
    return candidate if candidate.exists() else None


def default_lens_profile() -> Path | None:
    """Path of the bundled default calibrated lens profile."""
    return resource_path(DEFAULT_LENS_PROFILE_NAME)


def preview_samples() -> dict[str, Path]:
    """Bundled preview images that actually exist (label -> path)."""
    return {
        label: PREVIEW_DIR / name
        for label, name in PREVIEW_SAMPLES.items()
        if (PREVIEW_DIR / name).exists()
    }


def default_config_path() -> Path:
    """Standard location of the user config file (XDG)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "gat" / "config.json"


@dataclass
class Settings:
    """Pipeline parameters.

    The toolkit handles ONLY 2.7K 16:9 clips: the 1.2x desqueeze yields the
    ~2.13:1 cinematic frame and the export keeps the FULL resolution (no
    downscale), encoded as high-quality H.265. There is no format choice and no
    "low quality" option: the defaults are already high quality.
    """

    # Stabilization
    stabilize: bool = True
    gyroflow_bin: str | None = None  # None = auto-detect
    calibration_file: str | None = None  # None = bundled default profile
    gyroflow_codec: str = "H.264/AVC"
    gyroflow_bitrate: int = 100  # Mbps, Gyroflow intermediate file

    # Desqueeze / export (full resolution, high quality)
    squeeze: float = 1.2
    zoom: str = "auto"  # "auto" | float (anti-vignetting crop)
    crf: int = 18  # H.265: lower = higher quality (16-18 = high quality)
    preset: str = "slow"  # x265 preset ("slow" = high quality)
    audio_bitrate: str = "256k"

    # Summer look: a touch more saturation and warmth (off by default)
    look: bool = False
    look_intensity: int = 50  # 0-100; even 100 stays subtle

    def merged(self, overrides: dict) -> "Settings":
        """Return a copy with the non-None values of ``overrides`` applied."""
        data = asdict(self)
        for key, value in overrides.items():
            if value is not None and key in data:
                data[key] = value
        return Settings(**data)


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load :class:`Settings`, applying the config file when present.

    With ``config_path`` None the default location is used; a missing file
    silently yields the defaults.
    """
    settings = Settings()
    path = Path(config_path) if config_path else default_config_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Invalid config ({path}): {exc}") from exc
        settings = settings.merged(raw)
    return settings


def save_settings(settings: Settings, config_path: str | Path | None = None) -> Path:
    """Write :class:`Settings` to a JSON file (creating parent folders)."""
    path = Path(config_path) if config_path else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2))
    return path
