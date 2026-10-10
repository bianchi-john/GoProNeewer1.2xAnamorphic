"""Test della logica pura (nessuna dipendenza da ffmpeg/Gyroflow)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gat import core, gyroflow  # noqa: E402
from gat.metadata import MediaInfo  # noqa: E402


def _info(w, h):
    return MediaInfo(
        path=Path("x.mp4"), width=w, height=h, fps=59.94,
        duration=10.0, codec="hevc", has_gyro=True,
    )


# --- aspect_to_ratio -------------------------------------------------------

def test_aspect_explicit_ratio():
    assert abs(core.aspect_to_ratio("16:9") - 16 / 9) < 1e-6
    assert abs(core.aspect_to_ratio("2.13:1") - 2.13) < 1e-6
    assert abs(core.aspect_to_ratio("2.0") - 2.0) < 1e-6


def test_aspect_auto_4by3_gives_16by9():
    assert abs(core.aspect_to_ratio("auto", _info(2704, 2028)) - 16 / 9) < 1e-6


def test_aspect_auto_16by9_gives_cinema():
    ratio = core.aspect_to_ratio("auto", _info(2704, 1520))
    assert 2.1 < ratio < 2.15  # ~2.134 anamorfico


# --- zoom_factor -----------------------------------------------------------

def test_zoom_stabilized_is_one():
    assert core.zoom_factor("auto", _info(2704, 2028), stabilized=True) == 1.0


def test_zoom_auto_4by3_no_stab():
    assert core.zoom_factor("auto", _info(2704, 2028), stabilized=False) == 1.3


def test_zoom_auto_16by9_no_stab():
    assert core.zoom_factor("auto", _info(2704, 1520), stabilized=False) == 1.2


def test_zoom_explicit():
    assert core.zoom_factor("1.15", _info(2704, 1520), stabilized=True) == 1.15


# --- target_height ---------------------------------------------------------

def test_target_height_even():
    assert core.target_height(1920, 16 / 9) == 1080
    h = core.target_height(1920, 2.134)
    assert h % 2 == 0
    assert 898 <= h <= 902  # ~900


# --- build_vf --------------------------------------------------------------

def test_build_vf_contains_steps():
    vf = core.build_vf(1.2, 16 / 9, 1920, 1080, 1.0)
    assert "scale=trunc(iw*1.2/2)*2:ih" in vf
    assert "crop=" in vf
    assert "scale=1920:1080" in vf


# --- gyroflow benign detection --------------------------------------------

def test_benign_patterns():
    assert gyroflow.is_benign("Failed to initialize OpenCL Platform::list ...")
    assert gyroflow.is_benign("Cannot load libcuda.so.1")
    assert gyroflow.is_benign("libamfrt64.so.1 not found")
    assert not gyroflow.is_benign("Initialized wgpu for AMD")
    assert not gyroflow.is_benign("Done in 42.0s")


# --- output_name -----------------------------------------------------------

def test_output_name():
    assert core.output_name(Path("GX010050.MP4"), 1920, 900) == (
        "GX010050_anamorfico_1920x900.mp4"
    )


# --- collect_files ---------------------------------------------------------

def test_collect_files_dedup_and_mixed(tmp_path):
    (tmp_path / "a.MP4").write_bytes(b"")
    (tmp_path / "b.mp4").write_bytes(b"")
    (tmp_path / "note.txt").write_bytes(b"")
    # cartella + un file esplicito già incluso nella cartella -> nessun duplicato
    files = core.collect_files([tmp_path, tmp_path / "a.MP4"])
    names = sorted(p.name for p in files)
    assert names == ["a.MP4", "b.mp4"]


def test_collect_files_single_path(tmp_path):
    (tmp_path / "x.MP4").write_bytes(b"")
    files = core.collect_files(tmp_path)
    assert [p.name for p in files] == ["x.MP4"]
