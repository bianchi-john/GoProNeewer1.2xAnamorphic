"""Wrapper CLI per Gyroflow.

Gyroflow viene usato come eseguibile esterno (AppImage) via CLI::

    Gyroflow.AppImage <video> --preset <file.gyroflow> -f

Il preset viene generato al volo con il percorso ASSOLUTO del profilo lente
calibrato (così non si hardcoda nessun path utente). L'output è un file
``<nome>_stabilized.mp4`` accanto all'input.

Gestione del bug noto su hardware AMD: Gyroflow stampa ripetuti errori
``Failed to initialize OpenCL``, ``Cannot load libcuda.so.1`` /
``libamfrt64.so.1``. NON sono fatali: Gyroflow ricade su ``wgpu`` e completa.
Il successo si giudica dalla presenza del file ``_stabilized`` e dalla riga
``Done in <t>s``, non dal contenuto di stderr.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import config

LogCallback = Callable[[str], None]

# Pattern degli errori innocui da declassare a semplice info nel log.
_BENIGN_PATTERNS = (
    re.compile(r"Failed to initialize OpenCL", re.I),
    re.compile(r"Cannot load libcuda", re.I),
    re.compile(r"libamfrt64", re.I),
    re.compile(r"Platform::list", re.I),
    re.compile(r"clGetPlatformIDs", re.I),
    re.compile(r"Could not dynamically load CUDA", re.I),
    re.compile(r"DLL .* failed to open", re.I),
    # Rumore del backtrace Rust che segue il panic OpenCL innocuo.
    re.compile(r"^\s*\d+:\s", re.I),
    re.compile(r"^\s*at \./", re.I),
    re.compile(r"start_thread|__GI___clone|stack backtrace|note: run with", re.I),
)
# Righe che indicano l'esito reale.
_DONE_RE = re.compile(r"Done in ([\d.]+)\s*s", re.I)
_WGPU_RE = re.compile(r"Initialized wgpu", re.I)


class GyroflowError(RuntimeError):
    """Gyroflow non trovato o rendering non andato a buon fine."""


@dataclass
class GyroflowResult:
    output: Path
    done_seconds: float | None
    used_wgpu: bool


def is_benign(line: str) -> bool:
    """True se la riga di log è uno degli errori innocui noti (OpenCL/CUDA/AMF)."""
    return any(p.search(line) for p in _BENIGN_PATTERNS)


def find_gyroflow(explicit: str | None = None) -> str | None:
    """Individua l'eseguibile Gyroflow.

    Ordine: percorso esplicito → PATH ('gyroflow') → percorsi noti
    (``config.GYROFLOW_SEARCH_PATHS``) → AppImage inclusa nella cartella di
    test ``gopro/``.
    """
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists() or shutil.which(explicit):
            return str(p if p.exists() else explicit)
        return None

    for name in ("gyroflow", "Gyroflow"):
        found = shutil.which(name)
        if found:
            return found

    candidates: Iterable[str] = config.GYROFLOW_SEARCH_PATHS
    for cand in candidates:
        p = Path(cand).expanduser()
        if p.exists():
            return str(p)

    # Comodità in sviluppo: AppImage nella cartella di test del repo.
    repo_appimage = Path(__file__).resolve().parents[2] / "gopro" / "Gyroflow.AppImage"
    if repo_appimage.exists():
        return str(repo_appimage)

    return None


def write_preset(
    calibration_file: str | Path,
    *,
    codec: str = "H.264/AVC",
    bitrate: int = 100,
    dest_dir: str | Path | None = None,
) -> Path:
    """Genera un preset ``.gyroflow`` temporaneo con path assoluto del profilo.

    Restituisce il percorso del preset creato. Il chiamante è responsabile di
    rimuoverlo (vedi :func:`run`, che lo fa in automatico).
    """
    calib = Path(calibration_file).expanduser().resolve()
    if not calib.exists():
        raise GyroflowError(f"Profilo lente non trovato: {calib}")
    preset = {
        "version": 2,
        "calibration_file": str(calib),
        "output": {"codec": codec, "bitrate": bitrate},
    }
    dest_dir = Path(dest_dir) if dest_dir else Path(tempfile.gettempdir())
    dest_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=".gyroflow", dir=str(dest_dir))
    with os.fdopen(fd, "w") as fh:
        json.dump(preset, fh, indent=2)
    return Path(name)


def _find_stabilized(src: Path) -> Path | None:
    """Cerca il file ``<nome>_stabilized.*`` più recente accanto a ``src``."""
    stem = src.stem
    matches = sorted(
        src.parent.glob(f"{stem}_stabilized.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def run(
    video: str | Path,
    calibration_file: str | Path,
    *,
    gyroflow_bin: str | None = None,
    codec: str = "H.264/AVC",
    bitrate: int = 100,
    log: LogCallback | None = None,
    timeout: float | None = None,
) -> GyroflowResult:
    """Stabilizza ``video`` con Gyroflow applicando il profilo lente.

    Genera il preset al volo, lancia Gyroflow, filtra gli errori innocui e
    verifica il successo dalla presenza del file ``_stabilized`` (la riga
    ``Done in`` è usata come conferma aggiuntiva, non come requisito rigido).
    """
    video = Path(video)
    if not video.exists():
        raise GyroflowError(f"Video non trovato: {video}")

    binary = find_gyroflow(gyroflow_bin)
    if binary is None:
        raise GyroflowError(
            "Gyroflow non trovato. Scarica l'AppImage da gyroflow.xyz e indicala "
            "con --gyroflow /percorso/Gyroflow.AppImage (o mettila in uno dei "
            "percorsi noti)."
        )

    def emit(msg: str) -> None:
        if log:
            log(msg)

    # Rimuove eventuale output precedente per non scambiarlo per nuovo.
    old = _find_stabilized(video)
    if old is not None:
        old_mtime = old.stat().st_mtime
    else:
        old_mtime = 0.0

    preset = write_preset(
        calibration_file, codec=codec, bitrate=bitrate, dest_dir=video.parent
    )
    cmd = [binary, str(video), "--preset", str(preset), "-f"]
    emit(f"Gyroflow: {' '.join(cmd)}")

    # Su sistemi senza FUSE (o in sandbox) il mount dell'AppImage fallisce.
    # APPIMAGE_EXTRACT_AND_RUN=1 fa estrarre ed eseguire l'AppImage senza FUSE.
    env = os.environ.copy()
    # Evita lo spam del backtrace Rust dal panic OpenCL innocuo.
    env.setdefault("RUST_BACKTRACE", "0")
    if binary.lower().endswith(".appimage"):
        env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")

    done_seconds: float | None = None
    used_wgpu = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if not line:
                continue
            m = _DONE_RE.search(line)
            if m:
                done_seconds = float(m.group(1))
            if _WGPU_RE.search(line):
                used_wgpu = True
            if is_benign(line):
                emit(f"[gyroflow:ignorato] {line}")
            else:
                emit(f"[gyroflow] {line}")
        ret = proc.wait(timeout=timeout)
    except FileNotFoundError as exc:
        raise GyroflowError(f"Impossibile eseguire Gyroflow: {exc}") from exc
    finally:
        preset.unlink(missing_ok=True)

    stabilized = _find_stabilized(video)
    is_new = stabilized is not None and stabilized.stat().st_mtime >= old_mtime

    if stabilized is None or not is_new:
        raise GyroflowError(
            f"Gyroflow non ha prodotto il file stabilizzato per {video.name} "
            f"(exit code {ret}). Controlla il log sopra."
        )

    if done_seconds is not None:
        emit(f"Gyroflow: completato in {done_seconds:.1f}s -> {stabilized.name}")
    else:
        emit(f"Gyroflow: output prodotto -> {stabilized.name}")

    return GyroflowResult(
        output=stabilized, done_seconds=done_seconds, used_wgpu=used_wgpu
    )
