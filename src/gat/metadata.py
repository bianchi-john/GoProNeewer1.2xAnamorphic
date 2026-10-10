"""Read GoPro file metadata with ffprobe.

Detects resolution, fps, duration, codec, aspect ratio and the presence of the
GPMF gyro track (handler ``GoPro MET``) that Gyroflow needs for stabilization,
and validates the file against the single supported format (2.7K 16:9 Wide).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

# The ONLY supported format: 2.7K 16:9 Wide (2704x1520).
# The calibrated lens profile is valid for this format only, so 4:3 (or any
# other resolution) cannot be stabilized correctly: such files are flagged and
# skipped, never processed.
SUPPORTED_RESOLUTION = (2704, 1520)

# Tolerance used when recognising the aspect ratio from the real resolution.
_ASPECT_TOLERANCE = 0.03


class FFprobeError(RuntimeError):
    """ffprobe is missing or failed on a file."""


@dataclass
class MediaInfo:
    """Relevant metadata of a video file."""

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
        """Numeric aspect ratio (width / height)."""
        return self.width / self.height if self.height else 0.0

    @property
    def aspect_label(self) -> str:
        """Readable aspect ratio ('16:9', '4:3' or 'WxH')."""
        if not self.height:
            return "?"
        if abs(self.aspect - 16 / 9) < _ASPECT_TOLERANCE:
            return "16:9"
        if abs(self.aspect - 4 / 3) < _ASPECT_TOLERANCE:
            return "4:3"
        return f"{self.width}x{self.height}"

    @property
    def is_16by9(self) -> bool:
        """True when the aspect ratio is ~16:9."""
        return abs(self.aspect - 16 / 9) < _ASPECT_TOLERANCE

    @property
    def is_supported(self) -> bool:
        """True only for the supported format: 2.7K 16:9 (2704x1520)."""
        return (self.width, self.height) == SUPPORTED_RESOLUTION

    def summary(self) -> str:
        gyro = "gyro OK" if self.has_gyro else "NO gyro"
        return (
            f"{self.path.name}: {self.width}x{self.height} "
            f"({self.aspect_label}) {self.fps:.2f}fps {self.codec} [{gyro}]"
        )


def _parse_rate(value: str | None) -> float:
    """Convert a fraction such as '60000/1001' to float."""
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
    """Run ffprobe on ``path`` and return a :class:`MediaInfo`.

    The GPMF track is detected as a ``data`` stream whose handler is
    ``GoPro MET`` (the container of the GoPro gyro data).
    """
    path = Path(path)
    if not path.exists():
        raise FFprobeError(f"File not found: {path}")
    if shutil.which(ffprobe_bin) is None:
        raise FFprobeError(
            f"ffprobe not found ('{ffprobe_bin}'). Install ffmpeg: sudo apt install ffmpeg"
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
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as exc:  # pragma: no cover - depends on ffprobe
        raise FFprobeError(f"ffprobe failed on {path.name}: {exc.stderr.strip()}") from exc

    data = json.loads(out)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise FFprobeError(f"No video stream in {path.name}")

    width = int(video.get("width", 0))
    height = int(video.get("height", 0))
    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    codec = video.get("codec_name", "?")
    duration = float(fmt.get("duration", video.get("duration", 0.0)) or 0.0)

    gyro_handler = None
    has_gyro = False
    for stream in streams:
        tags = stream.get("tags", {}) or {}
        handler = tags.get("handler_name", "")
        # The GoPro gyro track is a data stream with handler "GoPro MET".
        if stream.get("codec_type") == "data" and "GoPro MET" in handler:
            has_gyro = True
            gyro_handler = handler
            break
        # Fallback: some dumps report "gpmd" as codec_tag_string.
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
    """Return warnings when the file is not in the supported format.

    The toolkit supports ONLY 2.7K 16:9 (2704x1520) clips because the
    calibrated lens profile is valid for that format alone. Non-conforming files
    are flagged and skipped, never processed.
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
