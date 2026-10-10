"""Lettura metadati dei file GoPro tramite ffprobe.

Rileva risoluzione, fps, durata, codec, aspect ratio e la presenza della traccia
giroscopio GPMF (handler ``GoPro MET``), necessaria per la stabilizzazione con
Gyroflow. Fornisce inoltre una validazione rispetto al formato di ripresa atteso
(2.7K Wide).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

# Unico formato SUPPORTATO: 2.7K 16:9 Wide (2704x1520).
# Il profilo lente calibrato è valido solo per questo formato, quindi il 4:3
# (e qualsiasi altra risoluzione) non può essere stabilizzato correttamente e
# viene segnalato e saltato, non elaborato.
SUPPORTED_RESOLUTION = (2704, 1520)

# Risoluzioni 2.7K note (solo per messaggi diagnostici più chiari).
KNOWN_2K7 = {
    (2704, 1520): "16:9",
    (2704, 2028): "4:3",
}

# Tolleranza nel riconoscere l'aspect ratio dalla risoluzione reale.
_ASPECT_TOLERANCE = 0.03


class FFprobeError(RuntimeError):
    """ffprobe assente o fallito su un file."""


@dataclass
class MediaInfo:
    """Metadati rilevanti di un file video."""

    path: Path
    width: int
    height: int
    fps: float
    duration: float
    codec: str
    has_gyro: bool
    gyro_handler: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def aspect(self) -> float:
        """Aspect ratio numerico (larghezza/altezza)."""
        return self.width / self.height if self.height else 0.0

    @property
    def aspect_label(self) -> str:
        """Etichetta leggibile dell'aspect ratio ('16:9', '4:3' o 'WxH')."""
        if not self.height:
            return "?"
        ar = self.aspect
        if abs(ar - 16 / 9) < _ASPECT_TOLERANCE:
            return "16:9"
        if abs(ar - 4 / 3) < _ASPECT_TOLERANCE:
            return "4:3"
        return f"{self.width}x{self.height}"

    @property
    def is_16by9(self) -> bool:
        """True se l'aspect ratio è ~16:9."""
        return abs(self.aspect - 16 / 9) < _ASPECT_TOLERANCE

    @property
    def is_supported(self) -> bool:
        """True solo per il formato supportato: 2.7K 16:9 (2704x1520)."""
        return (self.width, self.height) == SUPPORTED_RESOLUTION

    def summary(self) -> str:
        gyro = "gyro OK" if self.has_gyro else "NO gyro"
        return (
            f"{self.path.name}: {self.width}x{self.height} "
            f"({self.aspect_label}) {self.fps:.2f}fps {self.codec} [{gyro}]"
        )


def _parse_rate(value: str | None) -> float:
    """Converte una frazione tipo '60000/1001' in float."""
    if not value:
        return 0.0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        try:
            return float(value)
        except ValueError:
            return 0.0


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe(path: str | Path, *, ffprobe_bin: str = "ffprobe") -> MediaInfo:
    """Esegue ffprobe su ``path`` e restituisce un :class:`MediaInfo`.

    Rileva la traccia GPMF cercando uno stream ``data`` con handler
    ``GoPro MET`` (il contenitore dei dati giroscopio della GoPro).
    """
    path = Path(path)
    if not path.exists():
        raise FFprobeError(f"File non trovato: {path}")
    if shutil.which(ffprobe_bin) is None:
        raise FFprobeError(
            f"ffprobe non trovato ('{ffprobe_bin}'). Installa ffmpeg: sudo apt install ffmpeg"
        )

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError as exc:  # pragma: no cover - dipende da ffprobe
        raise FFprobeError(
            f"ffprobe fallito su {path.name}: {exc.stderr.strip()}"
        ) from exc

    data = json.loads(out)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise FFprobeError(f"Nessuno stream video in {path.name}")

    width = int(video.get("width", 0))
    height = int(video.get("height", 0))
    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(
        video.get("r_frame_rate")
    )
    codec = video.get("codec_name", "?")
    duration = float(fmt.get("duration", video.get("duration", 0.0)) or 0.0)

    gyro_handler = None
    has_gyro = False
    for stream in streams:
        tags = stream.get("tags", {}) or {}
        handler = tags.get("handler_name", "")
        # La traccia giroscopio GoPro è uno stream dati con handler "GoPro MET".
        if stream.get("codec_type") == "data" and "GoPro MET" in handler:
            has_gyro = True
            gyro_handler = handler
            break
        # Fallback: alcuni dump riportano "gpmd" come codec_tag_string.
        if stream.get("codec_tag_string") == "gpmd":
            has_gyro = True
            gyro_handler = handler or "gpmd"
            break

    info = MediaInfo(
        path=path,
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        codec=codec,
        has_gyro=has_gyro,
        gyro_handler=gyro_handler,
    )
    info.warnings = validate(info)
    return info


def validate(info: MediaInfo) -> list[str]:
    """Restituisce avvisi in inglese se il file non è nel formato supportato.

    Il tool supporta SOLO clip 2.7K 16:9 (2704x1520): il profilo lente calibrato
    è valido solo per questo formato. I file non conformi vanno segnalati e
    saltati, non elaborati.
    """
    warnings: list[str] = []
    if not info.is_supported:
        if not info.is_16by9:
            warnings.append(
                f"Not 16:9 ({info.aspect_label}): unsupported. "
                f"Only 2.7K 16:9 (2704x1520) clips can be processed — will be skipped."
            )
        else:
            warnings.append(
                f"Unexpected resolution {info.width}x{info.height}: "
                f"only 2.7K 16:9 (2704x1520) is supported — will be skipped."
            )
    if not info.has_gyro:
        warnings.append(
            "No GPMF gyro track: stabilization not possible "
            "(use the ORIGINAL files from the SD card)."
        )
    return warnings
