"""Main pipeline: scan, validate, Gyroflow, ffmpeg — plus the Summer look preview.

Order of operations (field-verified):

1. Gyroflow FIRST, on the ORIGINAL file (it reads the GPMF gyro data and
   corrects the lens with the calibrated profile). Optional.
2. ffmpeg AFTERWARDS, on the stabilized file: 1.2x anamorphic desqueeze ->
   anti-vignetting crop -> optional Summer look -> H.265 encode.

The desqueeze must happen AFTER Gyroflow.

All processing logic lives here and is shared by the CLI and the GUI.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config, gyroflow, metadata
from .config import Settings
from .metadata import MediaInfo

LogCallback = Callable[[str], None]
# progress(file_index, n_files, phase, fraction_0_1)
ProgressCallback = Callable[[int, int, str, float], None]

WORK_DIR_NAME = ".tmp_stabilized"


class PipelineError(RuntimeError):
    pass


@dataclass
class FileResult:
    source: Path
    output: Path | None
    ok: bool
    skipped: bool = False
    stabilized: bool = False
    message: str = ""


@dataclass
class PipelineReport:
    results: list[FileResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok and not r.skipped)

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.skipped)

    @property
    def failed(self) -> list[FileResult]:
        return [r for r in self.results if not r.ok]


# ---------------------------------------------------------------------------
# Geometry: full-resolution desqueeze (no downscale)
# ---------------------------------------------------------------------------
#
# Honest note on quality: the desqueeze (1.2x horizontal Lanczos scale) and,
# when enabled, the Gyroflow stabilization RESAMPLE the image. The output is
# therefore "near-original": very high quality at full resolution, but NOT
# bit-identical to the source. A low CRF (18) is used so the encode does not
# add visible losses on top of that resampling.


def _ff_even(value: float) -> int:
    """Mirror ffmpeg's ``trunc(x/2)*2``: an even integer by truncation."""
    return int(value / 2) * 2


def zoom_factor(zoom: str, stabilized: bool) -> float:
    """Anti-vignetting crop for 16:9 Wide clips.

    With stabilization Gyroflow already crops the edges -> zoom 1.0.
    Without it, 16:9 Wide needs ~1.2x to remove the vignetting.
    """
    zoom = str(zoom).strip().lower()
    if zoom == "auto":
        return 1.0 if stabilized else 1.2
    return float(zoom)


def output_dimensions(width: int, height: int, squeeze: float, zoom: float) -> tuple[int, int]:
    """Final (even) size after the 1.2x desqueeze and the anti-vignetting crop.

    From 2704x1520 with squeeze 1.2 and zoom 1.0 -> 3244x1520 (cinema ~2.13:1).
    Mirrors the sequential math of the ffmpeg filter (desqueeze, then crop).
    """
    w1 = _ff_even(width * squeeze)  # desqueeze
    w = _ff_even(w1 / zoom)  # anti-vignetting crop
    h = _ff_even(height / zoom)
    return w, h


# ---------------------------------------------------------------------------
# Summer look: a touch more saturation and warmth
# ---------------------------------------------------------------------------
#
# Implemented as a single ``lutyuv`` pass that works directly on the YUV planes
# (no RGB round trip): chroma is scaled around neutral (saturation) and nudged
# toward yellow/red (warmth: U down, V up). Even at 100% the effect stays a
# gentle "summer" tint, by design. The SAME filter string is used for the export
# and for the GUI preview, so the preview shows exactly what the export does.

LOOK_MAX_SATURATION = 0.30  # +30% chroma at intensity 100
LOOK_MAX_U_SHIFT = 0.022  # fraction of the chroma range, toward yellow
LOOK_MAX_V_SHIFT = 0.016  # fraction of the chroma range, toward red


def look_filter(intensity: float) -> str | None:
    """ffmpeg filter for the Summer look at ``intensity`` 0-100 (None = off)."""
    k = max(0.0, min(1.0, float(intensity) / 100.0))
    if k <= 0.0:
        return None
    sat = 1.0 + LOOK_MAX_SATURATION * k
    du = LOOK_MAX_U_SHIFT * k
    dv = LOOK_MAX_V_SHIFT * k
    # minval/maxval adapt the math to the pixel format (limited/full, 8/10-bit).
    mid = "(minval+maxval)/2"
    rng = "(maxval-minval)"
    u = f"clip((val-{mid})*{sat:.4f}+{mid}-{du:.4f}*{rng},minval,maxval)"
    v = f"clip((val-{mid})*{sat:.4f}+{mid}+{dv:.4f}*{rng},minval,maxval)"
    return f"lutyuv=u='{u}':v='{v}'"


def build_vf(squeeze: float, zoom: float, look_intensity: float = 0) -> str:
    """ffmpeg filter chain: desqueeze -> anti-vignetting crop -> (Summer look).

    NO downscale: the output keeps the full resolution. A desqueezed 16:9 clip
    is already ~2.13:1 cinematic, so no aspect crop is needed. The desqueeze
    scaler also converts to limited-range yuv420p (what the encoder outputs
    anyway), so the look always operates on the same, well-defined format.
    """
    chain = [
        f"scale=trunc(iw*{squeeze}/2)*2:ih:flags=lanczos:out_range=tv",
        "format=yuv420p",
        "setsar=1",
        f"crop=trunc(iw/{zoom}/2)*2:trunc(ih/{zoom}/2)*2",
    ]
    look = look_filter(look_intensity)
    if look:
        chain.append(look)
    return ",".join(chain)


def effective_look_intensity(settings: Settings) -> int:
    """Look intensity actually applied (0 when the look is off)."""
    return int(settings.look_intensity) if settings.look else 0


# ---------------------------------------------------------------------------
# Preview rendering (used by the GUI; same look filter as the export)
# ---------------------------------------------------------------------------

PREVIEW_WIDTH = 960


def _require_ffmpeg(ffmpeg_bin: str) -> None:
    if shutil.which(ffmpeg_bin) is None:
        raise PipelineError(f"ffmpeg not found ('{ffmpeg_bin}'). Install: sudo apt install ffmpeg")


def extract_preview_frame(
    video: str | Path,
    dest: str | Path,
    *,
    squeeze: float = 1.2,
    at: float | None = None,
    width: int = PREVIEW_WIDTH,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> Path:
    """Grab one frame of a clip, desqueeze it and save a small PNG for previews.

    The frame comes from the original (unstabilized) clip, so it is cropped by
    1.2x to hide the Wide-lens vignetting. It is only used to preview colors.
    """
    _require_ffmpeg(ffmpeg_bin)
    video, dest = Path(video), Path(dest)
    if at is None:
        duration = metadata.probe(video, ffprobe_bin=ffprobe_bin).duration
        at = duration / 2 if duration > 0 else 0.0
    vf = (
        f"scale=trunc(iw*{squeeze}/2)*2:ih,crop=trunc(iw/1.2/2)*2:trunc(ih/1.2/2)*2,"
        f"scale={width}:-2:flags=lanczos,format=rgb24"
    )
    cmd = [ffmpeg_bin, "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(video),
           "-frames:v", "1", "-vf", vf, str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise PipelineError(f"Could not extract a preview frame from {video.name}: {proc.stderr.strip()}")
    return dest


def render_look_preview(
    image: str | Path,
    intensity: float,
    *,
    width: int = PREVIEW_WIDTH,
    ffmpeg_bin: str = "ffmpeg",
) -> bytes:
    """Apply the Summer look to a still image and return PNG bytes.

    The image is converted to limited-range BT.709 YUV — the format the export
    pipeline feeds to the look — so the preview matches the exported colors.
    With ``intensity`` 0 the same conversions run without the look (the
    "before" image), which keeps before/after strictly comparable.
    """
    _require_ffmpeg(ffmpeg_bin)
    chain = [
        f"scale={width}:-2:flags=lanczos",
        "format=rgb24",
        "scale=out_color_matrix=bt709:out_range=tv",
        "format=yuv444p",
    ]
    look = look_filter(intensity)
    if look:
        chain.append(look)
    chain += ["scale=in_color_matrix=bt709:in_range=tv", "format=rgb24"]
    cmd = [ffmpeg_bin, "-v", "error", "-i", str(image), "-frames:v", "1",
           "-vf", ",".join(chain), "-f", "image2pipe", "-c:v", "png",
           "-compression_level", "0", "-"]  # in-memory only: favor speed
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise PipelineError(
            f"Preview rendering failed: {proc.stderr.decode(errors='replace').strip()}"
        )
    return proc.stdout


# ---------------------------------------------------------------------------
# Input scanning
# ---------------------------------------------------------------------------

def collect_files(inputs: "str | Path | list[str | Path]") -> list[Path]:
    """Collect .mp4 files from a path (folder/file) or a mixed list.

    Folders are expanded; single .mp4 files are taken as they are. Duplicates
    are removed; the result is sorted by name.
    """
    if isinstance(inputs, (str, Path)):
        return scan_input(inputs)
    seen: dict[Path, None] = {}
    for item in inputs:
        for f in scan_input(item):
            seen.setdefault(f.resolve(), None)
    return sorted(seen.keys(), key=lambda p: p.name.lower())


def scan_input(input_dir: str | Path) -> list[Path]:
    """List the .mp4 files (case-insensitive) of a folder, sorted by name."""
    input_dir = Path(input_dir)
    if input_dir.is_file():
        return [input_dir] if input_dir.suffix.lower() == ".mp4" else []
    if not input_dir.is_dir():
        raise PipelineError(f"Invalid input folder: {input_dir}")
    files = [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"]
    return sorted(files, key=lambda p: p.name.lower())


# ---------------------------------------------------------------------------
# ffmpeg export
# ---------------------------------------------------------------------------

def _run_ffmpeg(
    src: Path,
    dst: Path,
    vf: str,
    settings: Settings,
    *,
    duration: float,
    log: LogCallback | None,
    on_progress: Callable[[float], None] | None,
    ffmpeg_bin: str = "ffmpeg",
    verbose: bool = False,
) -> None:
    _require_ffmpeg(ffmpeg_bin)
    cmd = [
        ffmpeg_bin, "-hide_banner", "-loglevel", "warning", "-y",
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", vf,
        "-c:v", "libx265", "-crf", str(settings.crf), "-preset", settings.preset,
        "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
        # Tag the output colors explicitly (GoPro footage is BT.709).
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        "-c:a", "aac", "-b:a", settings.audio_bitrate,
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(dst),
    ]
    if log and verbose:
        log(f"ffmpeg: {' '.join(cmd)}")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if line.startswith("out_time_ms=") and on_progress and duration > 0:
            try:
                us = int(line.split("=", 1)[1])
                on_progress(max(0.0, min(1.0, (us / 1_000_000) / duration)))
            except (ValueError, ZeroDivisionError):
                pass
    ret = proc.wait()
    stderr = proc.stderr.read() if proc.stderr else ""
    if ret != 0:
        raise PipelineError(f"ffmpeg failed ({ret}) on {src.name}:\n{stderr.strip()}")
    if on_progress:
        on_progress(1.0)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def output_name(src: Path, width: int, height: int) -> str:
    return f"{src.stem}_anamorphic_{width}x{height}.mp4"


def process_file(
    src: Path,
    out_dir: Path,
    settings: Settings,
    *,
    info: MediaInfo | None = None,
    work_dir: Path | None = None,
    overwrite: bool = False,
    log: LogCallback | None = None,
    on_phase_progress: Callable[[str, float], None] | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    verbose: bool = False,
) -> FileResult:
    """Process one file: (Gyroflow) + desqueeze/crop/(look)/encode."""

    def emit(msg: str) -> None:
        if log:
            log(msg)

    def phase(name: str, frac: float) -> None:
        if on_phase_progress:
            on_phase_progress(name, frac)

    if info is None:
        info = metadata.probe(src, ffprobe_bin=ffprobe_bin)
    emit(info.summary())
    for w in info.warnings:
        emit(f"  ! {w}")

    # Only 2.7K 16:9 is supported: any other format is SKIPPED, never processed
    # (the lens profile is not valid for other formats).
    if not info.is_supported:
        emit("  -> SKIPPED (unsupported format).")
        return FileResult(src, None, ok=True, skipped=True, message="skipped: unsupported format")

    out_dir.mkdir(parents=True, exist_ok=True)

    want_stab = settings.stabilize
    if want_stab and not info.has_gyro:
        emit("  ! No GPMF gyro track: stabilization skipped for this file.")
        want_stab = False

    zoom = zoom_factor(settings.zoom, want_stab)
    out_w, out_h = output_dimensions(info.width, info.height, settings.squeeze, zoom)
    final = out_dir / output_name(src, out_w, out_h)

    if final.exists() and not overwrite:
        emit(f"  Already exists, skipping: {final.name}")
        return FileResult(src, final, ok=True, skipped=True, message="already exists")

    stabilized = False
    ffmpeg_input = src
    tmp_stab: Path | None = None
    work_src: Path | None = None
    try:
        if want_stab:
            work = work_dir or (out_dir / WORK_DIR_NAME)
            work.mkdir(parents=True, exist_ok=True)
            # Gyroflow writes next to its input: copy the original to the work dir.
            work_src = work / src.name
            if not work_src.exists():
                shutil.copy2(src, work_src)
            default_profile = config.default_lens_profile()
            calib = settings.calibration_file or (str(default_profile) if default_profile else None)
            if not calib:
                raise PipelineError(
                    "No lens profile available: pass one with --calibration or keep "
                    "the bundled src/gat/resources/neewer_lens.json."
                )
            phase("stabilization", 0.0)
            result = gyroflow.run(
                work_src,
                calib,
                gyroflow_bin=settings.gyroflow_bin,
                codec=settings.gyroflow_codec,
                bitrate=settings.gyroflow_bitrate,
                log=log,
                verbose=verbose,
            )
            tmp_stab = result.output
            ffmpeg_input = result.output
            stabilized = True
            phase("stabilization", 1.0)

        # Explicit status lines in the log.
        if stabilized:
            emit("  Stabilization: APPLIED (Gyroflow + calibrated lens profile)")
        else:
            emit("  Stabilization: OFF (desqueeze + export only)")
        look_k = effective_look_intensity(settings)
        emit(f"  Summer look: {'ON (intensity ' + str(look_k) + '%)' if look_k else 'OFF'}")

        vf = build_vf(settings.squeeze, zoom, look_k)
        emit(
            f"  Export {out_w}x{out_h} full-res (desqueeze {settings.squeeze}x, "
            f"zoom {zoom}, H.265 CRF {settings.crf} preset {settings.preset})"
        )
        phase("export", 0.0)
        _run_ffmpeg(
            ffmpeg_input,
            final,
            vf,
            settings,
            duration=info.duration,
            log=log,
            on_progress=lambda f: phase("export", f),
            ffmpeg_bin=ffmpeg_bin,
            verbose=verbose,
        )
    finally:
        # Remove Gyroflow intermediates (stabilized file and the copied original).
        if tmp_stab is not None:
            tmp_stab.unlink(missing_ok=True)
        if work_src is not None:
            work_src.unlink(missing_ok=True)

    size = final.stat().st_size / (1024 * 1024) if final.exists() else 0
    emit(f"  -> {final.name} ({size:.1f} MB)")
    return FileResult(src, final, ok=True, stabilized=stabilized, message=f"{size:.1f} MB")


def run_pipeline(
    input_path: "str | Path | list[str | Path]",
    out_dir: str | Path,
    settings: Settings,
    *,
    overwrite: bool = False,
    log: LogCallback | None = None,
    on_progress: ProgressCallback | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    verbose: bool = False,
) -> PipelineReport:
    """Process the .mp4 files of a folder, a single file or a list.

    ``verbose`` also logs the exact ffmpeg/Gyroflow command lines and Gyroflow's
    own output (useful for troubleshooting).
    """
    out_dir = Path(out_dir)
    files = collect_files(input_path)
    report = PipelineReport()
    if not files:
        raise PipelineError(f"No .MP4 files found in {input_path}")

    n = len(files)
    work_dir = out_dir / WORK_DIR_NAME
    for i, src in enumerate(files):
        if log:
            log(f"=== [{i + 1}/{n}] {src.name} ===")

        def phase_progress(phase_name: str, frac: float, _i=i) -> None:
            if on_progress:
                on_progress(_i, n, phase_name, frac)

        try:
            res = process_file(
                src,
                out_dir,
                settings,
                work_dir=work_dir,
                overwrite=overwrite,
                log=log,
                on_phase_progress=phase_progress,
                ffmpeg_bin=ffmpeg_bin,
                ffprobe_bin=ffprobe_bin,
                verbose=verbose,
            )
        except (PipelineError, gyroflow.GyroflowError, metadata.FFprobeError) as exc:
            if log:
                log(f"  ERROR: {exc}")
            res = FileResult(src, None, ok=False, message=str(exc))
        report.results.append(res)

    # Remove the work dir when empty.
    if work_dir.exists():
        try:
            next(work_dir.iterdir())
        except StopIteration:
            work_dir.rmdir()

    return report
