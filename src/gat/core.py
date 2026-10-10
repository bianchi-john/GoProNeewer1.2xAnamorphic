"""Pipeline principale: scansione, validazione, Gyroflow, ffmpeg.

Ordine delle operazioni (verificato sul campo):

1. Gyroflow PRIMA, sul file ORIGINALE (legge il giroscopio GPMF e corregge la
   lente con il profilo calibrato). Opzionale.
2. ffmpeg POI, sul file stabilizzato: desqueeze anamorfico 1.2x -> crop al
   formato finale -> ridimensionamento -> encode H.265.

Il desqueeze va fatto DOPO Gyroflow.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable

from . import config, gyroflow, metadata
from .config import Settings
from .metadata import MediaInfo

LogCallback = Callable[[str], None]
# progress(file_index, n_files, phase, fraction_0_1)
ProgressCallback = Callable[[int, int, str, float], None]


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
    def failed(self) -> list[FileResult]:
        return [r for r in self.results if not r.ok]


# ---------------------------------------------------------------------------
# Risoluzione dei parametri "auto"
# ---------------------------------------------------------------------------

def aspect_to_ratio(aspect: str, info: MediaInfo | None = None) -> float:
    """Converte una specifica di aspect ('16:9', '2.13:1', '2.13', 'auto') in float.

    'auto': 4:3 in input -> 16:9 (1080p TV); 16:9 in input -> 2.13:1 (cinema,
    cioè praticamente nessun crop verticale dopo il desqueeze).
    """
    aspect = str(aspect).strip().lower()
    if aspect == "auto":
        if info is not None and info.aspect_label == "4:3":
            return 16 / 9
        # Default per 16:9 (e sconosciuti): cinema anamorfico ~2.13:1.
        return 2704 * 1.2 / 1520  # ~2.134
    if ":" in aspect:
        w, _, h = aspect.partition(":")
        return float(Fraction(w) / Fraction(h))
    return float(aspect)


def zoom_factor(zoom: str, info: MediaInfo | None, stabilized: bool) -> float:
    """Determina il ritaglio anti-vignettatura.

    Con stabilizzazione Gyroflow ritaglia già i bordi -> zoom 1.0.
    Senza stabilizzazione: 4:3 Wide ~1.3x, 16:9 Wide ~1.2x.
    """
    zoom = str(zoom).strip().lower()
    if zoom == "auto":
        if stabilized:
            return 1.0
        if info is not None and info.aspect_label == "4:3":
            return 1.3
        return 1.2
    return float(zoom)


def target_height(width: int, ratio: float) -> int:
    """Altezza pari dal rapporto d'aspetto."""
    h = round(width / ratio)
    if h % 2:
        h -= 1
    return h


def build_vf(squeeze: float, ratio: float, width: int, height: int, zoom: float) -> str:
    """Costruisce la catena di filtri ffmpeg.

    desqueeze orizzontale -> crop centrato al formato -> crop anti-vignettatura
    -> scale finale. Porta la logica dello script bash di riferimento.
    """
    return (
        f"scale=trunc(iw*{squeeze}/2)*2:ih:flags=lanczos,setsar=1,"
        f"crop='min(iw,trunc(ih*{ratio:.6f}/2)*2)':'min(ih,trunc(iw/{ratio:.6f}/2)*2)',"
        f"crop=trunc(iw/{zoom}/2)*2:trunc(ih/{zoom}/2)*2,"
        f"scale={width}:{height}:flags=lanczos"
    )


# ---------------------------------------------------------------------------
# Scansione input
# ---------------------------------------------------------------------------

def scan_input(input_dir: str | Path) -> list[Path]:
    """Elenca i file .mp4 (case-insensitive) in una cartella, ordinati per nome."""
    input_dir = Path(input_dir)
    if input_dir.is_file():
        return [input_dir] if input_dir.suffix.lower() == ".mp4" else []
    if not input_dir.is_dir():
        raise PipelineError(f"Cartella di input non valida: {input_dir}")
    files = [
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".mp4"
    ]
    return sorted(files, key=lambda p: p.name.lower())


# ---------------------------------------------------------------------------
# ffmpeg
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
) -> None:
    if shutil.which(ffmpeg_bin) is None:
        raise PipelineError(
            f"ffmpeg non trovato ('{ffmpeg_bin}'). Installa: sudo apt install ffmpeg"
        )
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        vf,
        "-c:v",
        "libx265",
        "-crf",
        str(settings.crf),
        "-preset",
        settings.preset,
        "-tag:v",
        "hvc1",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        settings.audio_bitrate,
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(dst),
    ]
    if log:
        log(f"ffmpeg: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if line.startswith("out_time_ms=") and on_progress and duration > 0:
            try:
                us = int(line.split("=", 1)[1])
                frac = max(0.0, min(1.0, (us / 1_000_000) / duration))
                on_progress(frac)
            except (ValueError, ZeroDivisionError):
                pass
    ret = proc.wait()
    stderr = proc.stderr.read() if proc.stderr else ""
    if ret != 0:
        raise PipelineError(f"ffmpeg fallito ({ret}) su {src.name}:\n{stderr.strip()}")
    if on_progress:
        on_progress(1.0)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def output_name(src: Path, width: int, height: int) -> str:
    return f"{src.stem}_anamorfico_{width}x{height}.mp4"


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
) -> FileResult:
    """Elabora un singolo file: (Gyroflow) + desqueeze/crop/encode."""

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

    ratio = aspect_to_ratio(settings.aspect, info)
    height = target_height(settings.width, ratio)
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / output_name(src, settings.width, height)

    if final.exists() and not overwrite:
        emit(f"  Già presente, salto: {final.name}")
        return FileResult(src, final, ok=True, skipped=True, message="esistente")

    stabilized = False
    ffmpeg_input = src

    want_stab = settings.stabilize
    if want_stab and not info.has_gyro:
        emit("  ! Niente GPMF: salto la stabilizzazione per questo file.")
        want_stab = False

    tmp_stab: Path | None = None
    try:
        if want_stab:
            work = work_dir or (out_dir / ".tmp_stabilizzati")
            work.mkdir(parents=True, exist_ok=True)
            # Gyroflow scrive accanto all'input: copiamo l'originale nella work dir.
            work_src = work / src.name
            if not work_src.exists():
                shutil.copy2(src, work_src)
            calib = settings.calibration_file or (
                str(config.default_lens_profile()) if config.default_lens_profile() else None
            )
            if not calib:
                raise PipelineError(
                    "Profilo lente non disponibile: indicane uno con --calibration "
                    "o includi resources/neewer_lens.json."
                )
            phase("stabilizzazione", 0.0)
            result = gyroflow.run(
                work_src,
                calib,
                gyroflow_bin=settings.gyroflow_bin,
                codec=settings.gyroflow_codec,
                bitrate=settings.gyroflow_bitrate,
                log=log,
            )
            tmp_stab = result.output
            ffmpeg_input = result.output
            stabilized = True
            phase("stabilizzazione", 1.0)

        zoom = zoom_factor(settings.zoom, info, stabilized)
        vf = build_vf(settings.squeeze, ratio, settings.width, height, zoom)
        emit(
            f"  Export {settings.width}x{height} (AR {ratio:.3f}, zoom {zoom}, "
            f"CRF {settings.crf}){' [stabilizzato]' if stabilized else ''}"
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
        )
    finally:
        # Pulisce i file intermedi di Gyroflow.
        if tmp_stab is not None:
            tmp_stab.unlink(missing_ok=True)
            work_src = tmp_stab.parent / src.name
            work_src.unlink(missing_ok=True)

    size = final.stat().st_size / (1024 * 1024) if final.exists() else 0
    emit(f"  -> {final.name} ({size:.1f} MB)")
    return FileResult(
        src, final, ok=True, stabilized=stabilized, message=f"{size:.1f} MB"
    )


def run_pipeline(
    input_path: str | Path,
    out_dir: str | Path,
    settings: Settings,
    *,
    overwrite: bool = False,
    log: LogCallback | None = None,
    on_progress: ProgressCallback | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> PipelineReport:
    """Elabora tutti i file .mp4 di una cartella (o un singolo file)."""
    out_dir = Path(out_dir)
    files = scan_input(input_path)
    report = PipelineReport()
    if not files:
        raise PipelineError(f"Nessun file .MP4 trovato in {input_path}")

    n = len(files)
    work_dir = out_dir / ".tmp_stabilizzati"
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
            )
        except (PipelineError, gyroflow.GyroflowError, metadata.FFprobeError) as exc:
            if log:
                log(f"  ERRORE: {exc}")
            res = FileResult(src, None, ok=False, message=str(exc))
        report.results.append(res)

    # Pulizia della work dir se vuota.
    if work_dir.exists():
        try:
            next(work_dir.iterdir())
        except StopIteration:
            work_dir.rmdir()

    return report
