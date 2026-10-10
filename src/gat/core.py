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
# Geometria: desqueeze a piena risoluzione (niente downscale)
# ---------------------------------------------------------------------------
#
# Nota onesta sulla qualità: il desqueeze (scale orizzontale 1.2x con Lanczos)
# e, quando attiva, la stabilizzazione Gyroflow RICAMPIONANO l'immagine. Quindi
# l'output è "near-original": qualità molto alta a piena risoluzione, ma NON
# bit-identico alla sorgente. Per questo si usa un CRF basso (18) così da non
# aggiungere perdite percepibili sopra al ricampionamento.


def _ff_even(value: float) -> int:
    """Replica ``trunc(x/2)*2`` di ffmpeg: intero pari per troncamento."""
    return int(value / 2) * 2


def zoom_factor(zoom: str, stabilized: bool) -> float:
    """Ritaglio anti-vignettatura per clip 16:9 Wide.

    Con stabilizzazione, Gyroflow ritaglia già i bordi -> zoom 1.0.
    Senza stabilizzazione, in 16:9 Wide serve ~1.2x per togliere la vignettatura.
    """
    zoom = str(zoom).strip().lower()
    if zoom == "auto":
        return 1.0 if stabilized else 1.2
    return float(zoom)


def output_dimensions(width: int, height: int, squeeze: float, zoom: float) -> tuple[int, int]:
    """Dimensioni finali (pari) dopo desqueeze 1.2x e crop anti-vignettatura.

    Da 2704x1520 con squeeze 1.2 e zoom 1.0 -> ~3244x1520 (cinema ~2.13:1).
    Mirrora la matematica sequenziale del filtro ffmpeg (desqueeze poi crop).
    """
    w1 = _ff_even(width * squeeze)  # desqueeze
    w = _ff_even(w1 / zoom)  # crop anti-vignettatura
    h = _ff_even(height / zoom)
    return w, h


def build_vf(squeeze: float, zoom: float) -> str:
    """Catena di filtri ffmpeg: desqueeze 1.2x -> crop anti-vignettatura.

    NESSUN downscale: l'output resta a piena risoluzione. Il clip 16:9
    desqueezato è già ~2.13:1 cinematografico, quindi non serve altro crop di
    formato.
    """
    return (
        f"scale=trunc(iw*{squeeze}/2)*2:ih:flags=lanczos,setsar=1,"
        f"crop=trunc(iw/{zoom}/2)*2:trunc(ih/{zoom}/2)*2"
    )


# ---------------------------------------------------------------------------
# Scansione input
# ---------------------------------------------------------------------------

def collect_files(inputs: "str | Path | list[str | Path]") -> list[Path]:
    """Raccoglie i file .mp4 da un percorso (cartella/file) o da una lista mista.

    Le cartelle vengono espanse; i singoli file .mp4 sono presi così come sono.
    Rimuove i duplicati mantenendo l'ordine (per nome).
    """
    if isinstance(inputs, (str, Path)):
        return scan_input(inputs)
    seen: dict[Path, None] = {}
    for item in inputs:
        for f in scan_input(item):
            seen.setdefault(f.resolve(), None)
    return sorted(seen.keys(), key=lambda p: p.name.lower())


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

    # Solo 2.7K 16:9 è supportato: qualsiasi altro formato viene SALTATO,
    # non elaborato (il profilo lente non è valido per altri formati).
    if not info.is_supported:
        emit("  -> SKIPPED (unsupported format).")
        return FileResult(
            src, None, ok=True, skipped=True, message="skipped: unsupported format"
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    stabilized = False
    ffmpeg_input = src

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
            phase("stabilization", 0.0)
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
            phase("stabilization", 1.0)

        # Stato esplicito della stabilizzazione nel log.
        if stabilized:
            emit("  Stabilization: APPLIED (Gyroflow + calibrated lens profile)")
        else:
            emit("  Stabilization: OFF (desqueeze + export only)")

        vf = build_vf(settings.squeeze, zoom)
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
    input_path: "str | Path | list[str | Path]",
    out_dir: str | Path,
    settings: Settings,
    *,
    overwrite: bool = False,
    log: LogCallback | None = None,
    on_progress: ProgressCallback | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> PipelineReport:
    """Elabora i file .mp4 di una cartella, un singolo file o una lista."""
    out_dir = Path(out_dir)
    files = collect_files(input_path)
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
