"""Gyroflow CLI wrapper.

Gyroflow is used as an external executable (AppImage) through its CLI::

    Gyroflow.AppImage <video> --preset <file.gyroflow> -f

The preset is generated on the fly with the ABSOLUTE path of the calibrated
lens profile, so no user path is ever hard-coded. The output is a
``<name>_stabilized.mp4`` file next to the input.

Known harmless bug on AMD hardware: Gyroflow repeatedly prints
``Failed to initialize OpenCL``, ``Cannot load libcuda.so.1`` /
``libamfrt64.so.1`` (plus a Rust backtrace). These are NOT fatal: Gyroflow falls
back to ``wgpu`` and finishes the render. Success is judged from the presence of
the ``_stabilized`` file and the ``Done in <t>s`` line, never from stderr.
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

# Known harmless messages (GPU backend probing and the backtrace that follows).
_BENIGN_PATTERNS = (
    re.compile(r"Failed to initialize OpenCL", re.I),
    re.compile(r"Cannot load libcuda", re.I),
    re.compile(r"libamfrt64", re.I),
    re.compile(r"Platform::list", re.I),
    re.compile(r"clGetPlatformIDs", re.I),
    re.compile(r"Could not dynamically load CUDA", re.I),
    re.compile(r"DLL .* failed to open", re.I),
    # Rust backtrace noise following the harmless OpenCL panic.
    re.compile(r"^\s*\d+:\s", re.I),
    re.compile(r"^\s*at \./", re.I),
    re.compile(r"start_thread|__GI___clone|__libc_start|stack backtrace|note: run with", re.I),
)
# Lines that tell the real outcome.
_DONE_RE = re.compile(r"Done in ([\d.]+)\s*s", re.I)
_WGPU_RE = re.compile(r"Initialized wgpu", re.I)


class GyroflowError(RuntimeError):
    """Gyroflow not found, or the render did not succeed."""


@dataclass
class GyroflowResult:
    output: Path
    done_seconds: float | None
    used_wgpu: bool


def is_benign(line: str) -> bool:
    """True when the log line is one of the known harmless messages."""
    return any(p.search(line) for p in _BENIGN_PATTERNS)


def find_gyroflow(explicit: str | None = None) -> str | None:
    """Locate the Gyroflow executable.

    Order: explicit path -> PATH ('gyroflow') -> well-known locations
    (``config.GYROFLOW_SEARCH_PATHS``) -> AppImage in the repo test folder
    ``gopro/`` (development convenience).
    """
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p)
        return shutil.which(explicit)

    for name in ("gyroflow", "Gyroflow"):
        found = shutil.which(name)
        if found:
            return found

    candidates: Iterable[str] = config.GYROFLOW_SEARCH_PATHS
    for cand in candidates:
        p = Path(cand).expanduser()
        if p.exists():
            return str(p)

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
    """Write a temporary ``.gyroflow`` preset holding the absolute profile path.

    Returns the preset path. The caller removes it (:func:`run` does so).
    """
    calib = Path(calibration_file).expanduser().resolve()
    if not calib.exists():
        raise GyroflowError(f"Lens profile not found: {calib}")
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
    """Return the newest ``<name>_stabilized.*`` next to ``src``."""
    matches = sorted(
        src.parent.glob(f"{src.stem}_stabilized.*"),
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
    verbose: bool = False,
) -> GyroflowResult:
    """Stabilize ``video`` with Gyroflow using the given lens profile.

    Generates the preset, runs Gyroflow, filters the harmless errors and checks
    success from the presence of the ``_stabilized`` file (the ``Done in`` line
    is an extra confirmation, not a hard requirement). Gyroflow's own output is
    only echoed with ``verbose``; on failure its last lines are always shown.
    """
    video = Path(video)
    if not video.exists():
        raise GyroflowError(f"Video not found: {video}")

    binary = find_gyroflow(gyroflow_bin)
    if binary is None:
        raise GyroflowError(
            "Gyroflow not found. Download the AppImage from gyroflow.xyz and set it "
            "with --gyroflow /path/to/Gyroflow.AppImage (GUI: Advanced options), "
            "or place it in one of the well-known locations."
        )

    def emit(msg: str) -> None:
        if log:
            log(msg)

    # Remember any previous output so it is not mistaken for a new one.
    old = _find_stabilized(video)
    old_mtime = old.stat().st_mtime if old is not None else 0.0

    preset = write_preset(calibration_file, codec=codec, bitrate=bitrate, dest_dir=video.parent)
    cmd = [binary, str(video), "--preset", str(preset), "-f"]
    if verbose:
        emit(f"Gyroflow: {' '.join(cmd)}")
    else:
        emit("Gyroflow: stabilizing with the calibrated lens profile…")

    env = os.environ.copy()
    # Keep the harmless OpenCL panic from printing a long Rust backtrace.
    env.setdefault("RUST_BACKTRACE", "0")
    # Without FUSE (or in a sandbox) mounting the AppImage fails;
    # APPIMAGE_EXTRACT_AND_RUN=1 makes it extract and run instead.
    if binary.lower().endswith(".appimage"):
        env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")

    done_seconds: float | None = None
    used_wgpu = False
    benign_count = 0
    tail: list[str] = []  # Gyroflow's own (non-harmless) lines, for diagnostics
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
            if not line.strip():
                continue
            m = _DONE_RE.search(line)
            if m:
                done_seconds = float(m.group(1))
            if _WGPU_RE.search(line):
                used_wgpu = True
            if is_benign(line):
                benign_count += 1
            else:
                tail = (tail + [line])[-25:]
                if verbose:
                    emit(f"[gyroflow] {line}")
        ret = proc.wait(timeout=timeout)
    except FileNotFoundError as exc:
        raise GyroflowError(f"Cannot run Gyroflow: {exc}") from exc
    finally:
        preset.unlink(missing_ok=True)

    if benign_count:
        emit(
            f"Gyroflow: ignored {benign_count} harmless GPU-backend messages "
            f"(OpenCL/CUDA/AMF probing){' — rendered with wgpu' if used_wgpu else ''}."
        )

    stabilized = _find_stabilized(video)
    is_new = stabilized is not None and stabilized.stat().st_mtime >= old_mtime
    if stabilized is None or not is_new:
        if not verbose:
            for line in tail:
                emit(f"[gyroflow] {line}")
        raise GyroflowError(
            f"Gyroflow did not produce the stabilized file for {video.name} "
            f"(exit code {ret}). See the log above."
        )

    if done_seconds is not None:
        emit(f"Gyroflow: done in {done_seconds:.1f}s -> {stabilized.name}")
    else:
        emit(f"Gyroflow: output written -> {stabilized.name}")

    return GyroflowResult(output=stabilized, done_seconds=done_seconds, used_wgpu=used_wgpu)
